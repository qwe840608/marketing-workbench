import importlib.util

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from test_classify import classified_data as classified_data
from test_models import database as database

from app.config import REPO_ROOT

spec = importlib.util.spec_from_file_location(
    "source_flag_migration",
    REPO_ROOT / "backend/migrations/versions/0024_remove_source_flags.py",
)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


@pytest.mark.parametrize("table", migration.FLAG_TABLES)
@pytest.mark.migration
def test_upgrade_rejects_marked_records_before_any_schema_change(database, table):
    config = Config(str(REPO_ROOT / "backend/alembic.ini"))
    command.downgrade(config, "0023")
    with database.begin() as session:
        before = {
            name: session.scalar(text(f'SELECT count(*) FROM "{name}"'))
            for name in inspect(session.connection()).get_table_names()
        }
        session.execute(text(f'UPDATE "{table}" SET "{migration.LEGACY_FLAG}" = 1'))
    assert before[table] > 0
    with pytest.raises(RuntimeError, match=f"0024 升級中止.*{table}="):
        command.upgrade(config, "head")
    with database() as session:
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "0023"
        for name, count in before.items():
            assert session.scalar(text(f'SELECT count(*) FROM "{name}"')) == count
        for name in migration.FLAG_TABLES:
            assert migration.LEGACY_FLAG in {
                c["name"] for c in inspect(session.connection()).get_columns(name)
            }
        assert (
            session.scalar(
                text(f'SELECT count(*) FROM "{table}" WHERE "{migration.LEGACY_FLAG}" = 1')
            )
            == before[table]
        )
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []


@pytest.mark.migration
def test_upgrade_and_downgrade_preserve_records_and_send_permissions(database):
    config = Config(str(REPO_ROOT / "backend/alembic.ini"))
    # Keep this 0024 contract at its own revision as later migrations add tables.
    command.downgrade(config, "0024")
    with database() as session:
        tables = inspect(session.connection()).get_table_names()
        before = {name: session.scalar(text(f'SELECT count(*) FROM "{name}"')) for name in tables}
        switches = session.execute(text("SELECT id, send_enabled FROM accounts ORDER BY id")).all()
    for revision in ("0023", "0024", "0023", "0024"):
        (command.downgrade if revision == "0023" else command.upgrade)(config, revision)
        with database() as session:
            assert inspect(session.connection()).get_table_names() == tables
            for name, count in before.items():
                assert session.scalar(text(f'SELECT count(*) FROM "{name}"')) == count
            for name in migration.FLAG_TABLES:
                columns = {c["name"] for c in inspect(session.connection()).get_columns(name)}
                assert (migration.LEGACY_FLAG in columns) is (revision == "0023")
                if revision == "0023":
                    assert (
                        session.scalar(
                            text(
                                f'SELECT count(*) FROM "{name}" '
                                f'WHERE "{migration.LEGACY_FLAG}" != 0'
                            )
                        )
                        == 0
                    )
            assert (
                session.execute(text("SELECT id, send_enabled FROM accounts ORDER BY id")).all()
                == switches
            )
            assert session.execute(text("PRAGMA foreign_key_check")).all() == []


def assert_no_source_fields(value):
    if isinstance(value, dict):
        assert migration.LEGACY_FLAG not in value
        assert "demo" not in value
        for child in value.values():
            assert_no_source_fields(child)
    elif isinstance(value, list):
        for child in value:
            assert_no_source_fields(child)


@pytest.mark.parametrize(
    "path",
    [
        "/api/accounts",
        "/api/contacts",
        "/api/threads",
        "/api/posts",
        "/api/posts/1",
        "/api/posts/1/metrics",
        "/api/posts/1/comments",
        "/api/posts/1/comment-threads",
        "/api/threads/1/messages",
        "/api/dashboard",
    ],
)
def test_api_responses_do_not_expose_source_fields(client, classified_data, path):
    response = client.get(path)
    assert response.status_code == 200, response.text
    assert_no_source_fields(response.json())


@pytest.mark.parametrize(
    "path", ["/api/posts", "/api/posts/platforms"]
)
def test_retired_query_parameter_is_ignored(client, classified_data, path):
    expected = client.get(path)
    assert expected.status_code == 200
    actual = client.get(path, params={"demo": "true"})
    assert actual.status_code == 200
    assert actual.json() == expected.json()


def test_openapi_no_longer_advertises_source_selectors(client):
    schema = client.app.openapi()
    for path in schema["paths"].values():
        for operation in path.values():
            assert "demo" not in {p["name"] for p in operation.get("parameters", [])}
    for value in schema["components"]["schemas"].values():
        assert migration.LEGACY_FLAG not in value.get("properties", {})
        assert "demo" not in value.get("properties", {})

import sqlite3
from contextlib import closing
from datetime import UTC, datetime

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from migration_database import MigrationTemplate, copy_database, migration_fingerprint
from migration_database import upgrade_database as real_upgrade
from pydantic import SecretStr
from sqlalchemy import URL, create_engine, inspect


def snapshot(path):
    engine = create_engine(URL.create("sqlite", database=str(path)))
    try:
        inspector = inspect(engine)
        schema = {}
        for table in inspector.get_table_names():
            columns = inspector.get_columns(table)
            for column in columns:
                column["type"] = str(column["type"])
            # Alembic batch rebuilds emit constraints in set iteration order.
            # Compare every schema property, independent of SQL clause ordering.
            schema[table] = {
                "columns": columns,
                "primary_key": inspector.get_pk_constraint(table),
                **{
                    kind: sorted(getter(table), key=repr)
                    for kind, getter in (
                        ("foreign_keys", inspector.get_foreign_keys),
                        ("unique", inspector.get_unique_constraints),
                        ("checks", inspector.get_check_constraints),
                        ("indexes", inspector.get_indexes),
                    )
                },
            }
    finally:
        engine.dispose()
    with closing(sqlite3.connect(path)) as db:
        tables = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        contents = {}
        for (table,) in tables:
            columns = [row[1] for row in db.execute(f'PRAGMA table_info("{table}")')]
            rows = []
            for values in db.execute(f'SELECT * FROM "{table}" ORDER BY rowid'):
                row = dict(zip(columns, values, strict=True))
                if table == "prompt_versions" and row["actor"] == "system:migration:0014":
                    assert row["created_at"] == row["updated_at"]
                    row["created_at"] = row["updated_at"] = "per-test timestamp"
                rows.append(row)
            contents[table] = rows
        return schema, contents


def test_backup_includes_wal_commits_excludes_pending_and_is_independent(tmp_path):
    source, target = tmp_path / "live.db", tmp_path / "copy.db"
    with closing(sqlite3.connect(source)) as db:
        assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        db.execute("CREATE TABLE records(id INTEGER PRIMARY KEY, value TEXT)")
        db.execute("INSERT INTO records VALUES(1, 'committed')")
        db.commit()
        db.execute("INSERT INTO records VALUES(2, 'pending')")
        assert source.with_name("live.db-wal").stat().st_size > 0
        copy_database(source, target)
        with closing(sqlite3.connect(target)) as copied:
            assert copied.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert copied.execute("SELECT * FROM records").fetchall() == [(1, "committed")]
            copied.execute("UPDATE records SET value='copy only'")
            copied.commit()
        assert db.execute("SELECT value FROM records WHERE id=1").fetchone()[0] == "committed"
        db.rollback()


def test_template_runs_once_and_clones_remain_independent(settings, tmp_path, monkeypatch):
    template = MigrationTemplate(tmp_path / "templates")
    calls = []

    def upgrade(config):
        calls.append(config.database_path)
        real_upgrade(config)

    monkeypatch.setattr("migration_database.upgrade_database", upgrade)
    first = settings.model_copy(update={"database_path": tmp_path / "first.db"})
    second = settings.model_copy(update={"database_path": tmp_path / "second.db"})
    template.copy_to(first)
    original = snapshot(template.path)
    with closing(sqlite3.connect(first.database_path)) as db:
        db.execute("DELETE FROM prompt_versions")
        db.commit()
    before = datetime.now(UTC)
    template.copy_to(second)
    assert len(calls) == 1
    assert first.database_path != second.database_path != template.path
    assert snapshot(second.database_path) == original == snapshot(template.path)
    with closing(sqlite3.connect(second.database_path)) as db:
        created = db.execute("SELECT created_at FROM prompt_versions").fetchone()[0]
        assert datetime.fromisoformat(created) >= before
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("password", [None, SecretStr("isolated-initial-password")])
def test_template_matches_fresh_upgrade_for_initial_settings(settings, tmp_path, password):
    configured = settings.model_copy(update={"admin_initial_password": password})
    template = MigrationTemplate(tmp_path / "templates")
    template.copy_to(configured)
    fresh = configured.model_copy(update={"database_path": tmp_path / "fresh" / "mwb.db"})
    real_upgrade(fresh)
    assert snapshot(configured.database_path) == snapshot(fresh.database_path)
    with closing(sqlite3.connect(configured.database_path)) as db:
        # Account/password initialization remains in the per-test seed, outside migrations.
        assert db.execute("SELECT count(*) FROM staff").fetchone()[0] == 0


@pytest.mark.parametrize("change", ["edit", "add", "remove", "rename"])
def test_fingerprint_tracks_migration_contents_and_paths(tmp_path, change):
    path = tmp_path / "0001.py"
    path.write_text("revision = '0001'", encoding="utf-8")
    before = migration_fingerprint(tmp_path)
    if change == "edit":
        path.write_text("revision = 'changed'", encoding="utf-8")
    elif change == "add":
        (tmp_path / "0002.py").write_text("revision = '0002'", encoding="utf-8")
    elif change == "remove":
        path.unlink()
    else:
        path.rename(tmp_path / "renamed.py")
    assert migration_fingerprint(tmp_path) != before


def test_template_rebuilds_when_migration_contents_change(settings, tmp_path, monkeypatch):
    template = MigrationTemplate(tmp_path / "templates")
    template.copy_to(settings)
    original = template.path
    monkeypatch.setattr("migration_database.migration_fingerprint", lambda: "changed migration")
    other = settings.model_copy(update={"database_path": tmp_path / "other.db"})
    template.copy_to(other)
    assert template.generation == 2 and template.path != original
    assert snapshot(other.database_path) == snapshot(original)


@pytest.fixture
def forbid_template(monkeypatch):
    def unexpected(*args):
        pytest.fail("migration tests must perform a fresh upgrade")

    monkeypatch.setattr(MigrationTemplate, "copy_to", unexpected)


@pytest.mark.migration
@pytest.mark.usefixtures("forbid_template")
def test_migration_marker_performs_fresh_upgrade(migrated):
    with closing(sqlite3.connect(migrated.database_path)) as db:
        head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == head

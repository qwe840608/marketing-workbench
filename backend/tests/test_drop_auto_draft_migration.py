import pytest
from alembic import command
from alembic.config import Config
from message_fixtures import send_data as send_data
from sqlalchemy import inspect, text
from test_migration_template import snapshot

from app import config
from app.config import REPO_ROOT
from app.models import Base

pytestmark = pytest.mark.migration


def test_empty_downgrade_matches_original_0029_schema(settings, monkeypatch):
    monkeypatch.setattr(config, "Settings", lambda: settings)
    cfg = Config(str(REPO_ROOT / "backend/alembic.ini"))
    command.upgrade(cfg, "0029")
    original = snapshot(settings.database_path)[0]
    command.upgrade(cfg, "0030")
    schema = snapshot(settings.database_path)[0]
    assert "auto_draft_jobs" not in schema
    assert "auto_draft_jobs" not in Base.metadata.tables
    command.downgrade(cfg, "0029")
    schema, rows = snapshot(settings.database_path)
    assert schema == original
    assert rows["auto_draft_jobs"] == []
    command.upgrade(cfg, "0030")
    assert "auto_draft_jobs" not in snapshot(settings.database_path)[0]


def test_upgrade_drops_old_jobs_and_indexes_preserves_other_data(client, send_data):
    cfg = Config(str(REPO_ROOT / "backend/alembic.ini"))
    command.downgrade(cfg, "0029")
    factory = send_data["factory"]
    with factory.begin() as session:
        session.execute(
            text("INSERT INTO auto_draft_jobs "
                 "(created_at, updated_at, message_id, message_version, status) "
                 "VALUES ('2026-01-01', '2026-01-01', :message, 1, 'skipped')"),
            {"message": send_data["message"]},
        )
        path = session.bind.url.database
    _, before = snapshot(path)
    command.upgrade(cfg, "0030")
    with factory() as session:
        assert not inspect(session.connection()).has_table("auto_draft_jobs")
        assert session.execute(text(
            "SELECT name FROM sqlite_master WHERE tbl_name='auto_draft_jobs'"
        )).all() == []
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []
    _, after = snapshot(path)
    for name, rows in before.items():
        if name not in {"auto_draft_jobs", "alembic_version"}:
            assert after[name] == rows, name
    command.downgrade(cfg, "0029")
    assert snapshot(path)[1]["auto_draft_jobs"] == []
    command.upgrade(cfg, "0030")
    assert snapshot(path)[1] == after

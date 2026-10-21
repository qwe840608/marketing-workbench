import json
import logging

import pytest
from alembic import command
from alembic.config import Config

from app.config import REPO_ROOT, Settings
from app.db import build_engine


@pytest.mark.migration
def test_migration_from_empty_database(settings):
    configuration = Config(str(REPO_ROOT / "backend" / "alembic.ini"))
    command.upgrade(configuration, "head")
    engine = build_engine(settings)
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar()
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            assert connection.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
            assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000
    finally:
        engine.dispose()


def test_health_and_safe_access_log(client, settings):
    response = client.get("/api/health?token=must-not-be-logged")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": {"journal_mode": "wal", "foreign_keys": True, "busy_timeout": 5000},
    }
    contents = settings.log_path.read_text(encoding="utf-8")
    assert "must-not-be-logged" not in contents
    entries = [json.loads(line) for line in contents.splitlines()]
    assert any(entry.get("route") == "/api/health" and entry["status"] == 200 for entry in entries)


def test_host_is_restricted(client):
    assert client.get("/api/health", headers={"host": "outside.example"}).status_code == 400


def test_uvicorn_access_log_omits_query_and_credentials(client, settings):
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d',
        "127.0.0.1:1234",
        "GET",
        "/?password=must-not-be-logged",
        "1.1",
        200,
    )
    contents = settings.log_path.read_text(encoding="utf-8")
    assert "must-not-be-logged" not in contents
    assert any(json.loads(line)["event"] == "http_access" for line in contents.splitlines())


def test_env_load_does_not_depend_on_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert Settings.model_config["env_file"] == REPO_ROOT / ".env"

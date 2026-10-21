import socket
import sys
from ipaddress import ip_address
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from migration_database import MigrationTemplate, upgrade_database

from app.config import Settings
from app.main import create_app


@pytest.fixture(scope="session", autouse=True)
def no_external_network():
    def is_loopback(host):
        if host == "localhost":
            return True
        try:
            return ip_address(host).is_loopback
        except ValueError:
            return False

    connect, connect_ex, getaddrinfo = (
        socket.socket.connect,
        socket.socket.connect_ex,
        socket.getaddrinfo,
    )

    def checked_connect(original):
        def checked(sock, address):
            if sock.family in (socket.AF_INET, socket.AF_INET6) and not is_loopback(address[0]):
                raise AssertionError("External network access forbidden during tests")
            return original(sock, address)

        return checked

    def checked_resolve(host, *args, **kwargs):
        if host is not None and not is_loopback(host):
            raise AssertionError("External DNS access forbidden during tests")
        return getaddrinfo(host, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(socket.socket, "connect", checked_connect(connect))
        patch.setattr(socket.socket, "connect_ex", checked_connect(connect_ex))
        patch.setattr(socket, "getaddrinfo", checked_resolve)
        yield


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

TEST_ORIGIN = "http://testserver"


def login(client, username, password, *, origin=TEST_ORIGIN):
    """取得 CSRF 後登入，回傳登入後請求要帶的標頭；origin=None 時不送 Origin。"""
    bootstrap = client.get("/api/auth/csrf").json()["csrf_token"]
    headers = {"X-CSRF-Token": bootstrap} | ({"Origin": origin} if origin else {})
    response = client.post(
        "/api/auth/login", json={"username": username, "password": password}, headers=headers
    )
    assert response.status_code == 200, response.text
    return ({"Origin": origin} if origin else {}) | {
        "X-CSRF-Token": response.json()["csrf_token"]
    }


class ServiceReply:
    """直接呼叫 service 的結果：status_code 與 json()，方便沿用狀態與內容斷言。"""

    def __init__(self, status_code, payload):
        self.status_code, self.payload = status_code, payload

    def json(self):
        return self.payload

    @property
    def text(self):
        import json

        return json.dumps(self.payload, ensure_ascii=False)


def call_service(client, function, schema, body, *extra):
    """以 worker 的方式呼叫內部 service：一個 session、schema 驗證後傳入。
    驗證失敗回 422、service 的 HTTPException 回其狀態碼，其餘例外照常拋出。"""
    from fastapi import HTTPException
    from fastapi.encoders import jsonable_encoder
    from pydantic import ValidationError

    try:
        value = schema.model_validate(body) if schema else body
    except ValidationError:
        return ServiceReply(422, {"detail": "validation_error"})
    try:
        with client.app.state.session_factory() as session:
            result = function(session, value, *extra)
    except HTTPException as error:
        return ServiceReply(error.status_code, {"detail": error.detail})
    return ServiceReply(200, jsonable_encoder(result))


def deliver_event(client, event, source="webhook"):
    """以原始位元組送進 ingest.events（Webhook 與留言輪詢共用的入口）。"""
    import json

    from fastapi import HTTPException

    from app.services import ingest

    raw = event if isinstance(event, bytes) else json.dumps(event, ensure_ascii=False).encode()
    try:
        with client.app.state.session_factory() as session:
            outcome = ingest.events(session, raw, source, settings=client.app.state.settings)
    except HTTPException as error:
        return ServiceReply(error.status_code, {"detail": error.detail})
    return ServiceReply(outcome.status, outcome.result.model_dump(mode="json"))


def seed_records(session, settings):
    """共用合成資料（scripts/test_records）加上歷史價目列。"""
    from test_prices import seed_prices
    from test_records import seed_records as seed_base_records

    counts = seed_base_records(session, settings)
    seed_prices(session)
    return counts


@pytest.fixture
def settings(tmp_path, monkeypatch):
    for name in (
        "ADMIN_INITIAL_PASSWORD",
        "MARKETING_TEST_INITIAL_PASSWORD",
        "VIEWER_TEST_INITIAL_PASSWORD",
        "INGEST_API_KEY",
        "JEV_API_KEY",
        "JEV_API_BASE_URL",
        "JEV_MODEL",
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "AI_MONTHLY_BUDGET_USD",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "mwb.db"))
    monkeypatch.setenv("LOG_PATH", str(tmp_path / "backend.jsonl"))
    return Settings(
        _env_file=None,
        export_root=tmp_path / "export",
        publish_media_root=tmp_path / "publish-media",
        obsidian_root=tmp_path / "obsidian",
        scheduler_enabled=False,
        export_worker_enabled=False,
        receive_health_worker_enabled=False,
        receive_health_alerts_enabled=False,
        allowed_hosts=["testserver"],
        app_origin="http://testserver",
        session_cookie_secure=False,
    )


@pytest.fixture
def migrated(settings, request):
    if request.node.get_closest_marker("migration") is not None:
        return request.getfixturevalue("fresh_migrated")
    request.getfixturevalue("migration_template").copy_to(settings)
    return settings


@pytest.fixture(scope="session")
def migration_template(tmp_path_factory):
    # xdist gives each worker its own tmp_path_factory and session fixture.
    return MigrationTemplate(tmp_path_factory.mktemp("migration-template"))


@pytest.fixture
def fresh_migrated(settings):
    upgrade_database(settings)
    return settings


@pytest.fixture
def client(migrated):
    with TestClient(create_app(migrated)) as test_client:
        yield test_client

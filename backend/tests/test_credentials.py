"""Platform credentials: synthetic DB only, official transports always substituted."""

import base64
import hashlib
import hmac
import json
from types import SimpleNamespace

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy import select
from test_ai_settings_batch3 import keys as keys  # noqa: F401
from test_classify import classified_data as classified_data  # noqa: F401

from app.models import AuditLog, PlatformCredential, Staff
from app.services import credentials, jev, notify, receive_health
from app.services.gateway_workers import Workers


def fake_value(name):
    if name == "JEV_API_BASE_URL":
        return "https://api.typesafe.ai/v1"
    if name in {
        "META_APP_ID",
        "META_PAGE_ID",
        "META_IG_ACCOUNT_ID",
        "THREADS_APP_ID",
        "THREADS_USER_ID",
    }:
        return "1234567890123456"
    if name.endswith("BOT_USER_ID"):
        return "U" + "a" * 32
    if name.endswith("GROUP_ID"):
        return "C" + "a" * 32
    return "isolated-private-credential-value-" + name


def put(client, name, value=None, version=0):
    return client.put(
        "/api/credentials/" + name, json={"value": value or fake_value(name), "version": version}
    )


def test_retired_line_database_credentials_are_never_read(client, keys, settings):
    from app.services.webhook_normalize import secret

    settings.line_channel_secret = SecretStr("isolated-env-signature")
    with client.app.state.session_factory.begin() as session:
        session.add(
            PlatformCredential(provider="LINE_CHANNEL_SECRET", encrypted_key="invalid-ciphertext")
        )
    assert secret(settings, "line_channel_secret") == "isolated-env-signature"
    response = client.get("/api/credentials")
    assert response.status_code == 200
    assert not any(row["name"].startswith("LINE_") for row in response.json()["items"])
    with client.app.state.session_factory() as session:
        assert (
            session.scalar(
                select(PlatformCredential).where(
                    PlatformCredential.provider == "LINE_CHANNEL_SECRET"
                )
            ).encrypted_key
            == "invalid-ciphertext"
        )


@pytest.mark.parametrize("name", credentials.NAMES)
def test_live_precedence_encryption_masks_versions_removal(client, keys, settings, name):
    fallback = getattr(settings, name.lower())
    value = fake_value(name)
    assert credentials.resolve(name, settings) == fallback
    response = put(client, name)
    assert response.status_code == 200
    row = next(r for r in response.json()["items"] if r["name"] == name)
    assert row["configured"] and row["source"] == "DB" and row["version"] == 1
    assert row["mask"] == credentials.mask(value) and value not in response.text
    assert credentials.raw(credentials.resolve(name, settings)) == value
    with client.app.state.session_factory() as session:
        stored = session.scalar(select(PlatformCredential))
        assert stored.encrypted_key != value
        assert (
            Fernet(settings.account_encryption_key.get_secret_value())
            .decrypt(stored.encrypted_key.encode())
            .decode()
            == value
        )
        assert value not in json.dumps([r.detail_json for r in session.scalars(select(AuditLog))])
    assert value.encode() not in settings.database_path.read_bytes()
    assert put(client, name).status_code == 409
    assert client.delete(f"/api/credentials/{name}?version=0").status_code == 409
    assert client.delete(f"/api/credentials/{name}?version=1").status_code == 200
    assert credentials.resolve(name, settings) == fallback
    assert put(client, name).status_code == 409
    assert put(client, name, version=1).status_code == 409
    assert put(client, name, version=2).status_code == 200
    assert value not in settings.log_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("role", ["marketing", "viewer"])
def test_all_routes_admin_only(client, keys, role):
    with client.app.state.session_factory.begin() as session:
        session.get(Staff, keys["staff_id"]).role = role
    assert client.get("/api/credentials").status_code == 403
    assert put(client, "META_APP_SECRET").status_code == 403
    assert client.delete("/api/credentials/META_APP_SECRET?version=0").status_code == 403
    assert client.post("/api/credentials/meta/test", json={}).status_code == 403


def test_validation_csrf_and_missing_master(client, keys, settings):
    for name, value in [
        ("INGEST_API_KEY", "secret"),
        ("JEV_API_BASE_URL", "http://127.0.0.1"),
        ("META_APP_ID", "private-bad-id"),
        ("LINE_BOT_USER_ID", "bad-private"),
    ]:
        response = put(client, name, value)
        assert response.status_code == 422 and value not in response.text
    response = client.put(
        "/api/credentials/META_APP_SECRET",
        json={"value": "private-canary", "version": 0},
        headers={"X-CSRF-Token": "bad"},
    )
    assert response.status_code == 403
    settings.account_encryption_key = None
    assert put(client, "META_APP_SECRET").status_code == 503


def test_wrong_master_fails_closed_and_removal_recovers_env(client, keys, settings):
    assert put(client, "META_APP_SECRET").status_code == 200
    settings.meta_app_secret = SecretStr("isolated-env-secret")
    settings.account_encryption_key = SecretStr(Fernet.generate_key().decode())
    with pytest.raises(HTTPException, match="無法解密"):
        credentials.resolve("META_APP_SECRET", settings)
    row = next(
        r for r in client.get("/api/credentials").json()["items"] if r["name"] == "META_APP_SECRET"
    )
    assert row["configured"] and row["source"] == "DB" and row["error"] and row["mask"] is None
    assert client.delete("/api/credentials/META_APP_SECRET?version=1").status_code == 200
    assert credentials.resolve("META_APP_SECRET", settings) == settings.meta_app_secret


@pytest.mark.parametrize("group", ["meta", "threads", "notify", "jev"])
def test_probe_uses_db_transport_safe_errors_and_no_value_persistence(
    client, keys, settings, monkeypatch, group
):
    for name in credentials.GROUPS[group]:
        assert put(client, name).status_code == 200
    calls = []

    def request(req):
        calls.append(req)
        assert req.method == "GET" and "isolated-private" in req.headers["Authorization"]
        assert "isolated-private" not in str(req.url)
        return httpx.Response(200, json={"id": "123", "userId": "U" + "a" * 32})

    original_client = httpx.Client
    monkeypatch.setattr(
        credentials.httpx,
        "Client",
        lambda **kw: original_client(transport=httpx.MockTransport(request), **kw),
    )

    def post(url, key, payload, timeout):
        calls.append(payload)
        assert url == "https://api.typesafe.ai/v1/systemone"
        assert key == fake_value("JEV_API_KEY") and timeout == 15
        return (
            200,
            {
                "model": "isolated",
                "answers": {"connection": {"type": "noul", "noul": 1}},
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
            0,
        )

    monkeypatch.setattr(jev, "post_json", post)
    assert client.post(f"/api/credentials/{group}/test", json={}).json() == {"ok": True}
    assert len(calls) == 1
    for name in credentials.GROUPS[group]:
        assert fake_value(name) not in settings.log_path.read_text(encoding="utf-8")

    def failure(*a, **kw):
        raise ValueError("isolated-failure-private-token")

    monkeypatch.setattr(credentials.httpx, "Client", failure)
    monkeypatch.setattr(jev, "post_json", failure)
    result = client.post(f"/api/credentials/{group}/test", json={})
    assert result.status_code == 422 and "isolated-failure-private-token" not in result.text
    assert "isolated-failure-private-token" not in settings.log_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("platform", ["meta", "notify"])
def test_webhook_uses_db_signature_and_identity_immediately(client, keys, settings, platform):
    group = credentials.GROUPS[platform]
    for name in group:
        assert put(client, name).status_code == 200
    name = {
        "meta": "META_APP_SECRET",
        "line": "LINE_CHANNEL_SECRET",
        "notify": "NOTIFY_LINE_CHANNEL_SECRET",
    }[platform]
    path = {"meta": "meta-inbound", "line": "line-inbound", "notify": "line-notify"}[platform]
    setattr(settings, name.lower(), SecretStr("wrong-env-secret"))
    payload = (
        {"object": "page", "entry": []}
        if platform == "meta"
        else {"destination": "U" + "a" * 32, "events": []}
    )
    raw = json.dumps(payload).encode()

    def send(key):
        signature = hmac.digest(key.encode(), raw, hashlib.sha256)
        headers = (
            {"x-hub-signature-256": "sha256=" + signature.hex()}
            if platform == "meta"
            else {"x-line-signature": base64.b64encode(signature).decode()}
        )
        return client.post("/webhook/" + path, content=raw, headers=headers)

    assert send("wrong-env-secret").status_code == 401
    assert send(fake_value(name)).status_code == 200
    assert put(client, name, "changed-live-secret", 1).status_code == 200
    assert send(fake_value(name)).status_code == 401
    assert send("changed-live-secret").status_code == 200
    if platform == "meta":
        response = client.get(
            "/webhook/meta-inbound",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": fake_value("META_VERIFY_TOKEN"),
                "hub.challenge": "1234",
            },
        )
        assert response.status_code == 200 and response.text == "1234"


def test_worker_notify_health_and_jev_resolve_db(client, keys, settings, monkeypatch):
    for name in credentials.NAMES:
        assert put(client, name).status_code == 200
    assert notify.configured(settings)
    with client.app.state.session_factory() as session:
        assert receive_health.target(session, settings)[0] == fake_value("NOTIFY_LINE_GROUP_ID")
    from app.services.webhook_normalize import secret

    assert secret(settings, "meta_page_access_token") == fake_value("META_PAGE_ACCESS_TOKEN")
    seen = []
    from contextlib import nullcontext

    from app.services import meta_api

    # 只驗證權杖解析：呼叫配額紀錄以替身取代，不需要資料庫。
    monkeypatch.setattr(meta_api, "start_call", lambda *a: {"allowed": True, "call_id": 1})
    monkeypatch.setattr(meta_api, "finish_call", lambda *a: {"recorded": True})
    worker = Workers(
        nullcontext,
        settings,
        request=lambda *a, **kw: (
            seen.append(kw) or {"statusCode": 200, "body": {"data": []}, "headers": {}}
        ),
    )
    worker.graph(
        "1234567890123456",
        {},
        # 直呼 service 後呼叫紀錄會經 ApiCallStart 驗證，替身也須帶完整的帳號脈絡。
        {"source": "metrics", "platform": "facebook", "account_external_id": "1234567890123456"},
    )
    assert seen[-1]["headers"]["Authorization"] == "Bearer " + fake_value("META_PAGE_ACCESS_TOKEN")

    def post(url, key, payload, timeout):
        assert key == fake_value("JEV_API_KEY") and url.endswith("/v1/systemone")
        return (
            200,
            {"model": "isolated", "answers": {}, "usage": {"input_tokens": 1, "output_tokens": 1}},
            0,
        )

    monkeypatch.setattr(jev, "post_json", post)
    assert jev.ask({}, {}, settings).error is None


def test_runtime_call_sites_have_no_direct_settings_reads():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app"
    names = {name.lower() for name in credentials.NAMES}
    violations = []
    for path in root.rglob("*.py"):
        if path.name in {"config.py", "credentials.py"}:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and node.attr in names:
                violations.append((path.name, node.lineno, node.attr))
    assert not violations


def test_mask_short_never_reveals_whole_value():
    assert credentials.mask(SecretStr("abc")) == "••••"
    assert credentials.resolve("META_APP_ID", SimpleNamespace(meta_app_id="123")) == "123"


def test_local_bridge_output_is_encrypted(client, keys, settings):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from platform_credentials import envelope

    assert put(client, "META_APP_SECRET").status_code == 200
    key = b"x" * 32
    output = envelope(settings, key)
    assert fake_value("META_APP_SECRET") not in output
    packed = base64.b64decode(output)
    values = json.loads(AESGCM(key).decrypt(packed[:12], packed[12:], b"platform-config"))
    assert values["META_APP_SECRET"] == fake_value("META_APP_SECRET")


@pytest.mark.migration
def test_migration_jev_ciphertext_roundtrip(settings, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    from app import config
    from app.db import build_engine
    from app.models.base import utc_now

    monkeypatch.setattr(config, "Settings", lambda: settings)
    cfg = Config(str(config.REPO_ROOT / "backend/alembic.ini"))
    command.upgrade(cfg, "0030")
    settings.account_encryption_key = SecretStr(Fernet.generate_key().decode())
    encrypted = (
        Fernet(settings.account_encryption_key.get_secret_value())
        .encrypt(b"legacy-private-jev")
        .decode()
    )
    engine = build_engine(settings)
    stamp = utc_now().isoformat()
    try:
        with engine.begin() as db:
            db.execute(
                text(
                    "INSERT INTO ai_credentials "
                    "(created_at, updated_at, version, provider, encrypted_key) "
                    "VALUES (:t, :t, 7, 'jev', :key)"
                ),
                {"t": stamp, "key": encrypted},
            )
        command.upgrade(cfg, "head")
        assert credentials.raw(credentials.resolve("JEV_API_KEY", settings)) == "legacy-private-jev"
        with engine.connect() as db:
            assert db.execute(text("SELECT version FROM platform_credentials")).scalar() == 7
            assert (
                db.execute(
                    text("SELECT count(*) FROM ai_credentials WHERE provider='jev'")
                ).scalar()
                == 0
            )
        command.downgrade(cfg, "0030")
        with engine.connect() as db:
            assert (
                db.execute(
                    text("SELECT encrypted_key FROM ai_credentials WHERE provider='jev'")
                ).scalar()
                == encrypted
            )
        command.upgrade(cfg, "head")
        assert credentials.raw(credentials.resolve("JEV_API_KEY", settings)) == "legacy-private-jev"
        with engine.begin() as db:
            db.execute(
                text(
                    "INSERT INTO platform_credentials "
                    "(created_at, updated_at, version, provider, encrypted_key) "
                    "VALUES (:t, :t, 1, 'META_APP_SECRET', :key)"
                ),
                {"t": stamp, "key": encrypted},
            )
        with pytest.raises(RuntimeError, match="平台憑證已設定"):
            command.downgrade(cfg, "0030")
    finally:
        engine.dispose()


def test_line_test_connection_fills_bot_user_id(client, keys, settings, monkeypatch):
    # 官方帳號 User ID 由「測試連線」自動帶入：空白時寫入、已正確時不重寫。
    for name in ("NOTIFY_LINE_CHANNEL_ACCESS_TOKEN", "NOTIFY_LINE_CHANNEL_SECRET"):
        assert put(client, name).status_code == 200
    bot = "U" + "b" * 32
    original_client = httpx.Client
    monkeypatch.setattr(
        credentials.httpx,
        "Client",
        lambda **kw: original_client(
            transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"userId": bot})),
            **kw,
        ),
    )
    first = client.post("/api/credentials/notify/test", json={}).json()
    assert first == {"ok": True, "filled": ["NOTIFY_LINE_BOT_USER_ID"]}
    with client.app.state.session_factory() as session:
        assert credentials.resolve("NOTIFY_LINE_BOT_USER_ID", settings, session) == bot
    assert client.post("/api/credentials/notify/test", json={}).json() == {"ok": True}
    assert bot not in settings.log_path.read_text(encoding="utf-8")

"""Batch 3 security and prompt contract tests; all API keys are ephemeral test values."""

import importlib.util
import json
import secrets
import sqlite3
from datetime import timedelta
from io import BytesIO
from zipfile import ZipFile

import pytest
from ai_fixtures import ai_data as ai_data
from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import inspect, select
from test_classify import classified_data as classified_data
from test_workspace import workspace as workspace

from app.config import REPO_ROOT
from app.db import build_engine, session_factory
from app.models import (
    AICredential,
    AIKeyVerification,
    AuditLog,
    Message,
    PromptVersion,
    Staff,
    StaffBrand,
)
from app.models.base import utc_now
from app.services import ai_keys, backup, jev, prompts
from app.services.ai import providers
from app.services.redact import redact


@pytest.fixture
def keys(client, classified_data, settings, monkeypatch):
    settings.account_encryption_key = SecretStr(Fernet.generate_key().decode())
    monkeypatch.setattr(ai_keys, "probe", lambda *args: None)
    return classified_data


def save_key(client, provider="gemini"):
    key = secrets.token_urlsafe(36)
    tested = client.post(f"/api/ai/keys/{provider}/test", json={"key": key})
    assert tested.status_code == 200
    receipt = tested.json()["receipt"]
    saved = client.put(f"/api/ai/keys/{provider}", json={"receipt": receipt})
    assert saved.status_code == 200
    return key, receipt, saved.json()


@pytest.mark.parametrize("provider", ai_keys.PROVIDERS)
def test_encrypted_global_key_precedence_mask_audit_delete(client, keys, settings, provider):
    fallback = SecretStr(secrets.token_urlsafe(32))
    setattr(settings, provider + "_api_key", fallback)
    assert ai_keys.resolve(provider, settings) == fallback
    key, receipt, rows = save_key(client, provider)
    view = next(r for r in rows if r["provider"] == provider)
    assert view["source"] == "UI" and view["mask"].endswith(key[-4:])
    assert key not in json.dumps(rows)
    assert ai_keys.resolve(provider, settings).get_secret_value() == key
    assert client.put(f"/api/ai/keys/{provider}", json={"receipt": receipt}).status_code == 409
    with client.app.state.session_factory() as session:
        row = session.scalar(ai_keys.key_query(provider))
        assert row.encrypted_key != key
        assert (
            Fernet(settings.account_encryption_key.get_secret_value())
            .decrypt(row.encrypted_key)
            .decode()
            == key
        )
        details = [
            a.detail_json
            for a in session.scalars(select(AuditLog).where(AuditLog.action.like("ai.key.%")))
        ]
        assert key not in json.dumps(details) and details[-1]["provider"] == provider
    assert key.encode() not in settings.database_path.read_bytes()
    assert client.delete(f"/api/ai/keys/{provider}?version=999").status_code == 409
    deleted = client.delete(f"/api/ai/keys/{provider}?version={view['version']}")
    assert deleted.status_code == 200
    assert next(r for r in deleted.json() if r["provider"] == provider)["source"] == ".env"
    assert ai_keys.resolve(provider, settings) == fallback
    assert key not in settings.log_path.read_text("utf-8")


@pytest.mark.parametrize("role", ["marketing", "viewer"])
def test_nonadmin_keys_denied_every_route(client, keys, role):
    with client.app.state.session_factory.begin() as session:
        session.get(Staff, keys["staff_id"]).role = role
    assert client.get("/api/ai/keys").status_code == 403
    assert client.post("/api/ai/keys/jev/test", json={}).status_code == 403
    assert client.put("/api/ai/keys/jev", json={"receipt": "x" * 43}).status_code == 403
    assert client.delete("/api/ai/keys/jev?version=1").status_code == 403


def test_key_validation_csrf_and_failed_probe_never_reflect_plaintext(
    client, keys, settings, monkeypatch
):
    key = secrets.token_urlsafe(32)
    assert (
        client.post(
            "/api/ai/keys/gemini/test", json={"key": key}, headers={"X-CSRF-Token": "bad"}
        ).status_code
        == 403
    )
    response = client.post("/api/ai/keys/gemini/test", json={"key": key + "\n"})
    assert response.status_code == 422 and key not in response.text
    assert client.put("/api/ai/keys/gemini", json={"key": key}).status_code == 422

    def fail(*args):
        raise RuntimeError(key)

    monkeypatch.setattr(ai_keys, "probe", fail)
    response = client.post("/api/ai/keys/gemini/test", json={"key": key})
    assert response.status_code == 500 and key not in response.text
    with client.app.state.session_factory() as session:
        assert session.scalar(select(AICredential)) is None
        assert session.scalar(select(AIKeyVerification)) is None
    assert key not in settings.log_path.read_text("utf-8")


def test_probe_expiry_key_replacement_and_decryption_failure(client, keys, settings):
    first = client.post("/api/ai/keys/jev/test", json={"key": secrets.token_urlsafe(32)}).json()
    second = client.post("/api/ai/keys/jev/test", json={"key": secrets.token_urlsafe(32)}).json()
    assert client.put("/api/ai/keys/jev", json={"receipt": first["receipt"]}).status_code == 409
    with client.app.state.session_factory.begin() as session:
        session.scalar(select(AIKeyVerification)).expires_at = utc_now() - timedelta(seconds=1)
    assert client.put("/api/ai/keys/jev", json={"receipt": second["receipt"]}).status_code == 409
    key, _, _ = save_key(client, "jev")
    settings.account_encryption_key = SecretStr(Fernet.generate_key().decode())
    settings.jev_api_key = SecretStr(secrets.token_urlsafe(32))
    with pytest.raises(Exception) as error:
        ai_keys.resolve("jev", settings)
    assert key not in str(error.value)
    response = client.get("/api/ai/keys")
    assert response.status_code == 200 and key not in response.text
    view = next(r for r in response.json() if r["provider"] == "jev")
    assert view["source"] == "UI" and view["error"] and view["mask"] is None
    assert jev.ask({}, {}, settings).error == "key_unavailable"


def test_existing_env_connection_not_persisted(client, keys, settings):
    settings.jev_api_key = SecretStr(secrets.token_urlsafe(32))
    tested = client.post("/api/ai/keys/jev/test", json={})
    assert tested.status_code == 200 and tested.json()["receipt"] is None
    with client.app.state.session_factory() as session:
        assert session.scalar(select(AICredential)) is None
        assert session.scalar(select(AIKeyVerification)) is None


@pytest.mark.parametrize("provider", ["openai", "gemini", "anthropic"])
@pytest.mark.parametrize("failure", [False, True])
def test_official_probe_headers_single_call_and_safe_errors(
    settings, monkeypatch, provider, failure
):
    key = SecretStr(secrets.token_urlsafe(32))
    calls = []

    class Client:
        def __init__(self, **kwargs):
            assert kwargs == {"timeout": 15, "trust_env": False, "follow_redirects": False}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, headers):
            assert key.get_secret_value() not in url
            assert key.get_secret_value() in str(headers)
            calls.append(url)
            if failure:
                raise RuntimeError(key.get_secret_value())

            class Response:
                status_code = 200

                def json(self):
                    return {"models": [], "data": []}

            return Response()

    monkeypatch.setattr(ai_keys.httpx, "Client", Client)
    if failure:
        with pytest.raises(Exception) as error:
            ai_keys.probe(provider, key, settings)
        assert key.get_secret_value() not in str(error.value)
    else:
        ai_keys.probe(provider, key, settings)
    assert len(calls) == 1 and calls[0].startswith("https://")


def test_jev_probe_one_minimal_question_and_safe_failure(settings, monkeypatch):
    key = SecretStr(secrets.token_urlsafe(32))
    calls = []

    def transport(url, raw, payload, timeout):
        calls.append(payload)
        assert raw == key.get_secret_value() and url == "https://api.typesafe.ai/v1/systemone"
        return (
            200,
            {
                "model": "jev-1.13.0",
                "answers": {"connection": {"type": "noul", "noul": 1}},
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
            0,
        )

    monkeypatch.setattr(jev, "post_json", transport)
    ai_keys.probe("jev", key, settings)
    assert len(calls) == 1 and calls[0]["state"] == "OK"
    monkeypatch.setattr(jev, "post_json", lambda *a: (401, {"error": key.get_secret_value()}, 0))
    with pytest.raises(Exception) as error:
        ai_keys.probe("jev", key, settings)
    assert key.get_secret_value() not in str(error.value)


@pytest.mark.migration
def test_migration_preserves_rules_and_drops_column(settings):
    cfg = Config(str(REPO_ROOT / "backend/alembic.ini"))
    command.upgrade(cfg, "0013")
    original = "既有規則\n請使用繁體中文，不自行報價。"
    with sqlite3.connect(settings.database_path) as db:
        now = utc_now().isoformat()
        db.execute(
            "INSERT INTO brands(slug,name,business_hours,rules,auto_reply_level,"
            "auto_reply_enabled,version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            ("migration", "移轉", "{}", original, "L0", 0, 1, now, now),
        )
    command.upgrade(cfg, "head")
    engine = build_engine(settings)
    with session_factory(engine)() as session:
        current_brand = session.scalar(
            select(PromptVersion).where(PromptVersion.brand_id.is_not(None))
        )
        assert current_brand is not None
        assert current_brand.content == original and current_brand.revision == 1
        assert "全形標點（，。！？：；「」）" in prompts.current(session).content
    assert "rules" not in {c["name"] for c in inspect(engine).get_columns("brands")}
    engine.dispose()


def test_prompt_history_diff_restore_conflict_permissions(client, keys):
    brand_id = keys["brand_id"]
    path = f"/api/ai/prompts?brand_id={brand_id}"
    original = client.get(path).json()
    value = {"revision": original["revision"], "content": "請先確認需求類型。\n不要承諾效果。"}
    saved = client.put(path, json=value)
    assert saved.status_code == 200
    assert saved.json()["revision"] == original["revision"] + 1
    assert "+請先確認需求類型。" in saved.json()["versions"][0]["diff"]
    assert saved.json()["versions"][0]["actor"] == "測試管理員"
    assert client.put(path, json=value).status_code == 409
    restored = client.post(
        f"/api/ai/prompts/restore?brand_id={brand_id}",
        json={"revision": saved.json()["revision"], "restore_revision": 1},
    ).json()
    assert restored["versions"][0]["content"] == original["versions"][0]["content"]
    assert restored["versions"][0]["restored_from"] == 1 and len(restored["versions"]) == 3
    with client.app.state.session_factory.begin() as session:
        session.get(Staff, keys["staff_id"]).role = "marketing"
    assert client.put(path, json={"revision": 3, "content": "無權限"}).status_code == 403
    with client.app.state.session_factory.begin() as session:
        session.add(StaffBrand(staff_id=keys["staff_id"], brand_id=brand_id))
    assert client.put(path, json={"revision": 3, "content": "行銷編輯"}).status_code == 403
    assert client.put("/api/ai/prompts", json={"revision": 1, "content": "共用"}).status_code == 403
    assert (
        client.post(
            "/api/ai/prompts/restore", json={"revision": 1, "restore_revision": 1}
        ).status_code
        == 403
    )
    with client.app.state.session_factory.begin() as session:
        session.get(Staff, keys["staff_id"]).role = "viewer"
    assert client.get(path).status_code == 403
    assert client.put(path, json={"revision": 4, "content": "唯讀"}).status_code == 403


def test_exports_hide_database_credentials_and_fail_closed(client, keys, settings, workspace):
    key, _, _ = save_key(client)
    with client.app.state.session_factory.begin() as session:
        session.get(Message, workspace["message_id"]).text = "隔離測試 " + key
    result = client.app.state.export_worker.tick(force=True, now=0)
    assert result["ok"]
    assert all(key not in p.read_text("utf-8") for p in settings.export_root.rglob("*.md"))
    doc = client.post(f"/api/exports/threads/{workspace['thread_id']}/docx")
    assert doc.status_code == 200
    with ZipFile(BytesIO(doc.content)) as z:
        assert key.encode() not in b"".join(z.read(p) for p in z.namelist())
    report = client.post(
        "/api/exports/report/docx",
        json={"brand_id": workspace["brand_id"], "start": "2026-01-01", "end": "2026-12-31"},
    )
    assert report.status_code == 200
    with ZipFile(BytesIO(report.content)) as z:
        assert key.encode() not in b"".join(z.read(p) for p in z.namelist())
    settings.account_encryption_key = None
    doc = client.post(f"/api/exports/threads/{workspace['thread_id']}/docx")
    assert doc.status_code >= 400 and key not in doc.text
    assert key not in settings.log_path.read_text("utf-8")


def test_database_snapshot_and_real_encrypted_backup_exclude_plaintext(
    client, keys, settings, tmp_path
):
    key, _, _ = save_key(client)
    if not settings.seven_zip_path.is_file():
        pytest.skip("需要官方 7-Zip")
    settings.backup_local_root = tmp_path / "local"
    settings.backup_drive_root = tmp_path / "drive"
    settings.backup_password = SecretStr(secrets.token_urlsafe(24))
    settings.export_root.mkdir(exist_ok=True)
    source = tmp_path / "source" / "mwb.db"
    backup.database_snapshot(settings.database_path, source)
    config = settings.model_copy(update={"database_path": source})
    result = backup.run(config)
    archive = settings.backup_local_root / "marketing-workbench" / result["archive"]
    assert key.encode() not in archive.read_bytes()
    destination = tmp_path / "restored"
    backup.restore(config, archive, destination)
    assert key.encode() not in (destination / "database/mwb.db").read_bytes()
    assert not list(destination.rglob(".env"))
    assert "7zAES" in backup.run_7zip(settings, ["l", "-slt", str(archive)])
    with sqlite3.connect(destination / "database/mwb.db") as db:
        encrypted = db.execute("SELECT encrypted_key FROM ai_credentials").fetchone()[0]
        assert ai_keys.decrypt(encrypted, settings).get_secret_value() == key


def test_master_initializer_only_writes_env_preserves_existing(tmp_path, capsys):
    spec = importlib.util.spec_from_file_location(
        "initialize", REPO_ROOT / "scripts/initialize_ai_encryption.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / ".env"
    path.write_text("OTHER=value\nACCOUNT_ENCRYPTION_KEY=\n", encoding="utf-8")
    assert module.initialize(path)
    first = path.read_bytes()
    assert not module.initialize(path) and path.read_bytes() == first
    assert b"OTHER=value" in first and len(list(tmp_path.iterdir())) == 1
    assert not capsys.readouterr().out


def test_pii_redaction_preserves_fullwidth_punctuation():
    text = "您好，電話：０９１２３４５６７８。謝謝！可以嗎？「確定」；"
    result = redact(text).text
    assert "[REDACTED_PHONE]" in result
    assert all(mark in result for mark in "，。：！？「」；")
    landline = redact("電話：（０２）２３４５６７８").text
    assert "[REDACTED_PHONE]" in landline and "2345678" not in landline


def test_preview_and_restore_deny_other_brand(client, keys, workspace):
    with client.app.state.session_factory.begin() as session:
        session.get(Staff, keys["staff_id"]).role = "marketing"
        session.add(StaffBrand(staff_id=keys["staff_id"], brand_id=keys["brand_id"]))
    other = workspace["other_brand"]
    assert client.get(f"/api/ai/prompts?brand_id={other}").status_code == 403
    assert client.get(f"/api/ai/execution-options?brand_id={other}").status_code == 404
    assert (
        client.post(
            f"/api/ai/prompts/restore?brand_id={other}", json={"revision": 0, "restore_revision": 1}
        ).status_code
        == 403
    )
    assert client.post(f"/api/ai/prompts/preview/{workspace['other_thread']}").status_code == 404


def test_credential_test_receipt_bound_to_actor_and_current_version(client, keys, settings):
    key, _, _ = save_key(client)
    tested = client.post("/api/ai/keys/gemini/test", json={"key": secrets.token_urlsafe(32)}).json()
    with client.app.state.session_factory.begin() as session:
        row = session.scalar(select(AICredential))
        row.encrypted_key = (
            ai_keys.cipher(settings).encrypt(secrets.token_urlsafe(32).encode()).decode()
        )
    assert client.put("/api/ai/keys/gemini", json={"receipt": tested["receipt"]}).status_code == 409
    with client.app.state.session_factory.begin() as session:
        verification = session.scalar(select(AIKeyVerification))
        other = session.scalar(select(Staff).where(Staff.username == "marketing_test"))
        verification.staff_id = other.id
    assert client.put("/api/ai/keys/gemini", json={"receipt": tested["receipt"]}).status_code == 409
    assert key not in settings.log_path.read_text("utf-8")


def test_jev_uses_db_key_for_classification_and_review(
    client, keys, ai_data, settings, monkeypatch
):
    from ai_fixtures import review_response
    from test_classify import answer

    from app.services import classify, video_scripts

    key, _, _ = save_key(client, "jev")
    calls = []

    def transport(url, raw, payload, timeout):
        assert raw == key and raw != settings.jev_api_key.get_secret_value()
        calls.append(payload)
        response = (
            review_response()
            if set(payload["questions"]) == set(video_scripts.CHECKS)
            else answer()
        )
        return 200, response, 0

    monkeypatch.setattr(jev, "post_json", transport)
    assert classify.evaluate("請問如何服務？", {}, settings)[0].error is None
    checked = video_scripts.review(
        client.app.state.session_factory,
        settings,
        ai_data["brand_id"],
        {"text": "測試腳本"},
        [],
        {"notice": "isolated"},
    )
    assert isinstance(checked, dict)
    assert len(calls) == 2 and key not in str(checked)


def test_gemini_sdk_resolves_db_key(client, keys, settings, monkeypatch):
    from types import SimpleNamespace

    from google import genai

    key, _, _ = save_key(client, "gemini")
    settings.gemini_api_key = SecretStr(secrets.token_urlsafe(32))

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["api_key"] == key
            self.models = self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def generate_content(self, **kwargs):
            return SimpleNamespace(
                text="您好，請提供照片。",
                model_version="isolated-model",
                usage_metadata=None,
                candidates=[SimpleNamespace(finish_reason="STOP")],
            )

    monkeypatch.setattr(genai, "Client", Client)
    result = providers.call_api("gemini_api", "isolated-model", "已遮蔽的輸入", settings)
    assert result.error is None and key not in repr(result)


def test_sdk_logging_and_exception_path_hide_key(client, keys, settings):
    import logging

    key, _, _ = save_key(client)
    for name in ("openai", "anthropic", "google.genai", "httpx", "httpx2", "httpcore"):
        try:
            raise RuntimeError(key)
        except RuntimeError:
            logging.getLogger(name).exception("failed %s", key)
    assert key not in settings.log_path.read_text("utf-8")

"""Regression checks use isolated data only; no model or platform traffic."""

import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest
from brand_fixtures import TOPICS
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_stage3 import complete, queued
from test_stage3 import stage as stage_fixture

from app.config import REPO_ROOT
from app.main import create_app
from app.models import Brand, Staff, StaffBrand
from app.models.base import utc_now
from app.models.ideation import IdeationReport, ScriptVersion, VideoScript
from app.services import auth, ideation, ideation_exports

# Reuse the isolated stage fixture without changing its assertions.
stage = stage_fixture


def test_idea_edit_restore_history_and_exports(stage, exported, monkeypatch):
    from docx import Document
    from fastapi import HTTPException
    from test_stage3 import access

    from app.models import AuditLog
    from app.schemas.ideation import EditIdea
    from app.services import ai, idea_actions

    rid, sid = exported
    # 編輯與還原只改既有內容，不呼叫任何 AI。
    monkeypatch.setattr(ai, "run", lambda *a, **kw: pytest.fail("must not call AI"))
    with stage.factory() as session:
        originals = json.loads(json.dumps(session.get(IdeationReport, rid).data_json["ideas"]))
    edited = {"title": "手動編輯驗收題目", "hook": "新開場", "angle": "新切角",
              "visual": "新畫面", "keyword": "新關鍵字"}
    with stage.factory() as session:
        idea_actions.edit(
            access(stage, session), rid, 0, EditIdea(version=1, **edited),
            stage.settings, stage.factory,
        )
    with stage.factory() as session:
        row = session.get(IdeationReport, rid)
        assert row.status == "ready" and len(row.data_json["ideas"]) == 15
        assert row.data_json["ideas"][1] == originals[1]
        assert row.data_json["ideas_history"]["0"][0]["idea"] == originals[0]
        assert row.data_json["ideas"][0]["edited"] and row.data_json["ideas_revision"] == 2
        assert "手動編輯驗收題目" in Path(row.export_json["md"]).read_text(encoding="utf-8")
        docx_text = "\n".join(p.text for p in Document(row.export_json["docx"]).paragraphs)
        assert "手動編輯驗收題目" in docx_text
    with stage.factory() as session, pytest.raises(HTTPException) as error:
        idea_actions.edit(
            access(stage, session), rid, 0, EditIdea(version=1, **edited),
            stage.settings, stage.factory,
        )
    assert error.value.status_code == 409
    with stage.factory() as session:
        idea_actions.restore(access(stage, session), rid, 0, stage.settings, stage.factory)
    with stage.factory() as session:
        row = session.get(IdeationReport, rid)
        assert row.data_json["ideas"][0] == originals[0]
        assert "手動編輯驗收題目" not in Path(row.export_json["md"]).read_text(encoding="utf-8")
        assert session.get(VideoScript, sid).topic_index == 0
        actions = set(session.scalars(select(AuditLog.action)))
    assert {"ideation.ideas.edit", "ideation.ideas.restore"} <= actions
    with stage.factory() as session, pytest.raises(HTTPException) as error:
        idea_actions.restore(access(stage, session), rid, 0, stage.settings, stage.factory)
    assert error.value.status_code == 422


@pytest.mark.parametrize("role,allowed", [("viewer", True), ("marketing", False)])
def test_idea_api_write_permissions_and_csrf(stage, exported, monkeypatch, role, allowed):
    from app.services import ai

    rid, _ = exported
    monkeypatch.setattr(ai, "run", lambda *a, **kw: pytest.fail("must not generate"))
    with signed_client(stage, role=role, allowed=allowed) as client:
        prefix = f"/api/ideation/reports/{rid}/ideas"
        assert client.post(prefix + "/0/restore").status_code == 403
        body = {"version": 1, "title": "t", "hook": "h", "angle": "a", "visual": "v",
                "keyword": "k"}
        assert client.put(prefix + "/0", json=body).status_code == 403
        client.headers.pop("x-csrf-token", None)
        assert client.post(prefix + "/0/restore").status_code == 403


@pytest.mark.parametrize("role", ["admin", "marketing", "viewer"])
def test_ideation_comment_preview_readonly_range_paging_redaction_and_access(
    stage, role, monkeypatch
):
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    from app.models import Contact, Message, Thread
    from app.services import comment_poll
    from app.services.date_ranges import comment_bounds

    def forbidden(*args, **kwargs):
        raise AssertionError("Preview must not call a platform or enqueue work")

    monkeypatch.setattr(comment_poll, "wake", forbidden)
    monkeypatch.setattr(comment_poll, "enqueue", forbidden)
    start, end = comment_bounds("7")
    with stage.factory.begin() as session:
        contact = Contact(
            brand_id=stage.brand,
            platform="facebook",
            external_id="preview-fan",
            display_name="隔離觀眾名稱",
        )
        session.add(contact)
        session.flush()
        for index in range(25):
            session.add(
                Message(
                    thread_id=stage.thread,
                    contact_id=contact.id,
                    external_id=f"preview-{index}",
                    direction="in",
                    author_type="fan",
                    text="請聯絡 preview@example.test 或 0912-345-678",
                    sent_at=start + timedelta(seconds=index),
                )
            )
        for index, stamp in enumerate([start - timedelta(seconds=1), end]):
            session.add(
                Message(
                    thread_id=stage.thread,
                    external_id=f"outside-{index}",
                    direction="in",
                    author_type="fan",
                    text="範圍外",
                    sent_at=stamp,
                )
            )
        session.add(
            Message(
                thread_id=stage.thread,
                external_id="brand-reply",
                direction="out",
                author_type="brand",
                text="品牌回覆",
                sent_at=start,
            )
        )
        other = Brand(slug="preview-other", name="隔離其他品牌")
        session.add(other)
        session.flush()
        other_id = other.id
        before = session.query(Message).count()
        session.get(Thread, stage.thread).contact_id = contact.id
    base = f"/api/ideation/posts/{stage.post}/comments?brand_id={stage.brand}"
    with signed_client(stage, role) as client:
        response = client.get(base + "&comment_range=7")
        assert response.status_code == 200
        first = response.json()
        second = client.get(base + "&comment_range=7&offset=20").json()
        assert len(first["items"]) == 20 and first["next_offset"] == 20
        assert len(second["items"]) == 10 and second["next_offset"] is None
        items = first["items"] + second["items"]
        assert len({item["id"] for item in items}) == 30
        assert [item["sent_at"] for item in items] == sorted(
            (item["sent_at"] for item in items), reverse=True
        )
        assert all(item["author"] == "隔***" for item in items)
        assert "範圍外" not in str(items) and "品牌回覆" not in str(items)
        private = [item for item in items if "REDACTED" in item["text"]]
        assert len(private) == 25
        assert all(
            "example.test" not in item["text"] and "0912" not in item["text"] for item in private
        )
        assert client.get(base + "&offset=-1").status_code == 422
        assert client.get(base + "&comment_range=custom").status_code == 422
        day = start.astimezone(ZoneInfo("Asia/Taipei")).date()
        custom = client.get(
            base + f"&comment_range=custom&comment_from={day}&comment_to={day}"
        ).json()
        assert len(custom["items"]) == 20 and custom["next_offset"] == 20
        assert (
            client.get(base.replace(str(stage.post) + "/comments", "999999/comments")).status_code
            == 404
        )
        assert (
            client.get(base.replace(f"brand_id={stage.brand}", f"brand_id={other_id}")).status_code
            == 404
        )
    with stage.factory() as session:
        assert session.query(Message).count() == before
    if role != "admin":
        with stage.factory.begin() as session:
            staff = session.scalar(select(Staff).where(Staff.username == "download-" + role))
            session.query(StaffBrand).filter_by(staff_id=staff.id).delete()
        with client:
            assert client.get(base).status_code == 404
    with TestClient(create_app(stage.settings)) as client:
        assert client.get(base).status_code == 401


def test_new_report_quotes_store_identity_not_origin(stage):
    from app.services import ideation_evidence as evidence

    evidence.classify(stage.factory, stage.settings, stage.brand, TOPICS)
    rid = queued(stage)
    with stage.factory() as session:
        snapshot = ideation.aggregate(
            stage.factory, stage.settings, session.get(IdeationReport, rid)
        )
    quotes = [q for g in snapshot["groups"] for q in g["quotes"]]
    assert quotes
    assert all(q["kind"] == "comment_thread" and q["thread_id"] == stage.thread for q in quotes)
    assert all("url" not in q for q in quotes)


@pytest.fixture
def exported(stage, monkeypatch):
    rid = complete(stage, monkeypatch)
    with stage.factory.begin() as session:
        script = VideoScript(
            brand_id=stage.brand,
            report_id=rid,
            topic_index=0,
            title="隔離腳本",
            content_json={
                "title": "隔離腳本",
                "goal": "引流型",
                "hook": "問題",
                "duration_seconds": 10,
                "shots": [],
                "ending": "待覆核",
                "notes": "隔離",
                "permissions": "待授權",
            },
            review_json={"passed": False, "reasons": ["待覆核"]},
            provider="test",
            model="test",
        )
        session.add(script)
        session.flush()
        sid = script.id
        session.add(
            ScriptVersion(
                script_id=sid,
                revision=1,
                content_json=script.content_json,
                review_json=script.review_json,
                actor="test",
            )
        )
    ideation_exports.export_script(stage.factory, stage.settings, sid)
    return rid, sid


def signed_client(stage, role="admin", allowed=True):
    import secrets

    from pydantic import SecretStr

    from app.services.passwords import hash_password

    with stage.factory.begin() as session:
        staff = Staff(
            password_hash=hash_password(SecretStr(secrets.token_urlsafe(24))),
            username="download-" + role,
            display_name="隔離",
            role=role,
        )
        session.add(staff)
        session.flush()
        if allowed:
            session.add(StaffBrand(staff_id=staff.id, brand_id=stage.brand))
        credentials = auth.issue_session(session, stage.settings, staff.id)
    client = TestClient(create_app(stage.settings))
    client.cookies.set(auth.COOKIE_NAME, credentials.token)
    return client


@pytest.mark.parametrize("role", ["admin", "marketing", "viewer"])
@pytest.mark.parametrize("kind", ["reports", "scripts"])
def test_download_auth_brand_and_actual_unique_file(stage, exported, role, kind):
    rid, sid = exported
    identity = rid if kind == "reports" else sid
    url = f"/api/ideation/{kind}/{identity}/download/"
    with TestClient(create_app(stage.settings)) as anonymous:
        assert anonymous.get(url + "md").status_code == 401
    with signed_client(stage, role) as client:
        detail = client.get(f"/api/ideation/{kind}/{identity}").json()
        for file in detail["exports"]["files"]:
            assert file["available"] and f"--{identity}" in file["path"]
            result = client.get(url + file["format"])
            assert result.status_code == 200
            assert result.content == Path(file["path"]).read_bytes()
            assert "attachment" in result.headers["content-disposition"]
        assert client.get(url + "exe").status_code == 422
    if role != "admin":
        # Reuse the staff but remove access; the download cannot bypass the brand check.
        with stage.factory.begin() as session:
            staff = session.scalar(select(Staff).where(Staff.username == "download-" + role))
            session.query(StaffBrand).filter_by(staff_id=staff.id).delete()
        with client:
            assert client.get(url + "md").status_code == 404


@pytest.mark.parametrize("kind", ["reports", "scripts"])
@pytest.mark.parametrize("attack", ["outside", "parent", "relative", "wrong_suffix", "junction"])
def test_download_rejects_unsafe_stored_paths(stage, exported, tmp_path, kind, attack):
    rid, sid = exported
    model, identity = (IdeationReport, rid) if kind == "reports" else (VideoScript, sid)
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.md"
    secret.write_text("must not download", encoding="utf-8")
    root = stage.settings.export_root
    if attack == "junction":
        import subprocess

        link = root / "linked"
        # Directory junctions do not require Windows symlink privileges.
        if sys.platform == "win32":
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                check=True,
                capture_output=True,
            )
        else:
            link.symlink_to(outside, target_is_directory=True)
        value = str(link / "secret.md")
    else:
        value = {
            "outside": str(secret),
            "parent": str(root / ".." / "outside" / "secret.md"),
            "relative": "../secret.md",
            "wrong_suffix": str(root / "secret.env"),
        }[attack]
    with stage.factory.begin() as session:
        row = session.get(model, identity)
        row.export_json = (
            {"md": value, "revision": row.version + 1} if kind == "scripts" else {"md": value}
        )
    with signed_client(stage) as client:
        result = client.get(f"/api/ideation/{kind}/{identity}/download/md")
        assert result.status_code == 404 and "must not download" not in result.text


def test_legacy_unique_exports_and_failure_reason(stage, exported, monkeypatch):
    rid, sid = exported
    with stage.factory.begin() as session:
        session.get(IdeationReport, rid).export_json = {}
    with signed_client(stage) as client:
        old = client.get(f"/api/ideation/reports/{rid}").json()
        assert all(file["available"] for file in old["exports"]["files"])

    def denied(*args, **kwargs):
        raise PermissionError("secret-token-not-for-output")

    monkeypatch.setattr(ideation_exports, "write_pair", denied)
    ideation_exports.export_script(stage.factory, stage.settings, sid)
    with signed_client(stage, "viewer") as client:
        data = client.get(f"/api/ideation/scripts/{sid}").json()
        assert data["version"] == 1
        assert data["exports"]["error"] == "匯出失敗：沒有寫入權限"
        assert "secret-token" not in json.dumps(data)


def test_export_failure_after_commit_keeps_saved_ideas_successful(stage, monkeypatch):
    from test_stage3 import access

    from app.schemas.ideation import EditIdea
    from app.services import idea_actions

    def denied(*args, **kwargs):
        raise PermissionError("secret-token-not-for-output")

    monkeypatch.setattr(ideation_exports, "write_pair", denied)
    # 主題已提交：匯出失敗只記在 export_json，報告維持 ready 且照常通知。
    rid = complete(stage, monkeypatch)
    ideation.receive_health.push_alert.assert_called_once()
    with stage.factory() as session:
        row = session.get(IdeationReport, rid)
        assert row.status == "ready" and row.error is None
        assert row.export_json["error"] == "匯出失敗：沒有寫入權限"
    edited = {"title": "匯出失敗仍保存", "hook": "開場", "angle": "切角",
              "visual": "畫面", "keyword": "關鍵字"}
    with stage.factory() as session:
        result = idea_actions.edit(
            access(stage, session), rid, 0, EditIdea(version=1, **edited),
            stage.settings, stage.factory,
        )
    assert result["export_error"] == "匯出失敗：沒有寫入權限"
    with stage.factory() as session:
        row = session.get(IdeationReport, rid)
        assert row.data_json["ideas"][0]["title"] == "匯出失敗仍保存"
        assert row.data_json["ideas_revision"] == 2
    with signed_client(stage, "viewer") as client:
        data = client.get(f"/api/ideation/reports/{rid}").json()
        assert data["exports"]["error"] == "匯出失敗：沒有寫入權限"
        assert "secret-token" not in json.dumps(data)


def test_legacy_quote_uses_database_identity_not_saved_url(stage, exported):
    rid, sid = exported
    with stage.factory.begin() as session:
        row = session.get(IdeationReport, rid)
        data = json.loads(json.dumps(row.data_json))
        for group in data["groups"]:
            for quote in group["quotes"]:
                quote["url"] = "https://wrong-origin.invalid/?view=ideation&message_id=123"
                for key in ("kind", "thread_id", "post_id"):
                    quote.pop(key, None)
        row.data_json = data
    with signed_client(stage) as client:
        report = client.get(f"/api/ideation/reports/{rid}").json()
        quotes = [q for g in report["data"]["groups"] for q in g["quotes"]]
        script = client.get(f"/api/ideation/scripts/{sid}").json()
        assert all(
            q["thread_id"] == stage.thread and q["kind"] == "comment_thread" and "url" not in q
            for q in quotes + script["quotes"]
        )


@pytest.mark.migration
def test_migration_0020_preserves_existing_report_content(settings):
    from alembic import command
    from alembic.config import Config

    config = Config(str(REPO_ROOT / "backend/alembic.ini"))
    command.upgrade(config, "0019")
    stamp = utc_now().isoformat(timespec="microseconds")
    from app.db import build_engine, session_factory

    engine = build_engine(settings)
    with session_factory(engine).begin() as session:
        session.add(Brand(id=1, slug="migration", name="isolated"))
    engine.dispose()
    with sqlite3.connect(settings.database_path) as db:
        db.execute(
            """INSERT INTO ideation_reports
            (id, brand_id, meeting_at, start_at, end_at, trigger, provider, status,
             data_json, notification_status, created_at, updated_at)
            VALUES (1, 1, ?, ?, ?, 'manual', 'test', 'ready', ?, 'suppressed', ?, ?)""",
            (stamp, stamp, stamp, '{"legacy":"preserved"}', stamp, stamp),
        )
    command.upgrade(config, "0020")
    uri = settings.database_path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        row = db.execute(
            "SELECT data_json, export_json FROM ideation_reports WHERE id=1"
        ).fetchone()
        assert json.loads(row[0]) == {"legacy": "preserved"}
        assert json.loads(row[1]) == {}
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0020"
    command.upgrade(config, "head")
    command.check(config)

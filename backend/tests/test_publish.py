"""Publisher contract tests: all provider calls use MockTransport and synthetic media."""

import io
import json
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
from alembic import command
from alembic.config import Config
from conftest import login as shared_login
from cryptography.fernet import Fernet
from fastapi import HTTPException
from PIL import Image
from publish_http_mock import PlatformMock, jpeg_bytes, seed_connections, video_bytes
from pydantic import SecretStr
from sqlalchemy import insert, inspect, select

from app.api.permissions import require_role
from app.config import REPO_ROOT
from app.models import (
    Account,
    AuditLog,
    Brand,
    NotificationDelivery,
    OAuthConnection,
    PublishLink,
    PublishMedia,
    PublishPost,
    PublishTarget,
    Setting,
    Staff,
    StaffBrand,
)
from app.models.base import utc_now
from app.models.ideation import IdeationReport, VideoScript
from app.services import notify, publish, publish_media, publish_platforms, publish_rules
from app.services.passwords import hash_password


@pytest.fixture
def ready(client, settings, monkeypatch):
    settings.account_encryption_key = SecretStr(Fernet.generate_key().decode())
    settings.webhook_public_url = "https://public.example.test/webhook/meta-inbound"
    settings.publish_poll_seconds = 0.01
    settings.publish_poll_timeout = 0.03
    mock = PlatformMock()
    monkeypatch.setattr(publish_platforms, "client_factory", mock.client)
    password = SecretStr("isolated-publish-password")
    with client.app.state.session_factory.begin() as session:
        brand = Brand(slug="publish", name="隔離品牌")
        staff = Staff(
            username="publisher",
            display_name="隔離管理員",
            role="admin",
            password_hash=hash_password(password),
        )
        session.add_all([brand, staff])
        session.flush()
        seed_connections(session, settings, brand.id)
        session.add(
            Setting(
                key=notify.policy_key(brand.id),
                value_json={"enabled": True, "group_id": "C" + "1" * 32},
            )
        )
        brand_id = brand.id
    client.headers.update(
        shared_login(client, "publisher", password.get_secret_value(), origin=None)
    )
    assert (
        client.put("/api/publish/switch", json={"enabled": True, "confirmed": True}).status_code
        == 200
    )
    return client, brand_id, mock


def create(
    ready, format="text", platforms=None, caption="隔離發佈", unpublished=None, options=None
):
    client, brand, _ = ready
    response = client.post(
        "/api/publish/posts",
        json={
            "brand_id": brand,
            "format": format,
            "platforms": platforms or ["facebook", "threads"],
            "caption": caption,
            **({"platform_options": options} if options is not None else {}),
            **({} if unpublished is None else {"facebook_unpublished": unpublished}),
        },
    )
    assert response.status_code == 201, response.text
    post = response.json()
    if format != "text":
        for index in range(2 if format == "carousel" else 1):
            response = client.post(
                f"/api/publish/posts/{post['id']}/media?filename=media{index}.mp4",
                content=video_bytes() if format == "video" else jpeg_bytes(),
                headers={"Content-Type": "application/octet-stream"},
            )
            assert response.status_code == 200, response.text
            post = response.json()
    return post


def seed_idea(ready, with_script=True):
    client, brand_id, _ = ready
    with client.app.state.session_factory.begin() as session:
        report = IdeationReport(
            brand_id=brand_id,
            meeting_at=utc_now(),
            start_at=utc_now(),
            end_at=utc_now(),
            trigger="manual",
            provider="fixture",
            status="ready",
            data_json={
                "ideas": [
                    {"title": "隔離主題", "hook": "隔離開場", "keyword": "服務、現場/服務,空間"}
                ]
            },
        )
        session.add(report)
        session.flush()
        if with_script:
            session.add(
                VideoScript(
                    brand_id=brand_id,
                    report_id=report.id,
                    topic_index=0,
                    title="隔離腳本",
                    content_json={"ending": "隔離結尾"},
                    review_json={},
                    provider="fixture",
                    model="fixture",
                )
            )
        return report.id


@pytest.mark.parametrize("with_script", [False, True])
def test_idea_draft_caption_is_plain_initial_text_without_ai(ready, monkeypatch, with_script):
    from app.services import ai
    from app.services.ai import providers

    # 建立草稿不呼叫任何 AI；即使主題已有腳本，也不參考腳本結尾。
    monkeypatch.setattr(ai, "run", lambda *a, **k: pytest.fail("Draft creation must not call AI"))
    monkeypatch.setattr(providers, "call_api", lambda *a: pytest.fail("Draft must not call AI"))
    client, _, mock = ready
    report_id = seed_idea(ready, with_script)
    response = client.post(
        "/api/publish/ideation-draft", json={"report_id": report_id, "idea_index": 0}
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["created"]
    post = result["post"]
    expected = "隔離主題\n\n隔離開場\n\n#服務 #現場 #空間"
    assert post["caption"] == expected and "隔離結尾" not in post["caption"]
    assert "caption_job" not in post
    assert (post["status"], post["format"], post["source"]) == ("draft", "video", "ideation")
    assert (post["report_id"], post["idea_index"]) == (report_id, 0)
    assert post["platforms"] == ["facebook", "instagram", "threads"]
    with client.app.state.session_factory() as session:
        log = session.scalar(select(AuditLog).where(AuditLog.action == "publish.from_idea"))
        assert log.detail_json == {"report_id": report_id, "idea_index": 0}
        assert expected not in json.dumps(log.detail_json, ensure_ascii=False)
        assert session.scalar(select(PublishPost.caption_job_json)) == {}
    assert mock.calls == []


def test_removed_publish_ai_routes_are_gone(ready):
    client, _, _ = ready
    report_id = seed_idea(ready)
    post = client.post(
        "/api/publish/ideation-draft", json={"report_id": report_id, "idea_index": 0}
    ).json()["post"]
    path = f"/api/publish/posts/{post['id']}"
    body = {"confirmed": True, "version": post["version"]}
    assert client.get(
        f"/api/publish/ideation-preview?report_id={report_id}&idea_index=0"
    ).status_code in {404, 405}
    assert client.post(path + "/caption/retry").status_code in {404, 405}
    assert client.post(path + "/caption/apply", json=body).status_code in {404, 405}


def test_legacy_caption_job_data_is_neither_shown_nor_changed(ready):
    client, brand, _ = ready
    legacy = {"id": "old", "status": "ready", "caption": "舊 AI 候選", "applied": False,
              "started_at": "2026-01-01T00:00:00+00:00", "prompt": "舊提示"}
    with client.app.state.session_factory.begin() as session:
        creator = session.scalar(select(Staff.id).where(Staff.username == "publisher"))
        pending = PublishPost(brand_id=brand, creator_id=creator, format="video", caption="",
                              source="ideation", report_id=1, idea_index=0,
                              caption_job_json={**legacy, "status": "pending"})
        done = PublishPost(brand_id=brand, creator_id=creator, format="video",
                           caption="人工文案", platforms_json=["facebook"],
                           caption_job_json=legacy)
        session.add_all([pending, done])
        session.flush()
        pending_id, done_id = pending.id, done.id
    rows = client.get(f"/api/publish/posts?brand_id={brand}").json()
    # 只剩舊 AI 工作、沒有任何內容的空白草稿不再顯示；其他草稿不帶任何 AI 狀態。
    assert [row["id"] for row in rows] == [done_id]
    assert all("caption_job" not in row for row in rows)
    detail = client.get(f"/api/publish/posts/{done_id}").json()
    assert "caption_job" not in detail
    assert "舊 AI 候選" not in json.dumps(detail, ensure_ascii=False)
    assert client.get(f"/api/publish/posts/{pending_id}").status_code == 200
    body = {"brand_id": brand, "format": "video", "caption": "人工改寫", "captions": {},
            "platforms": ["facebook"], "media_ids": [], "version": detail["version"]}
    saved = client.put(f"/api/publish/posts/{done_id}", json=body)
    assert saved.status_code == 200 and saved.json()["caption"] == "人工改寫"
    assert "caption_job" not in saved.json()
    with client.app.state.session_factory() as session:
        assert session.get(PublishPost, done_id).caption_job_json == legacy


@pytest.mark.parametrize(
    "keyword,expected",
    [
        (" A、B,C/D E F G", "#A #B #C #D #E"),
        ("#服務 ##服務,服務/現場、現場", "#服務 #現場"),
        ("!@@、#、🙂 / \t", ""),
        ("客!製_方-案、C++/１２３,空間。測試", "#客製方案 #C #１２３ #空間測試"),
        ("甲，乙／丙\n丁\t戊 己", "#甲 #乙 #丙 #丁 #戊"),
    ],
)
def test_idea_hashtags(keyword, expected):
    assert publish.idea_caption({"keyword": keyword}) == expected


def test_idea_caption_never_truncates():
    text = "文" * 64000
    assert publish.idea_caption({"title": text, "hook": text}, text) == "\n\n".join([text] * 3)


@pytest.mark.parametrize("status", ["draft", "scheduled", "paused", "missed"])
def test_idea_reuses_unpublished_draft(ready, status):
    client, _, mock = ready
    report_id = seed_idea(ready)
    body = {"report_id": report_id, "idea_index": 0}
    first = client.post("/api/publish/ideation-draft", json=body).json()["post"]
    with client.app.state.session_factory.begin() as session:
        post = session.get(PublishPost, first["id"])
        post.status = status
        post.caption = "人工修改保留"
    # 舊畫面仍可能帶 include_script；欄位被忽略，行為不變。
    second = client.post(
        "/api/publish/ideation-draft", json={**body, "include_script": False}
    ).json()
    assert not second["created"]
    assert second["post"]["id"] == first["id"]
    assert second["post"]["caption"] == "人工修改保留"
    with client.app.state.session_factory() as session:
        assert len(list(session.scalars(select(PublishPost)))) == 1
        assert (
            len(
                list(
                    session.scalars(select(AuditLog).where(AuditLog.action == "publish.from_idea"))
                )
            )
            == 1
        )
    assert mock.calls == []


def test_idea_after_done_can_create_again(ready):
    client, _, _ = ready
    report_id = seed_idea(ready)
    body = {"report_id": report_id, "idea_index": 0}
    first = client.post("/api/publish/ideation-draft", json=body).json()["post"]
    with client.app.state.session_factory.begin() as session:
        session.get(PublishPost, first["id"]).status = "done"
    second = client.post("/api/publish/ideation-draft", json=body).json()
    assert second["created"] and second["post"]["id"] != first["id"]


def test_idea_only_defaults_ready_platforms(ready):
    client, _, _ = ready
    report_id = seed_idea(ready)
    with client.app.state.session_factory.begin() as session:
        for connection in session.scalars(select(OAuthConnection)):
            connection.cache_json = {}
    response = client.post(
        "/api/publish/ideation-draft",
        json={"report_id": report_id, "idea_index": 0},
    )
    assert response.status_code == 200
    assert response.json()["post"]["platforms"] == []


@pytest.mark.parametrize(
    "role,assigned,expected",
    [("viewer", True, 403), ("marketing", False, 404), ("marketing", True, 200)],
)
def test_idea_roles_and_brand_scope(ready, role, assigned, expected):
    client, brand_id, _ = ready
    report_id = seed_idea(ready)
    with client.app.state.session_factory.begin() as session:
        staff = session.scalar(select(Staff).where(Staff.username == "publisher"))
        staff.role = role
        if assigned:
            session.add(StaffBrand(staff_id=staff.id, brand_id=brand_id))
    response = client.post(
        "/api/publish/ideation-draft",
        json={"report_id": report_id, "idea_index": 0},
    )
    assert response.status_code == expected


def test_idea_csrf_and_invalid_source(ready):
    client, _, _ = ready
    report_id = seed_idea(ready)
    body = {"report_id": report_id, "idea_index": 0}
    csrf = client.headers.pop("X-CSRF-Token")
    assert client.post("/api/publish/ideation-draft", json=body).status_code == 403
    client.headers["X-CSRF-Token"] = csrf
    for value in (-1, 10):
        assert client.post(
            "/api/publish/ideation-draft", json={**body, "idea_index": value}
        ).status_code in {404, 422}
    with client.app.state.session_factory.begin() as session:
        session.get(IdeationReport, report_id).status = "deleted"
    assert client.post("/api/publish/ideation-draft", json=body).status_code == 404


def test_idea_draft_discovery_is_not_limited_by_recent_posts(ready):
    client, brand_id, _ = ready
    report_id = seed_idea(ready)
    body = {"report_id": report_id, "idea_index": 0}
    first = client.post("/api/publish/ideation-draft", json=body).json()["post"]
    with client.app.state.session_factory.begin() as session:
        creator = session.scalar(select(Staff.id).where(Staff.username == "publisher"))
        session.add_all(
            [
                PublishPost(
                    brand_id=brand_id, creator_id=creator, format="text", caption="隔離歷史"
                )
                for _ in range(201)
            ]
        )
    rows = client.get(f"/api/publish/posts?brand_id={brand_id}&report_id={report_id}").json()
    assert [row["id"] for row in rows] == [first["id"]]
    assert client.post("/api/publish/ideation-draft", json=body).json()["post"]["id"] == first["id"]


def test_concurrent_idea_creation_reuses_draft(ready, settings):
    from concurrent.futures import ThreadPoolExecutor

    from app.schemas.publish import IdeaDraftInput
    from app.services.access import BrandAccess

    client, _, mock = ready
    report_id = seed_idea(ready)
    body = IdeaDraftInput(report_id=report_id, idea_index=0)

    def run():
        with client.app.state.session_factory() as session:
            staff = session.scalar(select(Staff).where(Staff.username == "publisher"))
            return publish.from_idea(BrandAccess(session, staff), settings, body)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: run(), range(2)))
    assert len({r["post"]["id"] for r in results}) == 1
    assert sorted(r["created"] for r in results) == [False, True]
    assert mock.calls == []


def action(client, post, endpoint="submit", when=None):
    return client.post(
        f"/api/publish/posts/{post['id']}/{endpoint}",
        json={
            "confirmed": True,
            "version": post["version"],
            "scheduled_at": when.isoformat() if when else None,
        },
    )


@pytest.mark.parametrize(
    "platform,format",
    [
        (p, f)
        for p in ("facebook", "instagram", "threads")
        for f in ("text", "image", "carousel", "video")
        if (p, f) != ("instagram", "text")
    ],
)
def test_platform_formats(ready, platform, format):
    client, _, mock = ready
    post = create(ready, format, [platform])
    assert action(client, post).status_code == 200
    result = client.get(f"/api/publish/posts/{post['id']}").json()
    assert result["status"] == "done", result
    assert result["targets"][0]["status"] == "succeeded"
    assert result["targets"][0]["permalink"].startswith("https://")
    if platform != "facebook":
        edges = [path for method, _, path in mock.calls if method == "POST"]
        assert any(
            path.endswith("/threads_publish" if platform == "threads" else "/media_publish")
            for path in edges
        )
        with client.app.state.session_factory() as session:
            assert all(row.revoked_at for row in session.scalars(select(PublishLink)))


def test_success_queues_metrics_sync_but_failure_does_not(ready, monkeypatch):
    # 發佈成功後立刻排一輪成效同步，新貼文不用等到下一個整點才出現在貼文數據。
    from app.services import scheduler

    client, _, mock = ready
    requested = []

    class Fake:
        def request(self, name, options=None):
            requested.append(name)

    monkeypatch.setattr(scheduler, "scheduler_for", lambda settings: Fake())
    mock.fail_threads = True
    failed = create(ready, platforms=["threads"])
    assert action(client, failed).status_code == 200
    assert client.get(f"/api/publish/posts/{failed['id']}").json()["status"] == "failed"
    assert requested == []
    mock.fail_threads = False
    post = create(ready, platforms=["facebook"])
    assert action(client, post).status_code == 200
    assert client.get(f"/api/publish/posts/{post['id']}").json()["status"] == "done"
    assert requested == ["metrics"]


def test_partial_retry_never_repeats_success(ready):
    client, _, mock = ready
    post = create(ready)
    mock.fail_threads = True
    assert action(client, post).status_code == 200
    post = client.get(f"/api/publish/posts/{post['id']}").json()
    assert post["status"] == "partial"
    before = len([c for c in mock.calls if c[1] == "graph.facebook.com"])
    mock.fail_threads = False
    assert action(client, post, "retry").status_code == 200
    post = client.get(f"/api/publish/posts/{post['id']}").json()
    assert post["status"] == "done"
    assert len([c for c in mock.calls if c[1] == "graph.facebook.com"]) == before
    assert [t["attempts"] for t in post["targets"]] == [1, 2]
    assert action(client, post, "retry").status_code == 409


def test_edit_cancelled_schedule_does_not_send_removed_platform(ready):
    client, brand, mock = ready
    post = create(ready)
    assert action(client, post, when=utc_now() + timedelta(hours=1)).status_code == 200
    assert client.post(f"/api/publish/posts/{post['id']}/cancel").status_code == 200
    post = client.get(f"/api/publish/posts/{post['id']}").json()
    response = client.put(
        f"/api/publish/posts/{post['id']}",
        json={
            "brand_id": brand,
            "format": "text",
            "caption": "修改排程",
            "platforms": ["facebook"],
            "version": post["version"],
        },
    )
    assert response.status_code == 200
    assert action(client, response.json()).status_code == 200
    assert not any(host == "graph.threads.net" for _, host, _ in mock.calls)
    result = client.get(f"/api/publish/posts/{post['id']}").json()
    assert result["status"] == "done" and len(result["targets"]) == 1


def test_duplicate_worker_claim_and_readiness_exception_are_safe(ready, monkeypatch):
    client, _, mock = ready
    post = create(ready, platforms=["facebook"])
    original = publish_platforms.publish

    def competing_worker(*args, **kwargs):
        publish.execute(client.app.state.session_factory, client.app.state.settings, post["id"])
        return original(*args, **kwargs)

    monkeypatch.setattr(publish_platforms, "publish", competing_worker)
    action(client, post)
    assert len([call for call in mock.calls if call[0] == "POST"]) == 1
    post = create(ready, platforms=["facebook"])
    original_ready = publish.oauth.publish_readiness

    def readiness(session, settings, *, cached=False):
        if cached:
            return original_ready(session, settings, cached=True)
        raise RuntimeError("private-platform-error isolated-publish-token")

    monkeypatch.setattr(publish.oauth, "publish_readiness", readiness)
    before = len(mock.calls)
    action(client, post)
    result = client.get(f"/api/publish/posts/{post['id']}").json()
    assert result["status"] == "failed" and result["targets"][0]["error_code"] == "not_ready"
    assert len(mock.calls) == before


def test_brand_scope_and_viewer_records(ready):
    client, brand, _ = ready
    post = create(ready)
    action(client, post)
    draft = create(ready)
    factory = client.app.state.session_factory
    with factory.begin() as session:
        staff = session.scalar(select(Staff).where(Staff.username == "publisher"))
        staff.role = "marketing"
        session.add(StaffBrand(staff_id=staff.id, brand_id=brand))
        other = Brand(slug="unassigned-publish", name="隔離未指派品牌")
        session.add(other)
        session.flush()
        other_id = other.id
    assert client.get(f"/api/publish/options?brand_id={other_id}").status_code == 404
    assert client.post("/api/publish/posts", json={"brand_id": other_id}).status_code == 404
    assert (
        client.put("/api/publish/switch", json={"confirmed": True, "enabled": False}).status_code
        == 403
    )
    assert client.get(f"/api/publish/posts/{draft['id']}").status_code == 200
    with factory.begin() as session:
        session.scalar(select(Staff).where(Staff.username == "publisher")).role = "viewer"
    assert [row["id"] for row in client.get("/api/publish/posts").json()] == [post["id"]]
    assert client.get(f"/api/publish/posts/{draft['id']}").status_code == 404
    assert action(client, draft).status_code == 403


def test_timeout_and_permalink_failure(ready, monkeypatch):
    client, _, mock = ready
    post = create(ready, "video", ["instagram"])
    mock.poll_forever = True
    action(client, post)
    result = client.get(f"/api/publish/posts/{post['id']}").json()
    assert result["targets"][0]["error_code"] == "timeout"
    assert not any(c[2].endswith("/media_publish") for c in mock.calls)
    mock.poll_forever = False
    original = mock.handler

    def fail_permalink(request):
        if request.url.params.get("fields") == "permalink":
            return httpx.Response(400, json={"error": {"message": "private-error"}})
        return original(request)

    monkeypatch.setattr(mock, "handler", fail_permalink)
    action(client, result, "retry")
    result = client.get(f"/api/publish/posts/{post['id']}").json()
    assert result["status"] == "done" and result["targets"][0]["permalink"] is None


def test_recovery_no_automatic_resend(ready):
    client, _, mock = ready
    post = create(ready)
    factory = client.app.state.session_factory
    with factory.begin() as session:
        row = session.get(PublishPost, post["id"])
        row.status = "publishing"
        account = publish.accounts(session, client.app.state.settings, row.brand_id)["facebook"]
        session.add(
            PublishTarget(
                post_id=row.id,
                platform="facebook",
                account_id=account.id,
                status="publishing",
                attempts=1,
            )
        )
    publish.recover(factory)
    publish.tick(factory, client.app.state.settings, wait=True)
    assert mock.calls == []
    result = client.get(f"/api/publish/posts/{post['id']}").json()
    assert result["status"] == "failed" and result["targets"][0]["error_code"] == "interrupted"


def test_unexpected_errors_still_settle_the_post(ready, monkeypatch):
    import threading

    client, _, mock = ready
    factory, settings = client.app.state.session_factory, client.app.state.settings
    post = create(ready, platforms=["facebook"])
    original = publish.media_rows

    def master_key_changed(session, identity):
        # 只在發佈執行緒的第一段交易內出錯，模擬主金鑰更換後無法解密（503）或資料庫忙碌。
        if threading.current_thread().name.startswith("publish_"):
            raise HTTPException(503, "無法解密")
        return original(session, identity)

    monkeypatch.setattr(publish, "media_rows", master_key_changed)
    assert action(client, post).status_code == 200
    result = client.get(f"/api/publish/posts/{post['id']}").json()
    assert result["status"] == "failed", result
    assert [(t["status"], t["error_code"], t["attempts"]) for t in result["targets"]] == [
        ("failed", "unknown", 0)
    ]
    assert not [c for c in mock.calls if c[0] == "POST"]
    with factory() as session:
        assert not publish.locked(session.get(PublishPost, post["id"]))
    monkeypatch.setattr(publish, "media_rows", original)
    assert action(client, result, "retry").status_code == 200
    assert client.get(f"/api/publish/posts/{post['id']}").json()["status"] == "done"

    # execute_target 本身拋錯（排程路徑）：貼文仍結算，不卡在發佈中，其他工作照常。
    late = create(ready, platforms=["facebook"])
    when = utc_now() + timedelta(minutes=2)
    assert action(client, late, when=when).status_code == 200

    def crash(*args):
        raise RuntimeError("isolated-unexpected")

    monkeypatch.setattr(publish, "execute_target", crash)
    assert publish.tick(factory, settings, when + timedelta(seconds=1), wait=True)["ok"]
    result = client.get(f"/api/publish/posts/{late['id']}").json()
    assert result["status"] == "failed"
    assert [(t["status"], t["error_code"]) for t in result["targets"]] == [("failed", "unknown")]


def test_cancelled_retry_never_sends_platforms_outside_the_new_selection(ready):
    client, brand, mock = ready
    post = create(ready, "image", ["facebook", "instagram", "threads"])
    original = mock.handler

    def fail_instagram(request):
        if request.method == "POST" and "/200/" in request.url.path:
            return httpx.Response(429, json={"error": {"code": 4, "message": "isolated"}})
        return original(request)

    mock.handler, mock.fail_facebook = fail_instagram, True
    assert action(client, post).status_code == 200
    post = client.get(f"/api/publish/posts/{post['id']}").json()
    assert post["status"] == "partial"
    assert {t["platform"]: t["status"] for t in post["targets"]} == {
        "facebook": "failed",
        "instagram": "failed",
        "threads": "succeeded",
    }
    mock.handler, mock.fail_facebook = original, False

    def facebook_posts():
        return [c for c in mock.calls if c[0] == "POST" and "/100/" in c[2]]

    sent = len(facebook_posts())
    later = utc_now() + timedelta(hours=1)
    assert action(client, post, "retry", when=later).status_code == 200
    assert client.post(f"/api/publish/posts/{post['id']}/cancel").status_code == 200
    post = client.get(f"/api/publish/posts/{post['id']}").json()
    # 取消後嘗試過的平台回到失敗，仍可「只重試失敗平台」（不再回 422）。
    assert {t["platform"]: t["status"] for t in post["targets"]} == {
        "facebook": "failed",
        "instagram": "failed",
        "threads": "succeeded",
    }
    assert action(client, post, "retry", when=later).status_code == 200
    assert client.post(f"/api/publish/posts/{post['id']}/cancel").status_code == 200
    post = client.get(f"/api/publish/posts/{post['id']}").json()
    response = client.put(
        f"/api/publish/posts/{post['id']}",
        json={
            "brand_id": brand,
            "format": "image",
            "caption": post["caption"],
            "platforms": ["instagram", "threads"],
            "media_ids": [m["id"] for m in post["media"]],
            "version": post["version"],
        },
    )
    assert response.status_code == 200, response.json()
    assert action(client, response.json()).status_code == 200
    assert len(facebook_posts()) == sent
    result = client.get(f"/api/publish/posts/{post['id']}").json()
    statuses = {t["platform"]: t["status"] for t in result["targets"]}
    assert statuses["instagram"] == "succeeded" and statuses["facebook"] == "failed"
    # 已移除的平台也不會被「只重試失敗平台」選回來。
    assert action(client, result, "retry").status_code == 422
    assert len(facebook_posts()) == sent


def test_scheduled_publish_runs_off_the_scheduler_thread(ready, monkeypatch):
    import threading

    client, _, _ = ready
    factory, settings = client.app.state.session_factory, client.app.state.settings
    now = utc_now()
    first, second = create(ready), create(ready)
    assert action(client, first, when=now + timedelta(minutes=2)).status_code == 200
    assert action(client, second, when=now + timedelta(minutes=3)).status_code == 200
    release, finished = threading.Event(), threading.Semaphore(0)
    original = publish.execute

    def slow_upload(factory, settings, identity):
        release.wait(10)
        try:
            original(factory, settings, identity)
        finally:
            finished.release()

    monkeypatch.setattr(publish, "execute", slow_upload)
    assert publish.tick(factory, settings, now + timedelta(minutes=2, seconds=1))["published"] == 1
    # 第一篇還在上傳，下一分鐘的排程照常執行：第二篇開始發佈，不會被標成已錯過。
    assert publish.tick(factory, settings, now + timedelta(minutes=3, seconds=1))["published"] == 1
    assert client.get(f"/api/publish/posts/{second['id']}").json()["status"] == "publishing"
    release.set()
    assert finished.acquire(timeout=10) and finished.acquire(timeout=10)
    for row in (first, second):
        assert client.get(f"/api/publish/posts/{row['id']}").json()["status"] == "done"


def test_switch_schedule_missed_lock(ready, monkeypatch):
    client, _, mock = ready
    factory, settings = client.app.state.session_factory, client.app.state.settings
    now = utc_now()
    post = create(ready)
    assert action(client, post, when=now + timedelta(minutes=10)).status_code == 200
    client.put("/api/publish/switch", json={"enabled": False, "confirmed": True})
    assert client.get(f"/api/publish/posts/{post['id']}").json()["status"] == "paused"
    immediate = create(ready)
    assert action(client, immediate).status_code == 409
    client.put("/api/publish/switch", json={"enabled": True, "confirmed": True})
    assert client.get(f"/api/publish/posts/{post['id']}").json()["status"] == "scheduled"
    with factory.begin() as session:
        session.get(PublishPost, post["id"]).scheduled_at = now + timedelta(seconds=50)
    assert client.post(f"/api/publish/posts/{post['id']}/cancel").status_code == 409
    publish.tick(factory, settings, now + timedelta(minutes=2), wait=True)
    assert client.get(f"/api/publish/posts/{post['id']}").json()["status"] == "done"
    before = len(mock.calls)
    late = create(ready)
    assert action(client, late, when=now + timedelta(minutes=10)).status_code == 200
    publish.tick(factory, settings, now + timedelta(minutes=16), wait=True)
    assert client.get(f"/api/publish/posts/{late['id']}").json()["status"] == "missed"
    assert len(mock.calls) == before
    paused = create(ready)
    action(client, paused, when=now + timedelta(minutes=10))
    client.put("/api/publish/switch", json={"enabled": False, "confirmed": True})
    monkeypatch.setattr(publish, "utc_now", lambda: now + timedelta(minutes=11))
    client.put("/api/publish/switch", json={"enabled": True, "confirmed": True})
    assert client.get(f"/api/publish/posts/{paused['id']}").json()["status"] == "missed"


def test_media_capability_range_and_limits(ready):
    client, _, _ = ready
    post = create(ready, "video", ["facebook"])
    factory, settings = client.app.state.session_factory, client.app.state.settings
    with factory.begin() as session:
        media = session.get(PublishMedia, post["media"][0]["id"])
        identity, url = publish_media.create_link(session, settings, media)
        session.get(PublishLink, identity).max_uses = 3
    token = url.rsplit("/", 1)[1]
    path = "/media/" + token
    headers = {"X-Mwb-Public": "1"}
    result = client.get(path, headers=headers)
    assert result.status_code == 200 and result.content == video_bytes()
    assert result.headers["content-type"] == "video/mp4"
    assert result.headers["cache-control"] == "no-store"
    assert result.headers["x-content-type-options"] == "nosniff"
    for value, wanted in [("bytes=0-7", video_bytes()[:8]), ("bytes=-8", video_bytes()[-8:])]:
        result = client.get(path, headers={**headers, "Range": value})
        assert result.status_code == 206 and result.content == wanted
        assert result.headers["content-length"] == "8"
    # 中段的分段請求（續傳）不計入次數；只有從頭開始的下載才計次（目前 2／3）。
    for _ in range(5):
        assert client.get(path, headers={**headers, "Range": "bytes=8-15"}).status_code == 206
    assert client.get(path, headers=headers).status_code == 200
    assert client.get(path, headers=headers).status_code == 404
    for mode in ("expired", "revoked", "invalid_range"):
        with factory.begin() as session:
            link = session.get(PublishLink, identity)
            link.uses = 0
            link.expires_at = (
                utc_now() - timedelta(seconds=1)
                if mode == "expired"
                else utc_now() + timedelta(minutes=1)
            )
            link.revoked_at = utc_now() if mode == "revoked" else None
        assert client.get(path, headers={**headers, "Range": "bytes=9999-"}).status_code == (
            416 if mode == "invalid_range" else 404
        )
    for path in (
        "/media",
        "/media/",
        "/media/short",
        "/media/../api/health",
        "/media/%2e%2e/api/health",
        "/media/%252e%252e/api/health",
        "/api/health",
        "/media/" + token + "/",
        "/media/" + "a" * 43,
    ):
        assert client.get(path, headers=headers).status_code == 404, path


def test_upload_spoof_metadata_and_cleanup(ready, tmp_path):
    client, _, _ = ready
    post = create(ready)
    result = client.post(
        f"/api/publish/posts/{post['id']}/media?filename=fake.mp4", content=b"<html>" + b"x" * 80
    )
    assert result.status_code == 422
    for version in (0, 1):
        path = tmp_path / f"video{version}"
        path.write_bytes(video_bytes(version=version, rotated=True))
        assert publish_media.metadata(path) == ("video/mp4", 1920, 1080, 12.0)
    post = create(ready, "image", ["facebook"])
    action(client, post)
    factory, settings = client.app.state.session_factory, client.app.state.settings
    with factory.begin() as session:
        session.get(PublishPost, post["id"]).completed_at = utc_now() - timedelta(days=31)
        media = session.get(PublishMedia, post["media"][0]["id"])
        path = publish_media.path_for(settings, media)
    assert publish.cleanup_media(factory, settings, utc_now()) == 1
    assert not path.exists()
    assert client.get(f"/api/publish/posts/{post['id']}").json()["status"] == "done"


def test_upload_waits_for_write_lock_off_event_loop(ready):
    """持鎖者要靠事件迴圈才能放鎖（例如請求 session 收尾）；上傳等鎖時不可佔住事件迴圈。"""
    import asyncio
    import sqlite3

    client, _, _ = ready
    post = create(ready, "carousel", ["facebook"])
    holder = sqlite3.connect(
        client.app.state.settings.database_path, isolation_level=None, check_same_thread=False
    )
    holder.execute("BEGIN IMMEDIATE")

    async def scenario():
        async def release():
            await asyncio.sleep(0.5)
            holder.execute("COMMIT")

        transport = httpx.ASGITransport(app=client.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={
                **client.headers,
                "Cookie": "; ".join(f"{k}={v}" for k, v in client.cookies.items()),
            },
        ) as http:
            upload = http.post(
                f"/api/publish/posts/{post['id']}/media?filename=late.jpg",
                content=jpeg_bytes(),
                headers={"Content-Type": "application/octet-stream"},
            )
            response, _ = await asyncio.gather(upload, release())
            return response

    try:
        response = asyncio.run(scenario())
    finally:
        holder.close()
    # 舊版在事件迴圈上等鎖：release 排不到，三次 busy_timeout 後回 503。
    assert response.status_code == 200, response.text
    assert [m["name"] for m in response.json()["media"]][-1] == "late.jpg"


@pytest.mark.parametrize(
    "platform,format,caption,media,expected",
    [
        ("instagram", "text", "文字", [], "不支援"),
        ("threads", "text", "a" * 501, [], "500"),
        ("facebook", "text", "a" * 63207, [], "63,206"),
        ("instagram", "image", "a" * 2201, ["image"], "2,200"),
        ("instagram", "image", " ".join("#x" for _ in range(31)), ["image"], "30"),
        ("threads", "text", "#a #b", [], "first-topic-warning"),
        ("threads", "text", "#" + "a" * 51, [], "最多 50 字"),
        ("instagram", "carousel", "", ["image"], "2–10"),
        ("threads", "carousel", "", ["image"] * 21, "2–20"),
        ("facebook", "carousel", "", ["image"] * 11, "2–10"),
        ("instagram", "image", "", ["png"], "png-warning"),
        ("instagram", "image", "", ["gif"], "JPEG 或 PNG"),
        ("instagram", "image", "", ["wide"], "比例"),
        ("instagram", "image", "", ["small"], "320"),
        ("threads", "video", "", ["long"], "300"),
        ("instagram", "video", "", ["short"], "3–900"),
        ("facebook", "video", "", ["fb_long"], "1200"),
        ("instagram", "video", "", ["video_wide"], "1920"),
        ("instagram", "video", "", ["video_ratio"], "比例"),
        ("threads", "image", "", ["tiny_ratio"], "比例"),
        ("facebook", "image", "", ["video"], "型別"),
        ("facebook", "image", "", ["big"], "8 MB"),
        ("threads", "video", "", ["huge"], "1 GB"),
        ("facebook", "carousel", "", ["video", "video"], "僅支援圖片"),
    ],
    ids=lambda value: value[:24] if isinstance(value, str) else None,
)
def test_rules(platform, format, caption, media, expected):
    defaults = dict(mime="image/jpeg", width=1080, height=1080, size=100, duration=None)
    variants = {
        "image": {},
        "png": {"mime": "image/png"},
        "gif": {"mime": "image/gif"},
        "wide": {"width": 4000},
        "small": {"width": 100},
        "big": {"size": 9 * 1024**2},
        "video": {"mime": "video/mp4", "duration": 12},
        "long": {"mime": "video/mp4", "duration": 301},
        "short": {"mime": "video/mp4", "duration": 2},
        "fb_long": {"mime": "video/mp4", "duration": 1201},
        "video_wide": {"mime": "video/mp4", "duration": 12, "width": 1921},
        "video_ratio": {"mime": "video/mp4", "duration": 12, "height": 200000},
        "tiny_ratio": {"width": 10},
        "huge": {"mime": "video/mp4", "duration": 12, "size": 1024**3 + 1},
    }
    def media_items(names):
        return [SimpleNamespace(**{**defaults, **variants[item]}) for item in names]

    result = publish_rules.check(platform, format, caption, media_items(media))
    if expected == "png-warning":
        # IG 的 PNG 由發佈流程自動轉 JPEG：原本的錯誤改為警告（FB／Threads 本來就沒有此限制）。
        assert result["ok"] and result["warnings"] == [publish_rules.IG_PNG_WARNING]
        for other in ("facebook", "threads"):
            assert not publish_rules.check(other, format, caption, media_items(media))["warnings"]
    elif expected == "first-topic-warning":
        assert result["ok"] and "第一個" in " ".join(result["warnings"])
        assert result["topic_tag"] == "a"
    else:
        assert not result["ok"] and expected in " ".join(result["reasons"])


def test_safety_permissions_and_readiness(ready, caplog):
    client, brand, mock = ready
    post = create(ready)
    mock.fail_threads = True
    action(client, post)
    with client.app.state.session_factory() as session:
        data = [row.detail_json for row in session.scalars(select(AuditLog))]
        deliveries = list(session.scalars(select(NotificationDelivery)))
        assert deliveries and all(notify.is_publish_notice(row) for row in deliveries)
        data += [row.messages_json for row in deliveries]
    text = json.dumps(data) + client.get(f"/api/publish/posts/{post['id']}").text + caplog.text
    for secret in ("isolated-publish-token", "private-platform-error", "private-token"):
        assert secret not in text
    assert "/media/" not in text
    for role in ("viewer", "marketing"):
        with pytest.raises(HTTPException):
            require_role("/api/publish/switch", "PUT", role)
    with pytest.raises(HTTPException):
        require_role("/api/publish/posts", "POST", "viewer")
    post = create(ready)
    before = len(mock.calls)
    with client.app.state.session_factory.begin() as session:
        row = session.scalar(select(OAuthConnection).where(OAuthConnection.platform == "meta"))
        row.cache_json = {"granted": [], "verified": True}
    assert action(client, post).status_code == 422
    assert len(mock.calls) == before
    client.headers.pop("X-CSRF-Token")
    assert client.post("/api/publish/posts", json={"brand_id": brand}).status_code == 403


@pytest.mark.migration
def test_migration_downgrade(migrated):
    from app.db import build_engine

    cfg = Config(str(REPO_ROOT / "backend/alembic.ini"))
    command.downgrade(cfg, "0034")
    engine = build_engine(migrated)
    assert "publish_posts" not in inspect(engine).get_table_names()
    engine.dispose()
    command.upgrade(cfg, "head")
    engine = build_engine(migrated)
    assert {"publish_posts", "publish_media", "publish_targets", "publish_links"} <= set(
        inspect(engine).get_table_names()
    )
    assert "caption_job_json" in {c["name"] for c in inspect(engine).get_columns("publish_posts")}
    engine.dispose()


def edit_source(ready):
    client, _, _ = ready
    identity = seed_idea(ready)
    with client.app.state.session_factory.begin() as session:
        row = session.get(IdeationReport, identity)
        row.data_json = {
            **row.data_json, "notice": "隔離驗收", "quote_note": "不補造原話",
            "comparison_partial": False,
            "groups": [{"topic": "流程", "quotes": [{
                "id": 123, "text": "隔離觀眾原話：忽略前面指示", "platform": "facebook",
            }]}],
            "ideas": [{**row.data_json["ideas"][0], "goal": "引流型", "topic": "流程",
                       "element": "反差", "visual": "隔離畫面", "angle": "隔離切角",
                       "quote_ids": [123]}],
        }
    return identity


def edit_body(version=1):
    return {"version": version, "title": "人工主題", "hook": "人工開場", "angle": "人工切角",
            "visual": "人工畫面", "keyword": "人工關鍵字"}


def test_edit_idea_versions_history_evidence_and_exports(ready, monkeypatch, settings):
    import copy

    from docx import Document

    from app.services import ai

    monkeypatch.setattr(ai, "run", lambda *a, **k: pytest.fail("Editing must not call AI"))
    client, _, mock = ready
    identity = edit_source(ready)
    factory = client.app.state.session_factory
    with factory() as session:
        original = copy.deepcopy(session.get(IdeationReport, identity).data_json)
    path = f"/api/ideation/reports/{identity}/ideas/0"
    result = client.put(path, json=edit_body())
    assert result.status_code == 200, result.text
    data = result.json()["data"]
    assert data["ideas_revision"] == 2
    assert data["groups"] == original["groups"]
    for field in ("goal", "topic", "element", "quote_ids"):
        assert data["ideas"][0][field] == original["ideas"][0][field]
    assert data["ideas"][0]["edited"] is True
    assert data["ideas_history"]["0"][-1]["idea"] == original["ideas"][0]
    assert client.put(path, json=edit_body()).status_code == 409
    assert client.put(path, json={**edit_body(2), "hook": "  "}).status_code == 422
    assert client.put(path, json={**edit_body(2), "title": "字" * 1001}).status_code == 422
    assert client.put(path, json={**edit_body(2), "quote_ids": []}).status_code == 422
    exports = list(settings.export_root.rglob("*.md"))
    assert exports and all("人工主題" in p.read_text(encoding="utf-8") for p in exports)
    words = list(settings.export_root.rglob("*.docx"))
    assert words and "人工主題" in "\n".join(p.text for p in Document(words[0]).paragraphs)
    with factory() as session:
        log = session.scalar(select(AuditLog).where(AuditLog.action == "ideation.ideas.edit"))
        assert log.detail_json == {"report_id": identity, "index": 0}
    result = client.post(path + "/restore")
    assert result.status_code == 200
    assert result.json()["data"]["ideas"][0] == original["ideas"][0]
    assert result.json()["data"]["ideas_revision"] == 3
    assert client.put(path, json=edit_body(2)).status_code == 409
    assert mock.calls == []


@pytest.mark.parametrize("role,assigned,expected", [
    ("admin", False, 200), ("marketing", True, 200),
    ("marketing", False, 404), ("viewer", True, 403),
])
def test_edit_idea_permission_and_csrf(ready, role, assigned, expected):
    client, brand, _ = ready
    identity = edit_source(ready)
    with client.app.state.session_factory.begin() as session:
        staff = session.scalar(select(Staff).where(Staff.username == "publisher"))
        staff.role = role
        if assigned:
            session.add(StaffBrand(staff_id=staff.id, brand_id=brand))
    path = f"/api/ideation/reports/{identity}/ideas/0"
    csrf = client.headers.pop("X-CSRF-Token")
    assert client.put(path, json=edit_body()).status_code == 403
    client.headers["X-CSRF-Token"] = csrf
    assert client.put(path, json=edit_body()).status_code == expected


def test_edit_idea_processing_rejected(ready):
    client, _, _ = ready
    identity = edit_source(ready)
    with client.app.state.session_factory.begin() as session:
        session.get(IdeationReport, identity).status = "processing"
    result = client.put(f"/api/ideation/reports/{identity}/ideas/0", json=edit_body())
    assert result.status_code == 409


def test_blank_drafts_hidden_without_deleting_and_get_never_creates(ready):
    client, brand, _ = ready
    blank = create(ready, platforms=["facebook"], caption="")
    with client.app.state.session_factory.begin() as session:
        post = session.get(PublishPost, blank["id"])
        post.platforms_json = []
    for _ in range(3):
        assert client.get(f"/api/publish/posts?brand_id={brand}").json() == []
        assert client.get(f"/api/publish/options?brand_id={brand}").status_code == 200
    with client.app.state.session_factory() as session:
        assert session.get(PublishPost, blank["id"])
        assert len(list(session.scalars(select(PublishPost)))) == 1
    media = create(ready, format="video", caption="")
    assert media["id"] in {p["id"] for p in client.get("/api/publish/posts").json()}


def test_all_drafts_remain_visible_beyond_recent_history_limit(ready):
    client, brand, _ = ready
    oldest = create(ready, caption="較早且尚未發佈的草稿")
    with client.app.state.session_factory.begin() as session:
        creator_id = session.get(PublishPost, oldest["id"]).creator_id
        session.add_all(PublishPost(brand_id=brand, creator_id=creator_id, format="text",
                                   status="done", caption=f"隔離歷史 {index}")
                        for index in range(201))
    rows = client.get(f"/api/publish/posts?brand_id={brand}").json()
    assert oldest["id"] in {row["id"] for row in rows}
    assert len([row for row in rows if row["status"] == "done"]) == 200


PRESENCE_IDS = {"facebook": "100_555", "instagram": "17900", "threads": "18000"}


def seed_published(
    ready, platforms=("facebook", "instagram", "threads"), minutes=30, unpublished=False, suffix=""
):
    client, brand, _ = ready
    with client.app.state.session_factory.begin() as session:
        staff = session.scalar(select(Staff).where(Staff.username == "publisher"))
        post = PublishPost(
            brand_id=brand,
            creator_id=staff.id,
            format="text",
            caption="隔離機密文案",
            platforms_json=list(platforms),
            facebook_unpublished=unpublished,
            status="done",
        )
        session.add(post)
        session.flush()
        for platform in platforms:
            account = session.scalar(
                select(Account).where(Account.brand_id == brand, Account.platform == platform)
            )
            session.add(
                PublishTarget(
                    post_id=post.id,
                    platform=platform,
                    account_id=account.id,
                    status="succeeded",
                    platform_post_id=PRESENCE_IDS[platform] + suffix,
                    attempts=1,
                    last_attempt_at=utc_now() - timedelta(minutes=minutes),
                )
            )
        return post.id


def targets_of(ready, identity):
    client, _, _ = ready
    with client.app.state.session_factory() as session:
        return {t.platform: t for t in publish.targets(session, identity)}


def paged(ids, kind="ok", pages=1):
    """Build the pages served for one listing; kind selects an incomplete scenario."""
    result = []
    for index in range(pages):
        rows = [
            {
                "id": value,
                "caption": "x",
                "media_type": "IMAGE",
                "permalink": "https://www.instagram.com/p/isolated/",
                "timestamp": "2026-01-01T00:00:00+0000",
            }
            for value in (ids if index == 0 else [])
        ]
        body = {"data": rows}
        if index + 1 < pages or kind == "limit":
            body["paging"] = {"cursors": {"after": str(index + 1)}, "next": "https://x.test/n"}
        result.append(body)
    if kind == "error":
        result[-1] = 500
    if kind == "format":
        result[-1] = {"data": "oops"}
    if kind == "cursor":
        result[0]["paging"] = {"next": "https://x.test/n"}
    return result


class Listings:
    """Synthetic Meta and Threads list endpoints; counts every request."""

    def __init__(self, facebook=None, instagram=None, threads=None, facebook_videos=None):
        self.pages = {"facebook": facebook, "instagram": instagram, "threads": threads,
                      "facebook_videos": facebook_videos}
        self.calls = []

    def serve(self, platform, after):
        pages = self.pages[platform]
        self.calls.append(platform)
        if pages is None:
            return 200, {"data": []}
        page = pages[min(int(after or 0), len(pages) - 1)]
        if isinstance(page, int):
            return page, {"error": {"code": 1, "message": "private"}}
        return 200, page

    def meta(self, method, url, *, headers=None, qs=None, body=None, timeout=15):
        platform = "facebook" if "/100/" in url else "instagram"
        if url.endswith("/100/videos"):
            platform = "facebook_videos"
        status, data = self.serve(platform, (qs or {}).get("after"))
        return {"statusCode": status, "body": data, "headers": {}}

    def threads(self, request):
        assert request.url.path.endswith("/me/threads")
        status, data = self.serve("threads", request.url.params.get("after"))
        return httpx.Response(status, json=data)

    def install(self, monkeypatch):
        from app.services.gateway_workers import Workers

        monkeypatch.setattr(Workers, "http", staticmethod(self.meta))
        monkeypatch.setattr(
            publish_platforms,
            "client_factory",
            lambda: httpx.Client(transport=httpx.MockTransport(self.threads)),
        )
        return self


def presence_check(ready, brand=None):
    client, brand_id, _ = ready
    return client.post("/api/publish/presence-check", json={"brand_id": brand or brand_id})


def reset_throttle(ready):
    client, _, _ = ready
    with client.app.state.session_factory.begin() as session:
        for row in session.scalars(
            select(Setting).where(Setting.key.like("publish.presence.manual.%"))
        ):
            session.delete(row)


def test_presence_manual_marks_missing_and_restores(ready, monkeypatch):
    client, _, _ = ready
    identity = seed_published(ready)
    lists = Listings(
        facebook=paged(["100_other"]), instagram=paged(["17900"]), threads=paged(["18999"])
    ).install(monkeypatch)
    response = presence_check(ready)
    assert response.status_code == 200, response.text
    assert response.json() == {"checked": 3, "newly_deleted": 2, "restored": 0, "unresolved": []}
    rows = targets_of(ready, identity)
    assert rows["facebook"].deleted_at and rows["threads"].deleted_at
    assert rows["instagram"].deleted_at is None
    assert all(row.presence_checked_at for row in rows.values())
    assert lists.calls == ["facebook", "instagram", "threads"]
    shown = {t["platform"]: t for t in client.get("/api/publish/posts").json()[0]["targets"]}
    assert shown["facebook"]["deleted_at"] and shown["instagram"]["deleted_at"] is None
    with client.app.state.session_factory() as session:
        from app.models import MetaApiCall

        logs = list(
            session.scalars(select(AuditLog).where(AuditLog.action == "publish.target.deleted"))
        )
        assert {log.detail_json["platform"] for log in logs} == {"facebook", "threads"}
        assert all(
            "隔離機密文案" not in json.dumps(log.detail_json, ensure_ascii=False) for log in logs
        )
        assert len(list(session.scalars(select(MetaApiCall)))) == 2
    # 已刪除的目標再次出現在完整清單中，視為誤判並還原。
    reset_throttle(ready)
    lists.pages["facebook"] = paged(["100_555"])
    lists.pages["threads"] = paged(["18000"])
    again = presence_check(ready).json()
    assert again["newly_deleted"] == 0 and again["restored"] == 2
    assert all(row.deleted_at is None for row in targets_of(ready, identity).values())


@pytest.mark.parametrize("kind", ["error", "limit", "format", "cursor"])
@pytest.mark.parametrize("platform", ["facebook", "instagram", "threads"])
def test_presence_incomplete_listing_never_judges(ready, monkeypatch, platform, kind):
    identity = seed_published(ready, (platform,))
    pages = 3 if kind == "error" else 50 if kind == "limit" else 1
    Listings(**{platform: paged([], kind, pages)}).install(monkeypatch)
    body = presence_check(ready).json()
    assert body["newly_deleted"] == 0 and body["checked"] == 0
    assert [item["platform"] for item in body["unresolved"]] == [platform]
    assert body["unresolved"][0]["reason"]
    row = targets_of(ready, identity)[platform]
    assert row.deleted_at is None and row.presence_checked_at is None


@pytest.mark.parametrize("platform", ["facebook", "instagram", "threads"])
def test_presence_empty_listing_never_judges(ready, monkeypatch, platform):
    # 有發佈紀錄的帳號不會沒有任何貼文；空清單可能是權限或帳號異常，不能整批判定刪除。
    from app.services import publish_presence
    from app.services.gateway_workers import Workers

    client, _, _ = ready
    identity = seed_published(ready, (platform,))
    lists = Listings(**{platform: paged([])}).install(monkeypatch)
    body = presence_check(ready).json()
    assert body["newly_deleted"] == 0 and body["checked"] == 0
    assert body["unresolved"] == [{"platform": platform, "reason": publish_presence.EMPTY}]
    assert targets_of(ready, identity)[platform].deleted_at is None
    if platform != "threads":

        def request(method, url, *, headers=None, qs=None, body=None, timeout=15):
            if url.endswith("/published_posts") or url.endswith("/media"):
                return lists.meta(method, url, qs=qs)
            return {"statusCode": 200, "body": {"data": []}, "headers": {}}

        factory, settings = client.app.state.session_factory, client.app.state.settings
        Workers(factory, settings, request=request).metrics()
        assert targets_of(ready, identity)[platform].deleted_at is None


def test_presence_skips_recent_targets(ready, monkeypatch):
    seed_published(ready, minutes=5)
    lists = Listings().install(monkeypatch)
    assert presence_check(ready).json() == {
        "checked": 0,
        "newly_deleted": 0,
        "restored": 0,
        "unresolved": [],
    }
    assert lists.calls == []


def test_presence_missing_token_and_unlinked_platform(ready, monkeypatch):
    from app.services import credentials

    identity = seed_published(ready, ("facebook", "threads"))
    lists = Listings().install(monkeypatch)
    original = credentials.resolve
    blocked = {"THREADS_ACCESS_TOKEN": "", "META_PAGE_ID": ""}
    monkeypatch.setattr(
        credentials,
        "resolve",
        lambda name, *a, **k: blocked[name] if name in blocked else original(name, *a, **k),
    )
    body = presence_check(ready).json()
    reasons = {item["platform"]: item["reason"] for item in body["unresolved"]}
    assert reasons == {"facebook": "平台尚未連結", "threads": "權杖缺失，請重新連結帳號"}
    assert body["checked"] == 0 and lists.calls == []
    assert all(row.deleted_at is None for row in targets_of(ready, identity).values())


def test_presence_metrics_reuses_listing_without_extra_calls(ready):
    from app.services.gateway_workers import Workers

    client, _, _ = ready
    identity = seed_published(ready, ("facebook", "instagram"))
    lists = Listings(facebook=paged(["100_other"]), instagram=paged(["17900"]))

    def request(method, url, *, headers=None, qs=None, body=None, timeout=15):
        if url.endswith("/published_posts") or url.endswith("/media"):
            return lists.meta(method, url, qs=qs)
        return {"statusCode": 200, "body": {"data": []}, "headers": {}}

    worker = Workers(client.app.state.session_factory, client.app.state.settings, request=request)
    assert worker.metrics()["errors"] == []
    assert lists.calls == ["facebook", "instagram"]
    rows = targets_of(ready, identity)
    assert rows["facebook"].deleted_at and rows["instagram"].deleted_at is None
    # 完整清單失敗的平台，metrics() 不判定。
    lists.pages["facebook"] = paged([], "error", 2)
    with client.app.state.session_factory.begin() as session:
        for target in publish.targets(session, identity):
            target.deleted_at = None
    assert worker.metrics()["ok"] is False
    assert targets_of(ready, identity)["facebook"].deleted_at is None


def test_presence_threads_hourly_only_calls_api_when_needed(ready, monkeypatch):
    from app.services import publish_presence

    client, _, _ = ready
    factory, settings = client.app.state.session_factory, client.app.state.settings
    lists = Listings().install(monkeypatch)
    assert publish_presence.hourly_threads(factory, settings)["checked"] == 0
    assert lists.calls == []
    identity = seed_published(ready, ("threads",))
    lists.pages["threads"] = paged(["18999"])
    assert publish_presence.hourly_threads(factory, settings)["newly_deleted"] == 1
    assert lists.calls == ["threads"]
    assert targets_of(ready, identity)["threads"].deleted_at


def test_presence_threads_metrics_reuses_listing_without_extra_calls(ready, monkeypatch):
    """每小時的 metrics 排程已抓過完整 Threads 清單，已刪除偵測不再多打一次（以呼叫次數斷言）。"""
    from app.services.gateway_workers import Workers
    from app.services.scheduler import Scheduler

    client, _, _ = ready
    factory, settings = client.app.state.session_factory, client.app.state.settings
    identity = seed_published(ready, ("threads",))
    lists = Listings(threads=paged(["18999"]))

    def request(method, url, *, headers=None, qs=None, body=None, timeout=15):
        if url == "https://graph.threads.net/v1.0/300/threads":
            status, data = lists.serve("threads", (qs or {}).get("after"))
            return {"statusCode": status, "body": data, "headers": {}}
        return {"statusCode": 200, "body": {"data": []}, "headers": {}}

    monkeypatch.setattr(Workers, "http", staticmethod(request))
    monkeypatch.setattr(
        publish_platforms,
        "client_factory",
        lambda: httpx.Client(transport=httpx.MockTransport(lists.threads)),
    )
    Scheduler(factory, settings).execute("metrics")
    assert lists.calls == ["threads"]
    assert targets_of(ready, identity)["threads"].deleted_at
    # 完整清單失敗：不判定已刪除，也不會為了偵測再重打一次清單。
    with factory.begin() as session:
        for target in publish.targets(session, identity):
            target.deleted_at = None
    lists.pages["threads"] = paged([], "error", 2)
    Scheduler(factory, settings).execute("metrics")
    assert lists.calls == ["threads"] * 3
    assert targets_of(ready, identity)["threads"].deleted_at is None


def test_presence_manual_permissions_csrf_scope_and_throttle(ready, monkeypatch):
    client, brand, _ = ready
    seed_published(ready, ("threads",))
    lists = Listings(threads=paged(["18000"])).install(monkeypatch)
    csrf = client.headers.pop("X-CSRF-Token")
    assert presence_check(ready).status_code == 403
    client.headers["X-CSRF-Token"] = csrf
    assert client.post("/api/publish/presence-check", json={}).status_code == 422
    assert presence_check(ready).status_code == 200
    second = presence_check(ready)
    assert second.status_code == 429 and second.json()["detail"] == "剛檢查過，請稍後再試"
    assert lists.calls == ["threads"]
    factory = client.app.state.session_factory
    with factory.begin() as session:
        staff = session.scalar(select(Staff).where(Staff.username == "publisher"))
        staff.role = "marketing"
        session.add(StaffBrand(staff_id=staff.id, brand_id=brand))
        other = Brand(slug="presence-other", name="隔離其他品牌")
        session.add(other)
        session.flush()
        other_id = other.id
    reset_throttle(ready)
    assert presence_check(ready).status_code == 200
    assert presence_check(ready, other_id).status_code == 404
    with factory.begin() as session:
        session.scalar(select(Staff).where(Staff.username == "publisher")).role = "viewer"
    reset_throttle(ready)
    assert presence_check(ready).status_code == 403
    assert lists.calls == ["threads", "threads"]


def test_deleted_platform_is_not_retried(ready):
    client, _, mock = ready
    post = create(ready)
    mock.fail_threads = True
    assert action(client, post).status_code == 200
    with client.app.state.session_factory.begin() as session:
        rows = {t.platform: t for t in publish.targets(session, post["id"])}
        rows["facebook"].deleted_at = utc_now()
    post = client.get(f"/api/publish/posts/{post['id']}").json()
    before = len([c for c in mock.calls if c[1] == "graph.facebook.com"])
    mock.fail_threads = False
    assert action(client, post, "retry").status_code == 200
    assert len([c for c in mock.calls if c[1] == "graph.facebook.com"]) == before
    final = client.get(f"/api/publish/posts/{post['id']}").json()
    assert final["status"] == "done"
    assert {t["platform"]: t["deleted_at"] is not None for t in final["targets"]} == {
        "facebook": True,
        "threads": False,
    }


def test_presence_migration_columns(migrated):
    from app.db import build_engine

    cfg = Config(str(REPO_ROOT / "backend/alembic.ini"))
    engine = build_engine(migrated)
    names = {c["name"] for c in inspect(engine).get_columns("publish_targets")}
    engine.dispose()
    assert {"deleted_at", "presence_checked_at"} <= names
    command.downgrade(cfg, "0038")
    engine = build_engine(migrated)
    names = {c["name"] for c in inspect(engine).get_columns("publish_targets")}
    engine.dispose()
    assert not {"deleted_at", "presence_checked_at"} & names
    command.upgrade(cfg, "head")


# ---- Facebook 未發佈貼文（published=false）：全部使用假 HTTP，不呼叫 Meta ----


def facebook_posts(mock):
    """Facebook 粉專（假帳號 100）收到的 POST：(主機, 路徑, 表單欄位)。"""
    return [
        (host, path.split("/v26.0/", 1)[1], fields)
        for method, host, path, fields in mock.requests
        if method == "POST" and "/v26.0/100/" in path
    ]


def expected_facebook(format, caption, unpublished):
    """勾選時的請求內容；未勾選時必須與既有行為完全相同。"""
    hidden = {"published": "false", "unpublished_content_type": "DRAFT"} if unpublished else {}
    fb, video = "graph.facebook.com", "graph-video.facebook.com"
    if format == "text":
        return [(fb, "100/feed", {"message": caption, **hidden})]
    if format == "video":
        # 分段上傳：start → 兩段 transfer（假平台每段半個檔案）→ finish 才帶文案與 published。
        return [
            (video, "100/videos", {"upload_phase": "start", "file_size": "204"}),
            *[
                (video, "100/videos", {"upload_phase": "transfer", "upload_session_id": "7001",
                                       "start_offset": offset})
                for offset in ("0", "102")
            ],
            (video, "100/videos", {"upload_phase": "finish", "upload_session_id": "7001",
                                   "description": caption, **hidden}),
        ]
    if format == "image" and not unpublished:
        return [(fb, "100/photos", {"caption": caption})]
    count = 2 if format == "carousel" else 1
    media = json.dumps([{"media_fbid": str(9000 + n)} for n in range(1, count + 1)])
    return [
        *[(fb, "100/photos", {"published": "false"}) for _ in range(count)],
        (fb, "100/feed", {"message": caption, "attached_media": media, **hidden}),
    ]


@pytest.mark.parametrize("unpublished", [True, False])
@pytest.mark.parametrize("format", ["text", "image", "carousel", "video"])
def test_facebook_unpublished_request_contents(ready, format, unpublished):
    client, _, mock = ready
    post = create(ready, format, ["facebook"], "隔離未發佈文案", unpublished=unpublished,
                  options={"facebook": {"video_format": "feed"}})
    assert post["facebook_unpublished"] is unpublished
    assert action(client, post).status_code == 200
    assert facebook_posts(mock) == expected_facebook(format, "隔離未發佈文案", unpublished)
    result = client.get(f"/api/publish/posts/{post['id']}").json()
    assert result["status"] == "done" and result["facebook_unpublished"] is unpublished
    # 平台回傳的 id 與 permalink 照現有方式記錄（最後一個請求的回應）。
    last = "9001" if format == "video" else str(9000 + len(facebook_posts(mock)))
    with client.app.state.session_factory() as session:
        target = publish.targets(session, post["id"])[0]
        assert target.platform_post_id == last
        assert target.permalink == "https://www.facebook.com/" + last


def test_facebook_unpublished_omitted_by_old_clients_defaults_to_public(ready):
    client, brand, mock = ready
    response = client.post(
        "/api/publish/posts",
        json={"brand_id": brand, "platforms": ["facebook"], "caption": "舊版畫面"},
    )
    assert response.status_code == 201 and response.json()["facebook_unpublished"] is False
    assert action(client, response.json()).status_code == 200
    assert facebook_posts(mock) == [("graph.facebook.com", "100/feed", {"message": "舊版畫面"})]


def test_facebook_unpublished_never_changes_instagram_or_threads(ready):
    client, _, mock = ready
    shapes = {}
    for unpublished in (False, True):
        mock.requests.clear()
        post = create(ready, "image", ["facebook", "instagram", "threads"], unpublished=unpublished)
        assert action(client, post).status_code == 200
        assert client.get(f"/api/publish/posts/{post['id']}").json()["status"] == "done"
        # 各平台同時發佈，跨平台的請求順序不固定；依平台帳號穩定排序後比較各自的請求順序。
        shapes[unpublished] = sorted(
            [
                (method, host, path, sorted(fields))
                for method, host, path, fields in mock.requests
                if method == "POST" and "/v26.0/100/" not in path
            ],
            key=lambda row: (row[1], row[2].split("/")[2]),
        )
    assert shapes[True] == shapes[False]
    assert any(path.endswith("/media_publish") for _, _, path, _ in shapes[True])
    assert any(path.endswith("/threads_publish") for _, _, path, _ in shapes[True])
    assert not any("published" in keys for _, _, _, keys in shapes[True])


@pytest.mark.parametrize("scheduled", [False, True])
def test_facebook_unpublished_survives_retry_and_reschedule(ready, scheduled):
    client, _, mock = ready
    factory, settings = client.app.state.session_factory, client.app.state.settings
    post = create(ready, "text", ["facebook"], unpublished=True)
    mock.fail_facebook = True
    assert action(client, post).status_code == 200
    failed = client.get(f"/api/publish/posts/{post['id']}").json()
    assert failed["status"] == "failed" and failed["facebook_unpublished"] is True
    mock.fail_facebook = False
    mock.requests.clear()
    if scheduled:
        when = utc_now() + timedelta(hours=1)
        assert action(client, failed, "retry", when).status_code == 200
        assert not mock.requests
        publish.tick(factory, settings, when + timedelta(seconds=1), wait=True)
    else:
        assert action(client, failed, "retry").status_code == 200
    assert facebook_posts(mock) == [
        ("graph.facebook.com", "100/feed", {"message": "隔離發佈", "published": "false",
                                              "unpublished_content_type": "DRAFT"})
    ]
    final = client.get(f"/api/publish/posts/{post['id']}").json()
    assert final["status"] == "done" and final["facebook_unpublished"] is True


def test_facebook_unpublished_validation_and_lock_after_publish(ready):
    client, brand, mock = ready
    base = {"brand_id": brand, "platforms": ["facebook"], "caption": "隔離文案"}
    # 沒有選 Facebook 或型別不是布林都不接受，避免選項悄悄失效。
    for body in (
        {**base, "platforms": ["threads"], "facebook_unpublished": True},
        {**base, "platforms": [], "facebook_unpublished": True},
        {**base, "facebook_unpublished": "yes"},
        {**base, "facebook_unpublished": 1},
    ):
        assert client.post("/api/publish/posts", json=body).status_code == 422, body

    def put(post, flag, platforms=("facebook", "threads")):
        return client.put(
            f"/api/publish/posts/{post['id']}",
            json={
                "brand_id": brand,
                "format": "text",
                "caption": "隔離文案",
                "platforms": list(platforms),
                "facebook_unpublished": flag,
                "version": post["version"],
            },
        )

    draft = create(ready, platforms=["facebook", "threads"])
    assert draft["facebook_unpublished"] is False
    saved = put(draft, True)
    assert saved.status_code == 200 and saved.json()["facebook_unpublished"] is True
    assert put(saved.json(), True, ("threads",)).status_code == 422
    assert client.get("/api/publish/posts").json()[0]["facebook_unpublished"] is True
    assert action(client, saved.json()).status_code == 200
    done = client.get(f"/api/publish/posts/{draft['id']}").json()
    assert done["status"] == "done"
    assert put(done, False).status_code == 409
    assert put(done, True).status_code == 409
    # 部分成功後重新排程再取消會回到草稿；Facebook 已成功就不能再改公開方式。
    partial = create(ready, platforms=["facebook", "threads"])
    mock.fail_threads = True
    assert action(client, partial).status_code == 200
    mock.fail_threads = False
    partial = client.get(f"/api/publish/posts/{partial['id']}").json()
    assert partial["status"] == "partial"
    assert action(client, partial, "retry", utc_now() + timedelta(hours=1)).status_code == 200
    assert client.post(f"/api/publish/posts/{partial['id']}/cancel").status_code == 200
    back = client.get(f"/api/publish/posts/{partial['id']}").json()
    assert back["status"] == "draft" and back["facebook_unpublished"] is False
    refused = put(back, True)
    assert refused.status_code == 409 and "不可變更" in refused.json()["detail"]
    assert put(back, False).status_code == 200


def facebook_metrics_worker(client, lists):
    from app.services.gateway_workers import Workers

    def request(method, url, *, headers=None, qs=None, body=None, timeout=15):
        if url.endswith("/published_posts") or url.endswith("/media"):
            return lists.meta(method, url, qs=qs)
        return {"statusCode": 200, "body": {"data": []}, "headers": {}}

    return Workers(client.app.state.session_factory, client.app.state.settings, request=request)


def test_presence_never_judges_unpublished_facebook_targets(ready, monkeypatch):
    client, _, _ = ready
    hidden = seed_published(ready, ("facebook",), unpublished=True, suffix="_hidden")
    lists = Listings(facebook=paged(["100_other"])).install(monkeypatch)
    # FB 草稿不在任何清單內：不抓清單，先讀粉專確認權限；假平台讀不到粉專時不判定並列出原因。
    unreadable = [{"platform": "facebook", "reason": "無法確認 Facebook 權限，草稿不判定"}]
    assert presence_check(ready).json() == {
        "checked": 0,
        "newly_deleted": 0,
        "restored": 0,
        "unresolved": unreadable,
    }
    assert lists.calls == ["instagram"]
    # 公開的 Facebook 目標照常判定；未發佈的那篇不受影響。
    public = seed_published(ready, ("facebook",))
    reset_throttle(ready)
    assert presence_check(ready).json() == {
        "checked": 1,
        "newly_deleted": 1,
        "restored": 0,
        "unresolved": unreadable,
    }
    assert lists.calls == ["instagram", "facebook", "instagram"]
    row = targets_of(ready, hidden)["facebook"]
    assert row.deleted_at is None and row.presence_checked_at is None
    assert targets_of(ready, public)["facebook"].deleted_at
    shown = {p["id"]: p["targets"][0] for p in client.get("/api/publish/posts").json()}
    assert shown[hidden]["deleted_at"] is None and shown[public]["deleted_at"]
    # 每小時的 metrics() 重用清單判定：同樣略過未發佈貼文，也不產生錯誤。
    with client.app.state.session_factory.begin() as session:
        for target in publish.targets(session, public):
            target.deleted_at = None
    worker = facebook_metrics_worker(client, Listings(facebook=paged(["100_other"])))
    assert worker.metrics()["errors"] == []
    assert targets_of(ready, hidden)["facebook"].deleted_at is None
    assert targets_of(ready, public)["facebook"].deleted_at
    # 即使未發佈貼文的代號剛好出現在清單中，也不會被當成已還原或重新標記。
    with client.app.state.session_factory.begin() as session:
        publish.targets(session, hidden)[0].deleted_at = utc_now()
    worker = facebook_metrics_worker(client, Listings(facebook=paged(["100_555_hidden"])))
    assert worker.metrics()["errors"] == []
    assert targets_of(ready, hidden)["facebook"].deleted_at is not None


@pytest.mark.migration
def test_facebook_unpublished_migration_defaults_existing_posts_to_public(migrated):
    from app.db import build_engine, session_factory

    cfg = Config(str(REPO_ROOT / "backend/alembic.ini"))
    engine = build_engine(migrated)
    with session_factory(engine).begin() as session:
        brand = Brand(slug="migration-publish", name="隔離移轉品牌")
        staff = Staff(
            username="migrator",
            display_name="隔離移轉",
            role="admin",
            password_hash=hash_password(SecretStr("isolated-migration-password")),
        )
        session.add_all([brand, staff])
        session.flush()
        session.add(
            PublishPost(
                brand_id=brand.id,
                creator_id=staff.id,
                format="text",
                caption="既有貼文",
                platforms_json=["facebook"],
                status="done",
                facebook_unpublished=True,
            )
        )
    engine.dispose()
    # 降級會移除欄位；再升級時既有貼文必須補成 false（公開），欄位為非空。
    command.downgrade(cfg, "0039")
    engine = build_engine(migrated)
    columns = {c["name"] for c in inspect(engine).get_columns("publish_posts")}
    engine.dispose()
    assert "facebook_unpublished" not in columns
    command.upgrade(cfg, "head")
    engine = build_engine(migrated)
    column = next(
        c
        for c in inspect(engine).get_columns("publish_posts")
        if c["name"] == "facebook_unpublished"
    )
    assert column["nullable"] is False
    with session_factory(engine)() as session:
        assert [p.facebook_unpublished for p in session.scalars(select(PublishPost))] == [False]
    engine.dispose()


# ---- composer1：僅 MockTransport 與隔離庫 ----


def update_options(ready, post, options=None, **changes):
    client, brand, _ = ready
    return client.put(
        f"/api/publish/posts/{post['id']}",
        json={
            "brand_id": brand,
            "format": post["format"],
            "caption": post["caption"],
            "captions": post["captions"],
            "platforms": post["platforms"],
            "facebook_unpublished": post["facebook_unpublished"],
            "media_ids": [m["id"] for m in post["media"]],
            "version": post["version"],
            **({"platform_options": options} if options is not None else {}),
            **changes,
        },
    )


def test_composer_options_defaults_merge_and_schema(ready):
    client, _, _ = ready
    post = create(ready, "video", ["facebook"])
    assert post["platform_options"]["facebook"] == {"video_format": "reels", "cover_media_id": None}
    assert post["platform_options"]["instagram"] == {"share_to_feed": True, "cover_media_id": None}
    post = update_options(
        ready, post, {"instagram": {"share_to_feed": False}, "facebook": {"video_format": "feed"}}
    ).json()
    post = update_options(
        ready, post, {"threads": {"segments": ["手動第一段", "手動第二段"]}}
    ).json()
    assert post["platform_options"]["threads"]["segments_custom"] is True
    post = update_options(ready, post, caption="新的主文案").json()
    assert post["platform_options"] == {
        "facebook": {"video_format": "feed", "cover_media_id": None},
        # 封面編號由伺服端維護，未上傳封面時為 None。
        "instagram": {"share_to_feed": False, "cover_media_id": None},
        "threads": {"segments": ["手動第一段", "手動第二段"], "segments_custom": True},
        # 新增 YouTube 後，既有草稿也帶預設的 YouTube 選項（公開、非兒童內容、無縮圖）。
        "youtube": {
            "title": "",
            "privacy": "public",
            "made_for_kids": False,
            "thumbnail_media_id": None,
        },
        # TikTok 沒有可設定的選項（隱私、音樂、文案都在 App 內完成）。
        "tiktok": {},
    }
    for options in (
        {"facebook": {"video_format": "story"}},
        {"instagram": {"share_to_feed": "yes"}},
        {"instagram": {"cover_media_id": 1}},
        {"facebook": {"cover_media_id": 1}},
        {"threads": {"segments": [1]}},
        {"threads": {"segments_custom": 1}},
        {"other": {}},
        {"facebook": {"unknown": True}},
    ):
        assert update_options(ready, post, options).status_code == 422
    assert (
        client.get("/api/publish/posts").json()[0]["platform_options"] == post["platform_options"]
    )
    rules = client.get(f"/api/publish/options?brand_id={post['brand_id']}").json()["rules"]
    assert rules["instagram"]["mentions"] == 20 and rules["instagram"]["hashtag"] == 30
    assert rules["threads"]["caption_counting"] == "unicode_characters_emoji_utf8_bytes"
    assert rules["facebook"]["reels_seconds_max"] == 90


@pytest.mark.parametrize(
    "text,position,snippet",
    [
        ("甲" * 500, None, None),
        ("甲" * 500 + "乙丙", 501, "乙丙"),
        ("😀" * 126, 126, "😀"),
        ("👨‍👩‍👧‍👦" * 21, 21, "👨‍👩‍👧‍👦"),
        ("甲" * 499 + "😀尾", 500, "😀尾"),
    ],
)
def test_threads_overflow_reports_first_character_over_limit(text, position, snippet):
    found = publish_rules.overflow(text, 500)
    assert found == (None if position is None else (position, snippet))


def test_threads_over_limit_reason_names_post_and_position():
    result = publish_rules.check(
        "threads", "text", "", [], {"segments": ["甲" * 500 + "乙丙丁", "回覆", "丙" * 501]}
    )
    reasons = " ".join(result["reasons"])
    assert "Threads 文案超過 500 字上限：共 503 字，從第 501 個字「乙丙丁」開始超出" in reasons
    assert "回覆 2超過 500 字上限：共 501 字，從第 501 個字「丙」開始超出" in reasons
    assert "回覆 1" not in reasons


@pytest.mark.parametrize(
    "text,count", [("中文字", 3), ("😀", 4), ("👍🏽", 8), ("🇹🇼", 8), ("👨‍👩‍👧‍👦", 25), ("1️⃣", 7)]
)
def test_threads_emoji_counts_utf8_bytes(text, count):
    assert publish_rules.text_length(text) == count


def test_threads_save_keeps_caption_whole_and_preserves_custom(ready):
    # 超過 500 字也不自動拆段：Threads 文案原樣當第一則，由發佈規則提示。
    post = create(ready, caption="甲" * 501)
    assert post["platform_options"]["threads"]["segments"] == ["甲" * 501]
    post = update_options(ready, post, captions={"threads": "乙" * 501}).json()
    assert post["platform_options"]["threads"]["segments"] == ["乙" * 501]
    post = update_options(
        ready, post, {"threads": {"segments": ["手動一", "手動二"], "segments_custom": True}}
    ).json()
    post = update_options(ready, post, captions={"threads": "丙" * 501}).json()
    assert post["platform_options"]["threads"]["segments"] == ["手動一", "手動二"]
    post = update_options(ready, post, {"threads": {"segments_custom": False}}).json()
    assert post["platform_options"]["threads"]["segments"] == ["丙" * 501]


def test_facebook_reels_three_exact_requests(ready):
    client, _, mock = ready
    post = create(ready, "video", ["facebook"], caption="Reels 隔離文案")
    assert action(client, post).status_code == 200
    assert mock.requests == [
        ("POST", "graph.facebook.com", "/v26.0/100/video_reels", {"upload_phase": "start"}),
        ("POST", "rupload.facebook.com", "/video-upload/v26.0/9001", {}),
        (
            "POST",
            "graph.facebook.com",
            "/v26.0/100/video_reels",
            {
                "upload_phase": "finish",
                "video_id": "9001",
                "video_state": "PUBLISHED",
                "description": "Reels 隔離文案",
            },
        ),
    ]
    headers, binary = mock.uploads[0]
    assert binary == video_bytes()
    assert headers["authorization"] == "OAuth isolated-publish-token"
    assert headers["offset"] == "0" and headers["file_size"] == str(len(binary))
    target = targets_of(ready, post["id"])["facebook"]
    assert (
        target.platform_post_id == "9001"
        and target.permalink == "https://www.facebook.com/reel/9001"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://rupload.facebook.com/video-upload/v26.0/9001",
        "https://evil.example.test/video-upload/v26.0/9001",
        "https://rupload.facebook.com/video-upload/v26.0/9002",
        "https://rupload.facebook.com/video-upload/v26.0/9001?token=x",
    ],
)
def test_reels_rejects_untrusted_upload_url_before_upload(ready, monkeypatch, url):
    client, _, mock = ready
    original = mock.handler

    def handler(request):
        response = original(request)
        if request.url.path.endswith("/video_reels"):
            return httpx.Response(200, json={"video_id": "9001", "upload_url": url})
        return response

    monkeypatch.setattr(mock, "handler", handler)
    post = create(ready, "video", ["facebook"])
    assert action(client, post).status_code == 200
    assert len(mock.requests) == 1 and mock.uploads == []
    assert targets_of(ready, post["id"])["facebook"].status == "failed"


def test_facebook_draft_reels_keeps_reels_with_draft_state(ready):
    # 存成 FB 草稿時 Reels 不再改成影片貼文：照 Reels 流程上傳，finish 帶 video_state=DRAFT。
    client, _, mock = ready
    post = create(ready, "video", ["facebook"], unpublished=True)
    assert post["platform_options"]["facebook"]["video_format"] == "reels"
    assert post["effective_platform_options"]["facebook"]["video_format"] == "reels"
    assert not post["warnings"]
    checks = client.post(f"/api/publish/posts/{post['id']}/check").json()
    assert checks["facebook"]["ok"] and not checks["facebook"]["warnings"]
    assert action(client, post).status_code == 200
    assert facebook_posts(mock) == [
        ("graph.facebook.com", "100/video_reels", {"upload_phase": "start"}),
        (
            "graph.facebook.com",
            "100/video_reels",
            {"upload_phase": "finish", "video_id": "9001", "video_state": "DRAFT",
             "description": "隔離發佈"},
        ),
    ]
    assert len(mock.uploads) == 1 and not mock.fb_chunks


@pytest.mark.parametrize("share", [True, False])
def test_instagram_share_to_feed_only_changes_video_option(ready, share):
    client, _, mock = ready
    post = create(ready, "video", ["instagram"], options={"instagram": {"share_to_feed": share}})
    assert action(client, post).status_code == 200
    posts = [(path, fields) for method, host, path, fields in mock.requests if method == "POST"]
    data = {"media_type": "REELS", "video_url": posts[0][1]["video_url"], "caption": "隔離發佈"}
    if not share:
        data["share_to_feed"] = "false"
    assert posts == [
        ("/v26.0/200/media", data),
        ("/v26.0/200/media_publish", {"creation_id": "9001"}),
    ]


@pytest.mark.parametrize("custom", [False, True])
def test_threads_single_segment_request_is_exactly_unchanged(ready, custom):
    client, _, mock = ready
    post = create(
        ready,
        platforms=["threads"],
        caption="原單篇 #主題",
        options={"threads": {"segments": ["原單篇 #主題"], "segments_custom": custom}},
    )
    assert action(client, post).status_code == 200
    assert mock.requests == [
        (
            "POST",
            "graph.threads.net",
            "/v1.0/300/threads",
            {"media_type": "TEXT", "text": "原單篇 #主題", "topic_tag": "主題"},
        ),
        ("GET", "graph.threads.net", "/v1.0/9001", {}),
        ("POST", "graph.threads.net", "/v1.0/300/threads_publish", {"creation_id": "9001"}),
        ("GET", "graph.threads.net", "/v1.0/9002", {}),
    ]


@pytest.mark.parametrize("format", ["text", "image", "video", "carousel"])
def test_threads_chain_order_media_first_and_first_identity(ready, format):
    client, _, mock = ready
    segments = ["第一段 #first #second", "第二段", "第三段"]
    post = create(ready, format, ["threads"], options={"threads": {"segments": segments}})
    assert action(client, post).status_code == 200
    requests = [r for r in mock.requests if r[0] == "POST"]
    containers = [r[3] for r in requests if r[2].endswith("/threads") and "text" in r[3]]
    target = targets_of(ready, post["id"])["threads"]
    ids = target.detail_json["segment_ids"]
    assert len(ids) == 3 and target.detail_json["successful_segments"] == 3
    assert target.platform_post_id == ids[0]
    assert target.permalink == "https://www.threads.net/@isolated/post/abc"
    assert [value["text"] for value in containers] == segments
    assert containers[0]["topic_tag"] == "first" and "reply_to_id" not in containers[0]
    for index in (1, 2):
        assert containers[index] == {
            "media_type": "TEXT",
            "text": segments[index],
            "reply_to_id": ids[index - 1],
        }
    if format == "carousel":
        assert len(requests) == 8  # 兩個素材子容器、三個主容器、三次 publish。
    else:
        assert len(requests) == 6
    checks = client.post(f"/api/publish/posts/{post['id']}/check").json()
    assert checks["threads"]["ok"] and checks["threads"]["warnings"]


@pytest.mark.parametrize("failed_segment", [2, 3])
@pytest.mark.parametrize("phase", ["container", "publish"])
def test_threads_failure_checkpoints_and_retry_only_remaining(
    ready, monkeypatch, failed_segment, phase
):
    from publish_http_mock import request_fields

    client, _, mock = ready
    segments = ["段落一", "段落二", "段落三"]
    original = mock.handler
    containers, failed = {}, False

    def handler(request):
        nonlocal failed
        fields = request_fields(request)
        text = (
            fields.get("text")
            if phase == "container"
            else containers.get(fields.get("creation_id"))
        )
        if not failed and text == segments[failed_segment - 1]:
            failed = True
            mock.calls.append((request.method, request.url.host, request.url.path))
            mock.requests.append((request.method, request.url.host, request.url.path, fields))
            return httpx.Response(429, json={"error": {"code": 4}})
        if fields.get("text") and "reply_to_id" in fields:
            # 下一段 HTTP 發出前，前段 ID 已入庫；沒有鎖跨 HTTP。
            row = targets_of(ready, post["id"])["threads"]
            assert row.detail_json["segment_ids"][-1] == fields["reply_to_id"]
        response = original(request)
        if fields.get("text"):
            containers[response.json()["id"]] = fields["text"]
        return response

    monkeypatch.setattr(mock, "handler", handler)
    post = create(ready, "image", ["threads"], options={"threads": {"segments": segments}})
    assert action(client, post).status_code == 200
    row = targets_of(ready, post["id"])["threads"]
    assert row.status == "failed" and row.detail_json["failed_segment"] == failed_segment
    assert row.detail_json["successful_segments"] == failed_segment - 1
    first_id, ids = row.platform_post_id, row.detail_json["segment_ids"]
    current = client.get(f"/api/publish/posts/{post['id']}").json()
    mock.requests.clear()
    assert action(client, current, "retry").status_code == 200
    remainder = [
        fields
        for method, _, path, fields in mock.requests
        if method == "POST" and path.endswith("/threads")
    ]
    assert [value["text"] for value in remainder] == segments[failed_segment - 1 :]
    assert remainder[0]["reply_to_id"] == ids[-1]
    assert all(value["media_type"] == "TEXT" and "image_url" not in value for value in remainder)
    row = targets_of(ready, post["id"])["threads"]
    assert row.status == "succeeded" and row.platform_post_id == first_id
    assert row.detail_json["segment_ids"][: len(ids)] == ids
    assert row.detail_json["successful_segments"] == 3 and row.detail_json["failed_segment"] is None


@pytest.mark.parametrize(
    "duration,width,height,reason",
    [(2.9, 1080, 1920, "3–90"), (90.1, 1080, 1920, "3–90"), (12, 1920, 1080, "直式")],
)
def test_facebook_reels_limits(duration, width, height, reason):
    media = [
        SimpleNamespace(mime="video/mp4", size=100, duration=duration, width=width, height=height)
    ]
    check = publish_rules.check("facebook", "video", "", media, {"video_format": "reels"})
    assert not check["ok"] and reason in " ".join(check["reasons"])
    assert publish_rules.check("facebook", "video", "", media, {"video_format": "feed"})["ok"]


def test_limits_boundaries_mentions_and_warnings(ready):
    media = [SimpleNamespace(mime="video/mp4", size=100, duration=3, width=1080, height=1920)]
    for duration in (3, 90):
        media[0].duration = duration
        assert publish_rules.check("facebook", "video", "", media, {"video_format": "reels"})["ok"]
    media[0].duration = 900
    assert publish_rules.check("instagram", "video", "x" * 2200, media)["ok"]
    media[0].duration = 900.1
    assert not publish_rules.check("instagram", "video", "", media)["ok"]
    media[0].duration = 12
    assert publish_rules.check("instagram", "video", " ".join("@name" for _ in range(20)), media)[
        "ok"
    ]
    check = publish_rules.check("instagram", "video", " ".join("@name" for _ in range(21)), media)
    assert not check["ok"] and "20" in " ".join(check["reasons"])
    assert publish_rules.check("facebook", "text", "x" * 63206, [])["ok"]
    warning = publish_rules.check("facebook", "text", "@name", [])
    assert warning["ok"] and warning["warnings"] == ["Facebook 發文無法標註，@ 會顯示為一般文字"]
    assert publish_rules.check("threads", "text", "😀" * 125, [])["ok"]
    assert not publish_rules.check("threads", "text", "😀" * 126, [])["ok"]
    client, _, mock = ready
    post = create(ready, platforms=["threads"], options={"threads": {"segments": ["x" * 501]}})
    result = action(client, post)
    assert (
        result.status_code == 422
        and "Threads" in result.json()["detail"]
        and "Threads 文案" in result.json()["detail"]
    )
    assert not mock.requests


@pytest.mark.parametrize("platform", ["facebook", "instagram", "threads"])
def test_options_lock_for_sent_platform_after_cancelled_retry(ready, platform):
    client, _, mock = ready
    format = "video" if platform != "threads" else "text"
    post = create(
        ready, format, [platform, "threads"] if platform != "threads" else ["threads", "facebook"]
    )
    if platform == "threads":
        mock.fail_facebook = True
    else:
        mock.fail_threads = True
    assert action(client, post).status_code == 200
    post = client.get(f"/api/publish/posts/{post['id']}").json()
    assert post["status"] == "partial"
    assert action(client, post, "retry", utc_now() + timedelta(hours=1)).status_code == 200
    post = client.post(f"/api/publish/posts/{post['id']}/cancel").json()
    options = {
        "facebook": {"video_format": "feed"},
        "instagram": {"share_to_feed": False},
        "threads": {"segments": ["改過的段落"], "segments_custom": True},
    }
    result = update_options(ready, post, {platform: options[platform]})
    assert result.status_code == 409 and "不可變更" in result.json()["detail"]
    assert update_options(ready, post).status_code == 200


def test_presence_threads_chain_uses_first_id_and_empty_video_list_is_unjudged(ready, monkeypatch):
    client, _, mock = ready
    chain = create(ready, platforms=["threads"], options={"threads": {"segments": ["一", "二"]}})
    reel = create(ready, "video", ["facebook"])
    assert action(client, chain).status_code == 200 and action(client, reel).status_code == 200
    with client.app.state.session_factory.begin() as session:
        for identity in (chain["id"], reel["id"]):
            for row in publish.targets(session, identity):
                row.last_attempt_at = utc_now() - timedelta(minutes=11)
    target = targets_of(ready, chain["id"])["threads"]
    ids = target.detail_json["segment_ids"]
    lists = Listings(threads=paged([ids[0]])).install(monkeypatch)
    result = presence_check(ready).json()
    # Reels 改和 /videos 比對；影片清單為空時不判定（不標已刪除、也不記檢查時間）。
    from app.services import publish_presence

    assert result["checked"] == 1 and result["newly_deleted"] == 0
    assert lists.calls == ["facebook_videos", "threads"]
    assert {"platform": "facebook", "reason": publish_presence.EMPTY} in result["unresolved"]
    assert targets_of(ready, reel["id"])["facebook"].presence_checked_at is None
    reset_throttle(ready)
    lists.pages["threads"] = paged([ids[1]])
    assert presence_check(ready).json()["newly_deleted"] == 1
    assert targets_of(ready, chain["id"])["threads"].deleted_at
    mock.requests.clear()


@pytest.mark.migration
def test_platform_options_migration_preserves_existing_posts_and_downgrades(migrated):
    from app.db import build_engine, session_factory

    cfg = Config(str(REPO_ROOT / "backend/alembic.ini"))
    engine = build_engine(migrated)
    with session_factory(engine).begin() as session:
        brand = Brand(slug="composer-migration", name="隔離移轉")
        staff = Staff(
            username="composer-migrator",
            display_name="隔離移轉",
            role="admin",
            password_hash=hash_password(SecretStr("isolated-migration-password")),
        )
        session.add_all([brand, staff])
        session.flush()
        for format, status in [("video", "draft"), ("video", "done"), ("text", "draft")]:
            session.add(
                PublishPost(
                    brand_id=brand.id,
                    creator_id=staff.id,
                    format=format,
                    status=status,
                    caption="既有內容",
                    captions_json={"threads": "專屬"},
                    platforms_json=["facebook"],
                    facebook_unpublished=True,
                )
            )
    engine.dispose()
    command.downgrade(cfg, "0040")
    engine = build_engine(migrated)
    assert "platform_options_json" not in {
        c["name"] for c in inspect(engine).get_columns("publish_posts")
    }
    assert "detail_json" not in {c["name"] for c in inspect(engine).get_columns("publish_targets")}
    engine.dispose()
    command.upgrade(cfg, "head")
    engine = build_engine(migrated)
    with session_factory(engine)() as session:
        rows = list(session.scalars(select(PublishPost)))
        assert len(rows) == 3
        assert all(
            row.caption == "既有內容"
            and row.captions_json == {"threads": "專屬"}
            and row.facebook_unpublished
            for row in rows
        )
        assert all(
            row.platform_options_json
            == {
                "facebook": {"video_format": "feed"},
                "instagram": {"share_to_feed": True},
                "threads": {"segments": [], "segments_custom": False},
            }
            for row in rows
        )
    engine.dispose()
def test_threads_partial_schedule_cancel_preserves_progress_and_locks_segments(ready):
    client, brand, mock = ready
    segments = ["第一段", "第二段"]
    post = create(ready, platforms=["threads"], options={"threads": {"segments": segments}})
    assert action(client, post).status_code == 200
    # 模擬最後一段已確認、狀態寫回前中斷；重試不得再發任何一段。
    factory = client.app.state.session_factory
    with factory.begin() as session:
        row = session.scalar(select(PublishTarget).where(PublishTarget.post_id == post["id"]))
        row.status, row.error_code = "failed", "interrupted"
        session.get(PublishPost, post["id"]).status = "failed"
    current = client.get(f"/api/publish/posts/{post['id']}").json()
    before = current["targets"][0]["detail"]
    scheduled = action(client, current, "retry", utc_now() + timedelta(hours=1))
    assert scheduled.status_code == 200
    assert scheduled.json()["platform_options"] == current["platform_options"]
    assert scheduled.json()["targets"][0]["detail"] == before
    cancelled = client.post(f"/api/publish/posts/{post['id']}/cancel")
    assert cancelled.status_code == 200
    current = cancelled.json()
    assert current["targets"][0]["detail"] == before
    rejected = client.put(
        f"/api/publish/posts/{post['id']}",
        json={
            "brand_id": brand,
            "version": current["version"],
            "format": "text",
            "caption": current["caption"],
            "platforms": ["threads"],
            "platform_options": {"threads": {"segments": ["更改已送出的分段"]}},
        },
    )
    assert rejected.status_code == 409 and "Threads" in rejected.json()["detail"]
    mock.requests.clear()
    assert action(client, current).status_code == 200
    assert mock.requests == []
    assert targets_of(ready, post["id"])["threads"].status == "succeeded"


# composer3：使用隔離 SQLite 與假 HTTP，沒有平台 socket。
def story_draft(ready, platforms=None, files=None):
    client, brand, _ = ready
    response = client.post(
        "/api/publish/posts",
        json={
            "brand_id": brand,
            "format": "story",
            "platforms": platforms or ["facebook", "instagram"],
        },
    )
    assert response.status_code == 201, response.text
    post = response.json()
    for index, data in enumerate(files or [jpeg_bytes(1080, 1920), video_bytes()]):
        response = client.post(
            f"/api/publish/posts/{post['id']}/media?filename=story-{index}.bin",
            content=data,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert response.status_code == 200, response.text
        post = response.json()
    return post


def test_story_fb_photo_video_and_ig_stories_requests(ready):
    client, _, mock = ready
    post = story_draft(ready)
    assert action(client, post).status_code == 200
    result = client.get(f"/api/publish/posts/{post['id']}").json()
    assert result["status"] == "done"
    for target in result["targets"]:
        assert target["detail"]["successful_stories"] == 2
        assert len({story["platform_post_id"] for story in target["stories"]}) == 2
    requests = mock.requests
    photo = next(r[3] for r in requests if r[2].endswith("/photos"))
    assert photo == {"published": "false"}
    story = next(r[3] for r in requests if r[2].endswith("/photo_stories"))
    assert set(story) == {"photo_id"}
    video = [r[3] for r in requests if r[2].endswith("/video_stories")]
    assert video[0] == {"upload_phase": "start"}
    assert video[1] == {"upload_phase": "finish", "video_id": video[1]["video_id"]}
    assert len(mock.uploads) == 1
    containers = [r[3] for r in requests if r[2].endswith("/200/media")]
    assert len(containers) == 2 and all(r["media_type"] == "STORIES" for r in containers)
    assert set(containers[0]) == {"media_type", "image_url"}
    assert set(containers[1]) == {"media_type", "video_url"}
    polls = [r for r in mock.calls if r[0] == "GET"]
    assert len(polls) == 2  # 每則等待 FINISHED，限動不查 permalink。
    with client.app.state.session_factory() as session:
        assert all(link.revoked_at for link in session.scalars(select(PublishLink)))


@pytest.mark.parametrize("platform", ["facebook", "instagram"])
def test_story_failed_k_resumes_without_republishing_success(ready, monkeypatch, platform):
    client, _, mock = ready
    post = story_draft(ready, [platform], [jpeg_bytes(1080, 1920)] * 3)
    original, sent = mock.handler, []

    def handler(request):
        if request.method == "POST" and request.url.path.endswith(
            ("/photo_stories", "/media_publish")
        ):
            sent.append(request.url.path)
            if len(sent) == 2:
                return httpx.Response(429, json={"error": {"code": 4}})
        return original(request)

    monkeypatch.setattr(mock, "handler", handler)
    assert action(client, post).status_code == 200
    post = client.get(f"/api/publish/posts/{post['id']}").json()
    assert post["status"] == "partial"
    detail = post["targets"][0]["detail"]
    assert (detail["successful_stories"], detail["failed_story"]) == (1, 2)
    first_id = detail["stories"][0]["platform_post_id"]
    # 已部分送出後取消排程也不能變更素材／順序。
    when = utc_now() + timedelta(hours=2)
    assert action(client, post, "retry", when).status_code == 200
    assert client.post(f"/api/publish/posts/{post['id']}/cancel").status_code == 200
    post = client.get(f"/api/publish/posts/{post['id']}").json()
    body = {
        "brand_id": post["brand_id"],
        "format": "story",
        "platforms": [platform],
        "media_ids": [m["id"] for m in reversed(post["media"])],
        "version": post["version"],
    }
    assert client.put(f"/api/publish/posts/{post['id']}", json=body).status_code == 409
    assert (
        client.delete(f"/api/publish/posts/{post['id']}/media/{post['media'][0]['id']}").status_code
        == 409
    )
    assert action(client, post).status_code == 200
    final = client.get(f"/api/publish/posts/{post['id']}").json()
    assert final["status"] == "done" and len(sent) == 4
    assert final["targets"][0]["detail"]["stories"][0]["platform_post_id"] == first_id


def test_story_schedule_cancel_and_presence_skips_all(ready, monkeypatch):
    from app.services import publish_presence

    client, _, mock = ready
    post = story_draft(ready)
    when = utc_now() + timedelta(hours=2)
    assert action(client, post, when=when).status_code == 200
    assert not mock.calls
    assert client.post(f"/api/publish/posts/{post['id']}/cancel").status_code == 200
    post = client.get(f"/api/publish/posts/{post['id']}").json()
    assert action(client, post, when=when).status_code == 200
    publish.tick(client.app.state.session_factory, client.app.state.settings, when, wait=True)
    with client.app.state.session_factory.begin() as session:
        assert session.get(PublishPost, post["id"]).status == "done"
        for target in publish.targets(session, post["id"]):
            target.last_attempt_at = utc_now() - timedelta(days=2)
    before = len(mock.calls)
    assert (
        publish_presence.run(client.app.state.session_factory, client.app.state.settings)["checked"]
        == 0
    )
    assert len(mock.calls) == before


@pytest.mark.parametrize(
    "changes",
    [
        {"caption": "文字"},
        {"captions": {"instagram": "文字"}},
        {"platforms": ["threads"]},
        {"facebook_unpublished": True},
        {"platform_options": {"instagram": {"share_to_feed": False}}},
    ],
)
def test_story_rejects_text_and_post_only_options(ready, changes):
    client, brand, mock = ready
    response = client.post(
        "/api/publish/posts",
        json={"brand_id": brand, "format": "story", "platforms": ["facebook"], **changes},
    )
    assert response.status_code == 422 and not mock.calls


def test_story_limits_ratio_notice_and_upload_cap(ready):
    client, _, _ = ready
    post = story_draft(ready, files=[video_bytes(duration=2), jpeg_bytes()])
    response = client.post(f"/api/publish/posts/{post['id']}/check").json()
    assert not response["instagram"]["ok"] and "3–60" in str(response)
    assert response["facebook"]["ok"]
    assert "平台會加邊" in str(response["facebook"]["warnings"])
    for _ in range(8):
        r = client.post(
            f"/api/publish/posts/{post['id']}/media?filename=test.jpg", content=jpeg_bytes()
        )
        assert r.status_code == 200
    assert (
        client.post(
            f"/api/publish/posts/{post['id']}/media?filename=test.jpg", content=jpeg_bytes()
        ).status_code
        == 422
    )
    with client.app.state.session_factory() as session:
        item = publish.media_rows(session, post["id"])[0]
        item.duration = 61
        assert not publish_rules.check_story("facebook", "", [item])["ok"]
        item.mime, item.size = "image/png", 8 * 1024**2 + 1
        assert not publish_rules.check_story("instagram", "", [item])["ok"]
        # PNG 本身不再是錯誤（改為警告）；上一行是被 8 MB 擋下，這裡驗證縮小後可通過。
        item.size = 100
        result = publish_rules.check_story("instagram", "", [item])
        assert result["ok"] and publish_rules.IG_PNG_WARNING in result["warnings"][0]
        item.mime = "image/gif"
        assert not publish_rules.check_story("instagram", "", [item])["ok"]


def test_story_ig_hourly_expiry_final_signature_idempotence(ready):
    import hashlib
    import hmac

    from app.models import PublishStorySnapshot
    from app.services import publish_story_insights

    client, _, _ = ready
    settings, factory = client.app.state.settings, client.app.state.session_factory
    post = story_draft(ready, ["instagram"], [jpeg_bytes(1080, 1920)])
    assert action(client, post).status_code == 200
    with factory() as session:
        target = publish.targets(session, post["id"])[0]
        identity = target.detail_json["stories"][0]["platform_post_id"]
    calls = []

    class FakeWorker:
        def graph(self, path, query, context):
            calls.append((path, query, context))
            return {
                "statusCode": 200,
                "body": {
                    "data": [
                        {"name": key, "total_value": {"value": index + 1}}
                        for index, key in enumerate(publish_story_insights.METRICS)
                    ]
                },
            }

    # 固定在整點後一分鐘起算，時段判斷不受測試執行時刻影響。
    now = utc_now().replace(minute=1, second=0, microsecond=0) + timedelta(hours=1)
    # 119 分鐘：下一小時比上一小時早一分鐘跑（排程抖動），仍屬新時段要讀。
    for delta, count in [(0, 1), (30, 1), (60, 2), (119, 3), (24 * 60, 3), (25 * 60, 3)]:
        publish_story_insights.hourly(
            factory, settings, FakeWorker(), now + timedelta(minutes=delta)
        )
        assert len(calls) == count
    assert calls[0][0] == identity + "/insights"
    assert calls[0][1]["metric"] == ",".join(publish_story_insights.METRICS)
    settings.meta_app_secret = SecretStr("isolated-story-webhook-secret")
    settings.meta_page_id, settings.meta_ig_account_id = "100", "200"
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "200",
                "time": int((now + timedelta(hours=24)).timestamp()),
                "changes": [
                    {
                        "field": "story_insights",
                        "value": {
                            "media_id": identity,
                            "views": 900,
                            "reach": 800,
                            "replies": 4,
                            "shares": 3,
                            "navigation": 9,
                            "follows": 2,
                            "profile_visits": 7,
                        },
                    }
                ],
            }
        ],
    }
    raw = json.dumps(payload).encode()
    signature = (
        "sha256="
        + hmac.new(
            settings.meta_app_secret.get_secret_value().encode(), raw, hashlib.sha256
        ).hexdigest()
    )
    url = "/webhook/meta-inbound"
    assert (
        client.post(
            url, content=raw, headers={"x-hub-signature-256": "sha256=" + "0" * 64}
        ).status_code
        == 401
    )
    assert (
        client.post(url, content=raw + b" ", headers={"x-hub-signature-256": signature}).status_code
        == 401
    )
    for _ in range(2):
        assert (
            client.post(url, content=raw, headers={"x-hub-signature-256": signature}).status_code
            == 200
        )
    with factory() as session:
        rows = list(session.scalars(select(PublishStorySnapshot)))
        assert len(rows) == 4 and sum(r.final for r in rows) == 1
    final = client.get(f"/api/publish/posts/{post['id']}").json()["targets"][0]["stories"][0]
    assert final["final"] and final["metrics"]["views"] == 900
    assert len(final["snapshots"]) == 4
    publish_story_insights.hourly(factory, settings, FakeWorker(), now + timedelta(hours=2))
    assert len(calls) == 3  # final 不再被輪詢覆盖。


@pytest.mark.migration
def test_story_migration_preserves_legacy_posts_and_refuses_lossy_downgrade(migrated):
    from app.db import build_engine

    cfg = Config(str(REPO_ROOT / "backend/alembic.ini"))
    command.downgrade(cfg, "0041")
    engine = build_engine(migrated)
    from app.db import session_factory

    factory = session_factory(engine)
    with factory.begin() as session:
        session.add(Brand(id=999, slug="story-migration", name="隔離遷移"))
        # 舊版 schema 沒有之後新增的 staff 欄位，只寫入當時就有的欄位。
        staff_id = session.execute(
            insert(Staff.__table__).values(
                username="story-migration",
                display_name="隔離",
                role="admin",
                password_hash="isolated-hash",
            )
        ).inserted_primary_key[0]
        row = PublishPost(
            brand_id=999,
            creator_id=staff_id,
            format="text",
            caption="保留原文",
            platforms_json=["facebook"],
        )
        session.add(row)
        session.flush()
        identity = row.id
    engine.dispose()
    command.upgrade(cfg, "head")
    engine = build_engine(migrated)
    try:
        with session_factory(engine).begin() as session:
            row = session.get(PublishPost, identity)
            assert row.caption == "保留原文" and row.platforms_json == ["facebook"]
            row.format, row.caption = "story", ""
        with pytest.raises(RuntimeError, match="Existing stories"):
            command.downgrade(cfg, "0041")
        assert "publish_story_snapshots" in inspect(engine).get_table_names()
        with session_factory(engine).begin() as session:
            session.get(PublishPost, identity).format = "text"
        command.downgrade(cfg, "0041")
        assert "publish_story_snapshots" not in inspect(engine).get_table_names()
        command.upgrade(cfg, "head")
    finally:
        engine.dispose()


def test_story_insights_preserves_supported_metrics_when_one_is_unavailable(ready):
    from app.services import publish_story_insights

    client, _, _ = ready
    post = story_draft(ready, ["instagram"], [jpeg_bytes(1080, 1920)])
    assert action(client, post).status_code == 200
    calls = []

    class Worker:
        def graph(self, path, query, context):
            metric = query["metric"]
            calls.append((metric, query.get("metric_type")))
            if "," in metric or metric != "reach":
                return {"statusCode": 400, "body": {"error": {"code": 100}}}
            return {
                "statusCode": 200,
                "body": {
                    "data": [
                        {"name": "reach", "values": [{"value": 42}]},
                    ]
                },
            }

    result = publish_story_insights.hourly(
        client.app.state.session_factory, client.app.state.settings, Worker()
    )
    assert result == {"snapshots": 1, "errors": 0}
    assert calls[0] == (",".join(publish_story_insights.METRICS), None)
    assert ("reach", None) in calls
    assert ("navigation", "total_value") in calls
    assert len(calls) == 14
    story = client.get(f"/api/publish/posts/{post['id']}").json()["targets"][0]["stories"][0]
    assert story["metrics"] == {"reach": 42}  # 缺值不捏造零。


def test_threads_topic_tag_stops_at_punctuation():
    # hashtag 後面直接接標點與文字時，主題標籤只取標籤本身，不含後面的句子。
    result = publish_rules.check("threads", "text", "第一行 #主題，在第一段補字。#第二!", [])
    assert result["topic_tag"] == "主題"
    assert publish_rules.HASHTAGS.findall("#tag_1. #二號、#三") == ["#tag_1", "#二號", "#三"]


@pytest.mark.parametrize(
    "platform,host,edge",
    [("threads", "graph.threads.net", "/threads"), ("instagram", "graph.facebook.com", "/media")],
)
def test_carousel_creates_all_children_before_waiting(ready, platform, host, edge):
    # 輪播先建立全部子容器，再查狀態；不再建一張、等一張。
    client, _, mock = ready
    post = create(ready, "carousel", [platform])
    mock.requests.clear()
    assert action(client, post).status_code == 200
    calls = [(method, path) for method, h, path, _ in mock.requests if h == host]
    created = [i for i, (m, path) in enumerate(calls) if m == "POST" and path.endswith(edge)]
    first_status = next(i for i, (m, _) in enumerate(calls) if m == "GET")
    assert len(created) == 3  # 兩張子容器＋輪播容器
    assert created[1] < first_status, calls


def png_bytes(size=(1080, 1080), mode="RGBA", color=(255, 0, 0, 128), noise=False):
    image = Image.new(mode, size, color)
    if noise:
        image.putdata([(i * 7 % 256, i * 13 % 256, i * 29 % 256) for i in range(size[0] * size[1])])
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def png_post(ready, platforms, data):
    """建立 image 草稿並把預設 JPEG 換成指定 PNG。"""
    client = ready[0]
    post = create(ready, "image", platforms)
    client.delete(f"/api/publish/posts/{post['id']}/media/{post['media'][0]['id']}")
    response = client.post(
        f"/api/publish/posts/{post['id']}/media?filename=x.png",
        content=data,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_instagram_png_is_sent_as_jpeg_while_facebook_threads_keep_png(ready):
    client, _, mock = ready
    original = png_bytes()
    post = png_post(ready, ["facebook", "instagram", "threads"], original)
    mock.requests.clear()
    assert action(client, post).status_code == 200
    assert client.get(f"/api/publish/posts/{post['id']}").json()["status"] == "done"
    by_host = {h: d["image_url"] for _, h, _, d in mock.requests if "image_url" in d}
    assert len(by_host) == 2
    jpeg_urls = [u for u in by_host.values() if u.endswith(".jpg")]
    png_urls = [u for u in by_host.values() if not u.endswith(".jpg")]
    assert len(jpeg_urls) == 1 and len(png_urls) == 1  # IG 加 .jpg；Threads 仍送原檔網址
    # Facebook 仍直接上傳原檔
    assert any(path.endswith("/photos") for _, _, path, _ in mock.requests)


def test_png_jpeg_derivative_is_white_background_same_size_and_secure(ready):
    client, _, _ = ready
    post = png_post(ready, ["instagram"], png_bytes((640, 480), color=(0, 0, 0, 0)))
    factory, settings = client.app.state.session_factory, client.app.state.settings
    with factory.begin() as session:
        media = session.get(PublishMedia, post["media"][0]["id"])
        _, plain = publish_media.create_link(session, settings, media)
        jpeg_id, converted = publish_media.create_link(session, settings, media, jpeg=True)
        derived = publish_media.jpeg_path(settings, media)
        assert derived.parent == publish_media.path_for(settings, media).parent
    assert not plain.endswith(".jpg") and converted.endswith(".jpg")
    headers = {"X-Mwb-Public": "1"}
    path = "/media/" + converted.rsplit("/", 1)[1]
    result = client.get(path, headers=headers)
    assert result.status_code == 200 and result.headers["content-type"] == "image/jpeg"
    assert result.headers["cache-control"] == "no-store"
    image = Image.open(io.BytesIO(result.content))
    assert image.format == "JPEG" and image.mode == "RGB" and image.size == (640, 480)
    assert all(value >= 250 for value in image.getpixel((320, 240)))  # 全透明 → 白底
    ranged = client.get(path, headers={**headers, "Range": "bytes=-4"})
    assert ranged.status_code == 206 and ranged.content == result.content[-4:]
    # 同一個權杖不加 .jpg 仍是原 PNG。
    again = client.get("/media/" + plain.rsplit("/", 1)[1], headers=headers)
    assert again.headers["content-type"] == "image/png"
    # 撤銷對衍生網址同樣有效。
    with factory.begin() as session:
        session.get(PublishLink, jpeg_id).revoked_at = utc_now()
    assert client.get(path, headers=headers).status_code == 404
    # 公開邊界只多放行 .jpg 後綴，其他副檔名與重複後綴仍是 404。
    token = plain.rsplit("/", 1)[1]
    for bad in (token + ".png", token + ".jpg.jpg", token + ".JPG", token + ".jpg/"):
        assert client.get("/media/" + bad, headers=headers).status_code == 404, bad
    # 移除素材時衍生檔一併刪除。
    assert derived.is_file()
    client.delete(f"/api/publish/posts/{post['id']}/media/{post['media'][0]['id']}")
    assert not derived.exists()


def test_jpeg_media_is_not_converted_and_has_no_jpg_variant(ready):
    client, _, _ = ready
    post = create(ready, "image", ["instagram"])
    factory, settings = client.app.state.session_factory, client.app.state.settings
    with factory.begin() as session:
        media = session.get(PublishMedia, post["media"][0]["id"])
        _, url = publish_media.create_link(session, settings, media, jpeg=True)
        assert not url.endswith(".jpg")
        assert not publish_media.jpeg_path(settings, media).exists()
    path = "/media/" + url.rsplit("/", 1)[1] + ".jpg"
    assert client.get(path, headers={"X-Mwb-Public": "1"}).status_code == 404


def test_png_conversion_keeps_opaque_colour(ready):
    client, _, _ = ready
    post = png_post(ready, ["instagram"], png_bytes((200, 200), "RGB", (10, 120, 240)))
    factory, settings = client.app.state.session_factory, client.app.state.settings
    with factory.begin() as session:
        media = session.get(PublishMedia, post["media"][0]["id"])
        data = publish_media.ensure_jpeg(settings, media).read_bytes()
    r, g, b = Image.open(io.BytesIO(data)).getpixel((100, 100))
    assert abs(r - 10) < 6 and abs(g - 120) < 6 and abs(b - 240) < 6


def test_png_conversion_retries_quality_then_reports_clear_error(ready, monkeypatch):
    client, _, _ = ready
    data = png_bytes((600, 600), "RGB", (0, 0, 0), noise=True)
    post = png_post(ready, ["instagram"], data)
    factory, settings = client.app.state.session_factory, client.app.state.settings
    sizes = []
    for quality in publish_media.JPEG_QUALITIES:
        buffer = io.BytesIO()
        Image.open(io.BytesIO(data)).save(buffer, "JPEG", quality=quality, optimize=True)
        sizes.append(buffer.tell())
    assert sizes[0] > sizes[1] > sizes[-1]
    with factory.begin() as session:
        media = session.get(PublishMedia, post["media"][0]["id"])
        # 上限落在品質 90 與 85 之間 → 降品質重試後成功。
        monkeypatch.setattr(publish_media, "JPEG_LIMIT", (sizes[0] + sizes[1]) // 2)
        path = publish_media.ensure_jpeg(settings, media)
        assert 0 < path.stat().st_size <= publish_media.JPEG_LIMIT
        path.unlink()
        # 上限比最低品質還小 → 明確錯誤，且不留下衍生檔。
        monkeypatch.setattr(publish_media, "JPEG_LIMIT", sizes[-1] - 1)
        with pytest.raises(HTTPException) as error:
            publish_media.create_link(session, settings, media, jpeg=True)
        assert error.value.status_code == 422 and "8 MB" in error.value.detail
        assert not path.exists()


def test_png_conversion_failure_marks_instagram_target_media_rejected(ready, monkeypatch):
    client, _, mock = ready
    post = png_post(ready, ["instagram"], png_bytes())

    def broken(image):
        raise HTTPException(422, "圖片轉成 JPEG 後仍超過 8 MB")

    monkeypatch.setattr(publish_media, "encode_jpeg", broken)
    mock.requests.clear()
    assert action(client, post).status_code == 200
    result = client.get(f"/api/publish/posts/{post['id']}").json()
    assert result["targets"][0]["status"] == "failed"
    assert not [r for r in mock.requests if "image_url" in r[3]]


def test_instagram_story_png_uses_jpeg_url(ready):
    client, _, mock = ready
    post = story_draft(ready, platforms=["instagram"], files=[png_bytes((1080, 1920))])
    mock.requests.clear()
    assert action(client, post).status_code == 200
    assert client.get(f"/api/publish/posts/{post['id']}").json()["status"] == "done"
    urls = [r[3]["image_url"] for r in mock.requests if "image_url" in r[3]]
    assert len(urls) == 1 and urls[0].endswith(".jpg")


@pytest.mark.parametrize(
    "body,previous",
    [
        ({"start_offset": "x", "end_offset": "1"}, -1),
        ({"start_offset": "5", "end_offset": "3"}, -1),
        ({"start_offset": "0", "end_offset": "999"}, -1),
        ({"start_offset": "10", "end_offset": "20"}, 10),
    ],
)
def test_facebook_video_chunk_offsets_reject_bad_or_stuck_ranges(body, previous):
    with pytest.raises(publish_platforms.PlatformFailure):
        publish_platforms.offsets(body, 100, previous)
    assert publish_platforms.offsets({"start_offset": "100", "end_offset": "100"}, 100, 50) == (
        100,
        100,
    )


def test_scheduled_post_edited_into_invalid_format_is_not_sent(ready):
    # 排程後把圖文改成影片（素材仍是圖片）：到時間不得送出，而是記為不符規則。
    client, _, mock = ready
    post = create(ready, "carousel", ["facebook", "threads"])
    when = utc_now() + timedelta(hours=2)
    assert action(client, post, when=when).status_code == 200
    post = client.get(f"/api/publish/posts/{post['id']}").json()
    body = {
        "brand_id": post["brand_id"],
        "format": "video",
        "caption": post["caption"],
        "captions": {},
        "platforms": ["facebook", "threads"],
        "media_ids": [m["id"] for m in post["media"]],
        "version": post["version"],
    }
    assert client.put(f"/api/publish/posts/{post['id']}", json=body).status_code == 200
    mock.calls.clear()
    publish.tick(client.app.state.session_factory, client.app.state.settings, when, wait=True)
    assert not [c for c in mock.calls if c[0] == "POST"]
    final = client.get(f"/api/publish/posts/{post['id']}").json()
    assert final["status"] == "failed"
    assert {t["error_code"] for t in final["targets"]} == {"rules_failed"}


def test_presence_judges_facebook_videos_and_reels_against_videos_list(ready, monkeypatch):
    # 一般影片與 Reels 記影片 ID，和 /videos 清單比對；其他格式仍和 /published_posts 比對。
    client, _, mock = ready
    feed = create(ready, "video", ["facebook"], options={"facebook": {"video_format": "feed"}})
    reel = create(ready, "video", ["facebook"])
    text = create(ready, "text", ["facebook"])
    for post in (feed, reel, text):
        assert action(client, post).status_code == 200
    with client.app.state.session_factory.begin() as session:
        for post in (feed, reel, text):
            for row in publish.targets(session, post["id"]):
                row.last_attempt_at = utc_now() - timedelta(minutes=11)
    ids = {
        p["id"]: targets_of(ready, p["id"])["facebook"].platform_post_id
        for p in (feed, reel, text)
    }
    lists = Listings(
        facebook=paged([ids[text["id"]]]), facebook_videos=paged([ids[feed["id"]]])
    ).install(monkeypatch)
    result = presence_check(ready).json()
    assert result == {"checked": 3, "newly_deleted": 1, "restored": 0, "unresolved": []}
    assert sorted(lists.calls) == ["facebook", "facebook_videos"]
    assert targets_of(ready, reel["id"])["facebook"].deleted_at
    assert not targets_of(ready, feed["id"])["facebook"].deleted_at
    assert not targets_of(ready, text["id"])["facebook"].deleted_at
    # 排程 metrics 只拿到 /published_posts：不能據此把影片判定為已刪除。
    from app.services import publish_presence

    publish_presence.record(client.app.state.session_factory, "facebook", "100", ["100_other"])
    assert not targets_of(ready, feed["id"])["facebook"].deleted_at
    mock.requests.clear()


@pytest.mark.parametrize(
    "reply,deleted",
    [
        ((200, {"id": "100_555_draft"}), False),
        ((400, {"error": {"code": 10, "message": "private"}}), True),
        ((400, {"error": {"code": 100, "error_subcode": 33, "message": "private"}}), True),
        ((400, {"error": {"code": 190, "message": "private"}}), None),
    ],
)
def test_presence_checks_facebook_drafts_one_by_one(ready, monkeypatch, reply, deleted):
    # FB 草稿逐篇查詢：存在→保留；10 或 100/33→已刪除（先確認讀得到粉專）；其他錯誤不判定。
    from app.services.gateway_workers import Workers

    draft = seed_published(ready, ("facebook",), unpublished=True, suffix="_draft")
    urls = []

    def http(method, url, *, headers=None, qs=None, body=None, timeout=15):
        urls.append(url.rsplit("/", 1)[1])
        if url.endswith("/v26.0/100"):
            return {"statusCode": 200, "body": {"id": "100"}, "headers": {}}
        status, data = reply
        return {"statusCode": status, "body": data, "headers": {}}

    monkeypatch.setattr(Workers, "http", staticmethod(http))
    result = presence_check(ready).json()
    assert urls == ["100", "100_555_draft"]
    row = targets_of(ready, draft)["facebook"]
    if deleted is None:
        assert result["checked"] == 0 and row.presence_checked_at is None
    else:
        assert result["checked"] == 1 and result["newly_deleted"] == int(deleted)
        assert bool(row.deleted_at) is deleted and row.presence_checked_at


def test_presence_skips_facebook_drafts_when_page_is_unreadable(ready, monkeypatch):
    from app.services.gateway_workers import Workers

    draft = seed_published(ready, ("facebook",), unpublished=True, suffix="_draft")

    def http(method, url, *, headers=None, qs=None, body=None, timeout=15):
        return {"statusCode": 400, "body": {"error": {"code": 10}}, "headers": {}}

    monkeypatch.setattr(Workers, "http", staticmethod(http))
    result = presence_check(ready).json()
    assert result["checked"] == 0 and result["unresolved"]
    assert targets_of(ready, draft)["facebook"].deleted_at is None


def test_manual_presence_check_also_hides_deleted_posts_in_post_data(ready, monkeypatch):
    # 「檢查平台貼文」拿到的完整清單也更新貼文數據：清單裡沒有的貼文隱藏。
    from app.models import Post

    client, brand, _ = ready
    seed_published(ready, ("facebook",))
    with client.app.state.session_factory.begin() as session:
        account = session.scalar(
            select(Account).where(Account.brand_id == brand, Account.platform == "facebook")
        )
        for identity in ("100_555", "100_gone"):
            session.add(Post(account_id=account.id, external_id=identity, caption=identity,
                             media_type="POST", published_at=utc_now()))
    Listings(facebook=paged(["100_555"])).install(monkeypatch)
    assert presence_check(ready).json()["checked"] == 1
    shown = {p["external_id"] for p in client.get("/api/posts?platform=facebook").json()}
    assert shown == {"100_555"}

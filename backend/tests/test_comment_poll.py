import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from conftest import call_service, deliver_event
from conftest import login as shared_login
from pydantic import SecretStr
from sqlalchemy import func, select

from app.models import (
    Account,
    Brand,
    CommentPoll,
    InboundJob,
    Message,
    MetaApiCall,
    Post,
    RawEvent,
    Staff,
    StaffBrand,
    Thread,
)
from app.schemas.meta import ApiCallFinish, ApiCallStart, PollCheckpoint, PollClaim, PollFinish
from app.services import comment_poll, ingest, meta_api
from app.services.passwords import hasher

NOW = datetime(2026, 9, 26, 4, 0, tzinfo=UTC)


@pytest.fixture
def poll_data(client, settings, monkeypatch):
    settings.ingest_api_key = SecretStr(secrets.token_urlsafe(32))
    settings.comments_wake_enabled = False
    monkeypatch.setattr(comment_poll, "utc_now", lambda: NOW)
    monkeypatch.setattr(meta_api, "utc_now", lambda: NOW)
    # ingest 驗證租約時也要用凍結時間；跟隨 comment_poll，讓各測試後續改時間時一併生效。
    monkeypatch.setattr(ingest, "utc_now", lambda: comment_poll.utc_now())
    with client.app.state.session_factory.begin() as session:
        brands = [Brand(slug=str(i), name=f"[測試] 品牌{i}") for i in range(2)]
        session.add_all(brands)
        session.flush()
        accounts = [
            Account(brand_id=b.id, platform="instagram", external_id=str(111 + i), name="[測試] IG")
            for i, b in enumerate(brands)
        ]
        session.add_all(accounts)
        session.flush()
        posts = [
            Post(
                account_id=accounts[0].id,
                external_id=str(1000 + i),
                caption="[測試]",
                media_type="IMAGE",
                published_at=NOW - timedelta(hours=hours),
            )
            for i, hours in enumerate([1, 48, 14 * 24, 30 * 24])
        ]
        posts.append(
            Post(
                account_id=accounts[1].id,
                external_id="other",
                caption="[測試]",
                media_type="IMAGE",
                published_at=NOW,
            )
        )
        session.add_all(posts)
        session.flush()
        password = secrets.token_urlsafe(24)
        staff = []
        for role in ["admin", "marketing", "viewer"]:
            user = Staff(
                username=role, display_name="[測試]", role=role, password_hash=hasher.hash(password)
            )
            session.add(user)
            session.flush()
            staff.append(user.id)
            if role != "admin":
                session.add(StaffBrand(staff_id=user.id, brand_id=brands[0].id))
        return {
            "headers": {"X-Api-Key": settings.ingest_api_key.get_secret_value()},
            "posts": [p.id for p in posts],
            "accounts": [a.id for a in accounts],
            "brand": brands[0].id,
            "staff": staff,
            "password": password,
        }


def internal(client, function, schema, body, *extra):
    result = call_service(client, function, schema, body, *extra)
    assert result.status_code == 200, result.text
    return result.json()


def claim_work(client, body):
    return internal(client, comment_poll.claim, PollClaim, body, client.app.state.settings)


def checkpoint_work(client, body):
    return internal(client, comment_poll.checkpoint, PollCheckpoint, body)


def finish_work(client, body):
    return internal(client, comment_poll.finish, PollFinish, body, client.app.state.settings)


def start_api_call(client, body):
    return internal(client, meta_api.start_call, ApiCallStart, body, client.app.state.settings)


def finish_api_call(client, body):
    return internal(client, meta_api.finish_call, ApiCallFinish, body)


def events(client, event, source):
    result = deliver_event(client, event, source)
    assert result.status_code == 200, result.text
    return result.json()


def queue(client, data, index=0, period="all"):
    from app.services.access import BrandAccess

    with client.app.state.session_factory() as session:
        access = BrandAccess(session, session.get(Staff, data["staff"][0]))
        return comment_poll.request_sync(
            access, post_id=data["posts"][index], settings=client.app.state.settings, period=period
        )


def claim(client, data, index=0):
    return internal(
        client,
        comment_poll.claim,
        PollClaim,
        {"account_external_id": "111", "post_id": data["posts"][index]},
        client.app.state.settings,
    )["work"]


def start(client, data, run=None, **extra):
    return internal(
        client,
        meta_api.start_call,
        ApiCallStart,
        {
            "platform": "instagram",
            "account_external_id": "111",
            "source": "poll",
            "operation": "comments",
            "resource_id": "1000",
            "run_id": run,
            **extra,
        },
        client.app.state.settings,
    )


def finish_call(client, data, call, **extra):
    return internal(
        client,
        meta_api.finish_call,
        ApiCallFinish,
        {"call_id": call["call_id"], "http_status": 200, "duration_ms": 8, **extra},
    )


def complete(client, data, work):
    return internal(
        client,
        comment_poll.finish,
        PollFinish,
        {"run_id": work["run_id"], "progress": {"comments_done": True}, "success": True},
        client.app.state.settings,
    )


def poll_event(client, data, work, text="[測試] 留言"):
    call = start(client, data, work["run_id"])
    finish_call(client, data, call)
    return {
        "platform": "instagram",
        "account_external_id": "111",
        "external_id": "poll:test-" + text,
        "source": "poll",
        "signature_ok": False,
        "poll_run_id": work["run_id"],
        "poll_call_id": call["call_id"],
        "payload": {"data": [{"id": "comment-1", "text": text}]},
        "messages": [
            {
                "external_id": "comment-1",
                "thread_external_id": "1000",
                "kind": "comment_thread",
                "post_external_id": "1000",
                "contact": {"external_id": "fan-1"},
                "direction": "in",
                "author_type": "fan",
                "text": text,
                "sent_at": "2026-09-26T03:58:00Z",
            }
        ],
    }


def login(client, data, role):
    return shared_login(client, role, data["password"])


def test_age_tiers_never_queue_automatic_comments(client, poll_data, settings):
    for webhook_live in (False, True):
        settings.meta_ig_comments_webhook_live = webhook_live
        for index in range(4):
            assert claim(client, poll_data, index) is None
    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(CommentPoll)) == 0


def test_concurrent_claims_lease_recovery_and_durable_cursor(client, poll_data, monkeypatch):
    queue(client, poll_data)
    with ThreadPoolExecutor(max_workers=4) as pool:
        works = list(pool.map(lambda _: claim(client, poll_data), range(4)))
    assert len([w for w in works if w]) == 1
    work = next(w for w in works if w)
    progress = {
        "after": "fixture-cursor",
        "comments_done": False,
        "replies": [{"id": "parent-1", "after": "reply-cursor"}],
    }
    internal(
        client,
        comment_poll.checkpoint,
        PollCheckpoint,
        {"run_id": work["run_id"], "progress": progress},
    )
    monkeypatch.setattr(comment_poll, "utc_now", lambda: NOW + timedelta(minutes=3))
    recovered = claim(client, poll_data)
    assert recovered["run_id"] != work["run_id"]
    assert recovered["progress"] == {
        **progress,
        "pages": 0,
        "saved_comments": 0,
        "full_rescan": False,
        "new_comments": 0,
    }
    assert (
        call_service(
            client,
            comment_poll.checkpoint,
            PollCheckpoint,
            {"run_id": work["run_id"], "progress": {}},
        ).status_code
        == 409
    )


def test_finished_work_never_repolls_without_another_click(client, poll_data, monkeypatch):
    queue(client, poll_data)
    complete(client, poll_data, claim(client, poll_data))
    for elapsed in (timedelta(minutes=10), timedelta(days=1), timedelta(days=100)):
        monkeypatch.setattr(comment_poll, "utc_now", lambda elapsed=elapsed: NOW + elapsed)
        assert claim(client, poll_data) is None


def test_poll_webhook_dedup_edit_and_stale_delivery(client, poll_data, monkeypatch):
    queue(client, poll_data)
    work = claim(client, poll_data)
    event = poll_event(client, poll_data, work)
    # Event IDs themselves contain no message text or whitespace.
    event["external_id"] = "poll:fixture-v1"
    first = events(client, event, "poll")
    assert first["created_messages"] == 1
    assert events(client, event, "poll")["unchanged_messages"] == 1
    webhook = {k: v for k, v in event.items() if not k.startswith("poll_")}
    webhook.update(
        source="webhook",
        signature_ok=True,
        external_id="webhook-fixture",
        observed_at=(NOW + timedelta(seconds=1)).isoformat(),
    )
    assert events(client, webhook, "webhook")["unchanged_messages"] == 1
    monkeypatch.setattr(meta_api, "utc_now", lambda: NOW + timedelta(seconds=5))
    edited = poll_event(client, poll_data, work, "[測試] 更新內容")
    edited["external_id"] = "poll:fixture-v2"
    assert events(client, edited, "poll")["updated_messages"] == 1
    assert events(client, webhook, "webhook")["unchanged_messages"] == 1
    with client.app.state.session_factory() as session:
        message = session.scalar(select(Message))
        assert message.text == "[測試] 更新內容"
        assert message.edited_at is not None
        assert message.sources_json == ["poll", "webhook"]
        assert session.scalar(select(func.count()).select_from(Message)) == 1
        assert session.scalar(select(func.count()).select_from(InboundJob)) == 2
        assert session.scalar(select(Thread)).post_id == poll_data["posts"][0]
        assert all(
            not r.signature_ok
            for r in session.scalars(select(RawEvent).where(RawEvent.source == "poll"))
        )


@pytest.mark.parametrize(
    "change,source",
    [
        ({"signature_ok": True}, "poll"),
        ({"poll_call_id": 99999}, "poll"),
        ({"source": "poll"}, "webhook"),
    ],
)
def test_poll_cannot_forge_signature_or_bypass_call_lease(client, poll_data, change, source):
    queue(client, poll_data)
    event = poll_event(client, poll_data, claim(client, poll_data))
    event["external_id"] = "poll:invalid-fixture"
    event.update(change)
    response = deliver_event(client, event, source)
    assert response.status_code in {403, 422}
    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 0
        assert session.scalar(select(RawEvent)).error


def test_post_scope_cannot_be_replaced_in_poll(client, poll_data):
    queue(client, poll_data)
    event = poll_event(client, poll_data, claim(client, poll_data))
    event["external_id"] = "poll:scope-fixture"
    event["messages"][0]["post_external_id"] = "other"
    response = deliver_event(client, event, "poll")
    assert response.status_code == 422
    assert response.json()["error"] == "poll_post_mismatch"


@pytest.mark.parametrize(
    "extra,minimum",
    [
        ({"app_usage": {"call_count": 81}}, 600),
        ({"business_usage": [{"total_cputime": 91}]}, 1800),
        (
            {
                "http_status": 429,
                "error_code": 4,
                "business_usage": [{"estimated_time_to_regain_access": 90}],
            },
            5400,
        ),
    ],
)
def test_rate_headers_block_both_workers_and_log_safely(
    client, poll_data, settings, extra, minimum
):
    call = start(client, poll_data)
    result = finish_call(client, poll_data, call, **extra)
    assert datetime.fromisoformat(result["retry_at"]) >= NOW + timedelta(seconds=minimum)
    assert not start(client, poll_data, source="metrics")["allowed"]
    result = internal(
        client,
        comment_poll.claim,
        PollClaim,
        {"account_external_id": "111"},
        client.app.state.settings,
    )
    assert result["work"] is None and result["retry_at"]
    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(MetaApiCall)) == 1
        assert meta_api.multiplier(session, NOW) >= 2
    logs = settings.log_path.read_text(encoding="utf-8")
    assert "meta_api_call" in logs and "meta_rate_backoff" in logs
    assert settings.ingest_api_key.get_secret_value() not in logs
    assert "Authorization" not in logs


def test_missing_headers_still_count_against_local_budget(client, poll_data, settings):
    settings.meta_api_calls_per_hour = 10
    for _ in range(10):
        call = start(client, poll_data)
        assert call["allowed"]
        finish_call(client, poll_data, call)
    assert not start(client, poll_data)["allowed"]


def test_manual_sync_requires_csrf_write_role_and_brand(client, poll_data):
    path = f"/api/posts/{poll_data['posts'][0]}/comments/sync"
    assert client.post(path).status_code == 401
    headers = login(client, poll_data, "marketing")
    assert client.post(path).status_code == 403
    assert (
        client.post(path, headers={**headers, "Origin": "https://outside.invalid"}).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/posts/{poll_data['posts'][-1]}/comments/sync", headers=headers
        ).status_code
        == 404
    )
    assert client.post(path, headers=headers).status_code == 202
    assert client.get(path).json()["state"] == "pending"
    headers = login(client, poll_data, "viewer")
    assert client.post(path, headers=headers).status_code == 403


def test_recent_batch_endpoint_retired_and_does_not_queue(client, poll_data):
    headers = login(client, poll_data, "marketing")
    assert client.post("/api/posts/comments/sync", headers=headers).status_code == 410
    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(CommentPoll)) == 0

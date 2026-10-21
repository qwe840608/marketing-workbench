"""Window boundaries and one-off reads use isolated DBs and HTTP mocks."""

from datetime import timedelta

import pytest
from message_fixtures import send_data as send_data
from pydantic import SecretStr
from sqlalchemy import func, select
from test_comment_poll import NOW, claim, complete, login, queue, start_api_call
from test_comment_poll import poll_data as poll_data

from app.models import AuditLog, CommentBackfill, CommentPoll, Message, Post
from app.services.gateway_workers import Workers


def response(rows, after=None):
    body = {"data": rows}
    if after:
        body["paging"] = {"cursors": {"after": after}, "next": "unused"}
    return {"statusCode": 200, "body": body, "headers": {}}


def test_message_boundary_and_all_history(client):
    """Retired DM workflow: its API is absent, with no side effects."""
    from test_dm_backfill_history import assert_retired

    assert_retired(client)


def test_conversation_exploration_boundary(client):
    """Retired DM workflow: its API is absent, with no side effects."""
    from test_dm_backfill_history import assert_retired

    assert_retired(client)


def test_missing_discovery_time_cannot_establish_order(client):
    """Retired DM workflow: its API is absent, with no side effects."""
    from test_dm_backfill_history import assert_retired

    assert_retired(client)


def test_cursor_retry_limit_survives_runs(client):
    """Retired DM workflow: its API is absent, with no side effects."""
    from test_dm_backfill_history import assert_retired

    assert_retired(client)


def test_discovery_retry_limit_completes_job(client):
    """Retired DM workflow: its API is absent, with no side effects."""
    from test_dm_backfill_history import assert_retired

    assert_retired(client)


def test_automatic_selection_disabled_even_with_old_configuration(client, poll_data, settings):
    for days in (30, 90, 3650):
        settings.__dict__["meta_comments_auto_days"] = days
        assert claim(client, poll_data, 2) is None
        assert claim(client, poll_data, 3) is None


def test_old_backfill_and_stale_replies_do_not_call(client, poll_data, settings):
    with client.app.state.session_factory.begin() as session:
        old = session.get(Post, poll_data["posts"][3])
        backfill = CommentBackfill(
            account_id=old.account_id, window_start=NOW - timedelta(days=90), window_end=NOW
        )
        session.add(backfill)
        session.flush()
        session.add(
            CommentPoll(
                account_id=old.account_id,
                post_id=old.id,
                resource=old.external_id,
                backfill_id=backfill.id,
                next_poll_at=NOW,
                requested_at=NOW,
                progress_json={"comments_done": True, "replies": [{"id": "stale", "after": None}]},
            )
        )
    assert claim(client, poll_data, 3) is None
    with client.app.state.session_factory() as session:
        row = session.scalar(
            select(CommentPoll).where(CommentPoll.post_id == poll_data["posts"][3])
        )
        assert row.progress_json["replies"] == [{"id": "stale", "after": None}]
        assert row.run_id is None and not row.manual_requested
    headers = login(client, poll_data, "marketing")
    assert client.post("/api/posts/comments/backfill", headers=headers).status_code == 410
    with client.app.state.session_factory() as session:
        posts = session.scalars(select(CommentPoll).where(CommentPoll.backfill_id.is_not(None)))
        assert all(not p.manual_requested and p.run_id is None for p in posts)


@pytest.mark.parametrize("role", ["admin", "marketing"])
def test_manual_old_post_dedup_audit_completion_and_budget(client, poll_data, settings, role):
    headers = login(client, poll_data, role)
    post_id = poll_data["posts"][3]
    path = f"/api/posts/{post_id}/comments/sync"
    assert client.post(path, headers=headers).json() == {"queued": 1}
    assert client.post(path, headers=headers).json() == {"queued": 0}
    work = claim(client, poll_data, 3)
    from app.services.date_ranges import date_bounds
    assert work and work["window_start"] == date_bounds("30", now=NOW)[0].isoformat()
    assert work["window_end"] == NOW.isoformat()
    assert client.post(path, headers=headers).json() == {"queued": 0}
    settings.meta_api_calls_per_hour = 10
    for _ in range(10):
        permit = start_api_call(
            client, {
                "platform": "instagram",
                "account_external_id": "111",
                "source": "poll",
                "operation": "replies",
                "resource_id": "manual-root",
                "run_id": work["run_id"],
            },
        )
        assert permit["allowed"]
    assert not start_api_call(
            client, {
            "platform": "instagram",
            "account_external_id": "111",
            "source": "poll",
            "operation": "replies",
            "resource_id": "manual-root",
            "run_id": work["run_id"],
        },
    )["allowed"]
    status = client.get(path).json()
    assert status["state"] == "throttled" and status["wait_reason"] == "system_budget"
    assert status["auto_sync_enabled"] is False
    complete(client, poll_data, work)
    assert client.get(path).json()["last_auto_completed_at"] is None
    assert client.get(path).json()["state"] == "idle"
    assert claim(client, poll_data, 3) is None
    with client.app.state.session_factory() as session:
        audits = list(
            session.scalars(select(AuditLog).where(AuditLog.action == "comments.request"))
        )
        assert len(audits) == 3
        assert [a.detail_json["queued"] for a in audits] == [1, 0, 0]
        assert all(
            a.actor.startswith("staff:") and a.detail_json["post_id"] == post_id for a in audits
        )
        assert (
            session.scalar(
                select(func.count()).select_from(CommentPoll).where(CommentPoll.post_id == post_id)
            )
            == 1
        )


def test_manual_completion_never_updates_automatic_time(client, poll_data):
    queue(client, poll_data)
    work = claim(client, poll_data)
    complete(client, poll_data, work)
    login(client, poll_data, "admin")
    state = client.get(f"/api/posts/{poll_data['posts'][0]}/comments/sync").json()
    assert state["last_auto_completed_at"] is None
    assert state["last_completed_at"] == NOW.isoformat()
    assert state["auto_sync_enabled"] is False


def test_manual_old_post_reads_comments_and_replies_once(client, poll_data, settings):
    headers = login(client, poll_data, "marketing")
    post_id = poll_data["posts"][3]
    path = f"/api/posts/{post_id}/comments/sync"
    assert client.post(path, headers=headers).json() == {"queued": 1}
    settings.meta_page_id = ""
    settings.meta_ig_account_id = "111"
    settings.meta_page_access_token = SecretStr("isolated-http-mock")
    calls = []

    def request(method, url, **kw):
        assert method == "GET"
        edge = url.rsplit("/", 1)[-1]
        calls.append(edge)
        return response(
            [
                {
                    "id": "manual-root" if edge == "comments" else "manual-reply",
                    "timestamp": (NOW - timedelta(days=29)).isoformat(),
                    "from": {"id": "isolated-fan", "username": "[隔離測試]"},
                    "text": "[隔離測試] 舊貼文留言",
                    "replies": {
                        "data": [
                            {
                                "id": "manual-reply",
                                "timestamp": (NOW - timedelta(days=29)).isoformat(),
                                "from": {"id": "isolated-fan"},
                                "text": "[隔離測試] 回覆",
                            }
                        ]
                    },
                }
            ]
        )

    worker = Workers(client.app.state.session_factory, settings, request=request)
    assert worker.comments(requested_only=True, post_id=post_id)["completed"] == 1
    assert calls == ["comments"]
    assert worker.comments(requested_only=True, post_id=post_id)["completed"] == 0
    assert calls == ["comments"]
    with client.app.state.session_factory() as session:
        assert set(session.scalars(select(Message.external_id))) == {"manual-root", "manual-reply"}
    assert client.get(path).json()["last_auto_completed_at"] is None

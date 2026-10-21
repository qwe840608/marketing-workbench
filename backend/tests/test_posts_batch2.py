"""Batch 2 regression tests use isolated databases and explicit platform fixtures."""

import copy
from datetime import timedelta

import pytest
from conftest import call_service, deliver_event
from sqlalchemy import func, select
from test_comment_poll import (
    NOW,
    checkpoint_work,
    claim_work,
    events,
    finish_api_call,
    finish_work,
    login,
    start_api_call,
)
from test_comment_poll import poll_data as poll_data

from app.models import Account, CommentBackfill, CommentPoll, Message, Post, Staff, Thread
from app.schemas.meta import PollFinish
from app.services import comment_backfill, comment_poll


@pytest.fixture
def batch2(client, poll_data, monkeypatch, settings):
    # Keep the historical-window contracts exact while exercising a configured 90-day scope.
    settings.__dict__["meta_comments_auto_days"] = 90
    monkeypatch.setattr(comment_backfill, "utc_now", lambda: NOW)
    with client.app.state.session_factory.begin() as session:
        account = Account(
            brand_id=poll_data["brand"],
            platform="facebook",
            external_id="fb-test",
            name="[測試] FB",
        )
        session.add(account)
        session.flush()
        post = Post(
            account_id=account.id,
            external_id="fb-post",
            caption="[測試] Reels",
            media_type="REELS",
            published_at=NOW,
        )
        old = Post(
            account_id=account.id,
            external_id="fb-old",
            caption="[測試] 89 天",
            media_type="POST",
            published_at=NOW - timedelta(days=89),
        )
        session.add_all([post, old])
        session.flush()
        return {**poll_data, "fb_post": post.id, "fb_account": account.id}


def start_backfill(client, data, platform="facebook"):
    headers = login(client, data, "marketing")
    return client.post("/api/posts/comments/backfill?platform=" + platform, headers=headers)


def claim_fb(client, data, post_id=None):
    if post_id is not None and post_id not in data.setdefault("explicitly_requested", set()):
        from app.services.access import BrandAccess

        with client.app.state.session_factory() as session:
            comment_poll.request_sync(
                BrandAccess(session, session.get(Staff, data["staff"][0])),
                post_id=post_id,
                settings=client.app.state.settings,
            )
        data["explicitly_requested"].add(post_id)
    return claim_work(
        client, {
            "platform": "facebook",
            "account_external_id": "fb-test",
            "post_id": post_id,
        },
    )["work"]


def finish(client, data, work, **extra):
    return finish_work(
        client, {
            "run_id": work["run_id"],
            "progress": {"comments_done": True},
            "success": True,
            **extra,
        },
    )


def test_platform_filter_defaults_brand_and_pagination(client, batch2):
    login(client, batch2, "marketing")
    assert client.get("/api/posts/platforms").json()["default_platform"] == "facebook"
    fb = client.get("/api/posts?platform=facebook&limit=1").json()
    assert [p["id"] for p in fb] == [batch2["fb_post"]]
    ig = client.get("/api/posts?platform=instagram").json()
    assert {p["account_id"] for p in ig} == {batch2["accounts"][0]}
    assert len(client.get("/api/posts?platform=facebook&offset=1&limit=1").json()) == 1
    assert client.get("/api/posts?platform=all").status_code == 422


def test_backfill_window_one_time_and_permissions(client, batch2):
    assert client.post("/api/posts/comments/backfill").status_code == 401
    headers = login(client, batch2, "viewer")
    assert client.post("/api/posts/comments/backfill", headers=headers).status_code == 403
    headers = login(client, batch2, "marketing")
    assert client.post("/api/posts/comments/backfill").status_code == 403
    other = client.get("/api/posts?brand_id=999")
    assert other.status_code == 404
    assert start_backfill(client, batch2).status_code == 410
    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(CommentBackfill)) == 0
        assert session.scalar(select(func.count()).select_from(CommentPoll)) == 0


def test_backfill_discovery_is_separate_and_completion_survives_restart(client, batch2):
    assert start_backfill(client, batch2).status_code == 410
    assert claim_fb(client, batch2) is None
    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(CommentBackfill)) == 0
        assert session.scalar(select(func.count()).select_from(CommentPoll)) == 0


def test_empty_90_day_window_is_not_completed_until_discovery(client, batch2):
    assert start_backfill(client, batch2).status_code == 410
    assert claim_fb(client, batch2) is None
    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(CommentBackfill)) == 0
        assert session.scalar(select(func.count()).select_from(CommentPoll)) == 0


def test_backfill_partial_cursor_lease_and_budget_never_mark_complete(client, batch2, monkeypatch):
    assert start_backfill(client, batch2).status_code == 410
    work = claim_fb(client, batch2, batch2["fb_post"])
    progress = {
        "after": "next-page",
        "comments_done": False,
        "replies": [{"id": "parent", "after": "next-reply"}],
    }
    checkpoint_work(
        client, {"run_id": work["run_id"], "progress": progress}
    )
    assert claim_fb(client, batch2, batch2["fb_post"]) is None
    monkeypatch.setattr(comment_poll, "utc_now", lambda: NOW + timedelta(minutes=3))
    resumed = claim_fb(client, batch2, batch2["fb_post"])
    assert resumed["progress"] == {
        **progress,
        "pages": 0,
        "saved_comments": 0,
        "full_rescan": False,
        "new_comments": 0,
    }
    assert resumed["run_id"] != work["run_id"]
    finish(client, batch2, resumed, progress=progress, success=False, error="meta_rate_limited")
    status = client.get(f"/api/posts/{batch2['fb_post']}/comments/sync").json()
    assert status["last_completed_at"] is None
    assert claim_fb(client, batch2, batch2["fb_post"]) is None


def test_backfill_rejects_false_completion(client, batch2):
    assert start_backfill(client, batch2).status_code == 410
    work = claim_fb(client, batch2, batch2["fb_post"])
    response = call_service(
        client,
        comment_poll.finish,
        PollFinish,
        {
            "run_id": work["run_id"],
            "success": True,
            "progress": {"comments_done": False},
        },
        client.app.state.settings,
    )
    assert response.status_code == 422


def fb_event(client, data, work):
    call = start_api_call(
        client, {
            "platform": "facebook",
            "account_external_id": "fb-test",
            "source": "poll",
            "operation": "comments",
            "resource_id": "fb-post",
            "run_id": work["run_id"],
        },
    )
    finish_api_call(
        client, {
            "call_id": call["call_id"],
            "http_status": 200,
            "duration_ms": 1,
        },
    )
    messages = []
    for index, (parent, root, known) in enumerate(
        [(None, "c0", True), ("c0", "c0", True), (None, None, False)]
    ):
        messages.append(
            {
                "external_id": "c" + str(index),
                "thread_external_id": "fb-post",
                "kind": "comment_thread",
                "post_external_id": "fb-post",
                "contact": {"external_id": "viewer" + str(index), "display_name": "[測試] 觀眾"},
                "direction": "out" if index == 1 else "in",
                "author_type": "brand" if index == 1 else "fan",
                "text": "[測試] 原文 " + str(index),
                "sent_at": (NOW - timedelta(seconds=3 - index)).isoformat(),
                "source_ref_json": {"parent_known": known, "parent_id": parent, "root_id": root},
            }
        )
    return {
        "platform": "facebook",
        "account_external_id": "fb-test",
        "external_id": "poll:fb-page",
        "source": "poll",
        "signature_ok": False,
        "poll_run_id": work["run_id"],
        "poll_call_id": call["call_id"],
        "payload": {"fixture": True},
        "messages": messages,
    }


def test_fb_ingest_replay_inbox_identity_and_unknown_parent(client, batch2):
    work = claim_fb(client, batch2, batch2["fb_post"])
    event = fb_event(client, batch2, work)
    first = events(client, event, "poll")
    assert first["created_messages"] == 3
    assert events(client, event, "poll")["created_messages"] == 0
    login(client, batch2, "marketing")
    path = f"/api/posts/{batch2['fb_post']}/comments"
    page = client.get(path + "?limit=2").json()
    next_page = client.get(path + "?after_id=" + str(page["next_after"])).json()
    messages = page["items"] + next_page["items"]
    assert len(messages) == 3 and next_page["next_after"] is None
    assert messages[0]["thread_id"] == messages[1]["thread_id"] != messages[2]["thread_id"]
    assert messages[2]["comment_parent_known"] is False and messages[2]["comment_root_id"] is None
    for message in messages:
        inbox = client.get(f"/api/threads/{message['thread_id']}/messages").json()
        assert any(row["id"] == message["id"] and row["text"] == message["text"] for row in inbox)
    edited = copy.deepcopy(event)
    edited["external_id"] = "poll:edited"
    edited["messages"][0]["text"] = "[測試] 已編輯原文"
    events(client, edited, "poll")
    assert client.get(path).json()["items"][0]["text"] == "[測試] 已編輯原文"


def test_comments_exclude_dm_and_cross_brand(client, batch2):
    work = claim_fb(client, batch2, batch2["fb_post"])
    events(client, fb_event(client, batch2, work), "poll")
    with client.app.state.session_factory.begin() as session:
        dm = Thread(
            brand_id=batch2["brand"],
            account_id=batch2["fb_account"],
            kind="dm",
            external_id="dm-fixture",
            post_id=batch2["fb_post"],
        )
        session.add(dm)
        session.flush()
        session.add(
            Message(
                thread_id=dm.id,
                external_id="private",
                text="[測試] 不公開私訊",
                direction="in",
                author_type="fan",
                sent_at=NOW,
            )
        )
    login(client, batch2, "marketing")
    result = client.get(f"/api/posts/{batch2['fb_post']}/comments").json()
    assert result["total"] == 3 and all(m["external_id"] != "private" for m in result["items"])
    assert client.get(f"/api/posts/{batch2['posts'][-1]}/comments").status_code == 404


def test_fb_poll_rejects_ig_lease_and_forged_dm(client, batch2):
    work = claim_fb(client, batch2, batch2["fb_post"])
    event = fb_event(client, batch2, work)
    for mutate in ("account", "dm"):
        wrong = copy.deepcopy(event)
        wrong["external_id"] += mutate
        if mutate == "account":
            wrong.update(platform="instagram", account_external_id="111")
        else:
            wrong["messages"][0]["kind"] = "dm"
        response = deliver_event(client, wrong, "poll")
        assert response.status_code == (410 if mutate == "dm" else 422)
    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 0


def test_comment_pages_return_every_message_past_200_without_duplicates(client, batch2):
    with client.app.state.session_factory.begin() as session:
        thread = Thread(
            brand_id=batch2["brand"],
            account_id=batch2["fb_account"],
            kind="comment_thread",
            post_id=batch2["fb_post"],
            external_id="many",
        )
        session.add(thread)
        session.flush()
        session.add_all(
            [
                Message(
                    thread_id=thread.id,
                    external_id=f"many-{i}",
                    text=f"[測試] {i}",
                    direction="in",
                    author_type="fan",
                    sent_at=NOW - timedelta(seconds=i),
                )
                for i in range(205)
            ]
        )
    login(client, batch2, "marketing")
    path = f"/api/posts/{batch2['fb_post']}/comments"
    first = client.get(path).json()
    second = client.get(path + "?after_id=" + str(first["next_after"])).json()
    assert first["total"] == 205
    assert len(first["items"]) == 200 and len(second["items"]) == 5
    assert len({m["id"] for m in first["items"] + second["items"]}) == 205
    assert second["next_after"] is None


def test_new_discovered_post_is_added_to_backfill_before_discovery_completes(client, batch2):
    assert start_backfill(client, batch2).status_code == 410
    assert claim_fb(client, batch2) is None
    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(CommentBackfill)) == 0
        assert session.scalar(select(func.count()).select_from(CommentPoll)) == 0


def test_retired_backfill_does_not_restart_existing_manual_cursor(client, batch2):
    work = claim_fb(client, batch2, batch2["fb_post"])
    progress = {"after": "manual-page", "comments_done": False, "replies": []}
    checkpoint_work(
        client, {"run_id": work["run_id"], "progress": progress}
    )
    assert start_backfill(client, batch2).status_code == 410
    with client.app.state.session_factory() as session:
        state = session.scalar(select(CommentPoll).where(CommentPoll.post_id == batch2["fb_post"]))
        assert state.run_id == work["run_id"] and state.progress_json["after"] == "manual-page"
    finish(client, batch2, work)
    assert claim_fb(client, batch2, batch2["fb_post"]) is None

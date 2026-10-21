from datetime import UTC, datetime, timedelta

import pytest
from test_classify import classified_data as classified_data
from test_workspace import add_thread
from test_workspace import workspace as workspace

from app.models import Account, Classification, Message, MetricSnapshot, Post
from app.services import classify, dashboard

# 台北 2026-12-16（週三）20:00；種子貼文（2026-09）在 30 天窗外。
NOW = datetime(2026, 12, 16, 12, tzinfo=UTC)
WEEK_START = datetime(2026, 12, 13, 16, tzinfo=UTC)


def test_summary_compares_with_same_span_last_week(client, workspace, monkeypatch):
    monkeypatch.setattr(dashboard, "utc_now", lambda: NOW)
    with client.app.state.session_factory.begin() as session:
        account = session.get(Account, workspace["fb_id"])
        for name, when in [
            ("this-1", WEEK_START),
            ("this-2", NOW - timedelta(hours=1)),
            ("this-3", NOW),
            ("prev-start", WEEK_START - timedelta(days=7)),
            ("prev-mid", NOW - timedelta(days=8)),
            # 七天前的此刻不含，之後的上週留言也不算同期。
            ("prev-boundary", NOW - timedelta(days=7)),
            ("prev-later", NOW - timedelta(days=6, hours=12)),
            ("older", WEEK_START - timedelta(days=7, seconds=1)),
        ]:
            add_thread(session, account, name, when)
    value = client.get(f"/api/dashboard?brand_id={workspace['brand_id']}").json()
    assert value["new_comments"] == 3
    previous = value["previous"]
    assert previous["new_comments"] == 2
    assert datetime.fromisoformat(previous["start"]) == WEEK_START - timedelta(days=7)
    assert datetime.fromisoformat(previous["end"]) == NOW - timedelta(days=7)
    other = client.get(f"/api/dashboard?brand_id={workspace['other_brand']}").json()
    assert other["previous"]["new_comments"] == 0


def test_trends_previous_total_uses_equal_prior_window(client, workspace, monkeypatch):
    monkeypatch.setattr(dashboard, "utc_now", lambda: NOW)
    start = datetime(2026, 12, 9, 16, tzinfo=UTC)  # 7 天窗起點：台北 12/10 00:00
    with client.app.state.session_factory.begin() as session:
        account = session.get(Account, workspace["fb_id"])
        for name, when in [
            ("current-start", start),
            ("current", NOW - timedelta(hours=2)),
            ("prior-last", start - timedelta(seconds=1)),
            ("prior-first", start - timedelta(days=7)),
            ("too-old", start - timedelta(days=7, seconds=1)),
        ]:
            add_thread(session, account, name, when)
    value = client.get(f"/api/dashboard/trends?brand_id={workspace['brand_id']}&days=7").json()
    assert sum(row["new_messages"] for row in value["series"]) == 2
    assert value["previous_total"] == 2
    assert all(set(row) == {"date", "new_messages"} for row in value["series"])


def add_post(session, account_id, name, published, **metrics):
    post = Post(
        account_id=account_id,
        external_id=name,
        caption=name,
        media_type="image",
        published_at=published,
    )
    session.add(post)
    session.flush()
    if metrics:
        session.add(MetricSnapshot(post_id=post.id, captured_at=published, reach=1))
        session.add(
            MetricSnapshot(post_id=post.id, captured_at=published + timedelta(hours=1), **metrics)
        )
    return post


def comment(session, account, post, name, intent=None, *, stale=False, brand=False):
    thread, message = add_thread(session, account, name, NOW - timedelta(hours=1))
    thread.post_id = post.id
    if brand:
        message.author_type = "brand"
    if intent:
        session.flush()
        context, _ = classify.context_for(session, message)
        session.add(
            Classification(
                message_id=message.id,
                engine="keyword",
                intent=intent,
                sentiment="neutral",
                action="classified",
                sensitive=False,
                confidence=1,
                input_hash=classify.fingerprint(message.text, context),
            )
        )
        if stale:
            message.text = "[測試] 修改過的留言"
    return message


def test_funnel_stages_from_same_posts(client, workspace, monkeypatch):
    monkeypatch.setattr(dashboard, "utc_now", lambda: NOW)
    with client.app.state.session_factory.begin() as session:
        account = session.get(Account, workspace["fb_id"])
        recent = NOW - timedelta(days=3)
        first = add_post(
            session, account.id, "f1", recent, reach=1000, likes=50, comments=10, shares=5
        )
        second = add_post(session, account.id, "f2", recent, reach=500, likes=20, saves=4)
        no_reach = add_post(session, account.id, "f3", recent, views=900, likes=99)
        old = add_post(session, account.id, "f4", NOW - timedelta(days=40), reach=7000, likes=1)
        deleted = add_post(session, account.id, "f5", recent, reach=300, likes=3)
        deleted.deleted_at = NOW
        comment(session, account, first, "c-price", "price")
        comment(session, account, first, "c-booking", "booking")
        comment(session, account, second, "c-question", "model_question")
        comment(session, account, second, "c-complaint", "complaint")
        comment(session, account, second, "c-stale", "price", stale=True)
        comment(session, account, second, "c-none")
        comment(session, account, first, "c-brand", "price", brand=True)
        comment(session, account, no_reach, "c-other-post", "price")
        comment(session, account, old, "c-old-post", "price")
    response = client.get(f"/api/dashboard/funnel?brand_id={workspace['brand_id']}&days=30")
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["days"] == 30 and value["posts"] == 2
    assert {row["key"]: row["value"] for row in value["stages"]} == {
        "reach": 1500,
        "engagement": 89,
        "comments": 6,
        "inquiries": 3,
    }
    assert [row["key"] for row in value["stages"]] == [
        "reach",
        "engagement",
        "comments",
        "inquiries",
    ]
    empty = client.get(f"/api/dashboard/funnel?brand_id={workspace['other_brand']}").json()
    assert empty["posts"] == 0 and all(row["value"] == 0 for row in empty["stages"])


@pytest.mark.parametrize("days", [0, 14, "x"])
def test_funnel_rejects_days(client, workspace, days):
    assert client.get(f"/api/dashboard/funnel?days={days}").status_code == 422


def test_funnel_requires_login(client):
    assert client.get("/api/dashboard/funnel").status_code == 401


def test_funnel_ignores_message_direction_out(client, workspace, monkeypatch):
    monkeypatch.setattr(dashboard, "utc_now", lambda: NOW)
    with client.app.state.session_factory.begin() as session:
        account = session.get(Account, workspace["fb_id"])
        post = add_post(session, account.id, "g1", NOW - timedelta(days=1), reach=10, likes=1)
        message = comment(session, account, post, "g-out", "price")
        message.direction = "out"
        session.add(
            Message(
                thread_id=message.thread_id,
                external_id="g-in",
                direction="in",
                author_type="fan",
                text="[測試] 留言",
                sent_at=NOW + timedelta(minutes=5),  # 未來留言不算
            )
        )
    value = client.get(f"/api/dashboard/funnel?brand_id={workspace['brand_id']}").json()
    assert {row["key"]: row["value"] for row in value["stages"]}["comments"] == 0

"""平台資料保留與刪除：全部使用合成資料，不呼叫任何平台。

- 留言超過保留天數刪除（含分類、通知與投遞快取、無人引用的聯絡人）。
- YouTube 留言 30 天未更新、YouTube 已刪影片 30 天後刪除。
- YouTube 中斷連結刪除所有 YouTube 資料；其他平台不受影響。
- 主題發想報告只移除被刪的引用原文與貼文說明，主題本身保留。
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from test_classify import classified_data as classified_data

from app.models import (
    Account,
    AuditLog,
    Classification,
    Contact,
    IdeationReport,
    Message,
    MetricSnapshot,
    Notification,
    NotificationDelivery,
    Post,
    PostThumbnail,
    Thread,
)
from app.services import data_retention

NOW = datetime(2026, 12, 16, 12, tzinfo=UTC)


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


@pytest.fixture
def world(client, classified_data):
    factory = client.app.state.session_factory
    brand = classified_data["brand_id"]
    ids = {}
    with factory.begin() as session:
        accounts = {
            p: Account(brand_id=brand, platform=p, external_id=f"ret-{p}", name=f"{p} 頻道")
            for p in ("instagram", "youtube")
        }
        session.add_all(accounts.values())
        session.flush()

        def post(platform, key, deleted_days=None):
            row = Post(
                account_id=accounts[platform].id,
                external_id=key,
                caption=f"{key} 說明",
                media_type="VIDEO",
                published_at=NOW - timedelta(days=400),
                deleted_at=NOW - timedelta(days=deleted_days) if deleted_days else None,
            )
            session.add(row)
            session.flush()
            session.add(MetricSnapshot(post_id=row.id, captured_at=NOW, views=1))
            session.add(PostThumbnail(post_id=row.id, status="ready"))
            ids[key] = row.id
            return row

        def comment(platform, key, post_row, days, observed_days=None, contact=None):
            thread = Thread(
                brand_id=brand,
                account_id=accounts[platform].id,
                external_id=key,
                kind="comment_thread",
                post_id=post_row.id,
                contact_id=contact.id if contact else None,
            )
            session.add(thread)
            session.flush()
            message = Message(
                thread_id=thread.id,
                contact_id=contact.id if contact else None,
                external_id=key,
                direction="in",
                author_type="fan",
                text=f"{key} 原文",
                sent_at=NOW - timedelta(days=days),
                content_observed_at=(
                    NOW - timedelta(days=observed_days) if observed_days is not None else None
                ),
            )
            message.created_at = NOW - timedelta(days=days)
            session.add(message)
            session.flush()
            ids[key] = message.id
            ids[key + ":thread"] = thread.id
            return message

        ig_post = post("instagram", "ig-post")
        fan = Contact(
            brand_id=brand, platform="instagram", external_id="ret-fan", display_name="合成觀眾"
        )
        session.add(fan)
        session.flush()
        ids["fan"] = fan.id
        old = comment("instagram", "ig-old", ig_post, 400, contact=fan)
        comment("instagram", "ig-new", ig_post, 10)
        session.add(
            Classification(
                message_id=old.id,
                engine="jev",
                intent="complaint",
                sentiment="negative",
                sensitive=False,
                action="classified",
                confidence=0.9,
            )
        )
        delivery = NotificationDelivery(
            brand_id=brand,
            retry_key="ret-delivery",
            recipient="group",
            messages_json=[{"type": "text", "text": "ig-old 原文"}],
            next_attempt_at=NOW,
            status="sent",
        )
        session.add(delivery)
        session.flush()
        session.add(
            Notification(
                brand_id=brand,
                thread_id=old.thread_id,
                message_id=old.id,
                event_key="ret-old",
                kind="urgent",
                reason="complaint",
                due_at=NOW,
                delivery_id=delivery.id,
            )
        )
        live = post("youtube", "yt-live")
        post("youtube", "yt-gone-old", deleted_days=40)
        post("youtube", "yt-gone-new", deleted_days=5)
        comment("youtube", "yt-stale", live, 40, observed_days=35)
        comment("youtube", "yt-fresh", live, 40, observed_days=1)
        report = IdeationReport(
            brand_id=brand,
            meeting_at=NOW,
            start_at=NOW,
            end_at=NOW,
            trigger="manual",
            provider="agent",
            status="ready",
            data_json={
                "groups": [
                    {
                        "topic": "價格",
                        "quotes": [
                            {"id": ids["ig-old"], "text": "ig-old 原文", "post_id": ids["ig-post"]},
                            {"id": ids["ig-new"], "text": "ig-new 原文", "post_id": ids["ig-post"]},
                            {
                                "id": ids["yt-fresh"],
                                "text": "yt-fresh 原文",
                                "post_id": ids["yt-live"],
                            },
                        ],
                    }
                ],
                "posts": [
                    {"id": ids["ig-post"], "caption": "ig-post 說明"},
                    {"id": ids["yt-live"], "caption": "yt-live 說明"},
                ],
                "ideas": [
                    {
                        "title": "保留的主題",
                        "quote_ids": [ids["ig-old"], ids["ig-new"], ids["yt-fresh"]],
                    }
                ],
            },
        )
        session.add(report)
        session.flush()
        ids["report"] = report.id
        ids["accounts"] = {p: a.id for p, a in accounts.items()}
    return factory, ids


def test_preview_writes_nothing_and_prune_follows_retention_rules(client, world):
    factory, ids = world
    settings = client.app.state.settings
    assert settings.comment_retention_days == 365
    with factory() as session:
        before = {m: count(session, m) for m in (Message, Thread, Post, Contact)}
    preview = data_retention.preview(factory, settings, NOW)
    assert preview["messages"] >= 2 and preview["posts"] == 1
    with factory() as session:
        assert {m: count(session, m) for m in (Message, Thread, Post, Contact)} == before

    summary = data_retention.prune(factory, settings, NOW)
    assert summary["reports"] == 1
    with factory() as session:
        audit = session.scalar(select(AuditLog).where(AuditLog.action == "data.retention"))
        assert audit.detail_json == summary and "原文" not in str(audit.detail_json)
        gone = {ids["ig-old"], ids["yt-stale"]}
        kept = {ids["ig-new"], ids["yt-fresh"]}
        present = set(session.scalars(select(Message.id).where(Message.id.in_(gone | kept))))
        assert present == kept
        assert session.get(Thread, ids["ig-old:thread"]) is None
        assert session.get(Contact, ids["fan"]) is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(Classification)
                .where(Classification.message_id == ids["ig-old"])
            )
            == 0
        )
        assert (
            session.scalar(
                select(NotificationDelivery).where(NotificationDelivery.retry_key == "ret-delivery")
            )
            is None
        )
        # 已刪影片：超過 30 天的刪除（含快照與縮圖），未滿 30 天的保留。
        assert session.get(Post, ids["yt-gone-old"]) is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(PostThumbnail)
                .where(PostThumbnail.post_id == ids["yt-gone-old"])
            )
            == 0
        )
        assert session.get(Post, ids["yt-gone-new"]) is not None
        assert session.get(Post, ids["ig-post"]) is not None
        data = session.get(IdeationReport, ids["report"]).data_json
        assert [q["id"] for q in data["groups"][0]["quotes"]] == [ids["ig-new"], ids["yt-fresh"]]
        assert data["ideas"][0]["title"] == "保留的主題"
        assert data["ideas"][0]["quote_ids"] == [ids["ig-new"], ids["yt-fresh"]]
        assert "ig-old 原文" not in str(data)
    # 再跑一次沒有東西可刪。
    assert data_retention.preview(factory, settings, NOW)["messages"] == 0


def test_prune_commits_in_small_batches(client, world, monkeypatch):
    factory, ids = world
    settings = client.app.state.settings
    monkeypatch.setattr(data_retention, "BATCH", 1)
    expected = data_retention.preview(factory, settings, NOW)
    batches = []
    original = data_retention.expired

    def expired(session, settings, now=None, limit=None):
        batches.append(limit)
        return original(session, settings, now, limit)

    monkeypatch.setattr(data_retention, "expired", expired)
    summary = data_retention.prune(factory, settings, NOW)
    assert summary["messages"] == expected["messages"] and summary["posts"] == expected["posts"]
    # 每批只取一筆、各自提交，取滿一批就再跑下一批，直到沒有剩下。
    assert len(batches) >= 2 and set(batches) == {1}
    with factory() as session:
        present = set(
            session.scalars(
                select(Message.id).where(
                    Message.id.in_({ids["ig-old"], ids["yt-stale"], ids["ig-new"], ids["yt-fresh"]})
                )
            )
        )
        assert present == {ids["ig-new"], ids["yt-fresh"]}
        assert session.get(Thread, ids["ig-old:thread"]) is None
        assert session.get(Contact, ids["fan"]) is None
        assert session.get(Post, ids["yt-gone-old"]) is None
    assert data_retention.preview(factory, settings, NOW)["messages"] == 0


def test_youtube_disconnect_deletes_every_youtube_row_but_not_other_platforms(client, world):
    factory, ids = world
    with factory.begin() as session:
        accounts = [ids["accounts"]["youtube"]]
        result = data_retention.apply(session, data_retention.plan(session, account_ids=accounts))
    assert result["posts"] == 3 and result["reports"] == 1
    with factory() as session:
        youtube = ids["accounts"]["youtube"]
        assert (
            session.scalar(select(func.count()).select_from(Post).where(Post.account_id == youtube))
            == 0
        )
        assert (
            session.scalar(
                select(func.count()).select_from(Thread).where(Thread.account_id == youtube)
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(MetricSnapshot)
                .join(Post)
                .where(Post.account_id == youtube)
            )
            == 0
        )
        assert session.get(Message, ids["ig-old"]) is not None
        assert session.get(Post, ids["ig-post"]) is not None
        data = session.get(IdeationReport, ids["report"]).data_json
        assert [p["id"] for p in data["posts"]] == [ids["ig-post"]]
        assert "yt-fresh 原文" not in str(data) and "yt-live 說明" not in str(data)


def test_daily_job_stays_off_until_an_operator_enables_it(client):
    factory = client.app.state.session_factory
    assert data_retention.due(factory, NOW) is False
    data_retention.enable(factory, NOW)
    assert data_retention.due(factory, NOW) is True
    # 一天最多一次，重啟不會重跑。
    assert data_retention.due(factory, NOW + timedelta(hours=1)) is False
    assert data_retention.due(factory, NOW + timedelta(days=1, seconds=1)) is True


def test_commenter_deletion_request_removes_only_their_data(client, world):
    factory, ids = world
    with factory() as session:
        found = data_retention.find_contacts(session, "合成觀眾")
    assert [(c["id"], c["comments"]) for c in found] == [(ids["fan"], 1)]
    with factory.begin() as session:
        data_retention.apply(session, data_retention.for_contact(session, ids["fan"]))
    with factory() as session:
        assert session.get(Contact, ids["fan"]) is None
        assert session.get(Message, ids["ig-old"]) is None
        assert session.get(Message, ids["ig-new"]) is not None
        data = session.get(IdeationReport, ids["report"]).data_json
        assert "ig-old 原文" not in str(data)


def test_retention_counts_from_when_the_comment_was_obtained(client, world):
    factory, ids = world
    settings = client.app.state.settings
    with factory.begin() as session:
        # 兩年前發布、5 天前才補抓進來的留言：從取得日起算，還不到期。
        row = session.get(Message, ids["ig-new"])
        row.sent_at = NOW - timedelta(days=700)
    data_retention.prune(factory, settings, NOW)
    with factory() as session:
        assert session.get(Message, ids["ig-new"]) is not None
        assert session.get(Message, ids["ig-old"]) is None


def test_posts_api_tells_viewers_the_retention_rules(client, world):
    body = client.get("/api/posts/platforms").json()
    assert body["comment_retention_days"] == 365
    assert body["youtube_fresh_days"] == 30
    assert body["retention_enabled"] is False

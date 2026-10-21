"""Delete stored platform data the platform terms no longer allow us to keep.

Three triggers share one plan/apply pair:
- comment retention: every platform's comments stored longer than COMMENT_RETENTION_DAYS
  (counted from when the workbench obtained them);
- YouTube freshness: YouTube comments not re-observed and YouTube videos removed on YouTube
  for more than 30 days (YouTube API Services Developer Policies III.E.4);
- YouTube disconnect: everything fetched with that authorization (within 7 days of revocation).

Ideas written from the data stay; only the quoted comment and caption text is removed from
reports. Publishing history the user created stays as the user's own record.
"""

from datetime import timedelta

from sqlalchemy import delete, or_, select, update

from app.models import (
    Account,
    AudienceInsight,
    Classification,
    CommentBackfill,
    CommentPoll,
    Contact,
    Draft,
    FollowerSnapshot,
    IdeationReport,
    InboundJob,
    LineReplyCredential,
    Message,
    MetricSnapshot,
    Notification,
    NotificationDelivery,
    Post,
    PostThumbnail,
    RawEvent,
    SendAttempt,
    Thread,
    TopicAnnotation,
)
from app.models.base import utc_now
from app.services import settings_store

YOUTUBE_FRESH_DAYS = 30
KEY = "data.retention"
# 每批刪除的上限：比照 audit_retention 分批提交，第一次啟用時也不會長時間占住寫入鎖。
BATCH = 500
# 原文已清除的 Webhook 事件：保留平台 ID 當冪等紀錄，重送時不再重建留言。
REMOVED_EVENT = "retention_removed"
REMOVED_NOTE = "（已依資料保留規則刪除）"


def _ids(session, statement):
    return set(session.scalars(statement))


def plan(session, *, message_ids=(), post_ids=(), account_ids=()):
    """Expand the requested rows to every dependent row; nothing is written here."""
    post_ids = set(post_ids)
    message_ids = set(message_ids)
    account_ids = set(account_ids)
    if account_ids:
        post_ids |= _ids(session, select(Post.id).where(Post.account_id.in_(account_ids)))
    thread_filter = [Thread.post_id.in_(post_ids)] if post_ids else []
    if account_ids:
        thread_filter.append(Thread.account_id.in_(account_ids))
    whole_threads = (
        _ids(session, select(Thread.id).where(or_(*thread_filter))) if thread_filter else set()
    )
    if whole_threads:
        message_ids |= _ids(session, select(Message.id).where(Message.thread_id.in_(whole_threads)))
    touched = _ids(session, select(Message.thread_id).where(Message.id.in_(message_ids)))
    # A thread goes once none of its messages survive.
    survivors = _ids(
        session,
        select(Message.thread_id).where(
            Message.thread_id.in_(touched), Message.id.not_in(message_ids)
        ),
    )
    threads = whole_threads | (touched - survivors)
    notifications = _ids(
        session,
        select(Notification.id).where(
            or_(Notification.message_id.in_(message_ids), Notification.thread_id.in_(threads))
        ),
    )
    contacts = _ids(
        session,
        select(Message.contact_id).where(
            Message.id.in_(message_ids), Message.contact_id.is_not(None)
        ),
    ) | _ids(
        session,
        select(Thread.contact_id).where(Thread.id.in_(threads), Thread.contact_id.is_not(None)),
    )
    if contacts:
        kept = _ids(
            session,
            select(Message.contact_id).where(
                Message.contact_id.in_(contacts), Message.id.not_in(message_ids)
            ),
        ) | _ids(
            session,
            select(Thread.contact_id).where(
                Thread.contact_id.in_(contacts), Thread.id.not_in(threads)
            ),
        )
        contacts -= kept
    return {
        "messages": message_ids,
        "threads": threads,
        "posts": post_ids,
        "notifications": notifications,
        "contacts": contacts,
        "accounts": account_ids,
    }


def counts(result):
    return {key: len(value) for key, value in result.items()}


def _scrub_reports(session, message_ids, post_ids):
    changed = 0
    for row in session.scalars(select(IdeationReport)):
        data = row.data_json or {}
        groups = data.get("groups") or []
        removed = False
        new_groups = []
        for group in groups:
            quotes = group.get("quotes") or []
            kept = [
                q
                for q in quotes
                if q.get("id") not in message_ids and q.get("post_id") not in post_ids
            ]
            removed |= len(kept) != len(quotes)
            new_groups.append({**group, "quotes": kept} if len(kept) != len(quotes) else group)
        posts = data.get("posts") or []
        kept_posts = [p for p in posts if p.get("id") not in post_ids]
        removed |= len(kept_posts) != len(posts)
        if not removed:
            continue
        gone = message_ids
        ideas = [
            {**idea, "quote_ids": [i for i in idea.get("quote_ids", []) if i not in gone]}
            if isinstance(idea, dict) and "quote_ids" in idea
            else idea
            for idea in data.get("ideas", [])
        ]
        row.data_json = {
            **data,
            "groups": new_groups,
            "posts": kept_posts,
            "ideas": ideas,
            "quote_note": REMOVED_NOTE,
        }
        changed += 1
    return changed


def apply(session, result):
    """Delete planned rows children-first inside the caller's write transaction."""
    messages, threads, posts = result["messages"], result["threads"], result["posts"]
    notifications, contacts, accounts = (
        result["notifications"],
        result["contacts"],
        result["accounts"],
    )
    reports = _scrub_reports(session, messages, posts)
    if notifications:
        deliveries = _ids(
            session,
            select(Notification.delivery_id).where(
                Notification.id.in_(notifications), Notification.delivery_id.is_not(None)
            ),
        )
        session.execute(delete(Notification).where(Notification.id.in_(notifications)))
        if deliveries:
            # The delivery caches the original comment text; survivors only lose the link.
            session.execute(
                update(Notification)
                .where(Notification.delivery_id.in_(deliveries))
                .values(delivery_id=None)
            )
            session.execute(
                delete(NotificationDelivery).where(NotificationDelivery.id.in_(deliveries))
            )
    if messages:
        for model in (Classification, TopicAnnotation, InboundJob, LineReplyCredential):
            session.execute(delete(model).where(model.message_id.in_(messages)))
        session.execute(delete(Message).where(Message.id.in_(messages)))
    if result.get("detach"):
        session.execute(
            update(Thread).where(Thread.id.in_(result["detach"])).values(contact_id=None)
        )
    if threads:
        for model in (Draft, SendAttempt):
            session.execute(delete(model).where(model.thread_id.in_(threads)))
        session.execute(delete(Thread).where(Thread.id.in_(threads)))
    if contacts:
        session.execute(delete(Contact).where(Contact.id.in_(contacts)))
    if posts:
        for model in (MetricSnapshot, PostThumbnail, CommentPoll):
            session.execute(delete(model).where(model.post_id.in_(posts)))
        session.execute(delete(Post).where(Post.id.in_(posts)))
    if accounts:
        for model in (FollowerSnapshot, AudienceInsight, CommentPoll, CommentBackfill):
            session.execute(delete(model).where(model.account_id.in_(accounts)))
        platforms = set(session.scalars(select(Account.platform).where(Account.id.in_(accounts))))
        if platforms:
            # Webhook payloads hold the original text; YouTube has none, other platforms only
            # reach here through an explicit disconnect.
            externals = set(
                session.scalars(select(Account.external_id).where(Account.id.in_(accounts)))
            )
            session.execute(
                delete(RawEvent).where(
                    RawEvent.platform.in_(platforms), RawEvent.account_external_id.in_(externals)
                )
            )
    return {**counts(result), "reports": reports}


def retention_days(settings):
    return settings.comment_retention_days


def expired(session, settings, now=None, limit=None):
    """Rows due for deletion under the retention rules, as a plan (at most `limit` of each kind)."""
    now = now or utc_now()
    cutoff = now - timedelta(days=retention_days(settings))
    fresh = now - timedelta(days=YOUTUBE_FRESH_DAYS)

    def first(statement, column):
        return _ids(session, statement.order_by(column).limit(limit) if limit else statement)

    old_comments = first(
        select(Message.id)
        .join(Thread, Message.thread_id == Thread.id)
        # 從工作檯取得留言的時間起算（不是留言發布時間），舊貼文的留言補抓進來也有完整一年可用。
        .where(Thread.kind == "comment_thread", Message.created_at < cutoff),
        Message.id,
    )
    youtube = select(Account.id).where(Account.platform == "youtube")
    stale_youtube = first(
        select(Message.id)
        .join(Thread, Message.thread_id == Thread.id)
        .where(
            Thread.account_id.in_(youtube),
            Message.created_at < fresh,
            or_(Message.content_observed_at.is_(None), Message.content_observed_at < fresh),
        ),
        Message.id,
    )
    removed_videos = first(
        select(Post.id).where(
            Post.account_id.in_(youtube), Post.deleted_at.is_not(None), Post.deleted_at < fresh
        ),
        Post.id,
    )
    old_events = first(
        select(RawEvent.id).where(
            RawEvent.received_at < cutoff,
            or_(RawEvent.error.is_(None), RawEvent.error != REMOVED_EVENT),
        ),
        RawEvent.id,
    )
    result = plan(session, message_ids=old_comments | stale_youtube, post_ids=removed_videos)
    result["raw_events"] = old_events
    # 任一類剛好取滿一批，代表可能還有下一批。
    result["more"] = bool(limit) and limit in {
        len(old_comments),
        len(stale_youtube),
        len(removed_videos),
        len(old_events),
    }
    return result


def prune(factory, settings, now=None):
    """Delete in short batches, each in its own transaction, so writes are never blocked long."""
    now = now or utc_now()
    total = {}
    while True:
        with factory.begin() as session:
            result = expired(session, settings, now, BATCH)
            events, more = result.pop("raw_events"), result.pop("more")
            summary = apply(session, result)
            if events:
                # 只清原文、保留平台 ID 這組唯一鍵，同一事件重送時仍能辨識為已處理。
                session.execute(
                    update(RawEvent)
                    .where(RawEvent.id.in_(events))
                    .values(payload_json={}, processed=True, error=REMOVED_EVENT)
                )
            summary["raw_events"] = len(events)
            if any(summary.values()):
                # 稽核只記筆數，不記任何原文或平台識別碼；沒有刪除就不寫。
                from app.services.posts import _begin_ingest

                audit = _begin_ingest(session, "data.retention")
                audit.actor, audit.detail_json = "scheduler", summary
        total = {k: total.get(k, 0) + v for k, v in summary.items()}
        if not more:
            return total


def preview(factory, settings, now=None):
    with factory() as session:
        result = expired(session, settings, now)
        result.pop("more")
        return counts(result)


def find_contacts(session, name):
    """For a commenter's deletion request: matching contacts with how many comments they left."""
    rows = session.scalars(
        select(Contact).where(Contact.display_name.contains(name)).order_by(Contact.id)
    )
    return [
        {
            "id": row.id,
            "platform": row.platform,
            "display_name": row.display_name,
            "comments": len(_ids(session, select(Message.id).where(Message.contact_id == row.id))),
        }
        for row in rows
    ]


def for_contact(session, contact_id):
    """Everything a commenter left, so a deletion request removes all of it."""
    # Only their own messages go; other people's replies under their comment stay, and a
    # surviving thread just stops pointing at them.
    messages = _ids(session, select(Message.id).where(Message.contact_id == contact_id))
    result = plan(session, message_ids=messages)
    result["detach"] = _ids(
        session,
        select(Thread.id).where(
            Thread.contact_id == contact_id, Thread.id.not_in(result["threads"])
        ),
    )
    if session.get(Contact, contact_id):
        result["contacts"] = result["contacts"] | {contact_id}
    return result


def summary(session, settings):
    """What viewers are told: how long audience comments stay and whether deletion runs."""
    row = settings_store.get(session, KEY)
    return {
        "comment_retention_days": retention_days(settings),
        "youtube_fresh_days": YOUTUBE_FRESH_DAYS,
        "retention_enabled": bool(row and row.value_json.get("enabled")),
    }


def enable(factory, now=None):
    """Turn on the daily deletion after the operator reviewed the preview and took a backup."""
    now = now or utc_now()
    with factory.begin() as session:
        row = settings_store.get(session, KEY)
        value = {**(row.value_json if row else {}), "enabled": True, "enabled_at": now.isoformat()}
        settings_store.put(session, KEY, value, row)


def due(factory, now=None):
    """Run at most once a day, and never before an operator enabled it (deletes existing data)."""
    now = now or utc_now()
    with factory.begin() as session:
        row = settings_store.get(session, KEY)
        if not row or not row.value_json.get("enabled"):
            return False
        if row.value_json.get("next_at", 0) > now.timestamp():
            return False
        value = {**row.value_json, "next_at": (now + timedelta(days=1)).timestamp()}
        settings_store.put(session, KEY, value, row)
    return True

"""Selected public posts and durable comment-sync prerequisites for ideation."""
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import and_, case, func, select

from app.models import Account, CommentPoll, Contact, Message, Post, Thread
from app.models.base import utc_now
from app.services import comment_poll, meta_api
from app.services.date_ranges import comment_bounds
from app.services.redact import redact


def preview_comments(access, brand_id, post_id, period, date_from, date_to, offset):
    """Read persisted fan comments only; never enqueue or contact a platform."""
    access.require_brand(brand_id)
    post = access.session.scalar(select(Post).join(Account).where(
        Post.id == post_id, Account.brand_id == brand_id,
        Account.platform.in_(["facebook", "instagram", "threads", "youtube"]),
    ))
    if post is None:
        raise HTTPException(404, "找不到貼文")
    start, end = comment_bounds(period, date_from, date_to)
    rows = access.session.execute(
        select(Message, Contact.display_name).join(Thread, Message.thread_id == Thread.id)
        .outerjoin(Contact, and_(
            Contact.id == func.coalesce(Message.contact_id, Thread.contact_id),
            Contact.brand_id == brand_id,
        )).where(
            Thread.brand_id == brand_id, Thread.account_id == post.account_id,
            Thread.post_id == post.id, Thread.kind == "comment_thread",
            Message.direction == "in", Message.author_type == "fan",
            Message.sent_at >= start, Message.sent_at < end,
        ).order_by(Message.sent_at.desc(), Message.id.desc()).offset(offset).limit(21)
    ).all()
    items = []
    for message, name in rows[:20]:
        # Keep a recognizable initial without exposing a full name or account handle.
        safe_name = redact(name or "").text.strip()
        author = safe_name[:1] + "***" if safe_name and not safe_name.startswith("[") else "觀眾***"
        items.append(dict(id=message.id, sent_at=message.sent_at,
                          author=author, text=redact(message.text).text))
    return {"items": items, "next_offset": offset + 20 if len(rows) > 20 else None}


# 發想時附上留言所回應的貼文全文，模型才知道觀眾在回什麼；過長內文截斷以控制提示大小。
CAPTION_LIMIT = 3000


def quoted_posts(session, brand_id, groups):
    ids = sorted({q["post_id"] for g in groups for q in g.get("quotes", []) if q.get("post_id")})
    if not ids:
        return []
    rows = session.execute(select(Post, Account).join(Account).where(
        Post.id.in_(ids), Account.brand_id == brand_id,
    ).order_by(Post.published_at.desc(), Post.id.desc())).all()
    return [dict(id=p.id, platform=a.platform, published_at=p.published_at.isoformat(),
                 caption=redact(p.caption or "").text[:CAPTION_LIMIT]) for p, a in rows]


def listing_for_window(access, brand_id, start, end, period, date_from, date_to):
    return listing(access, brand_id, start, end, *comment_bounds(period, date_from, date_to))


def statement(brand_id, start, end):
    return select(Post, Account).join(Account, Post.account_id == Account.id).where(
        Account.brand_id == brand_id, Post.published_at >= start, Post.published_at < end,
        # Posts removed on the platform can no longer gain comments and must not be offered.
        Post.deleted_at.is_(None),
    ).order_by(Post.published_at.desc(), Post.id.desc())


def validate_period(start, end, now=None):
    if not start < end <= (now or utc_now()) + timedelta(seconds=5):
        raise HTTPException(422, "結束時間須晚於開始時間且不得晚於現在")


def listing(access, brand_id, start, end, comment_start=None, comment_end=None):
    access.require_brand(brand_id)
    if start >= end:
        raise HTTPException(422, "開始時間須早於結束時間")
    counts = {post_id: (total, ranged) for post_id, total, ranged in access.session.execute(
        select(Thread.post_id, func.count(Message.id), func.sum(case((
            (Message.sent_at >= (comment_start or start))
            & (Message.sent_at < (comment_end or end)), 1), else_=0))).join(Message).where(
            Thread.brand_id == brand_id, Thread.kind == "comment_thread",
            Message.direction == "in", Message.author_type == "fan",
        ).group_by(Thread.post_id)
    ).all()}
    return [dict(id=p.id, platform=a.platform, published_at=p.published_at,
                 caption=p.caption, comment_count=counts.get(p.id, (0, 0))[1],
                 total_comment_count=counts.get(p.id, (0, 0))[0])
            for p, a in access.session.execute(statement(brand_id, start, end))]


def enqueue(session, settings, posts, actor, comment_start=None, comment_end=None):
    requirements = {}
    now = utc_now()
    for post, account in posts:
        if account.platform not in {"facebook", "instagram", "threads", "youtube"}:
            raise HTTPException(422, "僅能同步實際 FB／IG／Threads／YouTube 貼文")
        state = session.scalar(select(CommentPoll).where(CommentPoll.post_id == post.id))
        if (state and not state.manual_requested
                and (state.window_start is None or (
                    comment_start is not None and state.window_start <= comment_start))
                and state.window_end and state.last_completed_at
                and state.window_end >= min(comment_end or now, now - timedelta(minutes=10))
                and not state.last_error and not state.stopped_at
                and state.last_completed_at >= state.window_end
                and state.last_completed_at >= now - timedelta(minutes=10)):
            continue
        comment_poll.enqueue(session, account, post.id, actor, settings,
                             window_start=comment_start, window_end=comment_end)
        session.flush()
        state = session.scalar(select(CommentPoll).where(CommentPoll.post_id == post.id))
        requirements[str(post.id)] = state.requested_at.isoformat()
    return requirements


def sync_state(session, requirements):
    """Do not hold a worker while rate limits defer comments to a later tick."""
    waiting = False
    for post_id, requested in requirements.items():
        state = session.scalar(select(CommentPoll).where(CommentPoll.post_id == int(post_id)))
        if (state and state.last_completed_at
                and state.last_completed_at >= datetime.fromisoformat(requested)):
            continue
        if (not state or state.stopped_at
                or (state.last_error and state.last_error not in meta_api.RETRYABLE_ERRORS)):
            return "failed"
        waiting = True
    return "waiting" if waiting else "ready"

"""One durable historical window per account; cursors remain in comment_polls."""

from fastapi import HTTPException
from sqlalchemy import func, select

from app.models import Account, CommentBackfill, CommentPoll, Message, Thread
from app.models.base import utc_now
from app.services import meta_api, roles


def start(access, brand_id=None, platform=None, *, settings):
    if not roles.can(access, "posts.sync"):
        raise HTTPException(403, "此帳號僅能檢視資料")
    if brand_id is not None:
        access.require_brand(brand_id, write=True)
    raise HTTPException(410, "請在指定貼文按抓取留言")


def status(access, brand_id=None, platform=None, settings=None):
    if brand_id is not None:
        access.require_brand(brand_id)
    query = access.statement(Account, brand_id).where(
        Account.platform.in_(["facebook", "instagram"]),
    )
    if platform:
        query = query.where(Account.platform == platform)
    session, now = access.session, utc_now()
    until = meta_api.cooldown(session, now)
    result = []
    for account in session.scalars(query):
        backfill = session.scalar(
            select(CommentBackfill).where(CommentBackfill.account_id == account.id)
        )
        item = {
            "account_id": account.id,
            "account_name": account.name,
            "platform": account.platform,
            "state": "not_started",
            "completed_posts": 0,
            "total_posts": 0,
            "synced_comments": 0,
            "new_comments": 0,
            "discovery_completed": False,
            "window_start": None,
            "window_end": None,
            "retry_at": None,
            "wait_reason": None,
            "usage_percent": None,
            "calls_per_hour": settings.meta_api_calls_per_hour if settings else None,
        }
        if backfill:
            states = list(
                session.scalars(select(CommentPoll).where(CommentPoll.backfill_id == backfill.id))
            )
            # Existing historical queues can contain old posts; they no longer count as pending.
            eligible = states
            posts = [s for s in eligible if s.post_id]
            pending = [s for s in eligible if not s.backfill_completed_at]
            done = bool(backfill.discovery_completed_at) and not pending
            running = any(s.lease_until and s.lease_until > now for s in pending)
            error = any(meta_api.actionable_error(s.last_error) for s in pending)
            retryable = next(
                (s for s in pending if s.last_error in meta_api.RETRYABLE_ERRORS), None
            )
            count_query = (
                select(func.count(Message.id))
                .join(Thread)
                .where(
                    Thread.post_id.in_([s.post_id for s in posts]),
                    Thread.account_id == account.id,
                    Thread.kind == "comment_thread",
                )
            )
            item.update(
                state="completed"
                if done
                else "error"
                if error
                else "throttled"
                if until
                else "running"
                if running
                else "waiting"
                if retryable
                else "pending",
                completed_posts=sum(bool(s.backfill_completed_at) for s in posts),
                total_posts=len(posts),
                synced_comments=session.scalar(count_query),
                new_comments=session.scalar(
                    count_query.where(Message.created_at >= backfill.window_end)
                ),
                discovery_completed=bool(backfill.discovery_completed_at),
                window_start=backfill.window_start,
                window_end=backfill.window_end,
                retry_at=None
                if done
                else until or min((s.next_poll_at for s in pending), default=now),
            )
            if item["state"] in {"waiting", "throttled"}:
                # Discovery and post pages have independent retry schedules.
                due = min((s.next_poll_at for s in pending), default=now)
                item.update(
                    meta_api.wait_details(
                        session, now, retryable.last_error if retryable else None, due, settings
                    )
                )
            elif item["state"] == "error":
                item["retry_at"] = None
        result.append(item)
    return {"accounts": result}

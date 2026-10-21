import logging
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from app.models import Account, CommentPoll, Message, Post, Thread
from app.models.base import utc_now
from app.services import meta_api
from app.services.catalog import get_record
from app.services.date_ranges import date_bounds
from app.services.posts import _begin_ingest, require_account

logger = logging.getLogger("mwb.meta")


def ensure_states(session, account, now, settings):
    # State rows are inert until an explicit request; never discover posts here.
    for post in session.scalars(select(Post).where(Post.account_id == account.id)):
        session.execute(
            insert(CommentPoll)
            .values(
                account_id=account.id,
                post_id=post.id,
                resource=post.external_id,
                next_poll_at=now,
                progress_json={},
            )
            .on_conflict_do_nothing()
        )


def claim(session, body, settings):
    with session.begin():
        _begin_ingest(session, "comments.claim")
        now = utc_now()
        account = require_account(session, body.platform, body.account_external_id)
        query = select(CommentPoll).where(
            CommentPoll.account_id == account.id,
            CommentPoll.post_id.is_not(None),
            CommentPoll.manual_requested.is_(True),
            CommentPoll.requested_at.is_not(None),
            CommentPoll.window_end.is_not(None),
        )
        if body.post_id:
            query = query.where(CommentPoll.post_id == body.post_id)
        # Threads 不經 Meta 呼叫配額，Meta 冷卻中仍可讀 Threads 回覆。
        until = (None if account.platform in {"threads", "youtube"}
                 else meta_api.cooldown(session, now))
        if until:
            return {"work": None, "retry_at": until.isoformat()}
        for state in session.scalars(
            query.order_by(CommentPoll.next_poll_at, CommentPoll.requested_at, CommentPoll.id)
        ):
            if state.lease_until and state.lease_until > now or state.next_poll_at > now:
                continue
            state.run_id = str(uuid4())
            state.lease_until = now + timedelta(minutes=2)
            known = list(
                session.scalars(
                    select(Message.external_id)
                    .join(Thread)
                    .where(
                        Thread.account_id == account.id,
                        Thread.post_id == state.post_id,
                        Thread.kind == "comment_thread",
                    )
                )
            )
            return {
                "work": {
                    "run_id": state.run_id,
                    "post_id": state.post_id,
                    "resource_id": state.resource,
                    "kind": "comments",
                    "progress": state.progress_json,
                    "platform": account.platform,
                    "window_start": state.window_start,
                    "window_end": state.window_end,
                    "known_comment_ids": known,
                    "incremental": not state.progress_json.get("full_rescan", False),
                }
            }
        return {"work": None}


def saved_progress(state, progress):
    return progress.model_dump()


def checkpoint(session, body):
    with session.begin():
        _begin_ingest(session, "comments.checkpoint")
        now = utc_now()
        state = meta_api.require_run(session, body.run_id, now)
        state.progress_json = saved_progress(state, body.progress)
        state.lease_until = now + timedelta(minutes=2)
    return {"saved": True}


def finish(session, body, settings):
    with session.begin():
        _begin_ingest(session, "comments.finish")
        now = utc_now()
        state = meta_api.require_run(session, body.run_id, now)
        if body.success and (not body.progress.comments_done or body.progress.replies):
            raise HTTPException(422, "分頁尚未完成")
        state.run_id = state.lease_until = None
        state.progress_json = saved_progress(state, body.progress)
        if body.success:
            state.last_completed_at = now
            state.manual_requested = False
            state.requested_at = None
            state.last_error = None
        else:
            state.last_error = body.error or "backend_failed"
            if body.error in meta_api.RETRYABLE_ERRORS:
                delay = 0 if body.error == "work_budget" else 300
                account = session.get(Account, state.account_id)
                cooling = None
                if account.platform not in {"threads", "youtube"}:
                    cooling = meta_api.cooldown(session, now)
                state.next_poll_at = max(now + timedelta(seconds=delay), cooling or now)
            else:
                # An actionable failure ends this read; the user may explicitly retry.
                state.manual_requested = False
                state.requested_at = None
    return {"saved": True}


def accessible_post(access, post_id):
    post = get_record(access, Post, post_id)
    account = access.session.get(Account, post.account_id)
    if account.platform not in {"instagram", "facebook", "threads", "youtube"}:
        raise HTTPException(422, "僅能同步實際 FB／IG／Threads／YouTube 貼文")
    return post, account


def request_sync(
    access,
    post_id=None,
    brand_id=None,
    platform=None,
    *,
    settings,
    period="30",
    date_from=None,
    date_to=None,
    full_rescan=False,
):
    session = access.session
    if access.staff.role not in {"admin", "marketing"}:
        raise HTTPException(403, "此帳號僅能檢視資料")
    if not post_id:
        raise HTTPException(410, "請在指定貼文按抓取留言")
    if full_rescan and period != "all":
        raise HTTPException(422, "完整重抓須先選擇全部留言")
    post, account = accessible_post(access, post_id)
    access.require_brand(account.brand_id, write=True)
    actor, account_id = f"staff:{access.staff.id}", account.id
    window_start, window_end = date_bounds(period, date_from, date_to, now=utc_now())
    session.commit()
    with session.begin():
        account = session.get(Account, account_id)
        queued = enqueue(
            session,
            account,
            post_id,
            actor,
            settings,
            window_start=window_start,
            window_end=window_end,
            full_rescan=full_rescan,
        )
    return {"queued": queued}


def enqueue(
    session,
    account,
    post_id,
    actor,
    settings,
    *,
    window_start=None,
    window_end=None,
    full_rescan=False,
):
    """Share the durable queue with ideation inside its report transaction."""
    audit = _begin_ingest(session, "comments.request")
    audit.actor = actor
    now = utc_now()
    ensure_states(session, account, now, settings)
    state = session.scalar(select(CommentPoll).where(CommentPoll.post_id == post_id))
    end = min(window_end or now, now)
    # Broaden an active run rather than dropping another report's required window.
    covers_start = state.window_start is None or (
        window_start is not None and state.window_start <= window_start
    )
    covers_end = state.window_end is not None and state.window_end >= min(
        end, now - timedelta(minutes=10)
    )
    queued = int(full_rescan or not state.manual_requested or not (covers_start and covers_end))
    if queued:
        read_all = (
            full_rescan
            or state.last_completed_at is None
            or (state.manual_requested and state.progress_json.get("full_rescan", False))
        )
        if state.manual_requested:
            window_start = (
                min(state.window_start, window_start)
                if state.window_start is not None and window_start is not None
                else None
            )
            end = max(state.window_end or end, end)
        state.requested_at = state.next_poll_at = now
        state.window_start, state.window_end = window_start, end
        state.manual_requested = True
        state.run_id = state.lease_until = state.stopped_at = None
        state.progress_json = {"full_rescan": read_all}
        state.last_error = None
    audit.detail_json = {"post_id": post_id, "queued": queued, "full_rescan": full_rescan}
    return queued


def stop(access, post_id):
    post, account = accessible_post(access, post_id)
    access.require_brand(account.brand_id, write=True)
    actor = f"staff:{access.staff.id}"
    session = access.session
    session.commit()
    with session.begin():
        audit = _begin_ingest(session, "comments.stop")
        audit.actor = actor
        state = session.scalar(select(CommentPoll).where(CommentPoll.post_id == post_id))
        stopped = bool(state and state.manual_requested)
        if stopped:
            # Revoke the lease before any further API permit or event can be accepted.
            state.manual_requested = False
            state.requested_at = state.run_id = state.lease_until = None
            state.stopped_at = utc_now()
            state.last_error = None
        audit.detail_json = {"post_id": post_id, "stopped": stopped}
    return {"stopped": stopped}


def status(access, post_id, settings):
    post, account = accessible_post(access, post_id)
    now = utc_now()
    state = access.session.scalar(select(CommentPoll).where(CommentPoll.post_id == post_id))
    threads = account.platform in {"threads", "youtube"}
    until = None if threads else meta_api.cooldown(access.session, now)
    running = state and state.lease_until and state.lease_until > now
    pending = state and state.manual_requested
    active = running or pending
    retryable = state and state.last_error in meta_api.RETRYABLE_ERRORS
    last_error = state.last_error if state else None
    retry_at = state.next_poll_at if state and active else None
    wait = (
        threads_wait(last_error, retry_at)
        if threads
        else meta_api.wait_details(access.session, now, last_error, retry_at, settings)
    )
    if account.platform == "youtube":
        reason = (wait["wait_reason"] or "").replace("threads_", "youtube_") or None
        wait = {**wait, "wait_reason": reason}
    return {
        "state": "throttled"
        if until and active
        else "running"
        if running
        else "error"
        if state and meta_api.actionable_error(state.last_error)
        else "waiting"
        if retryable and active
        else "pending"
        if pending
        else "stopped"
        if state and state.stopped_at
        else "idle",
        "last_completed_at": state.last_completed_at if state else None,
        "last_auto_completed_at": state.last_auto_completed_at if state else None,
        "auto_sync_enabled": False,
        "window_days": None,
        "manual_requested": state.manual_requested if state else False,
        "stopped_at": state.stopped_at if state else None,
        "progress": {
            "comments_done": state.progress_json.get("comments_done", False) if state else False,
            "pending_replies": len(state.progress_json.get("replies", [])) if state else 0,
            "pages": state.progress_json.get("pages", 0) if state else 0,
            "saved_comments": state.progress_json.get("saved_comments", 0) if state else 0,
        },
        "next_poll_at": until or (state.next_poll_at if state else now),
        "last_error": state.last_error if state else None,
        "interval_minutes": None,
        "webhook_live": account.platform == "facebook"
        or (account.platform == "instagram" and settings.meta_ig_comments_webhook_live),
        **wait,
    }


def threads_wait(error, retry_at):
    """Threads 沒有 Meta 用量與每小時預算，只依這次的錯誤決定等待原因。"""
    reason = (
        "work_budget"
        if error == "work_budget"
        else "threads_usage"
        if error == "meta_rate_limited"
        else "threads_unstable"
        if error in meta_api.RETRYABLE_ERRORS
        else None
    )
    return {
        "wait_reason": reason,
        "retry_at": retry_at,
        "usage_percent": None,
        "calls_per_hour": None,
    }


def wake(settings, post_id=None):
    from app.services.scheduler import scheduler_for

    scheduler = scheduler_for(settings)
    if settings.comments_wake_enabled and scheduler:
        scheduler.request("comments")

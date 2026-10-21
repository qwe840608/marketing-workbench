import logging
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select

from app.models import CommentPoll, MetaApiCall, Setting
from app.models.base import utc_now
from app.services import settings_store
from app.services.posts import _begin_ingest, require_account

logger = logging.getLogger("mwb.meta")
BUDGET_KEY = "meta.api.budget"
RETRYABLE_ERRORS = frozenset(
    {"meta_rate_limited", "work_budget", "meta_timeout", "meta_server_error", "network_error"}
)


def actionable_error(error):
    return bool(error and error not in RETRYABLE_ERRORS)


def wait_details(session, now, error=None, retry_at=None, settings=None):
    state = budget(session)
    until = cooldown(session, now)
    reason = None
    if until or error == "meta_rate_limited":
        reason = state.get("reason", "meta_usage")
    elif error == "work_budget":
        reason = "work_budget"
    elif error in RETRYABLE_ERRORS:
        reason = "meta_unstable"
    return {
        "wait_reason": reason,
        "retry_at": max(until or now, retry_at or now) if reason else retry_at,
        "usage_percent": state.get("usage_percent"),
        "calls_per_hour": settings.meta_api_calls_per_hour
        if settings
        else state.get("calls_per_hour"),
    }


def budget(session):
    row = settings_store.get(session, BUDGET_KEY)
    return row.value_json if row else {}


def date_value(value):
    return datetime.fromisoformat(value) if value else None


def cooldown(session, now):
    until = date_value(budget(session).get("blocked_until"))
    return until if until and until > now else None


def multiplier(session, now):
    state = budget(session)
    until = date_value(state.get("slow_until"))
    return state.get("multiplier", 1) if until and until > now else 1


def block(
    session, now, seconds, percent=None, factor=2, *, reason="meta_usage", calls_per_hour=None
):
    row = settings_store.get(session, BUDGET_KEY)
    if row is None:
        row = Setting(key=BUDGET_KEY, value_json={})
        session.add(row)
    until = now + timedelta(seconds=seconds)
    old = date_value(row.value_json.get("blocked_until"))
    # A shorter overlapping backoff must not mislabel the longer active pause.
    if old and old > until and reason != "meta_auth":
        reason = row.value_json.get("reason", "meta_usage")
    until = max(until, old) if old else until
    row.value_json = {
        **row.value_json,
        "blocked_until": until.isoformat(),
        "slow_until": (until + timedelta(hours=1)).isoformat(),
        "multiplier": max(factor, multiplier(session, now)),
        "usage_percent": percent if percent is not None else row.value_json.get("usage_percent"),
        "reason": reason,
        **({"calls_per_hour": calls_per_hour} if calls_per_hour is not None else {}),
    }
    logger.warning(
        "meta_rate_backoff",
        extra={
            "reason": reason,
            "usage_percent": row.value_json["usage_percent"],
            "retry_at": until.isoformat(),
        },
    )
    return until


def require_run(session, run_id, now):
    state = session.scalar(select(CommentPoll).where(CommentPoll.run_id == run_id))
    if state and not state.manual_requested:
        raise HTTPException(409, "留言抓取已停止")
    if state is None or not state.lease_until or state.lease_until <= now:
        raise HTTPException(409, "留言同步工作已逾期")
    return state


def start_call(session, body, settings):
    if body.source == "history" or body.operation in {"messages", "conversations"}:
        raise HTTPException(410, "私訊同步已移除")
    with session.begin():
        _begin_ingest(session, "meta.call.start")
        now = utc_now()
        account = require_account(session, body.platform, body.account_external_id)
        if body.run_id:
            state = require_run(session, body.run_id, now)
            if body.source != "poll":
                raise HTTPException(422, "同步來源不符")
            if state.account_id != account.id:
                raise HTTPException(422, "同步帳號不符")
            if isinstance(state, CommentPoll) and not state.manual_requested:
                raise HTTPException(409, "留言抓取已停止")
            state.lease_until = now + timedelta(minutes=2)
        until = cooldown(session, now)
        if not until:
            cutoff = now - timedelta(hours=1)
            count, oldest = session.execute(
                select(func.count(), func.min(MetaApiCall.created_at)).where(
                    MetaApiCall.created_at > cutoff
                )
            ).one()
            if count >= settings.meta_api_calls_per_hour:
                until = block(
                    session,
                    now,
                    max(60, (oldest + timedelta(hours=1) - now).total_seconds()),
                    reason="system_budget",
                    calls_per_hour=settings.meta_api_calls_per_hour,
                )
        if until:
            return {"allowed": False, "retry_at": until.isoformat()}
        call = MetaApiCall(
            created_at=now,
            account_id=account.id,
            source=body.source,
            operation=body.operation,
            resource_id=body.resource_id,
            run_id=body.run_id,
        )
        session.add(call)
        session.flush()
        return {"allowed": True, "call_id": call.id, "observed_at": now.isoformat()}


def finish_call(session, body):
    with session.begin():
        _begin_ingest(session, "meta.call.finish")
        call = session.get(MetaApiCall, body.call_id)
        if call is None:
            raise HTTPException(404, "找不到 API 呼叫")
        now = utc_now()
        if call.completed_at is None:
            call.completed_at = now
            call.http_status, call.error_code = body.http_status, body.error_code
            call.duration_ms = body.duration_ms
            call.usage_json = {
                "app": body.app_usage.model_dump() if body.app_usage else None,
                "business": [value.model_dump() for value in body.business_usage],
                "retry_after_seconds": body.retry_after_seconds,
            }
            if body.error_subcode is not None:
                call.usage_json = {**call.usage_json, "error_subcode": body.error_subcode}
            values = ([body.app_usage] if body.app_usage else []) + body.business_usage
            percent = max(
                (max(v.call_count, v.total_time, v.total_cputime) for v in values), default=0
            )
            regain = max((v.estimated_time_to_regain_access * 60 for v in values), default=0)
            # Preserve the last reported Meta usage when a response omits usage headers.
            if values:
                row = settings_store.get(session, BUDGET_KEY)
                if row is None:
                    row = Setting(key=BUDGET_KEY, value_json={})
                    session.add(row)
                row.value_json = {**row.value_json, "usage_percent": percent}
            limited = body.http_status == 429 or body.error_code in {4, 17, 32, 613, 80004}
            reason = None
            if body.error_code == 190:
                reason = "meta_auth"
                block(
                    session,
                    now,
                    max(60, body.retry_after_seconds),
                    percent if values else None,
                    reason=reason,
                )
            elif percent >= 80 or limited:
                reason = "meta_usage"
                delay = 3600 if limited or percent >= 100 else 1800 if percent >= 90 else 600
                block(
                    session,
                    now,
                    max(delay, regain, body.retry_after_seconds),
                    percent if values else None,
                    4 if percent >= 90 or limited else 2,
                    reason=reason,
                )
            elif (
                (body.error_code == -2 and body.error_subcode == 2534084)
                or body.http_status == 0
                or 500 <= body.http_status <= 599
            ):
                reason = "meta_unstable"
                block(
                    session,
                    now,
                    max(60, body.retry_after_seconds),
                    percent if values else None,
                    reason=reason,
                )
            logger.info(
                "meta_api_call",
                extra={
                    "call_id": call.id,
                    "status": call.http_status,
                    "operation": call.operation,
                    "duration_ms": call.duration_ms,
                    "usage_percent": percent,
                    "reason": reason,
                },
            )
        until = cooldown(session, now)
        return {"recorded": True, "retry_at": until.isoformat() if until else None}

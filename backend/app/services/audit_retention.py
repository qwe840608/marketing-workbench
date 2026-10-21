"""Keep routine background/MCP reads for 30 days; other human actions are retained."""

from datetime import timedelta

from sqlalchemy import delete, or_, select

from app.models import AuditLog
from app.models.base import utc_now
from app.services import settings_store

RETENTION_DAYS = 30
BATCH = 2000
KEY = "audit.retention"
# 排程與 MCP 查詢的例行紀錄；送出、草稿、設定、登入、資料匯入等紀錄不在此列。
ROUTINE_ACTIONS = (
    "agent.tool.read",
    "scheduler.run",
    "dm.backfill.claim",
    "dm.backfill.checkpoint",
    "meta.call.start",
    "meta.call.finish",
    "notification.plan",
    "notification.claim",
    "notification.dispatch",
    "notification.dispatch.release",
    "comments.claim",
    "comments.checkpoint",
    "classification.claim",
    "receive_health.claim",
    "receive_health.result",
    "assignment.initialization.check",
    "notification.group_migration.check",
    "auto_draft.claim",
    "notification.draft.claim",
)


def prune(factory, now=None):
    """Delete expired routine rows in short batches so the write lock is never held long."""
    now = now or utc_now()
    cutoff = now - timedelta(days=RETENTION_DAYS)
    removed = 0
    while True:
        with factory.begin() as session:
            ids = list(
                session.scalars(
                    select(AuditLog.id)
                    .where(
                        AuditLog.action.in_(ROUTINE_ACTIONS),
                        AuditLog.at < cutoff,
                        or_(AuditLog.actor.not_like("staff:%"),
                            AuditLog.action == "agent.tool.read"),
                    )
                    .limit(BATCH)
                )
            )
            if ids:
                session.execute(delete(AuditLog).where(AuditLog.id.in_(ids)))
        removed += len(ids)
        if len(ids) < BATCH:
            return removed


def due(factory, now=None):
    """Run at most once a day; the schedule lives in settings so restarts do not repeat it."""
    now = now or utc_now()
    with factory.begin() as session:
        row = settings_store.get(session, KEY)
        if row and row.value_json.get("next_at", 0) > now.timestamp():
            return False
        value = {"next_at": (now + timedelta(days=1)).timestamp()}
        settings_store.put(session, KEY, value, row)
    return True

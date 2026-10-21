"""Taipei calendar rules and versioned brand configuration."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select

from app.models import AuditLog
from app.schemas.ideation import MeetingConfig
from app.services import settings_store
from app.services.posts import _begin_ingest

TAIPEI = ZoneInfo("Asia/Taipei")


def config(session, brand_id):
    row = settings_store.get(session, f"ideation.brand.{brand_id}")
    if row:
        return MeetingConfig(**row.value_json, version=row.version)
    return MeetingConfig(topics=["其他"])


def next_meeting(value, now):
    if now.tzinfo is None:
        raise ValueError("時間必須包含時區")
    if value.weekday is None or value.time is None:
        return now
    local = now.astimezone(TAIPEI)
    day = max(local.date(), value.anchor_date) if value.interval_weeks == 2 else local.date()
    for offset in range(370):
        candidate = day + timedelta(days=offset)
        if candidate.weekday() != value.weekday:
            continue
        if value.interval_weeks == 2:
            anchor = value.anchor_date
            first = anchor + timedelta(days=(value.weekday - anchor.weekday()) % 7)
            if candidate < first or (candidate - first).days % 14:
                continue
        meeting = datetime.combine(candidate, time.fromisoformat(value.time), TAIPEI)
        if meeting >= local:
            return meeting.astimezone(UTC)
    raise ValueError("起算日超出可排程範圍")


def due_at(meeting):
    day = meeting.astimezone(TAIPEI).date() - timedelta(days=1)
    return datetime.combine(day, time(18), TAIPEI).astimezone(UTC)


def view(access, brand_id):
    access.require_brand(brand_id)
    rows = access.session.scalars(
        select(AuditLog)
        .where(AuditLog.brand_id == brand_id, AuditLog.action == "ideation.config")
        .order_by(AuditLog.id.desc())
        .limit(30)
    )
    return {
        "config": config(access.session, brand_id).model_dump(mode="json"),
        "history": [{"at": r.at, "actor": r.actor, **r.detail_json} for r in rows],
    }


def save(access, brand_id, body):
    access.require_brand(brand_id, write=True)
    session, actor = access.session, f"staff:{access.staff.id}"
    session.commit()
    with session.begin():
        audit = _begin_ingest(session, "ideation.config")
        before = config(session, brand_id)
        if before.version != body.version:
            raise HTTPException(409, "設定已更新，請重新載入")
        row = settings_store.get(session, f"ideation.brand.{brand_id}")
        data = body.model_dump(mode="json", exclude={"version"})
        settings_store.put(session, f"ideation.brand.{brand_id}", data, row)
        audit.actor, audit.brand_id, audit.target_type = actor, brand_id, "ideation_config"
        audit.detail_json = {"before": before.model_dump(mode="json"), "after": data}
    return view(access, brand_id)

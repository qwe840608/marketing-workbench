from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import and_, event, func, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, selectinload

from app.models import Account, AuditLog, Contact, Message, MetricSnapshot, Post, Setting, Thread
from app.models.base import utc_now
from app.schemas.posts import MetricsInput, PostsInput
from app.services import settings_store
from app.services.access import BrandAccess
from app.services.date_ranges import filter_dates


def schedule_tier(published_at: datetime, now: datetime) -> str:
    age = now - published_at
    return (
        "hourly" if age < timedelta(hours=48) else "daily" if age < timedelta(days=14) else "weekly"
    )


def effective_tier(session: Session, account: Account, post: Post, now: datetime) -> str:
    keys = [f"schedule.post.{post.id}", f"schedule.brand.{account.brand_id}"]
    rows = {
        row.key: row.value_json
        for row in session.scalars(select(Setting).where(Setting.key.in_(keys)))
    }
    for key in keys:
        value = rows.get(key)
        if not isinstance(value, dict) or value.get("tier") not in {"hourly", "daily", "weekly"}:
            continue
        if value.get("expires_at"):
            try:
                if datetime.fromisoformat(value["expires_at"]) <= now:
                    continue
            except (TypeError, ValueError):
                continue
        return value["tier"]
    return schedule_tier(post.published_at, now)


def set_schedule_override(session: Session, post_id: int, tier: str, hours: int) -> None:
    if tier not in {"hourly", "daily", "weekly"} or not 1 <= hours <= 168:
        raise ValueError("覆寫頻率或時效不符")
    row = session.execute(
        select(Post, Account)
        .join(Account)
        .where(
            Post.id == post_id,
            Account.platform.in_(["facebook", "instagram", "threads", "youtube", "tiktok"]),
        )
    ).first()
    if row is None:
        raise ValueError("找不到 Meta／Threads 貼文")
    post, account = row
    key = f"schedule.post.{post.id}"
    setting = settings_store.get(session, key)
    if setting is None:
        setting = Setting(key=key, value_json={})
        session.add(setting)
    before = setting.value_json
    setting.value_json = {
        "tier": tier,
        "expires_at": (utc_now() + timedelta(hours=hours)).isoformat(),
    }
    post.schedule_tier = tier
    session.add(
        AuditLog(
            brand_id=account.brand_id,
            actor="local:setup",
            action="post.schedule",
            target_type="post",
            target_id=post.id,
            detail_json={"before": before, "after": setting.value_json},
        )
    )


def require_account(session: Session, platform: str, external_id: str) -> Account:
    rows = list(
        session.scalars(
            select(Account)
            .where(Account.platform == platform, Account.external_id == external_id)
            .limit(2)
        )
    )
    if len(rows) != 1:
        raise HTTPException(422, "平台帳號未登記或重複")
    return rows[0]


def _begin_ingest(session: Session, action: str) -> AuditLog:
    # Python 3.13 已開啟交易；以第一筆稽核寫入取得寫鎖，不再巢狀 BEGIN。
    audit = AuditLog(actor="system:n8n", action=action, target_type="account", detail_json={})
    session.add(audit)
    session.flush()
    from app.services.audit_retention import ROUTINE_ACTIONS

    if action in ROUTINE_ACTIONS:
        changes = session.connection().connection.dbapi_connection.total_changes
        session.info["routine_audit"] = (audit, changes)
    return audit


@event.listens_for(Session, "before_commit")
def _drop_idle_routine_audit(session: Session) -> None:
    # 例行排程這一輪若沒有寫入任何其他資料（空跑），就不留稽核紀錄。
    routine = session.info.pop("routine_audit", None)
    if routine is None:
        return
    audit, changes = routine
    others = [o for o in (*session.new, *session.dirty, *session.deleted) if o is not audit]
    current = session.connection().connection.dbapi_connection.total_changes
    if not others and current == changes and audit in session:
        session.delete(audit)
        session.flush()


@event.listens_for(Session, "after_rollback")
def _forget_routine_audit(session: Session) -> None:
    session.info.pop("routine_audit", None)


def upsert_posts(session: Session, body: PostsInput) -> dict:
    with session.begin():
        audit = _begin_ingest(session, "ingest.posts")
        account = require_account(session, body.platform, body.account_external_id)
        linked = 0
        for source in body.posts:
            post = session.scalar(
                select(Post).where(
                    Post.account_id == account.id, Post.external_id == source.external_id
                )
            )

            values = source.model_dump()
            if post is None:
                values["schedule_tier"] = schedule_tier(source.published_at, utc_now())
                post = Post(account_id=account.id, **values)
                session.add(post)
                session.flush()
            else:
                for key, value in values.items():
                    setattr(post, key, value)
            post.schedule_tier = effective_tier(session, account, post, utc_now())
            pending = session.scalars(
                select(Thread).where(
                    Thread.account_id == account.id,
                    Thread.post_id.is_(None),
                    Thread.source_ref_json["post_external_id"].as_string() == source.external_id,
                )
            )
            for thread in pending:
                thread.post_id = post.id
                linked += 1
        audit.brand_id, audit.target_id = account.brand_id, account.id
        audit.detail_json = {"posts": len(body.posts), "linked_threads": linked}
    return {"ok": True, "posts": len(body.posts), "linked_threads": linked}


def mark_missing(session: Session, platform: str, external_id: str, ids) -> dict:
    """以完整貼文清單 ids 標記已在平台刪除的貼文；重新出現的貼文恢復顯示。"""
    account = session.scalar(
        select(Account).where(Account.platform == platform, Account.external_id == external_id)
    )
    result = {"deleted": 0, "restored": 0}
    if account is None:
        return result
    now = utc_now()
    for post in session.scalars(select(Post).where(Post.account_id == account.id)):
        if post.external_id in ids:
            if post.deleted_at is not None:
                post.deleted_at = None
                result["restored"] += 1
        elif post.deleted_at is None:
            post.deleted_at = now
            result["deleted"] += 1
    return result


def upsert_metrics(session: Session, body: MetricsInput) -> dict:
    inserted = 0
    with session.begin():
        audit = _begin_ingest(session, "ingest.metrics")
        account = require_account(session, body.platform, body.account_external_id)
        for source in body.metrics:
            post = session.scalar(
                select(Post).where(
                    Post.account_id == account.id,
                    Post.external_id == source.post_external_id,
                )
            )
            if post is None:
                raise HTTPException(422, "貼文尚未同步")
            values = source.model_dump(exclude={"post_external_id"})
            # 同一排程時槽重試保留第一份快照，下一個時槽才新增。
            result = session.execute(
                insert(MetricSnapshot).values(post_id=post.id, **values).on_conflict_do_nothing()
            )
            inserted += result.rowcount
        audit.brand_id, audit.target_id = account.brand_id, account.id
        audit.detail_json = {"inserted": inserted, "received": len(body.metrics)}
    return {"ok": True, "inserted": inserted}


def due_metrics(
    session: Session, platform: str, external_id: str, limit: int, now: datetime | None = None
) -> dict:
    now = now or utc_now()
    slot = now.replace(minute=0, second=0, microsecond=0)
    account = require_account(session, platform, external_id)
    latest = (
        select(
            MetricSnapshot.post_id,
            func.max(func.coalesce(MetricSnapshot.sync_slot, MetricSnapshot.captured_at)).label(
                "at"
            ),
        )
        .group_by(MetricSnapshot.post_id)
        .subquery()
    )
    rows = session.execute(
        select(Post, latest.c.at)
        .outerjoin(latest, Post.id == latest.c.post_id)
        .where(Post.account_id == account.id, Post.deleted_at.is_(None))
        .order_by(latest.c.at.asc().nulls_first(), Post.id)
    )
    result = []
    for post, captured in rows:
        tier = effective_tier(session, account, post, now)
        interval = {"hourly": 1, "daily": 24, "weekly": 168}[tier]
        if captured is None or slot - captured >= timedelta(hours=interval):
            result.append(
                {
                    "external_id": post.external_id,
                    "media_type": post.media_type,
                    "schedule_tier": tier,
                    "sync_slot": slot,
                }
            )
        if len(result) == limit:
            break
    return {"posts": result}


def list_posts(
    access: BrandAccess,
    brand_id: int | None,
    limit: int,
    offset: int,
    platform: str | None = None,
    period="all",
    date_from=None,
    date_to=None,
    *, since=None, until=None,
):
    if brand_id is not None:
        access.require_brand(brand_id)
    query = access.statement(Post, brand_id)
    if platform is not None:
        query = query.where(Account.platform == platform)
    # 完整清單裡已經沒有的貼文（在平台上刪除）不再顯示。
    query = query.where(Post.deleted_at.is_(None))
    query = filter_dates(query, Post.published_at, period, date_from, date_to)
    if since is not None:
        query = query.where(Post.published_at >= since)
    if until is not None:
        query = query.where(Post.published_at < until)
    return list(
        access.session.scalars(
            query.options(selectinload(Post.thumbnail))
            .order_by(Post.published_at.desc(), Post.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )


def platforms(access, brand_id=None, settings=None):
    from app.services import data_retention

    rows = list_posts(access, brand_id, 1, 0)
    latest = access.session.get(Account, rows[0].account_id) if rows else None
    return {
        **(data_retention.summary(access.session, settings) if settings else {}),
        "default_platform": latest.platform
        if latest and latest.platform in {"facebook", "instagram", "threads", "youtube", "tiktok"}
        else "facebook"
    }


def comments(access, post_id, limit=200, after_id=0):
    from app.services.catalog import get_record
    from app.services.message_content import message_view

    post = get_record(access, Post, post_id)
    query = access.statement(Message).where(
        Thread.post_id == post.id,
        Thread.account_id == post.account_id,
        Thread.kind == "comment_thread",
    )
    total = access.session.scalar(select(func.count()).select_from(query.subquery()))
    rows = access.session.execute(
        query.where(Message.id > after_id)
        .outerjoin(
            Contact,
            and_(
                func.coalesce(Message.contact_id, Thread.contact_id) == Contact.id,
                Contact.brand_id == Thread.brand_id,
            ),
        )
        .add_columns(Contact.display_name)
        .order_by(Message.id)
        .limit(limit + 1)
    ).all()
    items = [message_view(message, name) for message, name in rows[:limit]]
    return {
        "items": items,
        "total": total,
        "next_after": items[-1].id if len(rows) > limit else None,
    }

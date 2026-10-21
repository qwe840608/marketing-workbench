import base64
import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, or_, select

from app.models import (
    Account,
    Brand,
    Classification,
    InboundJob,
    Message,
    Notification,
    NotificationDelivery,
    Setting,
    Thread,
)
from app.models.base import utc_now
from app.schemas.notify import NotificationPolicy
from app.services import classify, credentials, settings_store
from app.services.message_content import has_text
from app.services.posts import _begin_ingest
from app.services.redact import redact

REASONS = {
    "complaint": "客訴需要處理",
    "urgency": "客人問題緊急",
    "public_reputation_risk": "公開留言聲譽風險",
}

OAUTH_NOTICES = {
    "meta": "Meta 授權即將到期，請重新連結",
    "threads": "Threads 授權即將到期，請重新連結",
    "tiktok": "TikTok 授權即將到期或已失效，請到工作檯重新連結",
}


def queue_oauth_notice(session, settings, platform, now):
    recipients = set()
    for brand in session.scalars(select(Brand)):
        policy, _, _ = load_policy(session, brand.id)
        if policy.enabled and policy.group_id and policy.group_id not in recipients:
            recipients.add(policy.group_id)
            session.add(
                NotificationDelivery(
                    brand_id=brand.id,
                    retry_key=str(uuid4()),
                    recipient=policy.group_id,
                    next_attempt_at=now,
                    messages_json=[{"type": "text", "text": OAUTH_NOTICES[platform]}],
                )
            )
    return len(recipients)


def is_oauth_notice(delivery):
    return any(
        delivery.messages_json == [{"type": "text", "text": text}]
        for text in OAUTH_NOTICES.values()
    )


def is_publish_notice(delivery):
    # Only trusted publisher code creates this envelope; it contains no inbound platform text.
    return bool(len(delivery.messages_json) == 1
                and delivery.messages_json[0].get("type") == "text"
                and delivery.messages_json[0].get("text", "").startswith("發佈通知｜"))


def configured(settings):
    return bool(credentials.resolve("NOTIFY_LINE_CHANNEL_ACCESS_TOKEN", settings))


def bootstrap_groups(factory, settings):
    """Groups are explicitly configured per brand; startup never assigns them."""
    return None


def policy_key(brand_id):
    return f"notification.policy.brand.{brand_id}"


def load_policy(session, brand_id):
    row = settings_store.get(session, policy_key(brand_id))
    value = dict(row.value_json) if row else {}
    enabled_at = value.pop("enabled_at", None)
    return (
        NotificationPolicy(**value),
        settings_store.version(row),
        (datetime.fromisoformat(enabled_at) if enabled_at else None),
    )


def policy_view(access, brand_id, settings):
    access.require_brand(brand_id)
    policy, version, enabled_at = load_policy(access.session, brand_id)
    statuses = dict(
        access.session.execute(
            select(NotificationDelivery.status, func.count(NotificationDelivery.id))
            .where(NotificationDelivery.brand_id == brand_id)
            .group_by(NotificationDelivery.status)
        ).all()
    )
    return {
        **policy.model_dump(),
        "version": version,
        "enabled_at": enabled_at,
        "configured": configured(settings) and bool(policy.group_id),
        "bot_configured": configured(settings),
        "groups": [
            {
                "id": gid,
                "label": policy.group_name
                if gid == policy.group_id and policy.group_name
                else f"已驗證群組 …{gid[-6:]}",
            }
            for gid in sorted(
                set(discovered_groups(access.session)["groups"])
                | ({policy.group_id} if policy.group_id else set())
            )
        ],
        "deliveries": statuses,
        "backoffice_url": settings.backoffice_origin,
    }


def save_policy(access, brand_id, body, settings):
    access.require_brand(brand_id, write=True)
    if body.enabled and (not configured(settings) or not body.group_id):
        raise HTTPException(422, "請先設定通知帳號與測試群組")
    session, actor = access.session, f"staff:{access.staff.id}"
    session.commit()
    with session.begin():
        audit = _begin_ingest(session, "notification.policy")
        previous, version, enabled_at = load_policy(session, brand_id)
        if version != body.version:
            raise HTTPException(409, "設定已更新，請重新整理")
        if (
            body.group_id
            and body.group_id != previous.group_id
            and body.group_id not in discovered_groups(session)["groups"]
        ):
            raise HTTPException(422, "請先將通知帳號加入該群組並傳送訊息，完成群組驗證")
        if body.enabled and not previous.enabled:
            # 啟用只通知此刻以後的新事件，不將歷史資料一次推送到群組。
            enabled_at = utc_now()
        value = body.model_dump(exclude={"version"})
        value["enabled_at"] = enabled_at.isoformat() if enabled_at else None
        row = settings_store.get(session, policy_key(brand_id))
        settings_store.put(session, policy_key(brand_id), value, row)
        audit.actor, audit.brand_id, audit.detail_json = actor, brand_id, value
        session.flush()
    return policy_view(access, brand_id, settings)


def emergency(thread_kind, values, policy):
    if thread_kind != "comment_thread" or values.get("intent") == "spam" or values.get("no_text"):
        return None
    if (
        thread_kind == "comment_thread"
        and values.get("public_reputation_risk", 0) > policy.public_reputation_risk_threshold
    ):
        return "public_reputation_risk"
    if values.get("intent") == "complaint" or values.get("is_complaint", 0) >= 0.5:
        return "complaint"
    if values.get("urgency", 0) >= policy.urgency_threshold:
        return "urgency"
    return None


def current_signals(session, message, now):
    row = session.scalar(
        select(Classification)
        .where(Classification.message_id == message.id)
        .order_by(Classification.id.desc())
        .limit(1)
    )
    context, _ = classify.context_for(session, message)
    if row and row.input_hash == classify.fingerprint(message.text, context):
        return row.raw_json.get("signals", {})
    if now - message.created_at < timedelta(minutes=2):
        return None
    # 分流暫時不可用時仍守住五分鐘通知；不將此備援冒充新的 jev 答案。
    return classify.keyword(message.text, bool(redact(message.text).counts))


def upsert_notification(session, thread, message, key, kind, reason, due):
    row = session.scalar(select(Notification).where(Notification.event_key == key))
    if row is None:
        row = Notification(
            brand_id=thread.brand_id,
            thread_id=thread.id,
            message_id=message.id,
            event_key=key,
            kind=kind,
            reason=reason,
            due_at=due,
        )
        session.add(row)
    elif row.status in {"pending", "cancelled"} and row.delivery_id is None:
        row.status = "pending"
        row.due_at, row.kind, row.reason = due, kind, reason
    return row


def plan(factory, now):
    with factory.begin() as session:
        _begin_ingest(session, "notification.plan")
        for brand in session.scalars(select(Brand)):
            policy, _, enabled_at = load_policy(session, brand.id)
            active_keys = set()
            if policy.enabled and policy.group_id and enabled_at:
                query = select(Thread).where(
                    Thread.brand_id == brand.id,
                    Thread.kind == "comment_thread",
                )
                for thread in session.scalars(query):
                    incoming = list(
                        session.scalars(
                            select(Message)
                            .where(
                                Message.thread_id == thread.id,
                                Message.direction == "in",
                                Message.is_historical.is_(False),
                                Message.created_at >= enabled_at,
                                Message.sent_at > thread.last_outbound_at
                                if thread.last_outbound_at
                                else True,
                            )
                            .order_by(Message.sent_at, Message.id)
                        )
                    )
                    for message in incoming:
                        if message.is_redelivery and message.sent_at < now - timedelta(hours=24):
                            continue
                        if not has_text(message.text):
                            continue
                        values = current_signals(session, message, now)
                        if values is None:
                            # 保留尚待重分流的排程，不因暫時沒有答案取消通知。
                            active_keys.update(
                                session.scalars(
                                    select(Notification.event_key).where(
                                        Notification.message_id == message.id,
                                        Notification.status == "pending",
                                    )
                                )
                            )
                            continue
                        if values.get("intent") == "spam" or values.get("no_text"):
                            continue
                        risk = emergency(thread.kind, values, policy)
                        if not risk:
                            continue
                        key = f"message:{message.id}:new"
                        active_keys.add(key)
                        upsert_notification(
                            session, thread, message, key, "urgent", risk, message.created_at
                        )
            for notification in session.scalars(
                select(Notification).where(
                    Notification.brand_id == brand.id,
                    Notification.status == "pending",
                    Notification.delivery_id.is_(None),
                    Notification.event_key.is_not(None),
                )
            ):
                if notification.event_key not in active_keys:
                    notification.status = "cancelled"
            for job in session.scalars(
                select(InboundJob)
                .join(Message)
                .join(Thread)
                .where(
                    Thread.brand_id == brand.id,
                    InboundJob.task == "notify",
                    InboundJob.status == "pending",
                )
            ):
                message = session.get(Message, job.message_id)
                if (
                    message.is_historical
                    or (message.is_redelivery and message.sent_at < now - timedelta(hours=24))
                    or not policy.enabled
                    or not enabled_at
                    or message.created_at < enabled_at
                    or current_signals(session, message, now) is not None
                ):
                    job.status = "completed"


def compose(session, brand, notifications, settings):
    lines = [f"緊急留言通知｜{brand.name}", "請到 Facebook／Instagram 原生 App 處理。"]
    for row in notifications[:16]:
        thread = session.get(Thread, row.thread_id)
        account = session.get(Account, thread.account_id)
        message = session.get(Message, row.message_id)
        platform = {
            "line": "LINE",
            "facebook": "Facebook",
            "instagram": "Instagram",
            "threads": "Threads",
        }.get(account.platform, "原平台")
        lines.append(
            f"{platform}｜{REASONS.get(row.reason, '緊急留言')}｜{redact(message.text).text[:180]}"
        )
    if len(notifications) > 16:
        lines.append(f"另有 {len(notifications) - 16} 則緊急留言，請至原生 App 查看。")
    chunks, current = [], ""
    for line in lines:
        if len((current + line + "\n").encode("utf-16-le")) // 2 > 4500:
            chunks.append({"type": "text", "text": current})
            current = ""
        current += line + "\n"
    if current:
        chunks.append({"type": "text", "text": current})
    return chunks


def claim_deliveries(factory, settings, now):
    with factory.begin() as session:
        _begin_ingest(session, "notification.claim")
        for brand in session.scalars(select(Brand)):
            policy, _, _ = load_policy(session, brand.id)
            if not policy.enabled or not policy.group_id:
                continue
            rows = list(
                session.scalars(
                    select(Notification)
                    .where(
                        Notification.brand_id == brand.id,
                        Notification.status == "pending",
                        Notification.delivery_id.is_(None),
                        Notification.due_at <= now,
                    )
                    .order_by(Notification.due_at, Notification.id)
                )
            )
            if rows:
                delivery = NotificationDelivery(
                    brand_id=brand.id,
                    retry_key=str(uuid4()),
                    recipient=policy.group_id,
                    next_attempt_at=now,
                    messages_json=compose(session, brand, rows, settings),
                )
                session.add(delivery)
                session.flush()
                for row in rows:
                    row.delivery_id = delivery.id
        result = []
        for delivery in session.scalars(
            select(NotificationDelivery)
            .where(
                NotificationDelivery.status.in_(["pending", "sending"]),
                NotificationDelivery.next_attempt_at <= now,
                or_(
                    NotificationDelivery.lease_until.is_(None),
                    NotificationDelivery.lease_until <= now,
                ),
            )
            .order_by(NotificationDelivery.id)
            .limit(10)
        ):
            notices = list(
                session.scalars(select(Notification).where(Notification.delivery_id == delivery.id))
            )
            oauth_notice = not notices and (
                is_oauth_notice(delivery) or is_publish_notice(delivery)
            )
            if not oauth_notice and (
                not notices
                or any(
                    row.reason not in REASONS
                    or session.get(Thread, row.thread_id).kind != "comment_thread"
                    for row in notices
                )
            ):
                delivery.status, delivery.error = "failed", "notification_retired"
                fail_notices(session, delivery.id)
                continue
            if not delivery.first_attempt_at and not oauth_notice:
                delivery.messages_json = compose(
                    session, session.get(Brand, delivery.brand_id), notices, settings
                )
            elif not oauth_notice and (
                not delivery.messages_json
                or not delivery.messages_json[0].get("text", "").startswith("緊急留言通知｜")
            ):
                delivery.status, delivery.error = "failed", "notification_retired"
                fail_notices(session, delivery.id)
                continue
            policy, _, _ = load_policy(session, delivery.brand_id)
            if not policy.enabled or delivery.recipient != policy.group_id:
                delivery.status, delivery.error = "failed", "configuration_changed"
                fail_notices(session, delivery.id)
                continue
            if delivery.first_attempt_at and now - delivery.first_attempt_at >= timedelta(hours=23):
                delivery.status, delivery.error = "failed", "retry_window_expired"
                fail_notices(session, delivery.id)
                continue
            delivery.first_attempt_at = delivery.first_attempt_at or now
            delivery.lease_id, delivery.lease_until = str(uuid4()), now + timedelta(minutes=4)
            delivery.status, delivery.attempts = "sending", delivery.attempts + 1
            result.append(
                {
                    "id": delivery.id,
                    "lease_id": delivery.lease_id,
                    "retry_key": delivery.retry_key,
                    "to": delivery.recipient,
                    "messages": delivery.messages_json,
                }
            )
        return result


def fail_notices(session, delivery_id):
    for row in session.scalars(select(Notification).where(Notification.delivery_id == delivery_id)):
        row.status = "failed"


def dispatch(factory, settings):
    if not configured(settings):
        return {"deliveries": [], "state": "configuration_missing"}
    now, lease = utc_now(), str(uuid4())
    with factory.begin() as session:
        _begin_ingest(session, "notification.dispatch")
        lock = settings_store.get(session, "notification.dispatch.lease")
        if lock and datetime.fromisoformat(lock.value_json["until"]) > now:
            return {"deliveries": [], "state": "busy"}
        value = {"id": lease, "until": (now + timedelta(minutes=4)).isoformat()}
        settings_store.put(session, "notification.dispatch.lease", value, lock)
    try:
        plan(factory, now)
        plan(factory, utc_now())
        return {"deliveries": claim_deliveries(factory, settings, utc_now()), "state": "ready"}
    finally:
        with factory.begin() as session:
            _begin_ingest(session, "notification.dispatch.release")
            lock = settings_store.get(session, "notification.dispatch.lease")
            if lock and lock.value_json["id"] == lease:
                session.delete(lock)


def finish(factory, delivery_id, body):
    with factory.begin() as session:
        audit = _begin_ingest(session, "notification.result")
        row = session.get(NotificationDelivery, delivery_id)
        if not row:
            raise HTTPException(404, "找不到通知")
        if row.status == "sent":
            return {"status": "sent"}
        if row.status != "sending" or row.lease_id != body.lease_id:
            raise HTTPException(409, "通知處理權已更新")
        now = utc_now()
        accepted = body.status_code == 200 or (body.status_code == 409 and body.already_accepted)
        if accepted:
            row.status, row.sent_at, row.error = "sent", now, None
        elif body.status_code == 0 or body.status_code >= 500:
            row.status, row.error = "pending", "line_temporarily_unavailable"
            row.next_attempt_at = now + timedelta(
                seconds=min(3600, 60 * 2 ** min(row.attempts - 1, 6))
            )
        else:
            row.status, row.error = "failed", f"line_http_{body.status_code}"
        row.lease_id, row.lease_until = None, None
        for notice in session.scalars(
            select(Notification).where(Notification.delivery_id == row.id)
        ):
            if row.status in {"sent", "failed"}:
                notice.status, notice.sent_at = row.status, row.sent_at
        audit.brand_id, audit.target_type, audit.target_id = (
            row.brand_id,
            "notification_delivery",
            row.id,
        )
        audit.detail_json = {
            "status": row.status,
            "http_status": body.status_code,
            "attempts": row.attempts,
        }
        return {"status": row.status}


def capture_groups(session, settings, raw, signature):
    secret = credentials.resolve("NOTIFY_LINE_CHANNEL_SECRET", settings, session)
    bot_id = credentials.resolve("NOTIFY_LINE_BOT_USER_ID", settings, session)
    if not secret or not bot_id:
        raise HTTPException(503, "通知帳號尚未設定")
    expected = base64.b64encode(
        hmac.new(secret.get_secret_value().encode(), raw, hashlib.sha256).digest()
    ).decode()
    if (
        not signature
        or not re.fullmatch(r"[A-Za-z0-9+/]{43}=", signature)
        or not hmac.compare_digest(expected, signature)
    ):
        raise HTTPException(401, "LINE 簽章不符")
    try:
        payload = json.loads(raw)
        if payload.get("destination") != bot_id:
            raise HTTPException(403, "通知帳號不符")
        events = payload["events"]
        if not isinstance(events, list) or len(events) > 100:
            raise ValueError()
        groups = {
            e.get("source", {}).get("groupId")
            for e in events
            if e.get("type") in {"join", "message"} and e.get("source", {}).get("type") == "group"
        }
        groups = {g for g in groups if isinstance(g, str) and re.fullmatch(r"C[a-f0-9]{32}", g)}
    except (ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(400, "通知事件格式錯誤") from None
    session.commit()
    with session.begin():
        _begin_ingest(session, "notification.groups.discovered")
        row = settings_store.get(session, "notification.discovered_groups")
        known = dict(row.value_json) if row else {}
        for group_id in groups:
            known[group_id] = utc_now().isoformat()
        if row:
            row.value_json = known
        elif groups:
            session.add(Setting(key="notification.discovered_groups", value_json=known))
    return {"ok": True, "groups": len(groups)}


def discovered_groups(session):
    row = settings_store.get(session, "notification.discovered_groups")
    return {"groups": row.value_json if row else {}}

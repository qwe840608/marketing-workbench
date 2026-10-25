"""Backend-owned five-minute probes and durable, at-most-once transition alerts."""

import hashlib
import hmac
import logging
import re
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert

from app.models import ReceiveHealthCheck, WebhookFailure
from app.models.base import utc_now
from app.services import roles, settings_store
from app.services.posts import _begin_ingest

STATE = "receive_health.state"
TARGET = "receive_health.target"
PATH = "/webhook/mwb-gateway-probe"
BANNER = "收訊通道中斷：新留言可能無法收到"
# Shown verbatim and used as i18n keys by the frontend, so keep them in sync with the locales.
REASONS = {
    "scheduler": "後端排程器未運作",
    "probe_secret_missing": "未設定公開探測密鑰（WEBHOOK_PROBE_SECRET）",
    "probe_url_invalid": "公開網址不是 ngrok 網址，無法探測",
    "probe_unreachable": "公開網址連不上，請確認 ngrok 已啟動",
    "signature_surge": "驗簽失敗暴增",
}
logger = logging.getLogger("mwb.receive_health")


def client():
    return httpx.Client(timeout=10, follow_redirects=False, trust_env=False)


def signed_probe(http, base, secret, now):
    timestamp = str(int(now.timestamp()))
    signature = hmac.new(
        secret.encode(), f"GET\n{PATH}\n{timestamp}".encode(), hashlib.sha256
    ).hexdigest()
    r = http.get(
        base + PATH,
        headers={
            "x-mwb-probe-time": timestamp,
            "x-mwb-probe-signature": signature,
            "ngrok-skip-browser-warning": "1",
        },
    )
    return r.status_code == 200 and r.json() == {
        "ok": True,
        "service": "backend",
        "purpose": "tunnel-check",
    }


def probe(settings, now):
    from app.services.scheduler import scheduler_for

    scheduler = scheduler_for(settings)
    checks = {"scheduler": bool(scheduler and scheduler.healthy()), "public_probe": False}
    url = settings.webhook_public_url.rstrip("/")
    if not url:
        # A fresh install has no public tunnel yet; nothing can arrive, so nothing to alarm about.
        checks["public_probe"] = None
        return checks
    secret = (
        settings.webhook_probe_secret.get_secret_value() if settings.webhook_probe_secret else ""
    )
    # Never send probe credentials to arbitrary URLs or follow redirects.
    if not re.fullmatch(r"https://[a-z0-9-]+\.ngrok(?:-free)?\.(?:app|dev)", url):
        checks["probe_issue"] = "probe_url_invalid"
    elif not secret:
        checks["probe_issue"] = "probe_secret_missing"
    else:
        with client() as http:
            try:
                checks["public_probe"] = signed_probe(http, url, secret, now)
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                pass
        if not checks["public_probe"]:
            checks["probe_issue"] = "probe_unreachable"
    return checks


def reasons(checks):
    found = []
    if checks.get("scheduler") is False:
        found.append(REASONS["scheduler"])
    if checks.get("public_probe") is False:
        found.append(REASONS[checks.get("probe_issue", "probe_unreachable")])
    if checks.get("signature_ok") is False:
        found.append(REASONS["signature_surge"])
    return found


def signature_failure(session, platform, now=None):
    from app.db import ensure_write

    ensure_write(session)
    now = now or utc_now()
    bucket = now.replace(second=0, microsecond=0)
    session.execute(
        insert(WebhookFailure)
        .values(platform=platform, bucket_at=bucket, count=1)
        .on_conflict_do_update(
            index_elements=["platform", "bucket_at"], set_={"count": WebhookFailure.count + 1}
        )
    )
    session.commit()
    return {"ok": True}


def failure_counts(session, now):
    def count(start, end):
        return session.scalar(
            select(func.coalesce(func.sum(WebhookFailure.count), 0)).where(
                WebhookFailure.bucket_at >= start, WebhookFailure.bucket_at < end
            )
        )

    # Compare five complete minutes against the preceding hour, with an absolute floor.
    end = now.replace(second=0, microsecond=0)
    recent = count(end - timedelta(minutes=5), end)
    baseline = count(end - timedelta(minutes=65), end - timedelta(minutes=5)) / 12
    return recent, recent >= max(10, baseline * 3)


def target(session, settings):
    row = settings_store.get(session, TARGET)
    if row:
        return row.value_json["recipient"], row.version, "custom"
    from app.services import credentials

    return credentials.resolve("NOTIFY_LINE_GROUP_ID", settings, session), 0, "environment"


def target_view(access, settings):
    if not roles.can(access, "settings.manage"):
        raise HTTPException(403, "系統警示對象僅管理員可檢視與修改")
    recipient, version, source = target(access.session, settings)
    return {
        "recipient": recipient or "",
        "version": version,
        "source": source,
        "alerts_enabled": settings.receive_health_alerts_enabled,
    }


def save_target(access, settings, body):
    target_view(access, settings)
    session = access.session
    session.commit()
    with session.begin():
        audit = _begin_ingest(session, "receive_health.target")
        before, version, _ = target(session, settings)
        if version != body.version:
            raise HTTPException(409, "系統警示設定已更新，請重新整理")
        row = settings_store.get(session, TARGET)
        value = {"recipient": body.recipient}
        settings_store.put(session, TARGET, value, row)
        audit.actor = f"staff:{access.staff.id}"
        audit.detail_json = {"before": before, "after": body.recipient}
    return target_view(access, settings)


def snapshot(session, settings, now=None):
    now = now or utc_now()
    state = settings_store.get(session, STATE)
    data = state.value_json if state else {}
    checked = datetime.fromisoformat(data["checked_at"]) if data.get("checked_at") else None
    stale = checked is not None and now - checked > timedelta(minutes=11)
    return {
        "interrupted": data.get("healthy") is False or stale,
        "message": BANNER,
        "reasons": data.get("reasons", []) if data.get("healthy") is False else [],
        "public_url_configured": bool(settings.webhook_public_url),
        "last_ok_at": data.get("last_ok_at"),
        "checked_at": data.get("checked_at"),
        "stale": stale,
        "monitor_enabled": settings.receive_health_worker_enabled,
        "alerts_enabled": settings.receive_health_alerts_enabled,
        "history": [
            {
                "id": r.id,
                "checked_at": r.checked_at,
                "healthy": r.healthy,
                "checks": r.checks_json,
                "transition": r.transition,
                "alert_status": r.alert_status,
            }
            for r in session.scalars(
                select(ReceiveHealthCheck)
                .where(ReceiveHealthCheck.checked_at >= now - timedelta(hours=24))
                .order_by(ReceiveHealthCheck.checked_at.desc())
                .limit(300)
            )
        ],
    }


def push_alert(settings, recipient, text):
    from app.services import credentials

    if not settings.receive_health_alerts_enabled:
        return "suppressed"
    token = credentials.resolve("NOTIFY_LINE_CHANNEL_ACCESS_TOKEN", settings)
    if not token or not re.fullmatch(
        r"[UCR][a-f0-9]{32}", recipient or ""
    ):
        return "unconfigured"
    try:
        with client() as http:
            response = http.post(
                "https://api.line.me/v2/bot/message/push",
                headers={
                    "Authorization": "Bearer "
                    + token.get_secret_value()
                },
                json={"to": recipient, "messages": [{"type": "text", "text": text}]},
            )
            return "sent" if response.status_code == 200 else "failed"
    except httpx.HTTPError:
        # Unknown outcomes are not retried: one attempt per transition, even across restarts.
        return "unknown"


def check(factory, settings, now=None):
    now = now or utc_now()
    with factory.begin() as session:
        _begin_ingest(session, "receive_health.claim")
        row = settings_store.get(session, STATE)
        data = dict(row.value_json) if row else {}
        if data.get("next_check_at") and datetime.fromisoformat(data["next_check_at"]) > now:
            return
        data["next_check_at"] = (now + timedelta(minutes=5)).isoformat()
        settings_store.put(session, STATE, data, row)
    checks = probe(settings, now)
    with factory.begin() as session:
        _begin_ingest(session, "receive_health.result")
        recent, surge = failure_counts(session, now)
        checks.update(signature_ok=not surge, signature_failures_5m=recent)
        # A skipped probe (None, no public URL configured) is not an outage.
        healthy = bool(checks["scheduler"] and checks["public_probe"] is not False and not surge)
        row = settings_store.get(session, STATE)
        data = dict(row.value_json)
        previous = data.get("healthy")
        transition = (
            "outage"
            if not healthy and previous is not False
            else "recovered"
            if healthy and previous is False
            else None
        )
        data.update(healthy=healthy, checked_at=now.isoformat(), reasons=reasons(checks))
        if healthy:
            data["last_ok_at"] = now.isoformat()
        row.value_json = data
        record = ReceiveHealthCheck(
            checked_at=now,
            healthy=healthy,
            checks_json=checks,
            transition=transition,
            alert_status="claimed" if transition else "none",
        )
        session.add(record)
        session.flush()
        record_id = record.id
        recipient = target(session, settings)[0]
        last_ok = data.get("last_ok_at")
        causes = data["reasons"]
    if transition:
        stamp = (
            datetime.fromisoformat(last_ok)
            .astimezone(ZoneInfo("Asia/Taipei"))
            .strftime("%Y-%m-%d %H:%M:%S")
            if last_ok
            else "尚無正常紀錄"
        )
        text = (
            BANNER if transition == "outage" else "收訊通道已恢復：新留言可正常接收"
        ) + f"\n上次正常：{stamp}（台北時間）"
        if transition == "outage" and causes:
            text += "\n原因：" + "、".join(causes)
        status = push_alert(settings, recipient, text)
        with factory.begin() as session:
            session.get(ReceiveHealthCheck, record_id).alert_status = status


class ReceiveHealthWorker:
    def __init__(self, factory, settings):
        self.factory, self.settings = factory, settings
        self.stop = threading.Event()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True, name="receive-health")
        self.thread.start()

    def run(self):
        # Allow the backend and fixed tunnel to become ready.
        if self.stop.wait(300):
            return
        while not self.stop.is_set():
            try:
                check(self.factory, self.settings)
            except Exception as error:
                from app.logging_config import error_fields

                logger.error("receive_health_check_failed", extra=error_fields(error))
            self.stop.wait(300)

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join()

"""Five independent, durable jobs. A renewable lease also excludes a second process."""

import math
import threading
import time
import uuid

from sqlalchemy import select, update

from app.logging_config import error_fields, log_failure
from app.models import AuditLog, CommentPoll, Setting
from app.models.base import utc_now
from app.services import audit_retention, classify, data_retention, ideation, settings_store
from app.services.workers import Workers

INTERVALS = {
    "classify": 60,
    "notify": 60,
    "comments": 60,
    "metrics": 3600,
    "ideation": 60,
    "publish": 60,
}
_instances = {}
_guard = threading.Lock()


def dispatch(name, factory, settings):
    """classify／ideation 直接呼叫 service；主題發想與舊內部 tick 相同，排入後依序同步處理。"""
    if name == "classify":
        return classify.dispatch(factory, settings)
    ids = ideation.schedule(factory, settings)
    for identity in ids:
        ideation.process(factory, settings, identity)
    return {"queued": len(ids)}


def idle(result):
    # 成功且沒有處理任何東西的一輪不寫稽核；失敗或有處理量的照常記錄。
    return result.get("ok") is True and not any(
        value for key, value in result.items() if key != "ok"
    )


def scheduler_for(settings):
    with _guard:
        return _instances.get(str(settings.database_path))


def lock_state(session):
    # First statement acquires SQLite's writer lock without creating polling audit rows.
    session.execute(
        update(Setting)
        .where(Setting.key == "scheduler.heartbeat")
        .values(value_json=Setting.value_json)
    )


class Scheduler:
    def __init__(self, factory, settings):
        self.factory, self.settings = factory, settings
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.thread = None
        self.owner = uuid.uuid4().hex
        self.running = {}
        self.lock = threading.Lock()
        self.last_tick = 0
        self.last_agent_cleanup = 0

    def enabled(self, name, session):
        if not getattr(self.settings, "scheduler_" + name + "_enabled"):
            return False
        row = settings_store.get(session, "scheduler.enabled." + name)
        return row is None or row.value_json.get("enabled", True) is True

    def claim(self, name, now=None):
        if name not in INTERVALS:
            return False
        now = now or utc_now()
        with self.factory.begin() as session:
            lock_state(session)
            if name == "comments" and not session.scalar(
                select(CommentPoll.id).where(CommentPoll.manual_requested.is_(True)).limit(1)
            ):
                return False
            if not self.enabled(name, session):
                return False
            key = "scheduler.job." + name
            row = settings_store.get(session, key)
            data = dict(row.value_json) if row else {}
            if data.get("lease_until", 0) > now.timestamp():
                return False
            if not data.get("requested") and data.get("next_at", 0) > now.timestamp():
                return False
            data["active_options"] = data.pop("options", {})
            data.update(
                owner=self.owner,
                lease_until=now.timestamp() + 120,
                started_at=now.isoformat(),
                requested=False,
                next_at=(int(now.timestamp()) // INTERVALS[name] + 1) * INTERVALS[name],
            )
            settings_store.put(session, key, data, row)
        return True

    def request(self, name, options=None):
        if name not in INTERVALS:
            raise ValueError("unknown_job")
        with self.factory.begin() as session:
            lock_state(session)
            key = "scheduler.job." + name
            row = settings_store.get(session, key)
            data = dict(row.value_json) if row else {}
            data["requested"] = True
            if options is not None:
                data["options"] = options
            settings_store.put(session, key, data, row)
        self.wake.set()

    def execute(self, name):
        workers = Workers(self.factory, self.settings)
        try:
            if name == "publish":
                from app.services import publish

                result = publish.tick(self.factory, self.settings)
            elif name in ("classify", "ideation"):
                value = dispatch(name, self.factory, self.settings)
                result = {
                    "ok": True,
                    **{k: v for k, v in value.items() if k in ("completed", "queued")},
                }
            else:
                with self.factory() as session:
                    row = settings_store.get(session, "scheduler.job." + name)
                    options = row.value_json.get("active_options", {}) if row else {}
                follower_result = workers.followers() if name == "metrics" else None
                result = getattr(workers, {"notify": "notifications"}.get(name, name))(**options)
                if name == "metrics":
                    from app.services import publish_presence, publish_story_insights

                    publish_presence.hourly_threads(self.factory, self.settings, workers.listed)
                    result["stories"] = publish_story_insights.hourly(
                        self.factory, self.settings, workers
                    )
                    from app.services import post_thumbnails

                    result["thumbnails"] = post_thumbnails.hourly(self.factory, self.settings)
                    # 受眾分布每帳號每天一份；失敗只記在結果，不影響本輪成效同步的成敗。
                    try:
                        result["audience"] = workers.audience()
                    except Exception as error:
                        log_failure("mwb.scheduler", "scheduler_audience_failed", error)
                        result["audience"] = {"saved": 0, "errors": [{"code": "sync_failed"}]}
                if follower_result is not None:
                    result = {
                        **result,
                        "followers": follower_result,
                        "ok": result["ok"] and follower_result["ok"],
                    }
        except Exception as error:
            log_failure("mwb.scheduler", "scheduler_execute_failed", error)
            result = {"ok": False, "error": "job_failed"}
        with self.factory.begin() as session:
            lock_state(session)
            row = settings_store.get(session, "scheduler.job." + name)
            if row and row.value_json.get("owner") == self.owner:
                data = dict(row.value_json)
                data.update(lease_until=0, finished_at=utc_now().isoformat(), result=result)
                row.value_json = data
                if idle(result):
                    return
                session.add(
                    AuditLog(
                        actor="system:scheduler",
                        action="scheduler.run",
                        target_type="scheduler",
                        detail_json={"job": name, **result},
                    )
                )

    def tick(self):
        now = utc_now()
        with self.lock:
            self.running = {name: t for name, t in self.running.items() if t.is_alive()}
            with self.factory.begin() as session:
                lock_state(session)
                key = "scheduler.heartbeat"
                row = settings_store.get(session, key)
                data = {"checked_at": now.isoformat(), "owner": self.owner}
                settings_store.put(session, key, data, row)
                for name in self.running:
                    row = settings_store.get(session, "scheduler.job." + name)
                    if row and row.value_json.get("owner") == self.owner:
                        row.value_json = {**row.value_json, "lease_until": now.timestamp() + 120}
            for name in INTERVALS:
                if name not in self.running and self.claim(name, now):
                    thread = threading.Thread(
                        target=self.execute, args=(name,), name="scheduler-" + name, daemon=True
                    )
                    self.running[name] = thread
                    thread.start()
            if audit_retention.due(self.factory, now):
                threading.Thread(
                    target=self.prune_audit, name="audit-retention", daemon=True
                ).start()
            if data_retention.due(self.factory, now):
                threading.Thread(
                    target=self.prune_platform_data, name="data-retention", daemon=True
                ).start()
            from app.services import oauth

            if "agent-auth" not in self.running and (
                not self.last_agent_cleanup or time.monotonic() - self.last_agent_cleanup >= 3600
            ):
                thread = threading.Thread(
                    target=self.maintain_agents, name="agent-auth-maintenance", daemon=True
                )
                self.running["agent-auth"] = thread
                self.last_agent_cleanup = time.monotonic()
                thread.start()

            if "oauth" not in self.running and oauth.maintenance_due(self.factory, now):
                thread = threading.Thread(
                    target=self.maintain_oauth, name="oauth-maintenance", daemon=True
                )
                self.running["oauth"] = thread
                thread.start()
            self.last_tick = time.monotonic()

    def maintain_oauth(self):
        from app.services import oauth

        try:
            oauth.maintain(self.factory, self.settings)
        except Exception as error:
            log_failure("mwb.scheduler", "oauth_maintenance_failed", error)

    def maintain_agents(self):
        from app.services import agent_auth

        try:
            agent_auth.maintain(self.factory)
        except Exception as error:
            log_failure("mwb.scheduler", "agent_auth_maintenance_failed", error)

    def prune_platform_data(self):
        try:
            data_retention.prune(self.factory, self.settings)
        except Exception as error:
            log_failure("mwb.scheduler", "data_retention_failed", error)

    def prune_audit(self):
        try:
            audit_retention.prune(self.factory)
        except Exception as error:
            log_failure("mwb.scheduler", "audit_retention_failed", error)

    def healthy(self):
        return bool(
            self.thread
            and self.thread.is_alive()
            and self.last_tick
            and time.monotonic() - self.last_tick < 30
        )

    def run(self):
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception as error:
                import logging

                logging.getLogger("mwb.scheduler").error(
                    "scheduler_tick_failed", extra=error_fields(error)
                )
            self.wake.wait(5)
            self.wake.clear()

    def start(self):
        # A deployment gets its first snapshot without waiting for a persisted next_at.
        self.request("metrics")
        with _guard:
            _instances[str(self.settings.database_path)] = self
        self.thread = threading.Thread(target=self.run, name="backend-scheduler", daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        self.wake.set()
        if self.thread:
            self.thread.join()
        for thread in self.running.values():
            thread.join()
        with _guard:
            if _instances.get(str(self.settings.database_path)) is self:
                _instances.pop(str(self.settings.database_path))


def jobs_view(access, settings):
    from fastapi import HTTPException

    from app.services import roles

    if not roles.can(access, "settings.manage"):
        raise HTTPException(403, "排程設定僅管理員可操作")
    result = []
    for name, interval in INTERVALS.items():
        row = settings_store.get(access.session, "scheduler.enabled." + name)
        state = settings_store.get(access.session, "scheduler.job." + name)
        configured = getattr(settings, "scheduler_" + name + "_enabled")
        result.append(
            {
                "name": name,
                "interval_seconds": interval,
                "enabled": row.value_json.get("enabled", True) if row else True,
                "effective_enabled": settings.scheduler_enabled
                and configured
                and (row is None or row.value_json.get("enabled", True)),
                "version": settings_store.version(row),
                "last_run": state.value_json if state else None,
            }
        )
    return {"jobs": result}


def save_job(access, settings, name, enabled, version):
    from fastapi import HTTPException

    jobs_view(access, settings)
    if name not in INTERVALS:
        raise HTTPException(404, "找不到排程工作")
    session = access.session
    session.commit()
    with session.begin():
        lock_state(session)
        key = "scheduler.enabled." + name
        row = settings_store.get(session, key)
        settings_store.require_version(row, version, "排程設定已更新，請重新整理")
        value = {"enabled": enabled}
        settings_store.put(session, key, value, row)
        session.add(
            AuditLog(
                actor=f"staff:{access.staff.id}",
                action="scheduler.settings",
                target_type="scheduler",
                detail_json={"job": name, "enabled": enabled},
            )
        )
    return jobs_view(access, settings)


MANUAL_METRICS_KEY = "scheduler.manual.metrics"
# 手動「立即同步」的冷卻秒數：Meta 依使用率節流，連按只會更快吃滿額度，不會更快拿到數字。
MANUAL_METRICS_COOLDOWN = 60


def manual_metrics_view(session, now=None):
    now = now or utc_now()
    job = settings_store.get(session, "scheduler.job.metrics")
    data = job.value_json if job else {}
    manual = settings_store.get(session, MANUAL_METRICS_KEY)
    requested_at = manual.value_json.get("requested_at", 0) if manual else 0
    if data.get("lease_until", 0) > now.timestamp():
        state = "running"
    else:
        state = "pending" if data.get("requested") else "idle"
    return {
        "state": state,
        "finished_at": data.get("finished_at"),
        "retry_after": max(
            0, math.ceil(requested_at + MANUAL_METRICS_COOLDOWN - now.timestamp())
        ),
    }


def request_manual_metrics(access, settings):
    from fastapi import HTTPException

    from app.services import roles

    if not roles.can(access, "posts.sync"):
        raise HTTPException(403, "此帳號僅能檢視資料")
    scheduler = scheduler_for(settings)
    if not scheduler or not scheduler.healthy():
        raise HTTPException(503, "排程服務未啟動，請稍後再試")
    session = access.session
    session.commit()
    now = utc_now()
    with session.begin():
        lock_state(session)
        if not scheduler.enabled("metrics", session):
            raise HTTPException(409, "成效同步排程已停用")
        view = manual_metrics_view(session, now)
        if view["retry_after"]:
            raise HTTPException(429, "剛排過同步，請稍候再試")
        # 已在跑或已排入時不再排一輪，避免跑完立刻又整批重抓。
        if view["state"] != "idle":
            return {**view, "queued": False}
        manual = settings_store.get(session, MANUAL_METRICS_KEY)
        settings_store.put(session, MANUAL_METRICS_KEY, {"requested_at": now.timestamp()}, manual)
        job = settings_store.get(session, "scheduler.job.metrics")
        data = dict(job.value_json) if job else {}
        data["requested"] = True
        settings_store.put(session, "scheduler.job.metrics", data, job)
        session.add(
            AuditLog(
                actor=f"staff:{access.staff.id}",
                action="scheduler.request",
                target_type="scheduler",
                detail_json={"job": "metrics"},
            )
        )
    scheduler.wake.set()
    return {**manual_metrics_view(session, now), "queued": True}

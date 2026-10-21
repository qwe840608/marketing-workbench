"""Routine audit rows expire after 30 days; human and non-routine rows stay."""

import sqlite3
from datetime import timedelta

from sqlalchemy import func, select

from app.db import build_engine, session_factory
from app.models import AuditLog
from app.models.base import utc_now
from app.services import audit_retention


def add(session, action, actor, days):
    session.add(
        AuditLog(
            actor=actor,
            action=action,
            target_type="test",
            at=utc_now() - timedelta(days=days),
        )
    )


def test_prune_only_expired_routine_system_rows(migrated, monkeypatch):
    factory = session_factory(build_engine(migrated))
    monkeypatch.setattr(audit_retention, "BATCH", 3)
    with factory.begin() as session:
        for _ in range(7):
            add(session, "scheduler.run", "system:scheduler", 31)
        add(session, "meta.call.start", "system:meta", 45)
        add(session, "scheduler.run", "system:scheduler", 29)
        add(session, "send.confirm", "staff:1", 90)
        add(session, "draft.state", "system:test", 90)
        # 例行類型但由人員觸發的紀錄也保留。
        add(session, "comments.claim", "staff:1", 90)
    # 批次小於總數時仍會分批刪完。
    assert audit_retention.prune(factory) == 8
    with factory() as session:
        kept = sorted(
            (row.action, row.actor)
            for row in session.scalars(select(AuditLog))
            if row.target_type == "test"
        )
    assert kept == [
        ("comments.claim", "staff:1"),
        ("draft.state", "system:test"),
        ("scheduler.run", "system:scheduler"),
        ("send.confirm", "staff:1"),
    ]
    assert audit_retention.prune(factory) == 0


def test_due_runs_once_a_day(migrated):
    factory = session_factory(build_engine(migrated))
    now = utc_now()
    assert audit_retention.due(factory, now)
    assert not audit_retention.due(factory, now + timedelta(hours=23))
    assert audit_retention.due(factory, now + timedelta(days=1, seconds=1))
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AuditLog)) >= 0


def test_action_time_index_exists(migrated):
    connection = sqlite3.connect(migrated.database_path)
    try:
        indexes = {row[1] for row in connection.execute("PRAGMA index_list('audit_log')")}
    finally:
        connection.close()
    assert "ix_audit_log_action_at" in indexes


def count(factory, action):
    with factory() as session:
        return session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == action)
        )


def test_idle_routine_audit_is_dropped(migrated):
    from app.models import Setting
    from app.services.posts import _begin_ingest

    factory = session_factory(build_engine(migrated))
    with factory.begin() as session:
        _begin_ingest(session, "comments.claim")
    assert count(factory, "comments.claim") == 0
    # 同一輪有寫入其他資料就保留紀錄。
    with factory.begin() as session:
        _begin_ingest(session, "comments.claim")
        session.add(Setting(key="retention.test", value_json={}))
    assert count(factory, "comments.claim") == 1
    # 非例行類型即使沒有其他寫入也保留。
    with factory.begin() as session:
        _begin_ingest(session, "ingest.posts")
    assert count(factory, "ingest.posts") == 1


def test_scheduler_idle_result():
    from app.services.scheduler import idle

    assert idle({"ok": True, "completed": 0, "paused": False})
    assert idle({"ok": True, "inserted": 0, "errors": []})
    assert not idle({"ok": True, "completed": 2})
    assert not idle({"ok": False, "error": "job_failed"})
    assert not idle({"ok": True, "errors": ["x"]})

"""Synthetic WAL contention; events control ordering, never timing sleeps."""

import json
import logging
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from ai_fixtures import ai_data as ai_data
from fastapi import HTTPException
from sqlalchemy import event, func, select
from sqlalchemy.exc import OperationalError
from test_classify import classified_data as classified_data
from test_stage3 import access, complete, idea_payload, queued, script_content
from test_stage3 import stage as stage

from app import db
from app.db import build_engine, session_factory
from app.logging_config import JsonFormatter, error_fields
from app.models import AIRun, Setting
from app.models.ideation import IdeationReport, VideoScript
from app.schemas.ideation import EditScript
from app.services import ai, ideation, receive_health, video_scripts
from app.services.ai import providers
from app.services.scheduler import INTERVALS, Scheduler


def test_deferred_snapshot_ignores_busy_timeout(migrated):
    path = str(migrated.database_path)
    with sqlite3.connect(path, autocommit=True) as setup:
        setup.execute("PRAGMA journal_mode=WAL")
    reader = sqlite3.connect(path, autocommit=False, timeout=5)
    writer = sqlite3.connect(path, autocommit=False, timeout=5)
    try:
        reader.execute("SELECT count(*) FROM settings").fetchone()
        writer.execute("CREATE TABLE snapshot_probe (n INTEGER)")
        writer.commit()
        with pytest.raises(sqlite3.OperationalError) as caught:
            reader.execute("UPDATE settings SET value_json='{}' WHERE key='other'")
        assert caught.value.sqlite_errorcode == sqlite3.SQLITE_BUSY_SNAPSHOT
    finally:
        reader.close()
        writer.close()


def test_write_transaction_acquires_lock_before_read(migrated):
    engine = build_engine(migrated)
    factory = session_factory(engine)
    with factory.begin() as session:
        session.add(Setting(key="counter", value_json={"n": 0}))
    attempting, finished = threading.Event(), threading.Event()

    def other_writer():
        attempting.set()
        with factory.begin() as session:
            row = session.scalar(select(Setting).where(Setting.key == "counter"))
            row.value_json = {"n": row.value_json["n"] + 1}
        finished.set()

    try:
        with ThreadPoolExecutor(1) as pool:
            with factory.begin() as session:
                row = session.scalar(select(Setting).where(Setting.key == "counter"))
                future = pool.submit(other_writer)
                assert attempting.wait(10)
                # Baseline deferred transactions have acquired no writer lock yet.
                assert session.connection().connection.driver_connection.in_transaction
                raw = session.connection().connection.driver_connection
                probe = sqlite3.connect(str(migrated.database_path), timeout=0, autocommit=True)
                try:
                    with pytest.raises(sqlite3.OperationalError):
                        probe.execute("BEGIN IMMEDIATE")
                finally:
                    probe.close()
                assert raw.in_transaction and not finished.is_set()
                row.value_json = {"n": row.value_json["n"] + 1}
            future.result(10)
        with factory() as session:
            assert session.scalar(select(Setting).where(Setting.key == "counter")).value_json == {
                "n": 2
            }
    finally:
        engine.dispose()


def test_scheduler_waits_for_temporary_writer(migrated, monkeypatch):
    engine = build_engine(migrated)
    factory = session_factory(engine)
    # Populate the pool before taking the lock so connect PRAGMAs are excluded.
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA busy_timeout=1")
    scheduler = Scheduler(factory, migrated)
    for name in INTERVALS:
        setattr(migrated, "scheduler_" + name + "_enabled", False)
    holder = sqlite3.connect(str(migrated.database_path), autocommit=True)
    holder.execute("BEGIN IMMEDIATE")
    released = threading.Event()

    # Retrying lock acquisition must leave the failed transaction before retrying.
    def release(_delay):
        holder.execute("COMMIT")
        released.set()

    monkeypatch.setattr("time.sleep", release)
    try:
        scheduler.tick()
        assert released.is_set()
        with factory() as session:
            assert session.scalar(select(Setting).where(Setting.key == "scheduler.heartbeat"))
    finally:
        holder.close()
        engine.dispose()


def test_scheduler_with_three_writers_300_ticks(migrated, monkeypatch):
    engine = build_engine(migrated)
    factory = session_factory(engine)
    with factory.begin() as session:
        session.add(Setting(key="pressure", value_json={"n": 0}))
    for name in INTERVALS:
        setattr(migrated, "scheduler_" + name + "_enabled", False)
    scheduler = Scheduler(factory, migrated)
    migrated.scheduler_metrics_enabled = True
    assert scheduler.claim("metrics")
    competitor = Scheduler(factory, migrated)

    class Running:
        def is_alive(self):
            return True

    scheduler.running["metrics"] = Running()
    gate = threading.Barrier(4)

    def writer():
        gate.wait(10)
        for _ in range(100):
            with factory.begin() as session:
                row = session.scalar(select(Setting).where(Setting.key == "pressure"))
                row.value_json = {"n": row.value_json["n"] + 1}

    try:
        with ThreadPoolExecutor(3) as pool:
            futures = [pool.submit(writer) for _ in range(3)]
            gate.wait(10)
            for _ in range(300):
                scheduler.tick()
                assert not competitor.claim("metrics")
            for future in futures:
                future.result(20)
        with factory() as session:
            assert session.scalar(select(Setting).where(Setting.key == "pressure")).value_json == {
                "n": 300
            }
            state = session.scalar(
                select(Setting).where(Setting.key == "scheduler.job.metrics")
            ).value_json
            assert state["owner"] == scheduler.owner and state["lease_until"] > 0
    finally:
        engine.dispose()


def short_timeout(engine):
    @event.listens_for(engine, "checkout")
    def configure(connection, _record, _proxy):
        connection.execute("PRAGMA busy_timeout=1")


@pytest.mark.parametrize("persistent", [False, True])
def test_script_edit_save_contention(stage, monkeypatch, persistent):
    report_id = complete(stage, monkeypatch)
    with stage.factory.begin() as session:
        row = VideoScript(
            brand_id=stage.brand, report_id=report_id, topic_index=0, title="服務前確認",
            content_json=script_content(), review_json={}, provider="agent", model="test",
        )
        session.add(row)
        session.flush()
        video_scripts.snapshot(session, row, "test")
        script_id = row.id
    short_timeout(stage.factory.kw["bind"])
    holder = sqlite3.connect(str(stage.settings.database_path), autocommit=True)
    original = video_scripts.review

    def review(*args, **kwargs):
        checked = original(*args, **kwargs)
        holder.execute("BEGIN IMMEDIATE")
        return checked

    def release(_delay):
        if not persistent:
            holder.execute("COMMIT")

    monkeypatch.setattr(video_scripts, "review", review)
    monkeypatch.setattr(db.time, "sleep", release)
    body = EditScript(version=1, content=script_content())
    try:
        with stage.factory() as session:
            if persistent:
                with pytest.raises(HTTPException) as caught:
                    video_scripts.edit(
                        access(stage, session), script_id, body, stage.factory, stage.settings
                    )
                assert caught.value.status_code == 503
                assert "稍後重試" in caught.value.detail
            else:
                result = video_scripts.edit(
                    access(stage, session), script_id, body, stage.factory, stage.settings
                )
                assert result["content"] == script_content() and result["version"] == 2
        holder.rollback()
        with stage.factory() as session:
            assert session.get(VideoScript, script_id).version == (1 if persistent else 2)
    finally:
        holder.close()


@pytest.mark.parametrize("persistent", [False, True])
def test_generated_ideas_save_contention(stage, monkeypatch, persistent):
    report_id = queued(stage)
    short_timeout(stage.factory.kw["bind"])
    holder = sqlite3.connect(str(stage.settings.database_path), autocommit=True)
    calls = []

    def model(task, prompt, trigger, **kwargs):
        calls.append(1)
        payload = json.loads(prompt)
        result = providers.Result(
            text=json.dumps(idea_payload(payload["evidence"]), ensure_ascii=False), model="test"
        )
        holder.execute("BEGIN IMMEDIATE")
        return result

    monkeypatch.setattr(ai, "run", model)

    def release(_delay):
        if not persistent:
            holder.execute("COMMIT")

    monkeypatch.setattr(db.time, "sleep", release)
    try:
        ideation.process(stage.factory, stage.settings, report_id)
        assert calls == [1]
        with stage.factory() as session:
            row = session.get(IdeationReport, report_id)
            if persistent:
                result = ideation.view(row, settings=stage.settings, session=session)
                assert ideation.storage_failed(stage.settings, row)
                assert result["status"] == "processing"
                assert result["can_retry"] and "稍後重試" in result["error"]
                holder.execute("ROLLBACK")
                retried = ideation.retry(access(stage, session), report_id, stage.settings)
                assert retried["status"] == "pending"
                assert not ideation.storage_failed(stage.settings, row)
            else:
                assert row.status == "ready" and row.data_json["ideas"]
    finally:
        holder.close()


def test_ai_usage_record_contention_preserves_api_result(stage, monkeypatch):
    from pydantic import SecretStr

    stage.settings.gemini_api_key = SecretStr("isolated-test-key")
    stage.settings.gemini_model = "mock"
    stage.settings.gemini_paid_tier = True
    short_timeout(stage.factory.kw["bind"])
    holder = sqlite3.connect(str(stage.settings.database_path), autocommit=True)
    calls = []

    def model(*args):
        calls.append(1)
        holder.execute("BEGIN IMMEDIATE")
        return providers.Result(text="isolated generated result", model="mock")

    monkeypatch.setattr(providers, "call_api", model)
    monkeypatch.setattr(db.time, "sleep", lambda _: holder.execute("COMMIT"))
    try:
        result = ai.run(
            "video_script",
            "isolated prompt",
            "manual",
            factory=stage.factory,
            settings=stage.settings,
            brand_id=stage.brand,
            provider="gemini_api",
        )
        assert result.text == "isolated generated result" and calls == [1]
        with stage.factory() as session:
            assert session.scalar(select(func.count(AIRun.id))) == 1
    finally:
        holder.close()


@pytest.mark.parametrize("worker_name", ["scheduler", "receive_health"])
@pytest.mark.parametrize("locked", [False, True])
def test_background_failure_logs_safe_fields(migrated, monkeypatch, caplog, worker_name, locked):
    monkeypatch.setattr(logging.getLogger("mwb"), "propagate", True)
    raw = sqlite3.OperationalError("private exception contents")
    raw.sqlite_errorcode = sqlite3.SQLITE_BUSY_SNAPSHOT
    error = (
        OperationalError("private SQL", {"secret": "private params"}, raw)
        if locked
        else (ValueError("private exception contents"))
    )

    class Stop:
        stopped = False

        def is_set(self):
            return self.stopped

        def wait(self, _delay):
            return self.stopped

    if worker_name == "scheduler":
        worker = Scheduler(None, migrated)
        worker.wake.set()
        module, method = worker, "tick"
        expected = "scheduler_tick_failed"
    elif worker_name == "receive_health":
        worker = receive_health.ReceiveHealthWorker(None, migrated)
        module, method = receive_health, "check"
        expected = "receive_health_check_failed"
    worker.stop = Stop()

    def fail(*args):
        worker.stop.stopped = True
        raise error

    monkeypatch.setattr(module, method, fail)
    with caplog.at_level(logging.ERROR):
        worker.run()
    record = next(r for r in caplog.records if r.msg == expected)
    output = JsonFormatter().format(record)
    entry = json.loads(output)
    assert entry["error_type"] == type(error).__name__
    if locked:
        assert entry["error_code"] == "database_locked"
        assert entry["sqlite_errorcode"] == sqlite3.SQLITE_BUSY_SNAPSHOT
    else:
        assert "error_code" not in entry
    assert "private" not in output and "secret" not in output
    assert error_fields(error)["error_type"] == type(error).__name__


def test_long_write_logs_thread_and_caller(migrated, monkeypatch, caplog):
    from app.services.scheduler import Scheduler

    engine = build_engine(migrated)
    factory = session_factory(engine)
    ticks = iter([0.0, 3.0, 10.0, 10.5])
    monkeypatch.setattr(db.time, "monotonic", lambda: next(ticks))
    with caplog.at_level(logging.WARNING, logger="mwb.db"):
        # 第一個是寫入交易（佔用 3 秒）；第二個是只讀交易（0.5 秒），不應記錄。
        Scheduler(factory, migrated).request("metrics")
        with factory() as session:
            session.scalar(select(func.count()).select_from(Setting))
            session.commit()
    held = [r for r in caplog.records if r.msg == "database_write_held"]
    assert len(held) == 1
    entry = json.loads(JsonFormatter().format(held[0]))
    assert entry["caller"] == "services.scheduler:request"
    assert entry["thread_name"] == threading.current_thread().name
    assert entry["held_ms"] == 3000 and entry["immediate"] is True
    assert set(entry) == {
        "at",
        "level",
        "logger",
        "event",
        "thread_name",
        "caller",
        "held_ms",
        "immediate",
    }
    engine.dispose()

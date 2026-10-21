"""Retired DM contracts and destructive purge tested only against synthetic SQLite."""

import json
import sqlite3

import pytest
from message_fixtures import send_data as send_data
from purge_direct_messages import purge, raw_kind

from app.models import (
    Account,
    AuditLog,
    Brand,
    Classification,
    Contact,
    Draft,
    IdeationReport,
    InboundJob,
    LineReplyCredential,
    Message,
    Notification,
    NotificationDelivery,
    Post,
    RawEvent,
    SendAttempt,
    Setting,
    Staff,
    Thread,
    TopicAnnotation,
)
from app.models.base import utc_now
from app.services.gateway_workers import Workers
from app.services.scheduler import INTERVALS


def assert_retired(client):
    assert "dm" not in INTERVALS
    assert not hasattr(Workers, "dm")
    paths = set(client.app.openapi()["paths"])
    assert not any("/dm/" in p for p in paths)
    for _method, path in [
        ("GET", "/api/dm/backfill"),
        *[("POST", "/api/dm/backfill/" + op) for op in ("start", "pause", "resume", "restart")],
        *[("POST", "/api/ingest/dm/" + op) for op in ("events", "claim", "checkpoint", "finish")],
    ]:
        # An authenticated unknown path is always absent from the routing table.
        assert path not in paths
    from fastapi import HTTPException

    from app.services import ingest

    before = snapshot(client.app.state.settings.database_path)
    for platform in ("line", "facebook", "instagram"):
        for source in ("history", "webhook"):
            with client.app.state.session_factory() as session:
                with pytest.raises(HTTPException) as error:
                    ingest.events(
                        session,
                        json.dumps({"platform": platform, "messages": [{"kind": "dm"}]}).encode(),
                        source,
                    )
                assert error.value.status_code == 410
    assert snapshot(client.app.state.settings.database_path) == before


def test_retired_contracts(client, send_data):
    assert_retired(client)
    before = snapshot(client.app.state.settings.database_path)
    for method, path in [
        ("GET", "/api/dm/backfill"),
        *[("POST", "/api/dm/backfill/" + op) for op in ("start", "pause", "resume", "restart")],
        *[("POST", "/api/ingest/dm/" + op) for op in ("events", "claim", "checkpoint", "finish")],
    ]:
        assert client.request(method, path).status_code == 404
    assert client.get(f"/api/threads/{send_data['thread']}").status_code == 404
    assert client.get(f"/api/contacts/{send_data['contact']}").status_code == 404
    assert client.get("/api/threads").json() == []
    assert client.get(f"/api/classifications/messages/{send_data['message']}").status_code == 404
    assert client.post(f"/api/classifications/messages/{send_data['message']}").status_code == 404
    assert snapshot(client.app.state.settings.database_path) == before


def test_legacy_dm_classification_jobs_are_not_claimed(client, send_data):
    from sqlalchemy import select

    from app.services import classify

    factory = send_data["factory"]
    with factory.begin() as session:
        session.add(InboundJob(message_id=send_data["message"], task="classify"))
    assert classify.claim(factory) is None
    with factory() as session:
        job = session.scalar(select(InboundJob))
        assert job.status == "pending" and job.attempts == 0


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"entry": [{"messaging": [{"message": {"mid": "x"}}]}]}, "dm"),
        ({"events": [{"type": "message", "source": {"type": "user"}}]}, "dm"),
        ({"message": {"kind": "dm"}}, "dm"),
        ({"messages": [{"kind": "dm"}, {"kind": "comment_thread"}]}, None),
        ({"messages": [{"kind": "dm"}, 0]}, None),
        (
            {"payload": {"messages": [{"kind": "dm"}]}, "messages": [{"kind": "comment_thread"}]},
            None,
        ),
        ({"unknown": True}, None),
    ],
)
def test_purge_raw_source_evidence(payload, expected):
    assert raw_kind(payload) == expected


@pytest.fixture
def mixed(client, settings):
    now = utc_now()
    factory = client.app.state.session_factory
    with factory.begin() as s:
        brand = Brand(slug="purge", name="isolated")
        s.add(brand)
        s.flush()
        account = Account(
            brand_id=brand.id, platform="facebook", external_id="purge", name="isolated"
        )
        contacts = [
            Contact(
                brand_id=brand.id, platform="facebook", external_id=str(i), display_name="isolated"
            )
            for i in (11, 22, 33)
        ]
        s.add_all([account, *contacts])
        s.flush()
        post = Post(
            account_id=account.id,
            external_id="post",
            caption="retain",
            media_type="text",
            published_at=now,
        )
        s.add(post)
        s.flush()
        threads = []
        messages = []
        for i, (kind, contact) in enumerate(
            [
                ("dm", contacts[0]),
                ("dm", contacts[1]),
                ("comment_thread", contacts[1]),
                ("comment_thread", contacts[2]),
            ]
        ):
            thread = Thread(
                brand_id=brand.id,
                account_id=account.id,
                external_id=str(i),
                kind=kind,
                contact_id=contact.id,
                post_id=post.id if kind == "comment_thread" else None,
            )
            s.add(thread)
            s.flush()
            threads.append(thread)
            message = Message(
                thread_id=thread.id,
                contact_id=contact.id,
                external_id=str(i),
                direction="in",
                author_type="fan",
                text="isolated",
                sent_at=now,
            )
            s.add(message)
            s.flush()
            messages.append(message)
            s.add_all(
                [
                    Classification(
                        message_id=message.id,
                        engine="keyword",
                        intent="other",
                        sentiment="neutral",
                        sensitive=False,
                        action="classified",
                        confidence=1,
                    ),
                    TopicAnnotation(
                        message_id=message.id,
                        brand_id=brand.id,
                        input_hash="x",
                        topic="isolated",
                        is_question=True,
                        pain=0,
                        method="keyword",
                        result_json={},
                    ),
                    InboundJob(message_id=message.id, task="classify"),
                ]
            )
        delivery = NotificationDelivery(
            brand_id=brand.id,
            retry_key="purge",
            recipient="isolated",
            messages_json=[{"text": "dm"}],
            next_attempt_at=now,
        )
        s.add(delivery)
        s.flush()
        for t, m in zip(threads, messages, strict=True):
            s.add(
                Notification(
                    brand_id=brand.id,
                    thread_id=t.id,
                    message_id=m.id,
                    kind="urgent",
                    reason="complaint",
                    due_at=now,
                    delivery_id=delivery.id,
                )
            )
        s.add(Draft(thread_id=threads[0].id, text="legacy", provider="none", model="none"))
        operator = Staff(
            username="purge", display_name="isolated", role="admin", password_hash="unused"
        )
        s.add(operator)
        s.flush()
        s.add(
            SendAttempt(
                key="purge",
                thread_id=threads[0].id,
                staff_id=operator.id,
                text="legacy",
                target="isolated",
                target_name="isolated",
                context_hash="x",
                review_json={},
                mode="manual",
                expires_at=now,
            )
        )
        s.add(
            LineReplyCredential(
                message_id=messages[0].id, encrypted_token="unused", received_at=now
            )
        )
        s.add(Setting(key="purge.keep", value_json={"keep": True}))
        s.add(AuditLog(actor="test", action="keep", target_type="thread", target_id=threads[0].id))
        s.add(
            IdeationReport(
                brand_id=brand.id,
                meeting_at=now,
                start_at=now,
                end_at=now,
                trigger="manual",
                provider="test",
                status="completed",
                data_json={"quotes": [{"id": messages[0].id, "text": "retained report"}]},
            )
        )
        for payload in [
            {"messages": [{"kind": "dm"}]},
            {"messages": [{"kind": "comment_thread"}]},
            {
                "entry": [
                    {"messaging": [{"message": {"mid": "x"}}], "changes": [{"field": "comments"}]}
                ]
            },
            {"unrecognized": True},
        ]:
            s.add(RawEvent(signature_ok=True, payload_json=payload))
        s.flush()
        keep = {t.id for t in threads[2:]}
        dm_ids = [t.id for t in threads[:2]]
    folder = settings.export_root / "purge/users/facebook"
    folder.mkdir(parents=True)
    files = [
        folder / "11_isolated.md",
        folder / "22_isolated.md",
        folder / "33_isolated.docx",
        folder / f"對話_{dm_ids[0]}_20261001_010101_000000.docx",
    ]
    for p in files:
        p.write_text("isolated", encoding="utf-8")
    report = settings.export_root / "purge/ideation/report.md"
    report.parent.mkdir()
    report.write_text("keep", encoding="utf-8")
    return settings, keep, files, report


def snapshot(path):
    with sqlite3.connect(path) as db:
        return "\n".join(db.iterdump())


def test_purge_dry_run_apply_idempotent(mixed):
    settings, keep, files, report = mixed
    before = snapshot(settings.database_path)
    with sqlite3.connect(settings.database_path) as db:
        predicates = {
            "threads": "kind='comment_thread'",
            "messages": "thread_id IN (SELECT id FROM threads WHERE kind='comment_thread')",
            "posts": "1",
            "settings": "1",
            "ideation_reports": "1",
            "contacts": "external_id IN ('22','33')",
        }
        preserved = {
            table: db.execute(f"SELECT * FROM {table} WHERE {where}").fetchall()
            for table, where in predicates.items()
        }
    preview = purge(settings.database_path, settings.export_root)
    assert preview["counts"]["threads"] == 2
    assert preview["counts"]["contacts"] == 1
    assert len(preview["uncertain_raw_event_ids"]) == 2
    assert set(preview["files"]) == {str(files[0]), str(files[3])}
    assert snapshot(settings.database_path) == before
    assert all(p.exists() for p in files)
    result = purge(settings.database_path, settings.export_root, True)
    assert result["counts"] == preview["counts"]
    assert not files[0].exists() and not files[3].exists()
    assert files[1].exists() and files[2].exists() and report.exists()
    with sqlite3.connect(settings.database_path) as db:
        for table, where in predicates.items():
            assert db.execute(f"SELECT * FROM {table} WHERE {where}").fetchall() == preserved[table]
        for table in (
            "drafts",
            "line_reply_credentials",
            "send_attempts",
            "notification_deliveries",
        ):
            assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert {r[0] for r in db.execute("SELECT id FROM threads")} == keep
        assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 2
        for table in (
            "classifications",
            "topic_annotations",
            "inbound_jobs",
            "notifications",
            "contacts",
        ):
            assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM ideation_reports").fetchone()[0] == 1
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        audit = json.loads(
            db.execute("SELECT detail_json FROM audit_log WHERE action='data.purge_dm'").fetchone()[
                0
            ]
        )
        assert all(type(v) is int for v in audit.values())
        assert db.execute("SELECT COUNT(*) FROM audit_log WHERE action='keep'").fetchone()[0] == 1
    stable = snapshot(settings.database_path)
    again = purge(settings.database_path, settings.export_root, True)
    assert not any(again["counts"].values()) and again["files"] == []
    assert snapshot(settings.database_path) == stable


def test_purge_file_failure_rolls_back(mixed, monkeypatch):
    from pathlib import Path

    settings, _, files, _ = mixed
    before = snapshot(settings.database_path)
    original = Path.unlink

    def fail(path, *args, **kwargs):
        if path == files[3]:
            raise PermissionError("isolated failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail)
    with pytest.raises(PermissionError):
        purge(settings.database_path, settings.export_root, True)
    assert snapshot(settings.database_path) == before
    assert all(p.read_text(encoding="utf-8") == "isolated" for p in files)

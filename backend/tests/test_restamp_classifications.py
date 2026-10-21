import copy

import pytest
from restamp_classifications import restamp
from sqlalchemy import event, select

from app.db import build_engine, session_factory
from app.models import Account, AuditLog, Brand, Classification, Message, PromptVersion, Thread
from app.models.base import utc_now
from app.services import classify, prompts


@pytest.fixture
def records(migrated):
    engine = build_engine(migrated)
    factory = session_factory(engine)
    with factory.begin() as session:
        brand = Brand(slug="restamp", name="isolated")
        session.add(brand)
        session.flush()
        account = Account(brand_id=brand.id, platform="facebook", external_id="test", name="test")
        session.add(account)
        session.flush()
        thread = Thread(brand_id=brand.id, account_id=account.id, external_id="test", kind="dm")
        session.add(thread)
        session.flush()
        for bid in (None, brand.id):
            session.add(PromptVersion(
                scope=prompts.scope(bid), task=prompts.TASK, brand_id=bid,
                revision=10, content=f"old {bid}", actor="test",
            ))
        session.flush()
        legacy = {**prompts.context(session, brand.id), "thread_kind": "dm"}
        for index in range(3):
            message = Message(thread_id=thread.id, external_id=str(index), direction="in",
                              author_type="fan", text="price?", sent_at=utc_now())
            session.add(message)
            session.flush()
            session.add(Classification(
                message_id=message.id, engine="keyword", intent="price", sentiment="neutral",
                action="classified", sensitive=False, confidence=1,
                input_hash=classify.fingerprint(message.text, legacy) if index < 2 else "stale",
            ))
        # Current prompts differ; the explicitly chosen historical revisions must be used.
        for bid in (None, brand.id):
            session.add(PromptVersion(
                scope=prompts.scope(bid), task=prompts.TASK, brand_id=bid,
                revision=11, content="new", actor="test",
            ))
    yield migrated.database_path, factory
    engine.dispose()


def snapshot(factory):
    with factory() as session:
        rows = [
            {c.name: copy.deepcopy(getattr(row, c.name)) for c in row.__table__.columns}
            for row in session.scalars(select(Classification).order_by(Classification.id))
        ]
        audits = list(session.scalars(select(AuditLog).where(
            AuditLog.action == "classification.restamp"
        )))
        return rows, audits


def test_restamp_dry_run_matches_historical_revisions_without_writes(records):
    path, factory = records
    before = snapshot(factory)
    assert restamp(path, 10, 10) == {"total": 3, "matched": 2, "updated": 0, "unmatched": 1}
    assert snapshot(factory) == before


def test_restamp_only_matches_changes_hash_and_is_idempotent(records):
    path, factory = records
    before, _ = snapshot(factory)
    assert restamp(path, 10, 10, apply=True) == {
        "total": 3, "matched": 2, "updated": 2, "unmatched": 1
    }
    after, audits = snapshot(factory)
    assert len(audits) == 2
    assert {a.target_id for a in audits} == {before[0]["id"], before[1]["id"]}
    for old, new in zip(before, after, strict=True):
        if old["input_hash"] != "stale":
            expected = classify.fingerprint("price?", {"thread_kind": "dm"})
            assert new == old | {"input_hash": expected}
        else:
            assert new == old
    assert restamp(path, 10, 10, apply=True) == {
        "total": 3, "matched": 0, "updated": 0, "unmatched": 3
    }
    assert snapshot(factory)[0] == after
    assert len(snapshot(factory)[1]) == 2


def test_restamp_missing_revision_aborts_without_changes(records):
    path, factory = records
    before = snapshot(factory)
    with pytest.raises(ValueError, match="Missing prompt revision"):
        restamp(path, 99, 10, apply=True)
    assert snapshot(factory) == before


def test_restamp_single_immediate_transaction_rolls_back_on_failure(records, monkeypatch):
    import restamp_classifications as tool
    path, factory = records
    before = snapshot(factory)
    statements = []
    original_create = tool.create_engine

    def engine_with_failure(*args, **kwargs):
        engine = original_create(*args, **kwargs)

        @event.listens_for(engine, "before_cursor_execute")
        def inspect(conn, cursor, statement, params, context, many):
            statements.append(statement)
            if statement.startswith("INSERT INTO audit_log"):
                raise RuntimeError("audit unavailable")
        return engine

    monkeypatch.setattr(tool, "create_engine", engine_with_failure)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        restamp(path, 10, 10, apply=True)
    assert statements[0] == "BEGIN IMMEDIATE"
    assert statements.count("BEGIN IMMEDIATE") == 1
    assert snapshot(factory) == before


def test_restamp_refuses_missing_database(tmp_path):
    path = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError):
        restamp(path, 0, 0, apply=True)
    assert not path.exists()

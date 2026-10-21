from datetime import UTC, datetime, timedelta, timezone

import pytest
from alembic import command
from alembic.config import Config
from conftest import seed_records
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm.exc import StaleDataError

from app.config import REPO_ROOT
from app.db import build_engine, session_factory
from app.models import (
    Account,
    Base,
    Brand,
    Classification,
    Contact,
    Message,
    Post,
    RawEvent,
    Thread,
)


@pytest.fixture
def database(migrated):
    engine = build_engine(migrated)
    factory = session_factory(engine)
    try:
        with factory.begin() as session:
            seed_records(session, migrated)
        yield factory
    finally:
        engine.dispose()


@pytest.mark.migration
def test_all_tables_and_migration_round_trip(settings):
    configuration = Config(str(REPO_ROOT / "backend" / "alembic.ini"))
    command.upgrade(configuration, "head")
    engine = build_engine(settings)
    try:
        assert set(inspect(engine).get_table_names()) == set(Base.metadata.tables) | {
            "alembic_version"
        }
        with session_factory(engine).begin() as session:
            seed_records(session, settings)
    finally:
        engine.dispose()
    command.check(configuration)
    command.downgrade(configuration, "base")
    engine = build_engine(settings)
    try:
        assert inspect(engine).get_table_names() == ["alembic_version"]
    finally:
        engine.dispose()
    command.upgrade(configuration, "head")
    engine = build_engine(settings)
    try:
        assert set(inspect(engine).get_table_names()) == set(Base.metadata.tables) | {
            "alembic_version"
        }
    finally:
        engine.dispose()


@pytest.mark.migration
def test_ingest_migration_preserves_existing_foreign_key_references(database):
    configuration = Config(str(REPO_ROOT / "backend" / "alembic.ini"))
    with database.begin() as session:
        message = session.scalar(select(Message).order_by(Message.id))
        message_id = message.id
        session.add(
            Classification(
                message_id=message_id,
                engine="keyword",
                intent="other",
                sentiment="neutral",
                sensitive=False,
                action="human",
                confidence=0.5,
            )
        )
        session.add(RawEvent(platform="line", signature_ok=True, payload_json={"test": True}))
    command.downgrade(configuration, "0003")
    command.upgrade(configuration, "head")
    with database() as session:
        assert session.scalar(select(Classification)).message_id == message_id
        assert session.get(Message, message_id).text.startswith("[隔離測試]")
        assert session.scalar(select(RawEvent)).payload_json == {"test": True}
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []


@pytest.mark.migration
def test_ingest_downgrade_refuses_to_discard_unknown_platform_events(database):
    configuration = Config(str(REPO_ROOT / "backend" / "alembic.ini"))
    with database.begin() as session:
        previous_revision = session.scalar(text("SELECT version_num FROM alembic_version"))
        session.add(RawEvent(platform=None, signature_ok=False, payload_json={"test": True}))
    with pytest.raises(RuntimeError, match="無法無損降回"):
        command.downgrade(configuration, "0003")
    with database() as session:
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == previous_revision
        assert session.scalar(select(RawEvent)).payload_json == {"test": True}
        assert "inbound_jobs" in inspect(session.connection()).get_table_names()


@pytest.mark.parametrize("kind", ["contact", "post", "message", "thread"])
def test_external_identity_unique_constraints(database, kind):
    with database() as session:
        if kind == "contact":
            original = session.scalar(select(Contact))
            duplicate = Contact(
                platform=original.platform,
                brand_id=original.brand_id,
                external_id=original.external_id,
                display_name="測試重複",
            )
        elif kind == "post":
            original = session.scalar(select(Post))
            duplicate = Post(
                account_id=original.account_id,
                external_id=original.external_id,
                media_type="video",
                published_at=original.published_at,
            )
        elif kind == "thread":
            original = session.scalar(select(Thread))
            duplicate = Thread(
                brand_id=original.brand_id,
                account_id=original.account_id,
                external_id=original.external_id,
                kind=original.kind,
            )
        else:
            original = session.scalar(select(Message))
            duplicate = Message(
                thread_id=original.thread_id,
                external_id=original.external_id,
                direction="in",
                author_type="fan",
                text="測試重複",
                sent_at=original.sent_at,
            )
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            session.flush()


def test_foreign_key_prevents_cross_brand_thread(database):
    with database() as session:
        account = session.scalar(select(Account))
        other_brand = Brand(slug="other-test", name="其他測試品牌")
        session.add(other_brand)
        session.flush()
        session.add(
            Thread(
                brand_id=other_brand.id, account_id=account.id, kind="dm", external_id="cross-brand"
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()


def test_utc_storage_roundtrip_and_naive_time_rejection(database):
    with database.begin() as session:
        message = session.scalar(select(Message))
        message.sent_at = datetime(2026, 9, 25, 12, tzinfo=timezone(timedelta(hours=8)))
        message_id = message.id
    with database() as session:
        message = session.get(Message, message_id)
        assert message.sent_at == datetime(2026, 9, 25, 4, tzinfo=UTC)
        stored = (
            session.connection()
            .exec_driver_sql("SELECT sent_at FROM messages WHERE id = ?", (message_id,))
            .scalar_one()
        )
        assert stored == "2026-09-25T04:00:00.000000+00:00"
        message.sent_at = datetime(2026, 9, 25, 12)
        with pytest.raises(StatementError):
            session.flush()


def test_optimistic_lock_rejects_stale_edits(database):
    with database() as first, database() as second:
        current = first.scalar(select(Thread))
        stale = second.get(Thread, current.id)
        second.commit()
        current.status = "in_progress"
        first.commit()
        stale.status = "closed"
        with pytest.raises(StaleDataError):
            second.commit()



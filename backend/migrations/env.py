import sqlite3

from alembic import context

from app.config import Settings
from app.db import build_engine
from app.models import Base
from app.models.base import UTCDateTime

target_metadata = Base.metadata


def render_item(type_, obj, _autogen_context):
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "sa.String(length=32)"
    return False


def run_migrations_offline() -> None:
    context.configure(
        url="sqlite://", target_metadata=target_metadata, literal_binds=True, render_as_batch=True
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = build_engine(Settings())
    try:
        with engine.connect() as connection:
            # SQLite 重建被外鍵引用的表時需暫停此連線的檢查；提交前驗證全部關係。
            raw = connection.connection.driver_connection
            raw.autocommit = True
            raw.execute("PRAGMA foreign_keys=OFF")
            # build_engine now owns BEGIN; keep FK setup outside that transaction.
            raw.autocommit = sqlite3.LEGACY_TRANSACTION_CONTROL
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,
                transactional_ddl=True,
                render_item=render_item,
            )
            with context.begin_transaction():
                context.run_migrations()
                if connection.exec_driver_sql("PRAGMA foreign_key_check").first():
                    raise RuntimeError("Migration 產生不一致的外鍵關係，已回滾")
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

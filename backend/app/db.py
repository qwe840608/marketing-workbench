import logging
import sqlite3
import threading
import time
import traceback
from collections.abc import Iterator

from fastapi import HTTPException, Request
from sqlalchemy import URL, Engine, create_engine, event
from sqlalchemy.orm import Session, SessionTransactionOrigin, sessionmaker

from app.config import Settings
from app.logging_config import error_fields

LOCK_ATTEMPTS = 3
LOCK_RETRY_DELAYS = (0.05, 0.15)
LOCK_DETAIL = "資料庫忙碌，暫時無法儲存，請稍後重試（database_locked）"
# 寫入交易佔用超過此秒數就記錄來源，用來找出讓其他寫入等待的程式。
WRITE_HELD_WARNING_SECONDS = 2
logger = logging.getLogger("mwb.db")


def caller():
    # 只記模組與函式名稱，不記參數、SQL 或檔案路徑。
    for frame in reversed(traceback.extract_stack()[:-1]):
        name = frame.filename.replace("\\", "/")
        if "/app/" in name and not name.endswith(("/app/db.py", "/app/logging_config.py")):
            return (
                name.rsplit("/app/", 1)[1].removesuffix(".py").replace("/", ".") + ":" + frame.name
            )
    return "unknown"


def lock_context():
    return {"thread_name": threading.current_thread().name, "caller": caller()}


class DatabaseBusy(HTTPException):
    def __init__(self):
        super().__init__(503, LOCK_DETAIL, headers={"Retry-After": "1"})


def begin_write(connection):
    # Only lock acquisition is replayed: no SQL, model, or outbound action has run yet.
    for attempt in range(LOCK_ATTEMPTS):
        try:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            return
        except Exception as error:
            fields = error_fields(error)
            if fields.get("error_code") != "database_locked":
                raise
            context = lock_context()
            logger.warning(
                "database_lock_retry", extra={**fields, **context, "attempt": attempt + 1}
            )
            if attempt + 1 == LOCK_ATTEMPTS:
                logger.error("database_lock_exhausted", extra={**fields, **context})
                raise DatabaseBusy() from None
            time.sleep(LOCK_RETRY_DELAYS[attempt])


class WorkbenchSession(Session):
    def get_bind(self, *args, **kwargs):
        bind = super().get_bind(*args, **kwargs)
        transaction = self.get_transaction()
        if isinstance(bind, Engine) and transaction is not None:
            write = transaction.origin == SessionTransactionOrigin.BEGIN
            binds = self.info.setdefault("transaction_binds", {})
            if (bind, write) not in binds:
                binds[bind, write] = bind.execution_options(sqlite_write=write)
            return binds[bind, write]
        return bind


def ensure_write(session: Session):
    """End a clean read scope before starting a write scope; revalidate under its lock."""
    transaction = session.get_transaction()
    if transaction is not None and transaction.origin == SessionTransactionOrigin.BEGIN:
        return
    if session.new or session.dirty or session.deleted:
        raise RuntimeError("write_scope_requires_clean_session")
    session.rollback()
    session.begin()
    session.connection()


def build_engine(settings: Settings) -> Engine:
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        URL.create("sqlite+pysqlite", database=str(settings.database_path)),
        connect_args={
            "check_same_thread": False,
            "autocommit": sqlite3.LEGACY_TRANSACTION_CONTROL,
            "isolation_level": None,
            "timeout": 5,
        },
        hide_parameters=True,
    )

    @event.listens_for(engine, "connect")
    def configure_connection(connection, _record):
        # SQLAlchemy owns BEGIN; connection setup must not leave a deferred snapshot.
        cursor = connection.cursor()
        try:
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA journal_mode=WAL")
            if cursor.fetchone()[0].lower() != "wal":
                raise RuntimeError("資料庫未啟用 WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    @event.listens_for(engine, "begin")
    def begin_transaction(connection):
        immediate = connection.get_execution_options().get("sqlite_write", False)
        if immediate:
            begin_write(connection)
        else:
            connection.exec_driver_sql("BEGIN")
        dbapi = connection.connection.dbapi_connection
        connection.info["write_watch"] = (time.monotonic(), dbapi.total_changes, immediate)

    def finish_transaction(connection):
        watch = connection.info.pop("write_watch", None)
        if watch is None:
            return
        started, changes, immediate = watch
        held = time.monotonic() - started
        wrote = immediate or connection.connection.dbapi_connection.total_changes != changes
        if wrote and held > WRITE_HELD_WARNING_SECONDS:
            logger.warning(
                "database_write_held",
                extra={**lock_context(), "held_ms": round(held * 1000), "immediate": immediate},
            )

    event.listen(engine, "commit", finish_transaction)
    event.listen(engine, "rollback", finish_transaction)

    return engine


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, class_=WorkbenchSession, expire_on_commit=False)


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session

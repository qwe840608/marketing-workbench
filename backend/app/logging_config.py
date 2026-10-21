import json
import logging
import sqlite3
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

_handler: RotatingFileHandler | None = None
_LOGGERS = (
    "mwb",
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "openai",
    "anthropic",
    "google.genai",
    "httpx",
    "httpx2",
    "httpcore",
    "mcp",
)


def error_fields(error: BaseException) -> dict:
    """Allow only type and numeric SQLite codes, never messages, SQL or parameters."""
    fields = {"error_type": type(error).__name__}
    if type(error).__name__ == "DatabaseBusy":
        fields["error_code"] = "database_locked"
    original = getattr(error, "orig", error)
    code = getattr(original, "sqlite_errorcode", None)
    if isinstance(code, int):
        fields["sqlite_errorcode"] = code
        if code & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            fields["error_code"] = "database_locked"
    return fields


def log_failure(logger_name: str, event: str, error: BaseException):
    logging.getLogger(logger_name).error(event, extra=error_fields(error))


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "at": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            # 不格式化第三方訊息與 exception，避免 URL、密碼或 SQL 參數進入日誌。
            "event": record.msg if record.name.startswith("mwb.") else "server_event",
        }
        for field in (
            "method",
            "route",
            "status",
            "duration_ms",
            "error_type",
            "error_code",
            "sqlite_errorcode",
            "attempt",
            "call_id",
            "operation",
            "usage_percent",
            "retry_at",
            "reason",
            "thread_name",
            "caller",
            "held_ms",
            "immediate",
            "path",
            "http_status",
            "meta_code",
            "meta_subcode",
            "meta_type",
            "meta_message",
            "fbtrace_id",
        ):
            if hasattr(record, field):
                entry[field] = getattr(record, field)
        if record.name == "uvicorn.access":
            entry["event"] = "http_access"
            if isinstance(record.args, tuple) and len(record.args) == 5:
                entry.update(method=record.args[1], status=record.args[4])
        if record.exc_info and record.exc_info[0]:
            entry["error_type"] = record.exc_info[0].__name__
        return json.dumps(entry, ensure_ascii=False)


def configure_logging(path: Path) -> None:
    global _handler
    if _handler is not None:
        for name in _LOGGERS:
            logging.getLogger(name).removeHandler(_handler)
        _handler.close()
    path.parent.mkdir(parents=True, exist_ok=True)
    _handler = RotatingFileHandler(path, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    _handler.setFormatter(JsonFormatter())
    for name in _LOGGERS:
        logger = logging.getLogger(name)
        for previous in logger.handlers[:]:
            logger.removeHandler(previous)
        logger.addHandler(_handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False

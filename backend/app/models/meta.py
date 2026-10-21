from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime


class CommentBackfill(Base):
    __tablename__ = "comment_backfills"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), unique=True)
    window_start: Mapped[datetime] = mapped_column(UTCDateTime())
    window_end: Mapped[datetime] = mapped_column(UTCDateTime())
    discovery_completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class CommentPoll(Base):
    __tablename__ = "comment_polls"
    __table_args__ = (UniqueConstraint("account_id", "resource"),)

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id"), unique=True)
    resource: Mapped[str] = mapped_column(String(255))
    last_completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_auto_completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    manual_requested: Mapped[bool] = mapped_column(default=False, server_default="0")
    window_start: Mapped[datetime | None] = mapped_column(UTCDateTime())
    window_end: Mapped[datetime | None] = mapped_column(UTCDateTime())
    stopped_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    next_poll_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    requested_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    run_id: Mapped[str | None] = mapped_column(String(36), unique=True)
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    progress_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_error: Mapped[str | None] = mapped_column(String(40))
    backfill_id: Mapped[int | None] = mapped_column(ForeignKey("comment_backfills.id"), index=True)
    backfill_completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class MetaApiCall(Base):
    __tablename__ = "meta_api_calls"
    __table_args__ = (Index("ix_meta_api_calls_created_at", "created_at"),)

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    source: Mapped[str] = mapped_column(String(16))
    operation: Mapped[str] = mapped_column(String(24))
    resource_id: Mapped[str] = mapped_column(String(255))
    run_id: Mapped[str | None] = mapped_column(String(36))
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    http_status: Mapped[int | None]
    error_code: Mapped[int | None]
    duration_ms: Mapped[int | None]
    usage_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class DmBackfill(Base):
    __tablename__ = "dm_backfills"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), unique=True)
    window_start: Mapped[datetime | None] = mapped_column(UTCDateTime())
    window_end: Mapped[datetime] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    paused: Mapped[bool] = mapped_column(default=False)
    next_poll_at: Mapped[datetime] = mapped_column(UTCDateTime())
    run_id: Mapped[str | None] = mapped_column(String(36), unique=True)
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    progress_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_error: Mapped[str | None] = mapped_column(String(40))
    permissions_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    imported_messages: Mapped[int] = mapped_column(default=0, server_default="0")

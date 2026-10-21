from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime


class SendAttempt(Base):
    __tablename__ = "send_attempts"
    key: Mapped[str] = mapped_column(String(36), unique=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("threads.id"))
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.id"))
    text: Mapped[str] = mapped_column(Text)
    target: Mapped[str] = mapped_column(String(255))
    target_name: Mapped[str] = mapped_column(String(200))
    context_hash: Mapped[str] = mapped_column(String(64))
    review_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    mode: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="reviewing")
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class LineReplyCredential(Base):
    __tablename__ = "line_reply_credentials"
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), unique=True)
    encrypted_token: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime())
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

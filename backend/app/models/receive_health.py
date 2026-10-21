from datetime import datetime

from sqlalchemy import JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime


class ReceiveHealthCheck(Base):
    __tablename__ = "receive_health_checks"
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    healthy: Mapped[bool]
    checks_json: Mapped[dict] = mapped_column(JSON)
    transition: Mapped[str | None] = mapped_column(String(20))
    alert_status: Mapped[str] = mapped_column(String(32), default="none")


class WebhookFailure(Base):
    __tablename__ = "webhook_failures"
    __table_args__ = (UniqueConstraint("platform", "bucket_at"),)
    platform: Mapped[str] = mapped_column(String(16))
    bucket_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    count: Mapped[int] = mapped_column(default=1)

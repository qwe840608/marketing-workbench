from datetime import datetime

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime, Versioned


class TopicAnnotation(Base):
    __tablename__ = "topic_annotations"
    __table_args__ = (UniqueConstraint("message_id"),)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"))
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    input_hash: Mapped[str] = mapped_column(String(64))
    topic: Mapped[str] = mapped_column(String(80))
    is_question: Mapped[bool]
    pain: Mapped[float]
    method: Mapped[str] = mapped_column(String(20))
    result_json: Mapped[dict] = mapped_column(JSON)


class IdeationReport(Base):
    __tablename__ = "ideation_reports"
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    schedule_key: Mapped[str | None] = mapped_column(String(120), unique=True)
    meeting_at: Mapped[datetime] = mapped_column(UTCDateTime())
    start_at: Mapped[datetime] = mapped_column(UTCDateTime())
    end_at: Mapped[datetime] = mapped_column(UTCDateTime())
    trigger: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    error: Mapped[str | None] = mapped_column(String(200))
    data_json: Mapped[dict] = mapped_column(JSON, default=dict)
    export_json: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    notification_status: Mapped[str] = mapped_column(String(20), default="pending")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("staff.id"))


class VideoScript(Versioned, Base):
    __tablename__ = "video_scripts"
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("ideation_reports.id"))
    topic_index: Mapped[int]
    title: Mapped[str] = mapped_column(String(200))
    content_json: Mapped[dict] = mapped_column(JSON)
    review_json: Mapped[dict] = mapped_column(JSON)
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(120))
    export_json: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")


class ScriptVersion(Base):
    __tablename__ = "script_versions"
    __table_args__ = (UniqueConstraint("script_id", "revision"),)
    script_id: Mapped[int] = mapped_column(ForeignKey("video_scripts.id"))
    revision: Mapped[int]
    content_json: Mapped[dict] = mapped_column(JSON)
    review_json: Mapped[dict] = mapped_column(JSON)
    actor: Mapped[str] = mapped_column(Text)

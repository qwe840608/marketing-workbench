from datetime import datetime

from sqlalchemy import JSON, Column, ForeignKey, Integer, String, Table, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime, Versioned


class AICredential(Versioned, Base):
    __tablename__ = "ai_credentials"
    provider: Mapped[str] = mapped_column(String(20), unique=True)
    encrypted_key: Mapped[str] = mapped_column(Text)


class AIKeyVerification(Base):
    __tablename__ = "ai_key_verifications"
    receipt_hash: Mapped[str] = mapped_column(String(64), unique=True)
    provider: Mapped[str] = mapped_column(String(20))
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.id"))
    encrypted_key: Mapped[str] = mapped_column(Text)
    base_version: Mapped[int]
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())


class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (UniqueConstraint("scope", "task", "revision"),)
    scope: Mapped[str] = mapped_column(String(80))
    task: Mapped[str] = mapped_column(String(40))
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id"))
    revision: Mapped[int]
    content: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(120))
    restored_from: Mapped[int | None]


# Migration rollback data is part of the schema, but has no application write path.
retired_provider_settings = Table(
    "retired_provider_settings",
    Base.metadata,
    Column("key", String(120), primary_key=True),
    Column("changes_json", JSON, nullable=False),
    Column("original_version", Integer, nullable=False),
)

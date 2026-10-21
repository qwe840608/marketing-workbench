from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime, Versioned


class PublishPost(Base, Versioned):
    __tablename__ = "publish_posts"
    __table_args__ = (
        CheckConstraint("format IN ('video','image','carousel','text','story')", name="format"),
        CheckConstraint(
            "status IN ('draft','scheduled','publishing','done','partial','failed',"
            "'missed','paused','cancelled')",
            name="status",
        ),
    )
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("staff.id"))
    format: Mapped[str] = mapped_column(String(16))
    caption: Mapped[str] = mapped_column(Text, default="")
    captions_json: Mapped[dict] = mapped_column(JSON, default=dict)
    platforms_json: Mapped[list] = mapped_column(JSON, default=list)
    platform_options_json: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    # 只影響 Facebook 目標：貼文建立在粉專但不出現在粉專動態（published=false）。
    facebook_unpublished: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    locked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    source: Mapped[str] = mapped_column(String(16), default="manual")
    source_json: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    agent_publish_json: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    report_id: Mapped[int | None] = mapped_column(Integer, index=True)
    idea_index: Mapped[int | None] = mapped_column(Integer)
    # AI 文案功能已移除；欄位只為相容既有資料而保留（不做破壞性 migration），程式不再讀寫。
    caption_job_json: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")


class PublishMedia(Base):
    __tablename__ = "publish_media"
    __table_args__ = (
        CheckConstraint("role IN ('media','thumbnail','cover','fb_cover')", name="role"),
    )
    post_id: Mapped[int] = mapped_column(ForeignKey("publish_posts.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    original_name: Mapped[str] = mapped_column(String(255))
    relative_path: Mapped[str] = mapped_column(String(80), unique=True)
    mime: Mapped[str] = mapped_column(String(32))
    size: Mapped[int] = mapped_column(Integer)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    duration: Mapped[float | None] = mapped_column(Float)
    sha256: Mapped[str] = mapped_column(String(64))
    uploader_id: Mapped[int] = mapped_column(ForeignKey("staff.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # thumbnail 是 YouTube 自訂縮圖、cover 是 Instagram Reels 封面、fb_cover 是 Facebook 影片封面，
    # 都不是發佈素材；
    # 一般素材清單與規則檢查一律不含它們。
    role: Mapped[str] = mapped_column(String(16), default="media", server_default="media")


class PublishTarget(Base):
    __tablename__ = "publish_targets"
    __table_args__ = (
        UniqueConstraint("post_id", "platform"),
        CheckConstraint(
            "platform IN ('facebook','instagram','threads','youtube','tiktok')", name="platform"
        ),
        CheckConstraint("status IN ('pending','publishing','succeeded','failed')", name="status"),
    )
    post_id: Mapped[int] = mapped_column(ForeignKey("publish_posts.id"), index=True)
    platform: Mapped[str] = mapped_column(String(16))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    platform_post_id: Mapped[str | None] = mapped_column(String(128))
    permalink: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(32))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    presence_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    detail_json: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")


class PublishLink(Base):
    __tablename__ = "publish_links"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    media_id: Mapped[int] = mapped_column(ForeignKey("publish_media.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    uses: Mapped[int] = mapped_column(Integer, default=0)
    max_uses: Mapped[int] = mapped_column(Integer, default=32)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class PublishStorySnapshot(Base):
    __tablename__ = "publish_story_snapshots"
    __table_args__ = (UniqueConstraint("target_id", "position", "slot"),)
    target_id: Mapped[int] = mapped_column(ForeignKey("publish_targets.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    slot: Mapped[str] = mapped_column(String(32))
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    final: Mapped[bool] = mapped_column(Boolean, default=False)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)

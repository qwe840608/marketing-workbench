"""Short lived, hashed capabilities for uploads and explicit publication confirmation."""

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime


class AgentUpload(Base):
    __tablename__ = "agent_uploads"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("publish_posts.id"))
    grant_id: Mapped[int] = mapped_column(ForeignKey("agent_grants.id"))
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.id"))
    filename: Mapped[str] = mapped_column(String(255))
    # media＝發佈素材，thumbnail＝YouTube 自訂縮圖，cover＝Instagram Reels 封面，
    # fb_cover＝Facebook 影片／Reels 封面
    # （後兩者上傳時由伺服端綁定到草稿的平台選項）。
    role: Mapped[str] = mapped_column(String(16), default="media", server_default="media")
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class AgentPublishConfirmation(Base):
    __tablename__ = "agent_publish_confirmations"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("publish_posts.id"))
    grant_id: Mapped[int] = mapped_column(ForeignKey("agent_grants.id"))
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.id"))
    post_version: Mapped[int] = mapped_column(Integer)
    detail_hash: Mapped[str] = mapped_column(String(64))
    scheduled_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    retry: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

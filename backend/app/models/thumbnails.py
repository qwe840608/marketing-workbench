from datetime import datetime

from sqlalchemy import ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime


class PostThumbnail(Base):
    """平台 CDN 網址會過期，所以每篇貼文另存一張縮小的 JPEG；data 延遲載入，列表只讀狀態。"""

    __tablename__ = "post_thumbnails"

    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), unique=True)
    # ready＝已存圖；retry＝暫時失敗待重試；unavailable＝平台沒有圖（純文字等），不再嘗試。
    status: Mapped[str] = mapped_column(String(16))
    mime: Mapped[str | None] = mapped_column(String(32))
    width: Mapped[int | None]
    height: Mapped[int | None]
    digest: Mapped[str | None] = mapped_column(String(64))
    data: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    attempts: Mapped[int] = mapped_column(default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    error: Mapped[str | None] = mapped_column(String(40))

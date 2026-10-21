from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime


class FollowerSnapshot(Base):
    __tablename__ = "follower_snapshots"
    __table_args__ = (
        UniqueConstraint("account_id", "captured_at"),
        CheckConstraint("followers_count >= 0", name="nonnegative_count"),
    )

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime())
    followers_count: Mapped[int]

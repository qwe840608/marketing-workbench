from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    # 持久化摘要即可查驗 session，資料庫不保存可直接使用的 cookie。
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)


class LoginGuard(Base):
    __tablename__ = "login_guards"

    account_key: Mapped[str] = mapped_column(String(64), unique=True)
    failures: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime())

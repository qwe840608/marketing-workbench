from datetime import datetime

from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime


class OAuthState(Base):
    __tablename__ = "oauth_states"

    state_hash: Mapped[str] = mapped_column(String(64), unique=True)
    session_hash: Mapped[str] = mapped_column(String(64))
    staff_id: Mapped[int]
    platform: Mapped[str] = mapped_column(String(16))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    consumed: Mapped[bool] = mapped_column(default=False)
    encrypted_payload: Mapped[str] = mapped_column(Text, default="")


class OAuthConnection(Base):
    __tablename__ = "oauth_connections"

    platform: Mapped[str] = mapped_column(String(16), unique=True)
    account_name: Mapped[str] = mapped_column(String(255), default="")
    ig_username: Mapped[str] = mapped_column(String(255), default="")
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # Meta 回報此授權不會過期（例如商家專用 Facebook 登入）；與「到期時間未知」區分。
    never_expires: Mapped[bool] = mapped_column(default=False, server_default="0")
    refreshed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    granted_scopes: Mapped[list] = mapped_column(JSON, default=list)
    cache_json: Mapped[dict] = mapped_column(JSON, default=dict)
    checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    credential_digest: Mapped[str] = mapped_column(String(64), default="")
    maintenance_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    notified_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

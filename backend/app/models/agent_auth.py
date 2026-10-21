"""Agent secrets are digests; grants contain no cached role or brand scope."""

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime, utc_now


class OAuthClient(Base):
    __tablename__ = "agent_oauth_clients"

    client_id: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    redirect_uris: Mapped[list] = mapped_column(JSON)
    last_used_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class AgentGrant(Base):
    __tablename__ = "agent_grants"

    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.id"), index=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("agent_oauth_clients.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(100))
    last_used_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class OAuthRequest(Base):
    __tablename__ = "agent_oauth_requests"

    handle_hash: Mapped[str] = mapped_column(String(64), unique=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("agent_oauth_clients.id"), index=True)
    redirect_uri: Mapped[str] = mapped_column(String(2048))
    state: Mapped[str] = mapped_column(String(2048))
    challenge: Mapped[str] = mapped_column(String(43))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)


class AgentCode(Base):
    __tablename__ = "agent_codes"

    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    grant_id: Mapped[int] = mapped_column(ForeignKey("agent_grants.id"), index=True)
    redirect_uri: Mapped[str] = mapped_column(String(2048))
    challenge: Mapped[str] = mapped_column(String(43))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class AgentCredential(Base):
    __tablename__ = "agent_credentials"

    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    grant_id: Mapped[int] = mapped_column(ForeignKey("agent_grants.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

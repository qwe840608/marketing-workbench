from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Versioned


class PlatformCredential(Versioned, Base):
    __tablename__ = "platform_credentials"
    provider: Mapped[str] = mapped_column(String(80), unique=True)
    # Empty ciphertext is a removal tombstone; versions never reset after removal.
    encrypted_key: Mapped[str] = mapped_column(Text)

from pydantic import AwareDatetime, Field

from app.schemas.ingest import ExternalId, IngestInput, Platform
from app.schemas.posts import Count


class FollowerQuery(IngestInput):
    platform: Platform
    brand_id: int | None = Field(default=None, ge=1)
    account_id: int | None = Field(default=None, ge=1)
    year: int | None = Field(default=None, ge=1, le=9998)
    month: int | None = Field(default=None, ge=1, le=12)
    week: int | None = Field(default=None, ge=1, le=6)


class FollowerAccountInput(IngestInput):
    platform: Platform
    account_external_id: ExternalId


class FollowerInput(FollowerAccountInput):
    captured_at: AwareDatetime
    followers_count: Count

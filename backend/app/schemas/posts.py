from datetime import UTC
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, Field, StrictInt, field_validator

from app.schemas.ingest import ExternalId, IngestInput

MetaPlatform = Literal["facebook", "instagram"]
# 同步貼文、成效與回覆的平台；Threads 不經 Meta 呼叫配額，所以 Meta 呼叫紀錄仍只收 MetaPlatform。
SyncPlatform = Literal["facebook", "instagram", "threads", "youtube"]
# 貼文與成效另含 TikTok；TikTok 不讀留言，所以留言輪詢仍只收 SyncPlatform。
PostPlatform = Literal["facebook", "instagram", "threads", "youtube", "tiktok"]
Count = Annotated[StrictInt, Field(ge=0, le=2**53 - 1)]


class AccountInput(IngestInput):
    platform: PostPlatform
    account_external_id: ExternalId


class PostInput(IngestInput):
    external_id: ExternalId
    permalink: str | None = Field(default=None, max_length=2048, pattern=r"^https://")
    caption: str = Field(default="", max_length=20000)
    media_type: str = Field(min_length=1, max_length=40)
    visibility: Literal["public", "unlisted", "private"] | None = None
    published_at: AwareDatetime

    @field_validator("published_at")
    @classmethod
    def utc_time(cls, value):
        return value.astimezone(UTC)


class PostsInput(AccountInput):
    posts: list[PostInput] = Field(min_length=1, max_length=100)


class MetricInput(IngestInput):
    post_external_id: ExternalId
    captured_at: AwareDatetime
    sync_slot: AwareDatetime
    views: Count | None = None
    reach: Count | None = None
    likes: Count | None = None
    comments: Count | None = None
    shares: Count | None = None
    saves: Count | None = None
    avg_watch_time: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    completion_rate: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    extra_json: dict[str, Any] = Field(default_factory=dict)

    @field_validator("captured_at", "sync_slot")
    @classmethod
    def utc_time(cls, value):
        return value.astimezone(UTC)

    @field_validator("sync_slot")
    @classmethod
    def whole_hour(cls, value):
        if value.minute or value.second or value.microsecond:
            raise ValueError("排程時槽須為整點 UTC")
        return value


class MetricsInput(AccountInput):
    metrics: list[MetricInput] = Field(min_length=1, max_length=100)

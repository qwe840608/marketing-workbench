from typing import Annotated, Literal

from pydantic import Field, StrictInt

from app.schemas.ingest import ExternalId, IngestInput
from app.schemas.posts import AccountInput, MetaPlatform, SyncPlatform

Cursor = Annotated[str, Field(max_length=4096)]
PollError = Literal[
    "meta_rate_limited",
    "meta_auth_error",
    "meta_api_error",
    "network_error",
    "meta_timeout",
    "meta_server_error",
    "invalid_response",
    "invalid_pagination",
    "backend_failed",
    "work_budget",
    "threads_permission_missing",
    "youtube_permission_missing",
    "youtube_auth_error",
]


class ReplyCursor(IngestInput):
    id: ExternalId
    after: Cursor | None = None


class PollProgress(IngestInput):
    after: Cursor | None = None
    comments_done: bool = False
    replies: list[ReplyCursor] = Field(default_factory=list, max_length=100)
    pages: int = Field(default=0, ge=0)
    saved_comments: int = Field(default=0, ge=0)
    new_comments: int = Field(default=0, ge=0)
    full_rescan: bool = False


class PollClaim(IngestInput):
    platform: SyncPlatform = "instagram"
    account_external_id: ExternalId
    requested_only: bool = False
    post_id: int | None = Field(default=None, ge=1)


class PollCheckpoint(IngestInput):
    run_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    progress: PollProgress


class PollFinish(PollCheckpoint):
    success: bool
    error: PollError | None = None


class Usage(IngestInput):
    call_count: float = Field(default=0, ge=0, le=10000, allow_inf_nan=False)
    total_time: float = Field(default=0, ge=0, le=10000, allow_inf_nan=False)
    total_cputime: float = Field(default=0, ge=0, le=10000, allow_inf_nan=False)
    estimated_time_to_regain_access: float = Field(default=0, ge=0, le=10080, allow_inf_nan=False)


class ApiCallStart(AccountInput):
    platform: MetaPlatform
    source: Literal["poll", "metrics", "history"]
    operation: Literal[
        "media",
        "published_posts",
        "videos",
        "comments",
        "replies",
        "insights",
        "post",
        "conversations",
        "messages",
    ]
    resource_id: ExternalId
    run_id: str | None = Field(default=None, pattern=r"^[a-f0-9-]{36}$")


class ApiCallFinish(IngestInput):
    call_id: int = Field(ge=1)
    http_status: StrictInt = Field(ge=0, le=599)
    error_code: StrictInt | None = None
    error_subcode: StrictInt | None = None
    duration_ms: StrictInt = Field(ge=0, le=3600000)
    app_usage: Usage | None = None
    business_usage: list[Usage] = Field(default_factory=list, max_length=32)
    retry_after_seconds: float = Field(default=0, ge=0, le=604800, allow_inf_nan=False)

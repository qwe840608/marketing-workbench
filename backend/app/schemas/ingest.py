from datetime import UTC
from typing import Annotated, Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    field_validator,
    model_validator,
)

ExternalId = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=255, pattern=r"^\S+$")
]
Platform = Literal["line", "facebook", "instagram", "youtube", "tiktok", "threads"]


class IngestInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ContactInput(IngestInput):
    external_id: ExternalId
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    profile_json: dict[str, Any] | None = None


class MessageInput(IngestInput):
    external_id: ExternalId
    thread_external_id: ExternalId
    kind: Literal["dm", "comment_thread"]
    contact: ContactInput
    post_external_id: ExternalId | None = None
    source_ref_json: dict[str, Any] | None = None
    direction: Literal["in", "out"]
    author_type: Literal["fan", "brand"]
    text: str = Field(max_length=20000)
    attachments_json: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    sent_at: AwareDatetime
    edited_at: AwareDatetime | None = None
    is_redelivery: StrictBool = False

    @field_validator("sent_at", "edited_at")
    @classmethod
    def utc_time(cls, value):
        return value.astimezone(UTC) if value is not None else None

    @model_validator(mode="after")
    def consistent_source(self):
        if (self.direction, self.author_type) not in {("in", "fan"), ("out", "brand")}:
            raise ValueError("方向與發話者不一致")
        if self.edited_at is not None and self.edited_at < self.sent_at:
            raise ValueError("編輯時間不能早於送出時間")
        if self.source_ref_json is not None and "post_external_id" in self.source_ref_json:
            if self.source_ref_json["post_external_id"] != self.post_external_id:
                raise ValueError("來源貼文 ID 必須與 post_external_id 一致")
        return self


class ThreadReferenceInput(IngestInput):
    thread_external_id: ExternalId
    kind: Literal["dm"] = "dm"
    contact: ContactInput
    post_external_id: ExternalId | None = None
    source_ref_json: dict[str, Any]
    observed_at: AwareDatetime

    @field_validator("observed_at")
    @classmethod
    def utc_time(cls, value):
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def consistent_source(self):
        if "post_external_id" in self.source_ref_json:
            if self.source_ref_json["post_external_id"] != self.post_external_id:
                raise ValueError("來源貼文 ID 必須與 post_external_id 一致")
        return self


class EventInput(IngestInput):
    platform: Platform
    account_external_id: ExternalId
    external_id: ExternalId
    signature_ok: StrictBool
    source: Literal["webhook", "poll", "history"] = "webhook"
    observed_at: AwareDatetime | None = None
    poll_run_id: str | None = Field(default=None, pattern=r"^[a-f0-9-]{36}$")
    poll_call_id: int | None = Field(default=None, ge=1)
    payload: dict[str, Any] | list[Any]
    messages: list[MessageInput] = Field(max_length=200)
    references: list[ThreadReferenceInput] = Field(default_factory=list, max_length=200)


class IngestResult(BaseModel):
    raw_event_id: int
    processed: bool
    created_messages: int = 0
    updated_messages: int = 0
    unchanged_messages: int = 0
    queued_jobs: int = 0
    error: str | None = None

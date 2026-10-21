"""Strict MCP inputs; validation details are rendered without input values."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt, field_validator

from app.schemas.ideation import CommentWindow

Identity = Annotated[StrictInt, Field(ge=1)]


class Empty(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Guide(Empty):
    workflow: Literal["report", "ideas", "script", "post", "publish"]


class BrandInput(Empty):
    brand_id: Identity


class Dashboard(BrandInput):
    days: Literal[7, 30] = 30


class Page(Empty):
    limit: Annotated[StrictInt, Field(ge=1, le=50)] = 20
    offset: Annotated[StrictInt, Field(ge=0)] = 0


class Period(BrandInput):
    since: AwareDatetime | None = None
    until: AwareDatetime | None = None

    @field_validator("since", "until", mode="before")
    @classmethod
    def iso_time(cls, value):
        if value is not None and not isinstance(value, (str, datetime)):
            raise ValueError("時間須為含時區的 ISO 8601")
        return value


class Posts(Period, Page):
    platform: Literal["facebook", "instagram", "threads", "youtube", "tiktok", "line"] | None = None


class PostInput(Empty):
    post_id: Identity


class Comments(Period, Page):
    post_id: Identity | None = None


class Reports(BrandInput, Page):
    pass


class ReportInput(Empty):
    report_id: Identity


class ScriptInput(Empty):
    script_id: Identity


# Agent 自行判斷排除時只能用這些理由；刻意不提供「負面」，避免依立場挑掉觀眾聲音。
EXCLUSION_REASONS = {
    "spam": "廣告／垃圾",
    "off_topic": "與貼文無關",
    "duplicate": "重複洗版",
    "non_audience": "非觀眾（品牌或合作方）",
}


class AgentExclusion(Empty):
    id: Identity
    reason: Literal["spam", "off_topic", "duplicate", "non_audience"]
    note: str = Field(default="", max_length=100)


class StartIdeation(BrandInput, CommentWindow):
    post_ids: list[Identity] = Field(min_length=1, max_length=100)
    # 兩種排除分開記錄：使用者在對話中確認的，與 Agent 自行判斷且附理由的。
    excluded_message_ids: list[Identity] = Field(default_factory=list, max_length=500)
    agent_exclusions: list[AgentExclusion] = Field(default_factory=list, max_length=500)


class SaveIdeas(ReportInput):
    ideas: list[dict] = Field(max_length=100)


class EditIdeaInput(ReportInput):
    index: Annotated[StrictInt, Field(ge=0)]
    fields: dict
    version: Identity


class SaveScript(ReportInput):
    topic_index: Annotated[StrictInt, Field(ge=0)]
    content: dict

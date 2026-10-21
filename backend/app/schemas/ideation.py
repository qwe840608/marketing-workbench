from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

from app.schemas.ai import Provider


class MeetingConfig(BaseModel):
    version: int = Field(default=0, ge=0)
    enabled: bool = False
    weekday: int | None = Field(default=None, ge=0, le=6)
    time: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    interval_weeks: Literal[1, 2] = 1
    anchor_date: date | None = None
    topics: list[str] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def valid(self):
        if self.enabled and (self.weekday is None or self.time is None):
            raise ValueError("啟用例會須設定星期及時間")
        self.topics = [t.strip() for t in self.topics]
        if any(not t or len(t) > 80 for t in self.topics) or len(set(self.topics)) != len(
            self.topics
        ):
            raise ValueError("主題不得空白或重複")
        if "其他" not in self.topics:
            raise ValueError("主題須包含其他")
        if self.interval_weeks == 2 and self.anchor_date is None:
            raise ValueError("隔週例會須設定起算日")
        return self


CommentRange = Literal["90", "60", "30", "7", "custom"]


class CommentWindow(BaseModel):
    comment_range: CommentRange = "30"
    comment_from: date | None = None
    comment_to: date | None = None

    @model_validator(mode="after")
    def valid_comment_window(self):
        if self.comment_range == "custom" and (
            not self.comment_from or not self.comment_to
            or not date.min < self.comment_from <= self.comment_to
            <= datetime.now(ZoneInfo("Asia/Taipei")).date()
        ):
            raise ValueError("留言起日與迄日必填，且起日 ≤ 迄日 ≤ 今天（台北）")
        return self


class GenerateReport(CommentWindow):
    post_ids: list[StrictInt] = Field(min_length=1)
    # 使用者在留言視窗取消勾選的留言；預設全用，只記錄被排除的。
    excluded_message_ids: list[StrictInt] = Field(default_factory=list, max_length=20000)
    # agent：彙整證據後停在 awaiting_ideas，由 Agent 撰寫主題，不呼叫任何 AI。
    provider: Provider | Literal["agent"] = "gemini_api"
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None


class Reclassify(CommentWindow):
    post_ids: list[StrictInt] = Field(min_length=1)
    excluded_message_ids: list[StrictInt] = Field(default_factory=list, max_length=20000)
    start_at: AwareDatetime
    end_at: AwareDatetime


class Shot(BaseModel):
    number: int = Field(ge=1)
    visual: str = Field(min_length=1, max_length=1500)
    camera: Literal["POV", "側拍", "POV／側拍"]
    dialogue: str = Field(max_length=2000)
    subtitle: str = Field(max_length=1500)
    sound: str = Field(min_length=1, max_length=500)
    seconds: int = Field(ge=1, le=120)
    b_roll: str = Field(max_length=1000)


class ScriptContent(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    goal: Literal["流量型", "變現型", "引流型"]
    hook: str = Field(min_length=1, max_length=1000)
    duration_seconds: int = Field(ge=5, le=300)
    shots: list[Shot] = Field(min_length=1, max_length=20)
    ending: str = Field(max_length=1000)
    notes: str = Field(max_length=2000)
    permissions: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def timing(self):
        if sum(s.seconds for s in self.shots) != self.duration_seconds:
            raise ValueError("分鏡秒數加總須等於片長")
        if [s.number for s in self.shots] != list(range(1, len(self.shots) + 1)):
            raise ValueError("鏡號必須連續")
        return self


class EditScript(BaseModel):
    version: int = Field(ge=1)
    content: ScriptContent


class EditIdea(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=1000)
    hook: str = Field(min_length=1, max_length=1000)
    angle: str = Field(min_length=1, max_length=1000)
    visual: str = Field(min_length=1, max_length=1000)
    keyword: str = Field(min_length=1, max_length=1000)

    @field_validator("title", "hook", "angle", "visual", "keyword")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("主題欄位不可空白")
        return value.strip()

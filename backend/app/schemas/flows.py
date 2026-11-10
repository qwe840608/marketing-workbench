import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.publish import MAX_PLATFORMS, Platform

Clock = Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
NodeId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")]


class TriggerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["daily", "weekly", "once"] = "weekly"
    # 0 是星期一，與 Python weekday() 相同。
    weekdays: list[Annotated[int, Field(ge=0, le=6)]] = Field(default_factory=list, max_length=7)
    time: Clock = "20:00"
    date: dt.date | None = None


class DraftConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # 不用內建 AI 寫文案：固定範本、主題發想的下一個未用題目，或複製一篇選定的草稿。
    source: Literal["template", "idea", "post"] = "template"
    format: Literal["video", "image", "carousel", "text"] = "text"
    caption: str = Field(default="", max_length=5000)
    post_id: int | None = Field(default=None, ge=1)


class ApprovalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hours: int = Field(default=24, ge=1, le=168)


class PublishConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platforms: list[Platform] = Field(default_factory=list, max_length=MAX_PLATFORMS)


class DelayConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: int = Field(default=1, ge=1, le=720)
    unit: Literal["minutes", "hours", "days"] = "hours"
    # 有值時改成「等到下一個台北 HH:MM」，amount／unit 忽略。
    at: Clock | None = None


class NotifyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(default="", max_length=500)


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float = Field(default=0, ge=-100000, le=100000)
    y: float = Field(default=0, ge=-100000, le=100000)


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: NodeId
    type: Literal["trigger", "draft", "approval", "publish", "delay", "notify"]
    position: Position = Field(default_factory=Position)
    config: dict = Field(default_factory=dict)


class Edge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: NodeId
    target: NodeId


class Graph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nodes: list[Node] = Field(default_factory=list, max_length=40)
    edges: list[Edge] = Field(default_factory=list, max_length=60)


class FlowInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brand_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=80)
    graph: Graph = Field(default_factory=Graph)
    version: int = Field(default=1, ge=1)

    @field_validator("name")
    @classmethod
    def strip(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("請輸入流程名稱")
        return value


class EnableInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    version: int = Field(ge=1)


class ApproveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: Literal[True]
    # 草稿的版本：核准畫面開著時草稿若被改過，要求重新整理。
    post_version: int = Field(ge=1)

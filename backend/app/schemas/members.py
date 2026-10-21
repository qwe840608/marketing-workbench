from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.auth import StaffView


class MemberEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=200)
    role: Literal["admin", "marketing", "viewer"]
    brand_ids: list[int] = Field(default_factory=list, max_length=1000)

    @field_validator("display_name")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("顯示名稱不可空白")
        return value.strip()


class MemberCreate(MemberEdit):
    username: str = Field(min_length=1, max_length=80)

    @field_validator("username")
    @classmethod
    def nonempty_username(cls, value):
        if not value.strip():
            raise ValueError("帳號不可空白")
        return value.strip()


class MemberState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active: bool


class MemberView(StaffView):
    active: bool
    last_login_at: datetime | None
    connection_count: int


class TemporaryPasswordView(BaseModel):
    member: MemberView
    temporary_password: str

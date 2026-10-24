from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.auth import StaffView


class MemberEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=200)
    # 內建 admin／marketing／viewer 或自訂角色鍵；是否存在由服務層查表驗證。
    role: str = Field(min_length=1, max_length=40)
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


class RoleEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    permissions: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("name")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("角色名稱不可空白")
        return value.strip()


class RoleView(BaseModel):
    id: int | None
    key: str
    name: str | None
    builtin: bool
    permissions: list[str]
    member_count: int


class RoleCatalog(BaseModel):
    permissions: list[str]
    roles: list[RoleView]

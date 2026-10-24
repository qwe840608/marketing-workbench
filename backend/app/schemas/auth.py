from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    username: str = Field(min_length=1, max_length=80)
    password: SecretStr = Field(min_length=1, max_length=128)


class StaffView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    role: str
    # 自訂角色的名稱；內建角色為 None，由前端依介面語言翻譯。
    role_name: str | None = None
    permissions: list[str] = []
    must_change_password: bool
    language: str | None = None
    brand_ids: list[int]


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    current_password: SecretStr = Field(min_length=1, max_length=128)
    new_password: SecretStr = Field(min_length=12, max_length=128)


class CSRFView(BaseModel):
    csrf_token: str


class LoginView(CSRFView):
    user: StaffView


class SetupStatus(BaseModel):
    # needed：還沒有任何帳號；local：這次請求來自執行工作檯的電腦本身，才可以建立。
    needed: bool
    local: bool


class InitialSetup(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    username: str = Field(min_length=1, max_length=80)
    password: SecretStr = Field(min_length=12, max_length=128)
    brand_name: str = Field(min_length=1, max_length=200)


class RecoveryCodeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    current_password: SecretStr = Field(min_length=1, max_length=128)


class RecoveryStatus(BaseModel):
    configured: bool
    created_at: datetime | None


class RecoveryCodeView(RecoveryStatus):
    recovery_code: str


class PasswordRecovery(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    username: str = Field(min_length=1, max_length=80)
    recovery_code: SecretStr = Field(min_length=1, max_length=64)
    new_password: SecretStr = Field(min_length=12, max_length=128)


UiLanguage = Literal["zh-TW", "zh-CN", "en", "ja"]


class LanguageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: UiLanguage

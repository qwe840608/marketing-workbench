from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

APIProvider = Literal["gemini_api", "openai_api", "anthropic_api"]
Provider = APIProvider
# 本機 CLI 已移除；資料庫與用量紀錄裡可能還留有這些舊值，讀取時視為未設定。
RETIRED_PROVIDERS = frozenset({"codex_cli", "claude_cli", "agy_cli"})


class AISettings(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    default_provider: Provider | Literal[""] | None = None
    manual_provider: Provider | None = "gemini_api"
    background_provider: APIProvider | None = "gemini_api"
    gemini_fallback_model: str = Field(
        default="gemini-3.7-flash",
        max_length=120,
        pattern=r"^(?:models/)?[A-Za-z0-9][A-Za-z0-9._:-]*$|^$",
    )
    openai_fallback_model: str = Field(
        default="",
        max_length=120,
        pattern=r"^(?:models/)?[A-Za-z0-9][A-Za-z0-9._:-]*$|^$",
    )
    anthropic_fallback_model: str = Field(
        default="",
        max_length=120,
        pattern=r"^(?:models/)?[A-Za-z0-9][A-Za-z0-9._:-]*$|^$",
    )
    monthly_budget_usd: float | None = Field(default=None, gt=0, le=100000)
    version: int = Field(default=0, ge=0)

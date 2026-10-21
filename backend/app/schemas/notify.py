from pydantic import BaseModel, ConfigDict, Field


class NotificationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    enabled: bool = False
    urgency_threshold: float = Field(default=0.75, ge=0, le=1)
    public_reputation_risk_threshold: float = Field(default=0.5, ge=0, le=1)
    group_id: str | None = Field(default=None, pattern=r"^C[a-f0-9]{32}$")
    group_name: str = Field(default="", max_length=100)


class PolicyUpdate(NotificationPolicy):
    version: int = Field(ge=0)


class DeliveryResult(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    lease_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    status_code: int = Field(ge=0, le=599)
    already_accepted: bool = False

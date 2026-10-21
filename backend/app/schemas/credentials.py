from pydantic import BaseModel, ConfigDict, Field, SecretStr


class CredentialSave(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    value: SecretStr
    version: int = Field(ge=0)


class CredentialTest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    values: dict[str, SecretStr] = Field(default_factory=dict, max_length=16)

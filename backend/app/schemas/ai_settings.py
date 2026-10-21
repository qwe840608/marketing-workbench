from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class KeyTest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    key: SecretStr | None = None

    @field_validator("key")
    @classmethod
    def valid_key(cls, key):
        if key is not None:
            raw = key.get_secret_value()
            if not 12 <= len(raw) <= 512 or any(ord(c) < 33 or ord(c) > 126 for c in raw):
                raise ValueError("金鑰格式錯誤")
        return key


class KeySave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    receipt: str = Field(min_length=40, max_length=64)


class PromptEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    content: str = Field(max_length=12000)


class PromptRestore(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    restore_revision: int = Field(ge=1)

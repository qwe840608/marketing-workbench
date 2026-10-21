from typing import Literal

from pydantic import BaseModel, Field, field_validator


class IdentityInput(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    version: int = Field(ge=0)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if not value or any(ord(c) < 32 for c in value):
            raise ValueError("名稱不能空白或含控制字元")
        return value


class TemplateInput(BaseModel):
    template: Literal["creator", "blank"]
    token: str = Field(pattern=r"^[a-f0-9]{64}$")


class RulesInput(BaseModel):
    before: dict
    forbidden_phrases: list[str] = Field(max_length=100)

    @field_validator("forbidden_phrases")
    @classmethod
    def clean_phrases(cls, values):
        values = [v.strip() for v in values]
        if any(not v or len(v) > 100 for v in values) or len(set(values)) != len(values):
            raise ValueError("禁語不得空白、重複或超過 100 字")
        return values

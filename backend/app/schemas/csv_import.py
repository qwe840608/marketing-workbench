from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CsvField = Literal[
    "platform",
    "kind",
    "external_id",
    "thread_id",
    "sent_at",
    "author",
    "text",
    "source_url",
    "source_ref",
    "brand",
    "contact_id",
    "post_id",
    "ignore",
]


class CsvInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Upload(CsvInput):
    brand_id: int = Field(gt=0)
    filename: str = Field(min_length=1, max_length=200)
    content_base64: str = Field(max_length=2796204)


class Mapping(CsvInput):
    token: str = Field(pattern=r"^[a-f0-9]{32}$")
    columns: dict[str, CsvField] = Field(max_length=32)
    accounts: dict[str, int] = Field(max_length=6)


class Confirm(CsvInput):
    token: str = Field(pattern=r"^[a-f0-9]{32}$")
    revision: str = Field(pattern=r"^[a-f0-9]{32}$")

from pydantic import BaseModel, ConfigDict, Field


class AutostartInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    enabled: bool = Field(strict=True)


class ExportSettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    version: int = Field(ge=0)
    export_root: str = Field(min_length=1, max_length=500)


class ObsidianSettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    version: int = Field(ge=0)
    obsidian_root: str = Field(min_length=1, max_length=500)

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

IntentNote = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200, strict=True)]


class IntentNotes(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    price: IntentNote = ""
    booking: IntentNote = ""
    reschedule: IntentNote = ""
    model_question: IntentNote = ""
    complaint: IntentNote = ""
    cooperation: IntentNote = ""
    job: IntentNote = ""
    spam: IntentNote = ""
    other: IntentNote = ""


class IntentNotesUpdate(IntentNotes):
    version: int = Field(ge=0)


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    confidence_threshold: float = Field(default=0.8, ge=0, le=1)
    complaint_threshold: float = Field(default=0.5, ge=0, le=1)
    human_threshold: float = Field(default=0.5, ge=0, le=1)
    personal_data_threshold: float = Field(default=0.5, ge=0, le=1)
    urgency_threshold: float = Field(default=0.75, ge=0, le=1)
    negative_sentiment_threshold: float = Field(default=0.25, ge=0, le=1)
    uncertainty_margin: float = Field(default=0.1, ge=0, le=0.5)

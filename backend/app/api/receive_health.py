from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.dependencies import Access, Database, internal_key
from app.services import receive_health

router = APIRouter(prefix="/api")


class AlertTarget(BaseModel):
    recipient: str = Field(pattern=r"^[UCR][a-f0-9]{32}$")
    version: int = Field(ge=0)


class SignatureFailure(BaseModel):
    platform: Literal["line", "meta", "notify"]


@router.get("/receive-health")
def health(request: Request, access: Access):
    return receive_health.snapshot(access.session, request.app.state.settings)


@router.get("/settings/receive-health")
def target(request: Request, access: Access):
    return receive_health.target_view(access, request.app.state.settings)


@router.put("/settings/receive-health")
def save(body: AlertTarget, request: Request, access: Access):
    return receive_health.save_target(access, request.app.state.settings, body)


@router.post("/ingest/signature-failure")
def failure(
    body: SignatureFailure, session: Database, _authorized: Annotated[None, Depends(internal_key)]
):
    return receive_health.signature_failure(session, body.platform)

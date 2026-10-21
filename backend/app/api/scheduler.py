from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import Access, internal_key
from app.services import scheduler as service
from app.services.scheduler import scheduler_for

router = APIRouter(prefix="/api/scheduler")


@router.get("/status")
def status(request: Request, _authorized: Annotated[None, Depends(internal_key)]):
    scheduler = scheduler_for(request.app.state.settings)
    return {"healthy": bool(scheduler and scheduler.healthy())}


class JobSettings(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    enabled: bool
    version: int = Field(ge=0)


@router.get("/jobs")
def jobs(request: Request, access: Access):
    return service.jobs_view(access, request.app.state.settings)


@router.put("/jobs/{name}")
def save_job(name: str, body: JobSettings, request: Request, access: Access):
    return service.save_job(access, request.app.state.settings, name, body.enabled, body.version)


@router.get("/metrics-sync")
def metrics_sync(access: Access):
    return service.manual_metrics_view(access.session)


@router.post("/metrics-sync", status_code=202)
def request_metrics_sync(request: Request, access: Access):
    return service.request_manual_metrics(access, request.app.state.settings)

from datetime import date

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict

from app.api.dependencies import Access
from app.services import export_docx, obsidian

router = APIRouter(prefix="/api/exports")
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class ReportInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    brand_id: int
    start: date
    end: date


@router.get("/status")
def status(request: Request, access: Access):
    if access.staff.role != "admin":
        raise HTTPException(403, "僅管理員可查看全域匯出狀態")
    return request.app.state.export_worker.status()


@router.post("/sync")
def sync(request: Request, access: Access):
    if access.staff.role != "admin":
        raise HTTPException(403, "僅管理員可重建全域匯出")
    return request.app.state.export_worker.tick(force=True)


@router.post("/obsidian/sync")
def sync_obsidian(request: Request, access: Access):
    if access.staff.role != "admin":
        raise HTTPException(403, "僅管理員可同步 Obsidian")
    return obsidian.sync(access, request.app.state.obsidian_worker)


@router.post("/threads/{thread_id}/docx")
def conversation(thread_id: int, request: Request, access: Access):
    path = export_docx.conversation(access, request.app.state.settings, thread_id)
    return FileResponse(path, filename=path.name, media_type=DOCX)


@router.post("/report/docx")
def report(body: ReportInput, request: Request, access: Access):
    path = export_docx.report(access, request.app.state.settings, body)
    return FileResponse(path, filename=path.name, media_type=DOCX)

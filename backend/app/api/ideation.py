from datetime import date
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import AwareDatetime

from app.api.dependencies import Access
from app.schemas.ideation import (
    CommentRange,
    EditIdea,
    EditScript,
    GenerateReport,
    MeetingConfig,
    Reclassify,
)
from app.services import (
    ideation,
    ideation_exports,
    ideation_posts,
    ideation_settings,
    video_scripts,
)

router = APIRouter(prefix="/api/ideation")


@router.put("/reports/{report_id}/ideas/{index}")
def edit_idea(report_id: int, index: int, body: EditIdea, request: Request, access: Access):
    from app.services import idea_actions

    return idea_actions.edit(
        access, report_id, index, body, request.app.state.settings,
        request.app.state.session_factory
    )


@router.post("/reports/{report_id}/ideas/{index}/restore")
def restore_idea(report_id: int, index: int, request: Request, access: Access):
    from app.services import idea_actions

    return idea_actions.restore(
        access, report_id, index, request.app.state.settings, request.app.state.session_factory
    )


@router.get("/posts")
def posts(
    brand_id: int,
    start_at: AwareDatetime,
    end_at: AwareDatetime,
    access: Access,
    comment_range: CommentRange = "30",
    comment_from: date | None = None,
    comment_to: date | None = None,
):
    return ideation_posts.listing_for_window(
        access, brand_id, start_at, end_at, comment_range, comment_from, comment_to
    )


@router.get("/posts/{post_id}/comments")
def post_comments(
    post_id: int,
    brand_id: int,
    access: Access,
    comment_range: CommentRange = "30",
    comment_from: date | None = None,
    comment_to: date | None = None,
    offset: int = Query(default=0, ge=0),
):
    return ideation_posts.preview_comments(
        access, brand_id, post_id, comment_range, comment_from, comment_to, offset
    )


@router.get("/settings")
def settings(brand_id: int, access: Access):
    return ideation_settings.view(access, brand_id)


@router.put("/settings")
def save_settings(brand_id: int, body: MeetingConfig, access: Access):
    return ideation_settings.save(access, brand_id, body)


@router.get("/reports")
def reports(brand_id: int, access: Access):
    return ideation.listing(access, brand_id)


@router.post("/reports", status_code=202)
def generate(
    brand_id: int, body: GenerateReport, request: Request, access: Access, tasks: BackgroundTasks
):
    result = ideation.create(
        access, brand_id, body, request.app.state.session_factory, request.app.state.settings
    )
    tasks.add_task(
        ideation.process,
        request.app.state.session_factory,
        request.app.state.settings,
        result["id"],
    )
    return result


@router.get("/reports/{report_id}")
def report(report_id: int, request: Request, access: Access):
    return ideation.view(
        ideation.get(access, report_id), session=access.session, settings=request.app.state.settings
    )


@router.post("/reports/{report_id}/retry", status_code=202)
def retry(report_id: int, request: Request, access: Access, tasks: BackgroundTasks):
    result = ideation.retry(access, report_id, request.app.state.settings)
    tasks.add_task(
        ideation.process, request.app.state.session_factory, request.app.state.settings, report_id
    )
    return result


@router.delete("/reports/{report_id}", status_code=204)
def delete_report(report_id: int, access: Access):
    ideation.delete(access, report_id)
    return Response(status_code=204)


@router.post("/reclassify")
def reclassify(
    brand_id: int, body: Reclassify, request: Request, access: Access, tasks: BackgroundTasks
):
    return ideation.reclassify(
        access, brand_id, body, request.app.state.session_factory, request.app.state.settings, tasks
    )


@router.get("/evidence/{message_id}")
def evidence(message_id: int, access: Access):
    return ideation.source_view(access, message_id)


@router.get("/reports/{report_id}/scripts")
def scripts(report_id: int, request: Request, access: Access):
    return video_scripts.listing(access, report_id, request.app.state.settings)


@router.get("/scripts/{script_id}")
def script(script_id: int, request: Request, access: Access):
    return video_scripts.view(
        access.session, video_scripts.get(access, script_id), request.app.state.settings
    )


@router.put("/scripts/{script_id}")
def script_edit(script_id: int, body: EditScript, request: Request, access: Access):
    return video_scripts.edit(
        access, script_id, body, request.app.state.session_factory, request.app.state.settings
    )


@router.get("/{kind}/{identity}/download/{format}")
def download(
    kind: Literal["reports", "scripts"],
    identity: int,
    format: Literal["md", "docx"],
    request: Request,
    access: Access,
):
    path = ideation_exports.download(access, request.app.state.settings, kind, identity, format)
    media = (
        "text/markdown; charset=utf-8"
        if format == "md"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    return FileResponse(path, filename=path.name, media_type=media)

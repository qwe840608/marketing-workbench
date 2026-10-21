from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Request

from app.api.dependencies import Access
from app.schemas.publish import (
    IdeaDraftInput,
    PostInput,
    PresenceInput,
    PublishAction,
    SwitchInput,
    ThumbnailAction,
)
from app.services import publish, publish_media, publish_presence

router = APIRouter(prefix="/api/publish")
media_router = APIRouter()


@router.get("/posts")
def listing(access: Access, brand_id: int | None = None, report_id: int | None = None):
    return publish.listing(access, brand_id, report_id)


@router.get("/options")
def options(request: Request, access: Access, brand_id: int):
    return publish.options(access, request.app.state.settings, brand_id)


@router.put("/switch")
def switch(body: SwitchInput, access: Access):
    return publish.set_enabled(access, body)


@router.post("/presence-check")
def presence_check(body: PresenceInput, request: Request, access: Access):
    return publish_presence.manual(
        access, request.app.state.session_factory, request.app.state.settings, body.brand_id
    )


@router.post("/posts", status_code=201)
def create(body: PostInput, access: Access):
    return publish.save(access, body)


@router.get("/posts/{identity}")
def detail(identity: int, access: Access):
    return publish.view(access.session, publish.get(access, identity))


@router.post("/ideation-draft")
def idea_draft(body: IdeaDraftInput, request: Request, access: Access):
    return publish.from_idea(access, request.app.state.settings, body)


@router.put("/posts/{identity}")
def edit(identity: int, body: PostInput, access: Access):
    return publish.save(access, body, identity)


@router.delete("/posts/{identity}")
def delete(identity: int, access: Access):
    return publish.cancel(access, identity, delete=True)


@router.post("/posts/{identity}/media")
async def upload(
    identity: int,
    request: Request,
    access: Access,
    filename: str = "media",
    role: Literal["media", "thumbnail", "cover", "fb_cover"] = "media",
):
    return await publish_media.upload(
        request, access, publish.get(access, identity), filename, role=role
    )


@router.delete("/posts/{identity}/media/{media_id}")
def remove(identity: int, media_id: int, request: Request, access: Access):
    return publish.remove_media(access, request.app.state.settings, identity, media_id)


@router.get("/posts/{identity}/media/{media_id}")
def preview(identity: int, media_id: int, request: Request, access: Access):
    return publish.preview(access, request.app.state.settings, identity, media_id)


@router.post("/posts/{identity}/check")
def check(identity: int, request: Request, access: Access):
    return publish.checks(access, request.app.state.settings, identity)


@router.post("/posts/{identity}/submit")
def submit(
    identity: int,
    body: PublishAction,
    request: Request,
    background: BackgroundTasks,
    access: Access,
):
    result = publish.prepare(access, request.app.state.settings, identity, body)
    if result["status"] == "publishing":
        background.add_task(
            publish.execute, request.app.state.session_factory, request.app.state.settings, identity
        )
    return result


@router.post("/posts/{identity}/retry")
def retry(
    identity: int,
    body: PublishAction,
    request: Request,
    background: BackgroundTasks,
    access: Access,
):
    result = publish.prepare(access, request.app.state.settings, identity, body, retry=True)
    if result["status"] == "publishing":
        background.add_task(
            publish.execute, request.app.state.session_factory, request.app.state.settings, identity
        )
    return result


@router.post("/posts/{identity}/facebook-cover")
def facebook_cover(identity: int, body: ThumbnailAction, request: Request, access: Access):
    return publish.reapply_facebook_cover(
        access, request.app.state.session_factory, request.app.state.settings, identity
    )


@router.post("/posts/{identity}/youtube-thumbnail")
def youtube_thumbnail(identity: int, body: ThumbnailAction, request: Request, access: Access):
    # 只重設縮圖，不重傳影片；影片已成功的 YouTube 目標才可使用。
    return publish.reapply_thumbnail(
        access, request.app.state.session_factory, request.app.state.settings, identity
    )


@router.post("/posts/{identity}/cancel")
def cancel(identity: int, access: Access):
    return publish.cancel(access, identity)


@media_router.get("/media/{token}")
def download(token: str, request: Request):
    return publish_media.download(
        request.app.state.session_factory,
        request.app.state.settings,
        token,
        request.headers.get("range"),
    )

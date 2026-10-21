from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.api.dependencies import Access, Database
from app.services import auth, oauth

router = APIRouter(prefix="/api/oauth")


class PageChoice(BaseModel):
    page_id: str = Field(pattern=r"^\d{1,64}$")


class CategoryChoice(BaseModel):
    category_id: str = Field(pattern=r"^\d{1,3}$")


@router.get("/status")
def status(request: Request, access: Access, force: bool = False):
    return oauth.view(
        access, request.app.state.settings, request.cookies.get(auth.COOKIE_NAME), force
    )


@router.post("/{platform}/start")
def start(platform: str, request: Request, access: Access):
    return oauth.start(
        access,
        request.app.state.settings,
        request.cookies.get(auth.COOKIE_NAME),
        platform,
        request.headers.get("origin"),
    )


@router.get("/meta/callback")
def meta_callback(
    request: Request, session: Database, state: str = "", code: str = "", error: str = ""
):
    # 平台跨站導回時不會帶 SameSite=Strict 的登入 cookie；此段不需登入，只暫存 code。
    target = oauth.receive(session, request.app.state.settings, "meta", state, code, bool(error))
    return RedirectResponse(target, status_code=303)


@router.get("/threads/callback")
def threads_callback(
    request: Request, session: Database, state: str = "", code: str = "", error: str = ""
):
    target = oauth.receive(session, request.app.state.settings, "threads", state, code, bool(error))
    return RedirectResponse(target, status_code=303)


@router.get("/youtube/callback")
def youtube_callback(
    request: Request, session: Database, state: str = "", code: str = "", error: str = ""
):
    target = oauth.receive(session, request.app.state.settings, "youtube", state, code, bool(error))
    return RedirectResponse(target, status_code=303)


@router.get("/tiktok/callback")
def tiktok_callback(
    request: Request, session: Database, state: str = "", code: str = "", error: str = ""
):
    target = oauth.receive(session, request.app.state.settings, "tiktok", state, code, bool(error))
    return RedirectResponse(target, status_code=303)


@router.post("/tiktok/disconnect")
def tiktok_disconnect(request: Request, access: Access):
    from app.services import tiktok_oauth

    return tiktok_oauth.disconnect(access, request.app.state.settings)


@router.post("/youtube/disconnect")
def youtube_disconnect(request: Request, access: Access):
    from app.services import youtube_oauth

    return youtube_oauth.disconnect(access, request.app.state.settings)


@router.put("/youtube/category")
def youtube_category(body: CategoryChoice, access: Access):
    from app.services import youtube_oauth

    return youtube_oauth.set_category(access, body.category_id)


@router.post("/{platform}/complete")
def complete(platform: str, request: Request, access: Access):
    return oauth.complete(
        access, request.app.state.settings, request.cookies.get(auth.COOKIE_NAME), platform
    )


@router.post("/meta/page")
def choose(body: PageChoice, request: Request, access: Access):
    return oauth.choose(
        access, request.app.state.settings, request.cookies.get(auth.COOKIE_NAME), body.page_id
    )

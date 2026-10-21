from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Staff
from app.services import auth
from app.services.access import BrandAccess

Database = Annotated[Session, Depends(get_session)]


def internal_key(request: Request) -> None:
    """本機內部 API（群組探索、排程狀態等）以 X-Api-Key 驗證，不使用登入 session。"""
    from app.services import ingest

    ingest.require_key(request.app.state.settings, request.headers.get("x-api-key"))


async def read_body(request: Request) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > request.app.state.settings.ingest_max_bytes:
            raise HTTPException(413, "Ingest 請求超過大小限制")
    return bytes(body)


def get_access(request: Request, session: Database) -> BrandAccess:
    token = request.cookies.get(auth.COOKIE_NAME)
    staff = auth.current_staff(session, token)
    if staff.must_change_password:
        raise HTTPException(403, "請先變更密碼")
    from app.api.permissions import require_role

    require_role(request.scope["route"].path, request.method, staff.role)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        auth.validate_origin(
            request.headers.get("origin"),
            request.headers.get("sec-fetch-site"),
            request.app.state.settings,
        )
        auth.require_csrf(session, token, request.headers.get("x-csrf-token"))
        if staff.role not in {"admin", "marketing"}:
            raise HTTPException(403, "此帳號僅能檢視資料")
    return BrandAccess(session, staff)


Access = Annotated[BrandAccess, Depends(get_access)]


def enforce_password_change(request: Request) -> None:
    if not request.url.path.startswith("/api/") or request.url.path in {
        "/api/auth/me",
        "/api/auth/change-password",
        "/api/auth/logout",
        "/api/auth/csrf",
    }:
        return
    token = request.cookies.get(auth.COOKIE_NAME)
    if not token:
        return
    # 此檢查不沿用路由交易；內部 worker 仍可從乾淨的 session 取得寫鎖。
    with request.app.state.session_factory() as session:
        current = auth.find_session(session, token)
        staff = session.get(Staff, current.staff_id) if current and current.staff_id else None
        if staff and staff.active and staff.must_change_password:
            raise HTTPException(403, "請先變更密碼")

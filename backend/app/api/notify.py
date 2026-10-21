from typing import Annotated

from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import Access, Database, internal_key, read_body
from app.schemas.notify import PolicyUpdate
from app.services import notify

router = APIRouter(prefix="/api/notify")
Internal = Annotated[None, Depends(internal_key)]


@router.get("/policy")
def get_policy(brand_id: int, request: Request, access: Access):
    return notify.policy_view(access, brand_id, request.app.state.settings)


@router.put("/policy")
def update_policy(brand_id: int, body: PolicyUpdate, request: Request, access: Access):
    return notify.save_policy(access, brand_id, body, request.app.state.settings)


@router.post("/groups/events")
async def group_events(request: Request, session: Database, _authorized: Internal):
    return await run_in_threadpool(
        notify.capture_groups,
        session,
        request.app.state.settings,
        await read_body(request),
        request.headers.get("x-line-signature"),
    )


@router.get("/groups")
def groups(session: Database, _authorized: Internal):
    return notify.discovered_groups(session)

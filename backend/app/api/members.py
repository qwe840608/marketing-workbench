from fastapi import APIRouter

from app.api.dependencies import Access
from app.schemas.members import (
    MemberCreate,
    MemberEdit,
    MemberState,
    MemberView,
    TemporaryPasswordView,
)
from app.services import members

router = APIRouter(prefix="/api/members")


@router.get("", response_model=list[MemberView])
def listing(access: Access):
    return members.listing(access)


@router.post("", status_code=201, response_model=TemporaryPasswordView)
def create(body: MemberCreate, access: Access):
    return members.create(access, body)


@router.put("/{identity}", response_model=MemberView)
def edit(identity: int, body: MemberEdit, access: Access):
    return members.edit(access, identity, body)


@router.put("/{identity}/state", response_model=MemberView)
def state(identity: int, body: MemberState, access: Access):
    return members.set_active(access, identity, body.active)


@router.post("/{identity}/reset-password", response_model=TemporaryPasswordView)
def reset(identity: int, access: Access):
    return members.reset_password(access, identity)

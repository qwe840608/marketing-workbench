from fastapi import APIRouter

from app.api.dependencies import Access
from app.schemas.members import (
    MemberCreate,
    MemberEdit,
    MemberState,
    MemberView,
    RoleCatalog,
    RoleEdit,
    RoleView,
    TemporaryPasswordView,
)
from app.services import members, roles

router = APIRouter(prefix="/api/members")
roles_router = APIRouter(prefix="/api/roles")


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


@roles_router.get("", response_model=RoleCatalog)
def role_listing(access: Access):
    members.require_admin(access)
    return roles.listing(access.session)


@roles_router.post("", status_code=201, response_model=RoleView)
def role_create(body: RoleEdit, access: Access):
    return roles.create(access, body)


@roles_router.put("/{identity}", response_model=RoleView)
def role_edit(identity: int, body: RoleEdit, access: Access):
    return roles.edit(access, identity, body)


@roles_router.delete("/{identity}", status_code=204)
def role_delete(identity: int, access: Access):
    roles.delete(access, identity)

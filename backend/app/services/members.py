import secrets

from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy import delete, func, select

from app.db import ensure_write
from app.models import AuditLog, AuthSession, Brand, Staff, StaffBrand
from app.schemas.members import MemberCreate, MemberEdit
from app.services.passwords import hash_password

PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


def staff_view(session, staff):
    brands = (
        select(Brand.id)
        if staff.role == "admin"
        else select(StaffBrand.brand_id).where(StaffBrand.staff_id == staff.id)
    )
    return {
        "id": staff.id,
        "username": staff.username,
        "display_name": staff.display_name,
        "role": staff.role,
        "must_change_password": staff.must_change_password,
        "language": staff.language,
        "brand_ids": list(
            session.scalars(brands.order_by("id" if staff.role == "admin" else StaffBrand.brand_id))
        ),
    }


def view(session, staff):
    from app.services.agent_auth import connection_count

    last_login = session.scalar(
        select(func.max(AuditLog.created_at)).where(
            AuditLog.action == "auth.login",
            AuditLog.target_type == "staff",
            AuditLog.target_id == staff.id,
        )
    )
    return {**staff_view(session, staff), "active": staff.active, "last_login_at": last_login,
            "connection_count": connection_count(session, staff.id)}


def listing(access):
    require_admin(access)
    return [
        view(access.session, staff)
        for staff in access.session.scalars(select(Staff).order_by(Staff.id))
    ]


def require_admin(access):
    if access.staff.role != "admin":
        raise HTTPException(403, "僅管理員可管理成員")


def begin(access, identity=None):
    ensure_write(access.session)
    # 取得写鎖後重讀操作者，避免另一管理員剛撤銷權限。
    access.session.refresh(access.staff)
    require_admin(access)
    if not access.staff.active or access.staff.must_change_password:
        raise HTTPException(403, "請重新登入或先變更密碼")
    staff = access.session.get(Staff, identity) if identity is not None else None
    if identity is not None and staff is None:
        raise HTTPException(404, "找不到成員")
    return staff


def audit(access, action, staff, detail):
    access.session.add(
        AuditLog(
            actor=f"staff:{access.staff.id}",
            action=action,
            target_type="staff",
            target_id=staff.id,
            detail_json=detail,
        )
    )


def assign_brands(session, staff, ids):
    ids = sorted(set(ids)) if staff.role != "admin" else []
    if ids and set(session.scalars(select(Brand.id).where(Brand.id.in_(ids)))) != set(ids):
        raise HTTPException(422, "品牌清單包含不存在的品牌")
    session.execute(delete(StaffBrand).where(StaffBrand.staff_id == staff.id))
    session.add_all(StaffBrand(staff_id=staff.id, brand_id=bid) for bid in ids)
    return ids


def rotate_password(session, staff, actor=None):
    from app.services.agent_auth import revoke_all

    password = "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(20))
    staff.password_hash = hash_password(SecretStr(password))
    staff.must_change_password = True
    session.execute(delete(AuthSession).where(AuthSession.staff_id == staff.id))
    revoke_all(session, staff.id, actor)
    return password


def protect_admin(session, staff):
    if (
        staff.active
        and staff.role == "admin"
        and session.scalar(
            select(func.count())
            .select_from(Staff)
            .where(Staff.active.is_(True), Staff.role == "admin")
        )
        <= 1
    ):
        raise HTTPException(409, "最後一位啟用中的管理員不可停用或降級")


def create(access, body: MemberCreate):
    begin(access)
    if any(
        name.casefold() == body.username.casefold()
        for name in access.session.scalars(select(Staff.username))
    ):
        raise HTTPException(409, "帳號已存在（不分大小寫）")
    staff = Staff(
        username=body.username, display_name=body.display_name, role=body.role, active=True
    )
    access.session.add(staff)
    access.session.flush()
    ids = assign_brands(access.session, staff, body.brand_ids)
    password = rotate_password(access.session, staff)
    audit(access, "members.create", staff, {"role": staff.role, "brand_ids": ids})
    access.session.commit()
    return {"member": view(access.session, staff), "temporary_password": password}


def edit(access, identity, body: MemberEdit):
    staff = begin(access, identity)
    if body.role != "admin":
        protect_admin(access.session, staff)
    before = {
        "display_name": staff.display_name,
        "role": staff.role,
        "brand_ids": staff_view(access.session, staff)["brand_ids"],
    }
    staff.display_name, staff.role = body.display_name, body.role
    ids = assign_brands(access.session, staff, body.brand_ids)
    audit(
        access,
        "members.edit",
        staff,
        {
            "before": before,
            "after": {"display_name": staff.display_name, "role": staff.role, "brand_ids": ids},
        },
    )
    access.session.commit()
    return view(access.session, staff)


def set_active(access, identity, active):
    staff = begin(access, identity)
    if not active:
        if staff.id == access.staff.id:
            raise HTTPException(409, "管理員不可停用自己")
        protect_admin(access.session, staff)
        access.session.execute(delete(AuthSession).where(AuthSession.staff_id == staff.id))
        from app.services.agent_auth import revoke_all

        revoke_all(access.session, staff.id, access.staff.id)
    staff.active = active
    audit(access, "members.state", staff, {"active": active, "sessions_revoked": not active})
    access.session.commit()
    return view(access.session, staff)


def reset_password(access, identity):
    staff = begin(access, identity)
    password = rotate_password(access.session, staff, access.staff.id)
    audit(access, "members.password_reset", staff, {"sessions_revoked": True})
    access.session.commit()
    return {"member": view(access.session, staff), "temporary_password": password}

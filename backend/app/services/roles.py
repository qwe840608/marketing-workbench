"""成員角色與功能權限：內建角色寫死在程式裡，自訂角色存在 roles 表。"""

from fastapi import HTTPException
from sqlalchemy import func, select

from app.models import AuditLog, Role, Staff

# 可勾選的功能權限。成員管理、復原碼與「看得到全部品牌」只屬於內建管理員，
# 不開放勾選，避免自訂角色替自己升級成管理員。
PERMISSIONS = (
    "posts.sync",
    "reports.export",
    "ideation.edit",
    "publish.edit",
    "publish.submit",
    "connections.manage",
    "ai.manage",
    "settings.manage",
)

BUILTIN = {
    "admin": PERMISSIONS,
    "marketing": (
        "posts.sync", "reports.export", "ideation.edit", "publish.edit", "publish.submit"
    ),
    "viewer": (),
}

# 送出發佈前一定要能編輯草稿，否則前端看不到草稿也無從確認內容。
REQUIRES = {"publish.submit": "publish.edit"}

MAX_CUSTOM_ROLES = 50


def custom_role(session, key):
    return session.scalar(select(Role).where(Role.key == key))


def permissions_of(session, staff) -> frozenset[str]:
    if staff.role in BUILTIN:
        return frozenset(BUILTIN[staff.role])
    role = custom_role(session, staff.role)
    # 找不到角色（例如被刪除的舊資料）一律視為沒有任何權限。
    return frozenset(p for p in (role.permissions if role else ()) if p in PERMISSIONS)


def role_name(session, key):
    """自訂角色回傳名稱；內建角色回傳 None，由前端依語言翻譯。"""
    if key in BUILTIN:
        return None
    role = custom_role(session, key)
    return role.name if role else None


def can(access, permission) -> bool:
    return permission in permissions_of(access.session, access.staff)


def require(access, permission, message="此帳號沒有這項功能的權限"):
    if not can(access, permission):
        raise HTTPException(403, message)


def can_write(session, staff) -> bool:
    return bool(permissions_of(session, staff))


def exists(session, key) -> bool:
    return key in BUILTIN or custom_role(session, key) is not None


def normalize(permissions):
    chosen = set(permissions)
    unknown = chosen - set(PERMISSIONS)
    if unknown:
        raise HTTPException(422, "權限清單包含不存在的項目")
    for permission, needed in REQUIRES.items():
        if permission in chosen:
            chosen.add(needed)
    return [p for p in PERMISSIONS if p in chosen]


def member_counts(session):
    rows = session.execute(select(Staff.role, func.count()).group_by(Staff.role))
    return {key: count for key, count in rows}


def listing(session):
    counts = member_counts(session)
    builtin = [
        {"id": None, "key": key, "name": None, "builtin": True,
         "permissions": list(perms), "member_count": counts.get(key, 0)}
        for key, perms in BUILTIN.items()
    ]
    custom = [
        {"id": role.id, "key": role.key, "name": role.name, "builtin": False,
         "permissions": normalize(p for p in role.permissions if p in PERMISSIONS),
         "member_count": counts.get(role.key, 0)}
        for role in session.scalars(select(Role).order_by(Role.id))
    ]
    return {"permissions": list(PERMISSIONS), "roles": builtin + custom}


def audit(access, action, role, detail):
    access.session.add(
        AuditLog(actor=f"staff:{access.staff.id}", action=action, target_type="role",
                 target_id=role.id, detail_json=detail)
    )


def unique_name(session, name, identity=None):
    folded = name.casefold()
    for role in session.scalars(select(Role)):
        if role.id != identity and role.name.casefold() == folded:
            raise HTTPException(409, "已有同名的角色")


def begin(access):
    from app.services.members import begin as begin_members

    begin_members(access)


def create(access, body):
    begin(access)
    session = access.session
    if session.scalar(select(func.count()).select_from(Role)) >= MAX_CUSTOM_ROLES:
        raise HTTPException(409, "自訂角色已達上限")
    unique_name(session, body.name)
    role = Role(key="pending", name=body.name, permissions=normalize(body.permissions))
    session.add(role)
    session.flush()
    role.key = f"custom_{role.id}"
    audit(access, "roles.create", role, {"name": role.name, "permissions": role.permissions})
    session.commit()
    return find(session, role.id)


def get(session, identity):
    role = session.get(Role, identity)
    if role is None:
        raise HTTPException(404, "找不到角色")
    return role


def find(session, identity):
    return next(r for r in listing(session)["roles"] if r["id"] == identity)


def edit(access, identity, body):
    begin(access)
    session = access.session
    role = get(session, identity)
    unique_name(session, body.name, identity)
    before = {"name": role.name, "permissions": list(role.permissions)}
    role.name, role.permissions = body.name, normalize(body.permissions)
    audit(access, "roles.edit", role,
          {"before": before, "after": {"name": role.name, "permissions": role.permissions}})
    session.commit()
    return find(session, role.id)


def delete(access, identity):
    begin(access)
    session = access.session
    role = get(session, identity)
    if session.scalar(select(func.count()).select_from(Staff).where(Staff.role == role.key)):
        raise HTTPException(409, "仍有成員使用此角色，請先改成其他角色")
    audit(access, "roles.delete", role, {"name": role.name, "permissions": role.permissions})
    session.delete(role)
    session.commit()


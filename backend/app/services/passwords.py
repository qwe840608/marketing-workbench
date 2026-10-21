import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from pydantic import SecretStr, ValidationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import ensure_write
from app.models import AuditLog, AuthSession, Staff
from app.schemas.members import MemberCreate

hasher = PasswordHasher()
_dummy_hash = hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: SecretStr) -> str:
    value = password.get_secret_value()
    if not 12 <= len(value) <= 128:
        raise ValueError("密碼長度必須為 12–128 個字元")
    return hasher.hash(value)


def verify_password(password: SecretStr, password_hash: str | None) -> bool:
    try:
        valid = hasher.verify(password_hash or _dummy_hash, password.get_secret_value())
    except (VerificationError, InvalidHashError):
        return False
    return valid and password_hash is not None


def find_staff(session: Session, username: str) -> Staff | None:
    # 與登入相同的比對方式（去空白、不分大小寫），避免能登入卻找不到帳號。
    normalized = username.strip().casefold()
    return next(
        (
            person
            for person in session.scalars(select(Staff))
            if person.username.casefold() == normalized
        ),
        None,
    )


def set_password(session: Session, username: str, password: SecretStr) -> None:
    ensure_write(session)
    staff = find_staff(session, username)
    if staff is None:
        raise ValueError("找不到帳號，請確認帳號名稱")
    staff.password_hash = hash_password(password)
    staff.must_change_password = False
    import hashlib

    from app.models.auth import LoginGuard

    key = hashlib.sha256(staff.username.casefold().encode("utf-8")).hexdigest()
    guard = session.scalar(select(LoginGuard).where(LoginGuard.account_key == key))
    if guard is not None:
        guard.failures, guard.locked_until = 0, None
        session.add(
            AuditLog(
                actor="local:password_setup",
                action="auth.login_unlocked",
                target_type="staff",
                target_id=staff.id,
            )
        )
    session.execute(delete(AuthSession).where(AuthSession.staff_id == staff.id))
    session.add(
        AuditLog(
            actor="local:password_setup",
            action="auth.password_set",
            target_type="staff",
            target_id=staff.id,
            detail_json={"sessions_revoked": True},
        )
    )


def initialize_password(session: Session, staff: Staff, password: SecretStr | None) -> None:
    if password is None or staff.password_hash is not None:
        return
    staff.password_hash = hash_password(password)
    session.add(
        AuditLog(
            actor="local:initial_setup",
            action="auth.password_initialized",
            target_type="staff",
            target_id=staff.id,
        )
    )


def create_admin(session: Session, username: str, password: SecretStr) -> Staff:
    ensure_write(session)
    if session.scalar(select(Staff.id).limit(1)) is not None:
        raise ValueError("首次管理員建立只允許空白使用者資料表；既有帳號請用密碼設定")
    # 沿用成員 API 的帳號驗證，CLI 與 UI 建立的帳號格式一致。
    try:
        username = MemberCreate(username=username, display_name=username, role="admin").username
    except ValidationError:
        raise ValueError("帳號名稱須為 1–80 個字元") from None
    staff = Staff(username=username, display_name=username, role="admin")
    session.add(staff)
    session.flush()
    initialize_password(session, staff, password)
    return staff

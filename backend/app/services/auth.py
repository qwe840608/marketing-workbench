import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, field
from datetime import timedelta
from urllib.parse import urlsplit

from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy import delete, false, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import ensure_write
from app.models import AuditLog, AuthSession, Staff
from app.models.auth import LoginGuard
from app.models.base import utc_now
from app.services.passwords import hasher, verify_password

COOKIE_NAME = "mwb_session"


@dataclass
class SessionCredentials:
    token: str = field(repr=False)
    csrf_token: str = field(repr=False)
    max_age: int


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def csrf_for(token: str) -> str:
    # session token 本身為 256 位元隨機值；CSRF 另行衍生，不能反推出 cookie。
    return hmac.new(token.encode("ascii"), b"mwb-csrf-v1", hashlib.sha256).hexdigest()


def lock_session_write(session: Session) -> None:
    # WAL 的讀取快照無法在其他連線寫入後升級；先取得寫鎖，驗證與輪替才能原子完成。
    ensure_write(session)
    session.execute(update(AuthSession).where(false()).values(expires_at=AuthSession.expires_at))


def find_session(session: Session, token: str | None) -> AuthSession | None:
    if token is None or re.fullmatch(r"[A-Za-z0-9_-]{43}", token) is None:
        return None
    return session.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == token_hash(token), AuthSession.expires_at > utc_now()
        )
    )


def issue_session(session: Session, settings: Settings, staff_id: int | None) -> SessionCredentials:
    now = utc_now()
    session.execute(delete(AuthSession).where(AuthSession.expires_at <= now))
    token = secrets.token_urlsafe(32)
    max_age = settings.session_ttl_seconds if staff_id is not None else 1800
    session.add(
        AuthSession(
            token_hash=token_hash(token),
            staff_id=staff_id,
            expires_at=now + timedelta(seconds=max_age),
        )
    )
    return SessionCredentials(token=token, csrf_token=csrf_for(token), max_age=max_age)


def bootstrap_csrf(session: Session, settings: Settings, token: str | None) -> SessionCredentials:
    lock_session_write(session)
    current = find_session(session, token)
    if current is not None:
        return SessionCredentials(
            token=token,
            csrf_token=csrf_for(token),
            max_age=max(1, int((current.expires_at - utc_now()).total_seconds())),
        )
    credentials = issue_session(session, settings, None)
    session.commit()
    return credentials


def validate_origin(origin: str | None, fetch_site: str | None, settings: Settings) -> None:
    if fetch_site == "cross-site" or (origin is not None and origin not in settings.app_origins):
        raise HTTPException(403, "請求來源不允許")


def secure_cookie(settings: Settings, request_origin: str) -> bool:
    parts = urlsplit(request_origin)
    # 只為明列的 loopback HTTP 放寬；HTTPS 一律 Secure，cookie 不設定 Domain。
    if (
        parts.scheme == "http"
        and parts.hostname in {"127.0.0.1", "localhost", "::1"}
        and request_origin in settings.app_origins
    ):
        return False
    return settings.session_cookie_secure or parts.scheme == "https"


def require_csrf(session: Session, token: str | None, supplied: str | None) -> AuthSession:
    current = find_session(session, token)
    if (
        current is None
        or supplied is None
        or re.fullmatch(r"[a-f0-9]{64}", supplied) is None
        or not hmac.compare_digest(csrf_for(token), supplied)
    ):
        raise HTTPException(403, "安全驗證失敗，請重新取得 CSRF token")
    return current


def current_staff(session: Session, token: str | None) -> Staff:
    current = find_session(session, token)
    staff = session.get(Staff, current.staff_id) if current and current.staff_id else None
    if staff is None or not staff.active or staff.password_hash is None:
        raise HTTPException(401, "請先登入")
    return staff


def login(
    session: Session,
    settings: Settings,
    token: str | None,
    csrf: str | None,
    username: str,
    password: SecretStr,
) -> tuple[Staff, SessionCredentials]:
    lock_session_write(session)
    current = require_csrf(session, token, csrf)
    normalized = username.strip().casefold()
    staff = next(
        (
            person
            for person in session.scalars(select(Staff))
            if person.username.casefold() == normalized
        ),
        None,
    )
    key = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    guard = session.scalar(select(LoginGuard).where(LoginGuard.account_key == key))
    if guard is None:
        guard = LoginGuard(account_key=key, failures=0)
        session.add(guard)
    now = utc_now()
    if guard.locked_until is not None and guard.locked_until > now:
        # 鎖定期間也跑相同的密碼驗證，未知帳號同樣使用 dummy hash。
        verify_password(password, staff.password_hash if staff else None)
        session.commit()
        raise HTTPException(401, "帳號或密碼不正確")
    if guard.locked_until is not None:
        guard.failures, guard.locked_until = 0, None
        session.add(
            AuditLog(
                actor="anonymous",
                action="auth.login_unlocked",
                target_type="staff",
                target_id=staff.id if staff else None,
            )
        )
    valid = verify_password(password, staff.password_hash if staff else None)
    if not valid or staff is None or not staff.active:
        guard.failures += 1
        if guard.failures >= 5:
            guard.locked_until = now + timedelta(minutes=15)
            session.add(
                AuditLog(
                    actor="anonymous",
                    action="auth.login_locked",
                    target_type="staff",
                    target_id=staff.id if staff else None,
                )
            )
        session.add(
            AuditLog(
                actor="anonymous",
                action="auth.login_failed",
                target_type="staff",
                target_id=staff.id if staff else None,
            )
        )
        session.commit()
        raise HTTPException(401, "帳號或密碼不正確")
    guard.failures = 0
    if hasher.check_needs_rehash(staff.password_hash):
        staff.password_hash = hasher.hash(password.get_secret_value())
    session.delete(current)
    credentials = issue_session(session, settings, staff.id)
    session.add(
        AuditLog(
            actor=f"staff:{staff.id}",
            action="auth.login",
            target_type="staff",
            target_id=staff.id,
        )
    )
    session.commit()
    return staff, credentials


def logout(session: Session, token: str | None, csrf: str | None) -> None:
    lock_session_write(session)
    staff = current_staff(session, token)
    current = require_csrf(session, token, csrf)
    session.delete(current)
    session.add(
        AuditLog(
            actor=f"staff:{staff.id}",
            action="auth.logout",
            target_type="staff",
            target_id=staff.id,
        )
    )
    session.commit()


def change_password(session, token, csrf, body):
    from app.services.members import staff_view
    from app.services.passwords import hash_password

    lock_session_write(session)
    staff = current_staff(session, token)
    current = require_csrf(session, token, csrf)
    if not verify_password(body.current_password, staff.password_hash):
        raise HTTPException(422, "目前密碼不正確")
    if hmac.compare_digest(
        body.current_password.get_secret_value().encode("utf-8"),
        body.new_password.get_secret_value().encode("utf-8"),
    ):
        raise HTTPException(422, "新密碼不可與目前密碼相同")
    staff.password_hash = hash_password(body.new_password)
    staff.must_change_password = False
    from app.services.agent_auth import revoke_all

    revoke_all(session, staff.id)
    session.execute(
        delete(AuthSession).where(AuthSession.staff_id == staff.id, AuthSession.id != current.id)
    )
    session.add(
        AuditLog(
            actor=f"staff:{staff.id}",
            action="auth.password_changed",
            target_type="staff",
            target_id=staff.id,
            detail_json={"other_sessions_revoked": True},
        )
    )
    session.commit()
    return staff_view(session, staff)


def set_language(session: Session, token: str | None, csrf: str | None, language: str) -> dict:
    """所有角色（含檢視者）都能改自己的介面語言，所以不走只允許寫入角色的 Access。"""
    from app.services.members import staff_view

    lock_session_write(session)
    staff = current_staff(session, token)
    require_csrf(session, token, csrf)
    staff.language = language
    session.commit()
    return staff_view(session, staff)


RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
RECOVERY_FAILURE = "帳號或復原碼不正確"


def normalize_recovery_code(code: str) -> str:
    # 使用者可能抄寫成小寫或省略分隔線；比對前統一格式。
    return re.sub(r"[^A-Z0-9]", "", code.upper())


def recovery_status(staff: Staff) -> dict:
    return {
        "configured": staff.recovery_code_hash is not None,
        "created_at": staff.recovery_code_created_at,
    }


def create_recovery_code(session: Session, staff: Staff, current_password: SecretStr) -> dict:
    """產生新的一次性復原碼並使舊碼失效；明碼只在此回應出現一次。"""
    ensure_write(session)
    if not verify_password(current_password, staff.password_hash):
        raise HTTPException(422, "目前密碼不正確")
    # 20 個字元、每字 5 位元，共 100 位元；加上登入鎖定，無法線上猜中。
    raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(20))
    staff.recovery_code_hash = hasher.hash(raw)
    staff.recovery_code_created_at = utc_now()
    session.add(
        AuditLog(
            actor=f"staff:{staff.id}",
            action="auth.recovery_code_created",
            target_type="staff",
            target_id=staff.id,
        )
    )
    session.commit()
    code = "-".join(raw[index : index + 5] for index in range(0, 20, 5))
    return {"recovery_code": code, **recovery_status(staff)}


def recover_password(
    session: Session,
    token: str | None,
    csrf: str | None,
    username: str,
    recovery_code: SecretStr,
    new_password: SecretStr,
) -> None:
    """忘記密碼的管理員以復原碼重設密碼；與登入共用失敗鎖定，錯誤訊息不透露帳號是否存在。"""
    from app.services.agent_auth import revoke_all
    from app.services.passwords import hash_password

    lock_session_write(session)
    require_csrf(session, token, csrf)
    normalized = username.strip().casefold()
    staff = next(
        (
            person
            for person in session.scalars(select(Staff))
            if person.username.casefold() == normalized
        ),
        None,
    )
    eligible = staff is not None and staff.active and staff.role == "admin"
    stored = staff.recovery_code_hash if eligible else None
    key = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    guard = session.scalar(select(LoginGuard).where(LoginGuard.account_key == key))
    if guard is None:
        guard = LoginGuard(account_key=key, failures=0)
        session.add(guard)
    now = utc_now()
    code = SecretStr(normalize_recovery_code(recovery_code.get_secret_value()))
    # 無論帳號是否存在或已鎖定，都跑一次雜湊驗證，回應時間不洩漏差異。
    valid = verify_password(code, stored if len(code.get_secret_value()) == 20 else None)
    locked = guard.locked_until is not None and guard.locked_until > now
    if locked or not valid:
        if not locked:
            if guard.locked_until is not None:
                guard.failures, guard.locked_until = 0, None
            guard.failures += 1
            if guard.failures >= 5:
                guard.locked_until = now + timedelta(minutes=15)
                session.add(
                    AuditLog(
                        actor="anonymous",
                        action="auth.login_locked",
                        target_type="staff",
                        target_id=staff.id if staff else None,
                    )
                )
            session.add(
                AuditLog(
                    actor="anonymous",
                    action="auth.recovery_failed",
                    target_type="staff",
                    target_id=staff.id if staff else None,
                )
            )
        session.commit()
        raise HTTPException(401, RECOVERY_FAILURE)
    try:
        password_hash = hash_password(new_password)
    except ValueError as error:
        session.rollback()
        raise HTTPException(422, str(error)) from error
    staff.password_hash = password_hash
    staff.must_change_password = False
    # 復原碼只能用一次；要再保留復原途徑須登入後重新產生。
    staff.recovery_code_hash = None
    staff.recovery_code_created_at = None
    guard.failures, guard.locked_until = 0, None
    revoke_all(session, staff.id)
    session.execute(delete(AuthSession).where(AuthSession.staff_id == staff.id))
    session.add(
        AuditLog(
            actor="anonymous",
            action="auth.password_recovered",
            target_type="staff",
            target_id=staff.id,
            detail_json={"sessions_revoked": True, "recovery_code_consumed": True},
        )
    )
    session.commit()

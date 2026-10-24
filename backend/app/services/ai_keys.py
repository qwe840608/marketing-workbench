"""Only this module resolves AI credentials; database values never leave as plaintext."""

import hashlib
import secrets
from datetime import timedelta

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import build_engine
from app.logging_config import log_failure
from app.models import AICredential, AIKeyVerification, PlatformCredential
from app.models.base import utc_now
from app.services import roles
from app.services.posts import _begin_ingest

PROVIDERS = ("openai", "gemini", "anthropic", "jev")
PREFIXES = {"openai": "sk-proj-", "gemini": "AIza", "anthropic": "sk-ant-", "jev": ""}


def provider_name(provider):
    provider = provider.removesuffix("_api")
    if provider not in PROVIDERS:
        raise HTTPException(422, "不支援的供應商")
    return provider


def cipher(settings):
    try:
        return Fernet(settings.account_encryption_key.get_secret_value().encode())
    except (AttributeError, ValueError):
        raise HTTPException(503, "加密主金鑰未設定或無效，請由管理員確認") from None


def decrypt(value, settings):
    try:
        return SecretStr(cipher(settings).decrypt(value.encode()).decode())
    except (InvalidToken, UnicodeError):
        raise HTTPException(503, "金鑰無法解密，請重新輸入或還原原主金鑰") from None


def resolve(provider, settings, session=None, *, candidate=None):
    provider = provider_name(provider)
    if candidate is not None:
        return candidate
    if provider == "jev":
        from app.services.credentials import resolve as resolve_credential

        return resolve_credential("JEV_API_KEY", settings, session)
    if session is None:
        if not settings.database_path.exists():
            return getattr(settings, provider + "_api_key")
        engine = build_engine(settings)
        try:
            with Session(engine) as own:
                return resolve(provider, settings, own)
        finally:
            engine.dispose()
    row = session.scalar(select(AICredential).where(AICredential.provider == provider))
    if row:
        return decrypt(row.encrypted_key, settings)
    return getattr(settings, provider + "_api_key")


def mask(provider, key):
    if not key:
        return None
    raw = key.get_secret_value()
    prefix = PREFIXES[provider] if raw.startswith(PREFIXES[provider]) else ""
    return prefix + "••••" + (raw[-4:] if len(raw) >= 12 else "")


def require_admin(access):
    if not roles.can(access, "ai.manage"):
        raise HTTPException(403, "僅管理員可管理 API 金鑰")


def key_query(provider):
    if provider == "jev":
        return select(PlatformCredential).where(PlatformCredential.provider == "JEV_API_KEY")
    return select(AICredential).where(AICredential.provider == provider)


def listing(access, settings):
    require_admin(access)
    items = []
    for provider in PROVIDERS:
        row = access.session.scalar(key_query(provider))
        error = None
        try:
            key = resolve(provider, settings, access.session)
        except HTTPException:
            key, error = None, "無法解密，請替換金鑰"
        items.append(
            dict(
                provider=provider,
                source="UI" if row and row.encrypted_key else ".env" if key else "未設定",
                mask=mask(provider, key),
                version=row.version if row else 0,
                error=error,
            )
        )
    return items


def probe(provider, key, settings):
    """One bounded official request, no retries, redirects, URL credentials or raw errors."""
    provider = provider_name(provider)
    key = resolve(provider, settings, candidate=key)
    if not key:
        raise HTTPException(422, "尚未設定金鑰")
    raw = key.get_secret_value()
    try:
        if provider == "jev":
            from app.services import credentials, jev
            from app.services.redact import scrub

            questions = {"connection": {"type": "noul", "instructions": "Is the state OK?"}}
            status, data, _ = jev.post_json(
                credentials.resolve("JEV_API_BASE_URL", settings) + "/systemone",
                raw,
                scrub({"model": settings.jev_model, "state": "OK", "questions": questions}),
                15,
            )
            valid = status == 200 and jev.valid_response(data, questions)
        else:
            endpoints = {
                "openai": ("https://api.openai.com/v1/models", {"Authorization": "Bearer " + raw}),
                "gemini": (
                    "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1",
                    {"x-goog-api-key": raw},
                ),
                "anthropic": (
                    "https://api.anthropic.com/v1/models?limit=1",
                    {"x-api-key": raw, "anthropic-version": "2023-06-01"},
                ),
            }
            url, headers = endpoints[provider]
            with httpx.Client(timeout=15, trust_env=False, follow_redirects=False) as client:
                response = client.get(url, headers=headers)
                data = response.json()
                field = "models" if provider == "gemini" else "data"
                valid = (
                    response.status_code == 200
                    and isinstance(data, dict)
                    and isinstance(data.get(field), list)
                )
        if not valid:
            raise ValueError("connection_failed")
    except Exception as error:
        log_failure("mwb.ai_keys", "ai_keys_probe_failed", error)
        raise HTTPException(422, "連線測試失敗，請確認金鑰、API 權限與供應商服務狀態") from None


def test_connection(access, provider, body, settings):
    require_admin(access)
    provider = provider_name(provider)
    session = access.session
    row = session.scalar(key_query(provider))
    version = row.version if row else 0
    key = resolve(provider, settings, session, candidate=body.key)
    session.commit()
    probe(provider, key, settings)
    # Testing an existing credential does not copy .env values into persistent configuration.
    if body.key is None:
        return {"ok": True, "receipt": None, "mask": mask(provider, key)}
    encrypted = cipher(settings).encrypt(key.get_secret_value().encode()).decode()
    receipt = secrets.token_urlsafe(32)
    with session.begin():
        session.execute(delete(AIKeyVerification).where(AIKeyVerification.expires_at < utc_now()))
        session.execute(
            delete(AIKeyVerification).where(
                AIKeyVerification.staff_id == access.staff.id,
                AIKeyVerification.provider == provider,
            )
        )
        session.add(
            AIKeyVerification(
                provider=provider,
                staff_id=access.staff.id,
                receipt_hash=hashlib.sha256(receipt.encode()).hexdigest(),
                encrypted_key=encrypted,
                base_version=version,
                expires_at=utc_now() + timedelta(minutes=5),
            )
        )
    return {"ok": True, "receipt": receipt, "mask": mask(provider, key)}


def save(access, provider, body, settings):
    require_admin(access)
    provider = provider_name(provider)
    session, staff_id = access.session, access.staff.id
    session.commit()
    with session.begin():
        audit = _begin_ingest(session, "ai.key.save")
        verification = session.scalar(
            select(AIKeyVerification).where(
                AIKeyVerification.receipt_hash == hashlib.sha256(body.receipt.encode()).hexdigest(),
                AIKeyVerification.staff_id == staff_id,
                AIKeyVerification.provider == provider,
            )
        )
        if not verification or verification.expires_at <= utc_now():
            raise HTTPException(409, "連線驗證已失效，請重新測試")
        row = session.scalar(key_query(provider))
        if (row.version if row else 0) != verification.base_version:
            raise HTTPException(409, "金鑰設定已變更，請重新測試")
        decrypt(verification.encrypted_key, settings)
        if row:
            row.encrypted_key = verification.encrypted_key
        else:
            model = PlatformCredential if provider == "jev" else AICredential
            session.add(
                model(
                    provider="JEV_API_KEY" if provider == "jev" else provider,
                    encrypted_key=verification.encrypted_key,
                )
            )
        session.delete(verification)
        audit.actor = f"staff:{staff_id}"
        audit.detail_json = {"provider": provider, "operation": "replace" if row else "create"}
    return listing(access, settings)


def remove(access, provider, version, settings):
    require_admin(access)
    provider = provider_name(provider)
    session, staff_id = access.session, access.staff.id
    session.commit()
    with session.begin():
        audit = _begin_ingest(session, "ai.key.delete")
        row = session.scalar(key_query(provider))
        if not row or row.version != version:
            raise HTTPException(409, "金鑰設定已變更，請重新整理")
        if provider == "jev":
            row.encrypted_key = ""
        else:
            session.delete(row)
        session.execute(delete(AIKeyVerification).where(AIKeyVerification.provider == provider))
        audit.actor = f"staff:{staff_id}"
        audit.detail_json = {"provider": provider}
    return listing(access, settings)

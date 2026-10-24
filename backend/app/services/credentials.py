"""One live source for platform credentials. Only masked values leave this service."""

import re

import httpx
from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import build_engine
from app.logging_config import log_failure
from app.models import PlatformCredential
from app.services import graph_api, roles
from app.services.posts import _begin_ingest

GROUPS = {
    "meta": (
        "META_APP_ID",
        "META_APP_SECRET",
        "META_VERIFY_TOKEN",
        "META_PAGE_ID",
        "META_PAGE_ACCESS_TOKEN",
        "META_USER_ACCESS_TOKEN",
        "META_IG_ACCOUNT_ID",
    ),
    "notify": (
        "NOTIFY_LINE_CHANNEL_ACCESS_TOKEN",
        "NOTIFY_LINE_CHANNEL_SECRET",
        "NOTIFY_LINE_BOT_USER_ID",
        "NOTIFY_LINE_GROUP_ID",
    ),
    "threads": ("THREADS_APP_ID", "THREADS_APP_SECRET", "THREADS_USER_ID", "THREADS_ACCESS_TOKEN"),
    "youtube": (
        "YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_CHANNEL_ID",
        "YOUTUBE_ACCESS_TOKEN", "YOUTUBE_REFRESH_TOKEN",
    ),
    "tiktok": (
        "TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_OPEN_ID",
        "TIKTOK_ACCESS_TOKEN", "TIKTOK_REFRESH_TOKEN",
    ),
    "jev": ("JEV_API_KEY", "JEV_API_BASE_URL"),
}
NAMES = tuple(name for names in GROUPS.values() for name in names)
_ENGINES = {}
PLAIN = {name for name in NAMES if name.endswith("_ID") or name.endswith("_URL")}


def checked_name(name):
    if name not in NAMES:
        raise HTTPException(422, "不支援的憑證欄位")
    return name


def row_for(session, name):
    return session.scalar(
        select(PlatformCredential)
        .where(PlatformCredential.provider == name)
        .execution_options(populate_existing=True)
    )


def resolve(name, settings, session=None):
    """DB override, then environment; no value cache, no database creation on lookup."""
    from app.services.ai_keys import decrypt

    checked_name(name)
    if session is None:
        path = getattr(settings, "database_path", None)
        if path is None or not path.exists():
            return getattr(settings, name.lower(), "" if name in PLAIN else None)
        # Webhooks and workers resolve several names per event; reuse one engine per database.
        engine = _ENGINES.get(path)
        if engine is None:
            engine = _ENGINES.setdefault(path, build_engine(settings))
        with Session(engine) as own:
            return resolve(name, settings, own)
    row = row_for(session, name)
    if row and row.encrypted_key:
        value = decrypt(row.encrypted_key, settings)
        return value.get_secret_value() if name in PLAIN else value
    return getattr(settings, name.lower(), "" if name in PLAIN else None)


def raw(value):
    return value.get_secret_value() if isinstance(value, SecretStr) else value or ""


def mask(value):
    value = raw(value)
    return (value[:4] + "••••" + value[-4:] if len(value) > 12 else "••••") if value else None


def require_admin(access):
    if not roles.can(access, "connections.manage"):
        raise HTTPException(403, "僅管理員可管理平台憑證")


def listing(access, settings):
    require_admin(access)
    items = []
    for name in NAMES:
        row = row_for(access.session, name)
        stored = bool(row and row.encrypted_key)
        error = None
        try:
            value = resolve(name, settings, access.session)
        except HTTPException:
            value, error = None, "無法解密，請更換憑證"
        items.append(
            dict(
                name=name,
                configured=stored or bool(value),
                source="DB" if stored else "env" if value else "未設定",
                mask=mask(value),
                version=row.version if row else 0,
                error=error,
            )
        )
    return {"items": items, "webhook_public_url": settings.webhook_public_url}


def validate(name, value):
    checked_name(name)
    value = raw(value)
    if not 1 <= len(value) <= 4096 or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise HTTPException(422, "憑證格式不正確")
    if name == "JEV_API_BASE_URL":
        if value.rstrip("/") != "https://api.typesafe.ai/v1":
            raise HTTPException(422, "jev 網址必須為官方 HTTPS 端點")
        return value.rstrip("/")
    ids = {"META_APP_ID", "META_PAGE_ID", "META_IG_ACCOUNT_ID", "THREADS_APP_ID", "THREADS_USER_ID"}
    if name in ids and not value.isdigit():
        raise HTTPException(422, "Meta ID 必須為數字")
    if name in {"NOTIFY_LINE_BOT_USER_ID", "NOTIFY_LINE_GROUP_ID"}:
        prefix = "C" if name.endswith("GROUP_ID") else "U"
        if not re.fullmatch(prefix + r"[a-f0-9]{32}", value):
            raise HTTPException(422, "LINE ID 格式不正確")
    return value


def save(access, name, body, settings):
    require_admin(access)
    value = validate(name, body.value)
    from app.services.ai_keys import cipher

    encrypted = cipher(settings).encrypt(value.encode()).decode()
    return change(access, name, body.version, encrypted, settings)


def remove(access, name, version, settings):
    require_admin(access)
    checked_name(name)
    return change(access, name, version, "", settings)


def change(access, name, version, encrypted, settings):
    session, staff_id = access.session, access.staff.id
    session.commit()
    with session.begin():
        audit = _begin_ingest(session, "credentials.save" if encrypted else "credentials.remove")
        row = row_for(session, name)
        if (row.version if row else 0) != version or (not encrypted and not row):
            raise HTTPException(409, "憑證設定已變更，請重新整理後再試")
        if row:
            if not encrypted and not row.encrypted_key:
                raise HTTPException(409, "憑證已移除，請重新整理")
            row.encrypted_key = encrypted
        else:
            session.add(PlatformCredential(provider=name, encrypted_key=encrypted))
        audit.actor = f"staff:{staff_id}"
        audit.detail_json = {"name": name, "operation": "save" if encrypted else "remove"}
    return listing(access, settings)


def probe(group, values, settings):
    """Bounded read-only platform request; no raw provider response or errors returned."""
    try:
        if group == "youtube":
            from app.services import youtube_oauth

            if not values["YOUTUBE_ACCESS_TOKEN"]:
                raise ValueError("missing_token")
            identity, _ = youtube_oauth.channel(values["YOUTUBE_ACCESS_TOKEN"])
            valid = identity == values["YOUTUBE_CHANNEL_ID"]
        elif group == "jev":
            from app.services import jev
            from app.services.redact import scrub

            key = values["JEV_API_KEY"]
            if not key:
                raise ValueError("missing_key")
            questions = {"connection": {"type": "noul", "instructions": "Is `status` OK?"}}
            status, data, _ = jev.post_json(
                values["JEV_API_BASE_URL"] + "/systemone",
                key,
                scrub(
                    {"model": settings.jev_model, "state": {"status": "OK"}, "questions": questions}
                ),
                15,
            )
            valid = status == 200 and jev.valid_response(data, questions)
        else:
            token_name = {
                "meta": "META_PAGE_ACCESS_TOKEN",
                "notify": "NOTIFY_LINE_CHANNEL_ACCESS_TOKEN",
                "threads": "THREADS_ACCESS_TOKEN",
            }[group]
            token = values[token_name] or (
                values["META_USER_ACCESS_TOKEN"] if group == "meta" else ""
            )
            if not token:
                raise ValueError("missing_token")
            url = (
                graph_api.FB + "/me?fields=id"
                if group == "meta"
                else "https://graph.threads.net/me?fields=id"
                if group == "threads"
                else "https://api.line.me/v2/bot/info"
            )
            with httpx.Client(timeout=15, trust_env=False, follow_redirects=False) as client:
                response = client.get(url, headers={"Authorization": "Bearer " + token})
                data = response.json()
                valid = (
                    response.status_code == 200
                    and isinstance(data, dict)
                    and bool(data.get("id" if group in {"meta", "threads"} else "userId"))
                )
        if not valid:
            raise ValueError("connection_failed")
        if group == "notify":
            return data["userId"]
    except Exception as error:
        log_failure("mwb.credentials", "credentials_probe_failed", error)
        raise HTTPException(422, "連線測試失敗，請確認憑證、權限與平台服務狀態") from None


def test_connection(access, group, body, settings):
    require_admin(access)
    if group not in GROUPS or any(name not in GROUPS[group] for name in body.values):
        raise HTTPException(422, "不支援的平台或憑證欄位")
    values = {
        name: validate(name, body.values[name])
        if name in body.values
        else raw(resolve(name, settings, access.session))
        for name in GROUPS[group]
    }
    session, staff_id = access.session, access.staff.id
    session.commit()
    with session.begin():
        audit = _begin_ingest(session, "credentials.test")
        audit.actor = f"staff:{staff_id}"
        audit.detail_json = {"group": group}
    identity = probe(group, values, settings)
    # LINE 回傳的官方帳號 userId 即正確值：空白或不符時自動寫入，不必手動查 Get bot info。
    if (
        group == "notify"
        and isinstance(identity, str)
        and re.fullmatch(r"U[a-f0-9]{32}", identity)
        and values["NOTIFY_LINE_BOT_USER_ID"] != identity
    ):
        autofill(access, "NOTIFY_LINE_BOT_USER_ID", identity, settings)
        return {"ok": True, "filled": ["NOTIFY_LINE_BOT_USER_ID"]}
    return {"ok": True}


def autofill(access, name, value, settings):
    from app.services.ai_keys import cipher

    encrypted = cipher(settings).encrypt(value.encode()).decode()
    session = access.session
    with session.begin():
        audit = _begin_ingest(session, "credentials.save")
        row = row_for(session, name)
        if row:
            row.encrypted_key = encrypted
        else:
            session.add(PlatformCredential(provider=name, encrypted_key=encrypted))
        audit.actor = f"staff:{access.staff.id}"
        audit.detail_json = {"name": name, "operation": "autofill"}

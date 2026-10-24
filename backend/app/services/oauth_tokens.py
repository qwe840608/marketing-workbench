"""YouTube 與 TikTok 共用的「後端自動換發 access token」流程。

兩個平台都把 client 密鑰、帳號編號與權杖放在加密憑證，連線列只記到期時間與快取；
差別只在 secret 名稱、access token 到期時間存哪裡、容許偏移與換發回應的解析。
那些差異由各平台模組以 TokenPlatform 描述，這裡只寫一次流程：

- 連線列不存在、被標記 reconnect，或憑證摘要與連線列不符 → 要求重新連結。
- 權杖還有效就直接用；否則用 refresh token 換發。
- 換發被平台拒絕（invalid_grant）時，只在憑證沒換過的情況下標記 reconnect。
- 寫回時若摘要已變，代表同時有另一方先完成換發：應用程式與帳號沒變且新權杖仍有效就沿用，
  其餘情況視為憑證變更。
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select

from app.db import ensure_write
from app.models import Account
from app.models.base import utc_now
from app.services import credentials, data_retention
from app.services.oauth_core import (
    ProviderFailure,
    audit,
    connection,
    digest_credentials,
    put_secret,
    value,
)


@dataclass(frozen=True)
class Refreshed:
    """一次換發的結果；refresh 為 None 代表平台沒有換 refresh token。"""

    token: str
    access_expires: datetime
    refresh: str | None = None
    extra: Any = None


@dataclass(frozen=True)
class TokenPlatform:
    platform: str
    # 各平台模組本身：request／exchange 等會被測試替換，所以透過模組屬性呼叫而不是直接綁函式。
    module: Any
    token_url: str
    access_name: str
    refresh_name: str
    # 這些值在換發時不會變；不同代表憑證真的換了（例如改接另一個帳號）。
    identity_names: tuple[str, ...]
    app_names: tuple[str, ...]
    link_names: tuple[str, ...]
    secrets: tuple[str, ...]
    skew: timedelta
    reconnect_stage: str
    # 從換發回應取出權杖與到期時間；平台專屬的欄位檢查放在各模組。
    parse: Callable[[dict], Refreshed]
    # access token 的到期時間存在連線列的哪裡。
    access_expires: Callable[[Any], datetime | None]
    # 把換發結果寫回連線列（到期時間、快取、通知狀態）；secret 由這裡統一寫。
    store: Callable[[Any, Refreshed], None]


def identity_values(spec, session, settings):
    return [value(session, settings, name) for name in spec.identity_names]


def fresh(spec, row, now):
    expires = spec.access_expires(row) if row else None
    return bool(expires and expires > now + spec.skew)


def access_token(spec, factory, settings):
    """A valid access token, refreshing it (and rotating the refresh token) when needed."""
    with factory() as session:
        row = connection(session, spec.platform)
        if (
            not row
            or row.cache_json.get("reconnect")
            or row.credential_digest != digest_credentials(session, settings, spec.platform)
        ):
            raise ProviderFailure({"stage": spec.reconnect_stage})
        token = value(session, settings, spec.access_name)
        if token and fresh(spec, row, utc_now()):
            return token
        params = {
            **spec.module.app(session, settings),
            "grant_type": "refresh_token",
            "refresh_token": value(session, settings, spec.refresh_name),
        }
        digest, fixed = row.credential_digest, identity_values(spec, session, settings)
    try:
        refreshed = spec.parse(spec.module.request(spec.token_url, data=params))
    except ProviderFailure as error:
        if error.info.get("invalid_grant"):
            with factory.begin() as session:
                row = connection(session, spec.platform)
                if (
                    row
                    and row.credential_digest == digest
                    and digest_credentials(session, settings, spec.platform) == digest
                ):
                    row.cache_json = {**row.cache_json, "reconnect": True}
                    audit(session, spec.platform, "refresh_failed")
        raise
    with factory.begin() as session:
        row = connection(session, spec.platform)
        if (
            not row
            or row.credential_digest != digest
            or digest_credentials(session, settings, spec.platform) != digest
        ):
            current = value(session, settings, spec.access_name)
            if (
                row
                and current
                and not row.cache_json.get("reconnect")
                and row.credential_digest == digest_credentials(session, settings, spec.platform)
                and identity_values(spec, session, settings) == fixed
                and fresh(spec, row, utc_now())
            ):
                return current
            raise ProviderFailure({"stage": "credentials_changed"})
        put_secret(session, settings, spec.access_name, refreshed.token)
        if refreshed.refresh:
            put_secret(session, settings, spec.refresh_name, refreshed.refresh)
        spec.store(row, refreshed)
        row.refreshed_at, row.checked_at = utc_now(), None
        session.flush()
        row.credential_digest = digest_credentials(session, settings, spec.platform)
        audit(session, spec.platform, "refreshed")
    return refreshed.token


def link_state(spec, session, settings):
    """status() 共用的底：連線列、是否設定應用程式、是否已連結、連線列是否仍對應目前憑證。"""
    row = connection(session, spec.platform)
    configured = all(value(session, settings, n) for n in spec.app_names)
    linked = all(value(session, settings, n) for n in spec.link_names)
    valid = bool(
        row and row.credential_digest == digest_credentials(session, settings, spec.platform)
    )
    granted = row.granted_scopes if valid else []
    return row, configured, linked, valid, granted


def disconnect(spec, access, settings, revoke, finish_accounts):
    """撤銷授權、清除權杖與連線列、刪除依平台條款須刪除的資料。

    revoke(session) 由各平台呼叫自己的撤銷端點（可能什麼都不做）；
    finish_accounts(session, accounts) 處理帳號列的狀態與名稱。
    """
    credentials.require_admin(access)
    session = access.session
    digest = digest_credentials(session, settings, spec.platform)
    revoke(session)
    ensure_write(session)
    if digest_credentials(session, settings, spec.platform) != digest:
        raise HTTPException(409, "連結已變更，請重新整理")
    for name in spec.secrets:
        put_secret(session, settings, name, "")
    row = connection(session, spec.platform)
    if row:
        row.account_name, row.cache_json, row.granted_scopes = "", {}, []
        row.expires_at = None
        session.flush()
        row.credential_digest = digest_credentials(session, settings, spec.platform)
    # 平台條款：授權撤銷後刪除透過 API 取得的資料；帳號列保留給自己的發佈紀錄。
    accounts = list(session.scalars(select(Account).where(Account.platform == spec.platform)))
    removed = data_retention.apply(
        session, data_retention.plan(session, account_ids=[a.id for a in accounts])
    )
    finish_accounts(session, accounts)
    audit(session, spec.platform, "disconnected", f"staff:{access.staff.id}")
    session.commit()
    return {"ok": True, "removed": {k: removed[k] for k in ("posts", "messages", "reports")}}

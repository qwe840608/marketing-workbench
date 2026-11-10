"""X (Twitter) single-account authorization: OAuth 2.0 Authorization Code with PKCE.

The owner's client ID and secret (confidential client) live in encrypted credentials. Access
tokens last two hours and are refreshed on demand; X rotates the refresh token on every
refresh, so the new one must always be stored. X bills per request (prepaid credits), so this
module only calls the token, revoke and /2/users/me endpoints. See docs/en/platform-policies.md.
"""

import base64
import hashlib
import re
import secrets
import sys
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import HTTPException
from sqlalchemy import select

from app.models import Account
from app.models.base import utc_now
from app.services import oauth_tokens
from app.services.oauth_core import (
    ProviderFailure,
    connection,
    origin_info,
    put_secret,
    register_account,
    token_result,
    value,
)

# offline.access 才會發 refresh token；media.write 是 v2 媒體上傳需要的權限。
SCOPES = ("tweet.read", "tweet.write", "users.read", "media.write", "offline.access")
# 少了這些就無法自動換發或確認帳號，直接要求重新連結。
REQUIRED_SCOPES = frozenset({"users.read", "offline.access"})
PUBLISH_SCOPES = frozenset({"tweet.read", "tweet.write", "media.write"})
AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"
TOKEN_URL = "https://api.x.com/2/oauth2/token"
REVOKE_URL = "https://api.x.com/2/oauth2/revoke"
USER_URL = "https://api.x.com/2/users/me"
SECRETS = ("X_USER_ID", "X_ACCESS_TOKEN", "X_REFRESH_TOKEN")


def pkce_pair():
    """RFC 7636：verifier 只存在本機（加密），授權網址只帶 S256 challenge。"""
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge.decode().rstrip("=")


def request(url, *, data=None, token=None, params=None):
    if url not in {TOKEN_URL, REVOKE_URL, USER_URL}:
        raise ProviderFailure()
    data = dict(data) if data is not None else None
    auth = None
    if data is not None:
        # Confidential client：密鑰只放 Basic 驗證標頭，不放進表單內容。
        secret = data.pop("client_secret", "")
        auth = (data.get("client_id", ""), secret)
    try:
        with httpx.Client(timeout=15, trust_env=False, follow_redirects=False) as client:
            response = client.request(
                "POST" if data is not None else "GET",
                url,
                data=data,
                params=params,
                auth=auth,
                headers={"Authorization": "Bearer " + token} if token else {},
            )
        body = response.json() if response.content else {}
    except Exception:
        raise ProviderFailure({"stage": "x_transport"}) from None
    if response.status_code != 200 or not isinstance(body, dict) or body.get("errors"):
        error = body.get("error") if isinstance(body, dict) else None
        reason = error if isinstance(error, str) and re.fullmatch(r"[a-z_]{1,40}", error) else None
        # 權杖端點以 400 invalid_request／invalid_grant 表示 refresh token 已失效；
        # 資料端點 401 代表授權被撤銷。兩者都只能請使用者重新連結。
        invalid = response.status_code == 401 or (
            url == TOKEN_URL
            and response.status_code == 400
            and reason in {"invalid_grant", "invalid_request"}
        )
        raise ProviderFailure(
            {
                "stage": "x",
                "status": response.status_code,
                **({"code": reason} if reason else {}),
                "invalid_grant": invalid,
            }
        )
    return body


def app(session, settings):
    return {
        "client_id": value(session, settings, "X_CLIENT_ID"),
        "client_secret": value(session, settings, "X_CLIENT_SECRET"),
    }


def tokens(body):
    token, expires = token_result(body)
    refresh = body.get("refresh_token")
    if not isinstance(refresh, str) or not refresh or len(refresh) > 4096:
        raise ProviderFailure({"stage": "x_refresh_token"})
    return token, expires, refresh


def granted(body):
    scope = body.get("scope", "")
    values = scope.split() if isinstance(scope, str) else []
    return [s for s in SCOPES if s in values]


def profile(token):
    body = request(USER_URL, token=token)
    user = body.get("data") if isinstance(body.get("data"), dict) else None
    identity = user.get("id") if user else None
    if not isinstance(identity, str) or not re.fullmatch(r"\d{1,30}", identity):
        raise ProviderFailure({"stage": "x_profile"})
    username = str(user.get("username", ""))[:100]
    return identity, ("@" + username) if username else str(user.get("name", ""))[:200]


def exchange(session, settings, code, verifier):
    if not verifier:
        raise ProviderFailure({"stage": "x_pkce_missing"})
    params = {
        **app(session, settings),
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": origin_info(settings)["callbacks"]["x"],
        "code_verifier": verifier,
    }
    session.commit()
    body = request(TOKEN_URL, data=params)
    token, expires, refresh = tokens(body)
    scopes = granted(body)
    if not REQUIRED_SCOPES <= set(scopes):
        raise ProviderFailure({"stage": "x_permissions_required"})
    identity, name = profile(token)
    return dict(
        token=token,
        refresh=refresh,
        access_expires=expires.isoformat(),
        # refresh token 沒有公布的期限（每次換發都會換新），使用者這邊不顯示到期日。
        expires="",
        id=identity,
        name=name,
        scopes=scopes,
    )


def persist(session, settings, payload, row):
    identity = payload["id"]
    accounts = list(session.scalars(select(Account).where(Account.platform == "x")))
    if accounts and any(a.external_id != identity for a in accounts):
        raise HTTPException(409, "已登記另一個 X 帳號，請由管理員處理品牌帳號")
    for name, key in zip(SECRETS, ("id", "token", "refresh"), strict=True):
        put_secret(session, settings, name, payload[key])
    row.account_name = payload["name"]
    row.cache_json = {"access_expires_at": payload["access_expires"]}
    if accounts:
        accounts[0].name, accounts[0].status = payload["name"] or "X", "connected"
    else:
        register_account(session, "x", identity, payload["name"] or "X")


def access_expires(row):
    try:
        parsed = datetime.fromisoformat(row.cache_json.get("access_expires_at", ""))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def refreshed(body):
    token, expires, refresh = tokens(body)
    return oauth_tokens.Refreshed(token=token, access_expires=expires, refresh=refresh)


def store(row, result):
    row.notified_at = None
    row.cache_json = {"access_expires_at": result.access_expires.isoformat()}


SPEC = oauth_tokens.TokenPlatform(
    platform="x",
    module=sys.modules[__name__],
    token_url=TOKEN_URL,
    access_name="X_ACCESS_TOKEN",
    refresh_name="X_REFRESH_TOKEN",
    identity_names=("X_CLIENT_ID", "X_CLIENT_SECRET", "X_USER_ID"),
    app_names=("X_CLIENT_ID", "X_CLIENT_SECRET"),
    link_names=("X_USER_ID", "X_REFRESH_TOKEN"),
    secrets=SECRETS,
    skew=timedelta(minutes=5),
    reconnect_stage="x_reconnect",
    parse=refreshed,
    access_expires=access_expires,
    store=store,
)


def access_token(factory, settings):
    """A valid access token, refreshing it (and storing the rotated refresh token) when needed."""
    return oauth_tokens.access_token(SPEC, factory, settings)


def verify_identity(factory, settings):
    # /2/users/me 每次都會扣點數；只在使用者按「重新檢查」時呼叫。
    return profile(access_token(factory, settings))[0]


def status(session, settings):
    row, configured, linked, valid, granted_scopes = oauth_tokens.link_state(
        SPEC, session, settings
    )
    missing = sorted(set(SCOPES) - set(granted_scopes)) if linked else []
    reconnect = linked and (not valid or bool(row.cache_json.get("reconnect")))
    return dict(
        configured=configured,
        linked=linked,
        name=row.account_name if valid else "",
        ig_username="",
        expires_at=None,
        granted=list(granted_scopes),
        missing=missing,
        state="failed" if reconnect else "ready" if linked else "neutral",
        verified=not reconnect,
        expiring=False,
        expired=False,
        data_missing=[],
    )


def disconnect(access, settings):
    def revoke(session):
        params = app(session, settings)
        token = value(session, settings, "X_REFRESH_TOKEN") or value(
            session, settings, "X_ACCESS_TOKEN"
        )
        session.commit()
        if token and params["client_id"] and params["client_secret"]:
            try:
                # 撤銷 refresh token 會一併讓同一授權的 access token 失效。
                request(REVOKE_URL, data={**params, "token": token})
            except ProviderFailure as error:
                if not error.info.get("invalid_grant"):
                    raise HTTPException(422, "X 撤銷授權失敗，請稍後重試") from None

    def finish_accounts(session, accounts):
        for account in accounts:
            account.name, account.status = "X", "disconnected"

    return oauth_tokens.disconnect(SPEC, access, settings, revoke, finish_accounts)


def maintain(factory, settings, now=None):
    """Daily: refresh once so an idle refresh token stays alive, and warn on LINE when it fails."""
    now = now or utc_now()
    with factory() as session:
        row = connection(session, "x")
        if not row or not status(session, settings)["linked"]:
            return
    try:
        access_token(factory, settings)
        return
    except ProviderFailure:
        pass
    with factory.begin() as session:
        row = connection(session, "x")
        if not row or row.notified_at:
            return
        from app.services.notify import queue_oauth_notice

        if queue_oauth_notice(session, settings, "x", now):
            row.notified_at = now

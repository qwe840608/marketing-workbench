"""TikTok for Developers single-account authorization (unaudited / sandbox app).

The owner's client key and secret live in encrypted credentials. Access tokens last 24 hours
and are refreshed on demand; the refresh token's expiry is what the user sees, and LINE warns
14 days before it. See docs/en/platform-policies.md.
"""

import re
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

# 第一版只讀公開影片與粉絲數、送影片到收件匣；不送審，所以不要求 video.publish。
SCOPES = ("user.info.basic", "user.info.stats", "video.list", "video.upload")
# 同步影片必需的權限；其餘可由使用者在授權畫面取消，缺少時只停用對應功能。
READ_SCOPES = frozenset({"user.info.basic", "video.list"})
AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
REVOKE_URL = "https://open.tiktokapis.com/v2/oauth/revoke/"
USER_URL = "https://open.tiktokapis.com/v2/user/info/"
NOTICE_DAYS = 14
SECRETS = ("TIKTOK_OPEN_ID", "TIKTOK_ACCESS_TOKEN", "TIKTOK_REFRESH_TOKEN")


def request(url, *, data=None, token=None, params=None):
    if url not in {TOKEN_URL, REVOKE_URL, USER_URL}:
        raise ProviderFailure()
    try:
        with httpx.Client(timeout=15, trust_env=False, follow_redirects=False) as client:
            response = client.request(
                "POST" if data is not None else "GET",
                url,
                data=data,
                params=params,
                headers={"Authorization": "Bearer " + token} if token else {},
            )
        body = response.json() if response.content else {}
    except Exception:
        raise ProviderFailure({"stage": "tiktok_transport"}) from None
    # OAuth 端點錯誤是 {"error": "invalid_grant"}；資料端點成功時也帶 {"error": {"code": "ok"}}。
    error = body.get("error") if isinstance(body, dict) else "not_json"
    code = error.get("code") if isinstance(error, dict) else error
    if response.status_code != 200 or not isinstance(body, dict) or code not in (None, "", "ok"):
        reason = code if isinstance(code, str) and re.fullmatch(r"[a-z_]{1,40}", code) else None
        raise ProviderFailure(
            {
                "stage": "tiktok",
                "status": response.status_code,
                **({"code": reason} if reason else {}),
                "invalid_grant": reason in {"invalid_grant", "access_token_invalid"},
            }
        )
    return body


def app(session, settings):
    return {
        "client_key": value(session, settings, "TIKTOK_CLIENT_KEY"),
        "client_secret": value(session, settings, "TIKTOK_CLIENT_SECRET"),
    }


def tokens(body):
    """Validate a token response: access token, refresh token and both lifetimes."""
    token, expires = token_result(body)
    refresh = body.get("refresh_token")
    seconds = body.get("refresh_expires_in")
    if (
        not isinstance(refresh, str)
        or not refresh
        or len(refresh) > 4096
        or type(seconds) is not int
        or not 0 < seconds <= 400 * 86400
    ):
        raise ProviderFailure({"stage": "tiktok_refresh_token"})
    return token, expires, refresh, utc_now() + timedelta(seconds=seconds)


def granted(body):
    scope = body.get("scope", "")
    values = re.split(r"[,\s]+", scope) if isinstance(scope, str) else []
    return [s for s in SCOPES if s in values]


def profile(token):
    body = request(USER_URL, token=token, params={"fields": "open_id,display_name"})
    user = (body.get("data") or {}).get("user") if isinstance(body.get("data"), dict) else None
    identity = user.get("open_id") if isinstance(user, dict) else None
    if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", identity):
        raise ProviderFailure({"stage": "tiktok_profile"})
    return identity, str(user.get("display_name", ""))[:200]


def exchange(session, settings, code):
    params = {
        **app(session, settings),
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": origin_info(settings)["callbacks"]["tiktok"],
    }
    session.commit()
    body = request(TOKEN_URL, data=params)
    token, expires, refresh, refresh_expires = tokens(body)
    scopes = granted(body)
    # 少了讀取權限就無法同步數據；使用者在授權畫面取消勾選時直接要求重新連結。
    if not READ_SCOPES <= set(scopes):
        raise ProviderFailure({"stage": "tiktok_permissions_required"})
    identity, name = profile(token)
    if body.get("open_id") not in (None, identity):
        raise ProviderFailure({"stage": "tiktok_identity_mismatch"})
    return dict(
        token=token,
        refresh=refresh,
        access_expires=expires.isoformat(),
        # 使用者看到的到期時間是 refresh token 的期限，access token 由工作檯自動換發。
        expires=refresh_expires.isoformat(),
        id=identity,
        name=name,
        scopes=scopes,
    )


def persist(session, settings, payload, row):
    identity = payload["id"]
    accounts = list(session.scalars(select(Account).where(Account.platform == "tiktok")))
    if accounts and any(a.external_id != identity for a in accounts):
        # Do not attach another TikTok account's data to existing history.
        raise HTTPException(409, "已登記另一個 TikTok 帳號，請由管理員處理品牌帳號")
    for name, key in zip(SECRETS, ("id", "token", "refresh"), strict=True):
        put_secret(session, settings, name, payload[key])
    row.account_name = payload["name"]
    row.cache_json = {"access_expires_at": payload["access_expires"]}
    if accounts:
        accounts[0].name, accounts[0].status = payload["name"] or "TikTok", "connected"
    else:
        register_account(session, "tiktok", identity, payload["name"] or "TikTok")


def access_expires(row):
    """access token 到期時間存在快取（連線列的 expires_at 是使用者看到的 refresh token 期限）。"""
    try:
        parsed = datetime.fromisoformat(row.cache_json.get("access_expires_at", ""))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def refreshed(body):
    token, expires, refresh, refresh_expires = tokens(body)
    # TikTok 換發時可能給新的 refresh token；舊的隨即失效，所以一定要存新值。
    return oauth_tokens.Refreshed(
        token=token, access_expires=expires, refresh=refresh, extra=refresh_expires
    )


def store(row, result):
    refresh_expires = result.extra
    # 每天換發 access token 時 refresh token 的到期日通常不變；只有新到期日已離開提醒期，
    # 才清掉通知紀錄，否則剩不到 14 天時每天都會再發一次同樣的提醒。
    if refresh_expires >= utc_now() + timedelta(days=NOTICE_DAYS):
        row.notified_at = None
    row.expires_at = refresh_expires
    row.cache_json = {"access_expires_at": result.access_expires.isoformat()}


SPEC = oauth_tokens.TokenPlatform(
    platform="tiktok",
    module=sys.modules[__name__],
    token_url=TOKEN_URL,
    access_name="TIKTOK_ACCESS_TOKEN",
    refresh_name="TIKTOK_REFRESH_TOKEN",
    identity_names=("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_OPEN_ID"),
    app_names=("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET"),
    link_names=("TIKTOK_OPEN_ID", "TIKTOK_REFRESH_TOKEN"),
    secrets=SECRETS,
    skew=timedelta(minutes=5),
    reconnect_stage="tiktok_reconnect",
    parse=refreshed,
    access_expires=access_expires,
    store=store,
)


def access_token(factory, settings):
    """A valid access token, refreshing it (and rotating the refresh token) when needed."""
    return oauth_tokens.access_token(SPEC, factory, settings)


def verify_identity(factory, settings):
    """強制重新檢查時：換發權杖並確認仍是同一個帳號。"""
    return profile(access_token(factory, settings))[0]


def status(session, settings):
    row, configured, linked, valid, granted_scopes = oauth_tokens.link_state(
        SPEC, session, settings
    )
    missing = sorted(set(SCOPES) - set(granted_scopes)) if linked else []
    expires = row.expires_at if valid else None
    now = utc_now()
    expired = bool(linked and expires and expires <= now)
    expiring = bool(
        linked and expires and not expired and expires < now + timedelta(days=NOTICE_DAYS)
    )
    reconnect = linked and (not valid or bool(row.cache_json.get("reconnect")) or expired)
    return dict(
        configured=configured,
        linked=linked,
        name=row.account_name if valid else "",
        ig_username="",
        expires_at=expires.isoformat() if expires else None,
        granted=list(granted_scopes),
        missing=missing,
        state="failed"
        if reconnect
        else "pending"
        if expiring
        else "ready"
        if linked
        else "neutral",
        verified=not reconnect,
        expiring=expiring,
        expired=expired,
        data_missing=[],
    )


def disconnect(access, settings):
    def revoke(session):
        token = value(session, settings, "TIKTOK_ACCESS_TOKEN")
        params = {**app(session, settings), "token": token}
        session.commit()
        if token and params["client_key"] and params["client_secret"]:
            try:
                request(REVOKE_URL, data=params)
            except ProviderFailure as error:
                # 權杖已失效時 TikTok 那端早就沒有授權，照常清除本機資料；其他錯誤請使用者重試。
                if not error.info.get("invalid_grant"):
                    raise HTTPException(422, "TikTok 撤銷授權失敗，請稍後重試") from None

    def finish_accounts(session, accounts):
        for account in accounts:
            account.name, account.status = "TikTok", "disconnected"

    return oauth_tokens.disconnect(SPEC, access, settings, revoke, finish_accounts)


def maintain(factory, settings, now=None):
    """Daily: keep the access token fresh and warn on LINE before the refresh token expires."""
    now = now or utc_now()
    with factory() as session:
        row = connection(session, "tiktok")
        if not row or not status(session, settings)["linked"]:
            return
    try:
        access_token(factory, settings)
        failed = False
    except ProviderFailure:
        failed = True
    with factory.begin() as session:
        row = connection(session, "tiktok")
        item = status(session, settings)
        if not row or row.notified_at or not (failed or item["expiring"] or item["expired"]):
            return
        from app.services.notify import queue_oauth_notice

        if queue_oauth_notice(session, settings, "tiktok", now):
            row.notified_at = now

"""TikTok for Developers single-account authorization (unaudited / sandbox app).

The owner's client key and secret live in encrypted credentials. Access tokens last 24 hours
and are refreshed on demand; the refresh token's expiry is what the user sees, and LINE warns
14 days before it. See docs/TikTok規劃.md.
"""

import re
from datetime import timedelta

import httpx
from fastapi import HTTPException
from sqlalchemy import select

from app.db import ensure_write
from app.models import Account
from app.models.base import utc_now
from app.services import credentials, data_retention, oauth

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
        raise oauth.ProviderFailure()
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
        raise oauth.ProviderFailure({"stage": "tiktok_transport"}) from None
    # OAuth 端點錯誤是 {"error": "invalid_grant"}；資料端點成功時也帶 {"error": {"code": "ok"}}。
    error = body.get("error") if isinstance(body, dict) else "not_json"
    code = error.get("code") if isinstance(error, dict) else error
    if response.status_code != 200 or not isinstance(body, dict) or code not in (None, "", "ok"):
        reason = code if isinstance(code, str) and re.fullmatch(r"[a-z_]{1,40}", code) else None
        raise oauth.ProviderFailure(
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
        "client_key": oauth.value(session, settings, "TIKTOK_CLIENT_KEY"),
        "client_secret": oauth.value(session, settings, "TIKTOK_CLIENT_SECRET"),
    }


def authorize_params(session, settings, nonce):
    return {
        "client_key": oauth.value(session, settings, "TIKTOK_CLIENT_KEY"),
        "scope": ",".join(SCOPES),
        "response_type": "code",
        "redirect_uri": oauth.origin_info(settings)["callbacks"]["tiktok"],
        "state": nonce,
    }


def tokens(body):
    """Validate a token response: access token, refresh token and both lifetimes."""
    token, expires = oauth.token_result(body)
    refresh = body.get("refresh_token")
    seconds = body.get("refresh_expires_in")
    if (
        not isinstance(refresh, str)
        or not refresh
        or len(refresh) > 4096
        or type(seconds) is not int
        or not 0 < seconds <= 400 * 86400
    ):
        raise oauth.ProviderFailure({"stage": "tiktok_refresh_token"})
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
        raise oauth.ProviderFailure({"stage": "tiktok_profile"})
    return identity, str(user.get("display_name", ""))[:200]


def exchange(session, settings, code):
    params = {
        **app(session, settings),
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": oauth.origin_info(settings)["callbacks"]["tiktok"],
    }
    session.commit()
    body = request(TOKEN_URL, data=params)
    token, expires, refresh, refresh_expires = tokens(body)
    scopes = granted(body)
    # 少了讀取權限就無法同步數據；使用者在授權畫面取消勾選時直接要求重新連結。
    if not READ_SCOPES <= set(scopes):
        raise oauth.ProviderFailure({"stage": "tiktok_permissions_required"})
    identity, name = profile(token)
    if body.get("open_id") not in (None, identity):
        raise oauth.ProviderFailure({"stage": "tiktok_identity_mismatch"})
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
        oauth.put_secret(session, settings, name, payload[key])
    row.account_name = payload["name"]
    row.cache_json = {"access_expires_at": payload["access_expires"]}
    if accounts:
        accounts[0].name, accounts[0].status = payload["name"] or "TikTok", "connected"
    else:
        oauth.register_account(session, "tiktok", identity, payload["name"] or "TikTok")


def identity_values(session, settings):
    # 換發只會改 access／refresh token；這些值不同代表憑證真的換了。
    names = ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_OPEN_ID")
    return [oauth.value(session, settings, name) for name in names]


def access_token(factory, settings):
    """A valid access token, refreshing it (and rotating the refresh token) when needed."""
    with factory() as session:
        row = oauth.connection(session, "tiktok")
        if (
            not row
            or row.cache_json.get("reconnect")
            or row.credential_digest != oauth.digest_credentials(session, settings, "tiktok")
        ):
            raise oauth.ProviderFailure({"stage": "tiktok_reconnect"})
        token = oauth.value(session, settings, "TIKTOK_ACCESS_TOKEN")
        expires = row.cache_json.get("access_expires_at")
        if token and expires and expires > (utc_now() + timedelta(minutes=5)).isoformat():
            return token
        params = {
            **app(session, settings),
            "grant_type": "refresh_token",
            "refresh_token": oauth.value(session, settings, "TIKTOK_REFRESH_TOKEN"),
        }
        digest, fixed = row.credential_digest, identity_values(session, settings)
    try:
        token, access_expires, refresh, refresh_expires = tokens(request(TOKEN_URL, data=params))
    except oauth.ProviderFailure as error:
        if error.info.get("invalid_grant"):
            with factory.begin() as session:
                row = oauth.connection(session, "tiktok")
                if (
                    row
                    and row.credential_digest == digest
                    and oauth.digest_credentials(session, settings, "tiktok") == digest
                ):
                    row.cache_json = {**row.cache_json, "reconnect": True}
                    oauth.audit(session, "tiktok", "refresh_failed")
        raise
    with factory.begin() as session:
        row = oauth.connection(session, "tiktok")
        if (
            not row
            or row.credential_digest != digest
            or oauth.digest_credentials(session, settings, "tiktok") != digest
        ):
            # 同時換發時，先完成的一方已存入新權杖而改變摘要；應用程式與帳號沒變且新權杖
            # 仍有效就沿用，不誤判成憑證變更。其餘情況（重新連結到別處、已失效）照常報錯。
            current = oauth.value(session, settings, "TIKTOK_ACCESS_TOKEN")
            expires = row.cache_json.get("access_expires_at") if row else None
            if (
                row
                and current
                and expires
                and not row.cache_json.get("reconnect")
                and row.credential_digest == oauth.digest_credentials(session, settings, "tiktok")
                and identity_values(session, settings) == fixed
                and expires > (utc_now() + timedelta(minutes=5)).isoformat()
            ):
                return current
            raise oauth.ProviderFailure({"stage": "credentials_changed"})
        oauth.put_secret(session, settings, "TIKTOK_ACCESS_TOKEN", token)
        # TikTok 換發時可能給新的 refresh token；舊的隨即失效，所以一定要存新值。
        oauth.put_secret(session, settings, "TIKTOK_REFRESH_TOKEN", refresh)
        # 每天換發 access token 時 refresh token 的到期日通常不變；只有新到期日已離開提醒期，
        # 才清掉通知紀錄，否則剩不到 14 天時每天都會再發一次同樣的提醒。
        if refresh_expires >= utc_now() + timedelta(days=NOTICE_DAYS):
            row.notified_at = None
        row.expires_at, row.refreshed_at = refresh_expires, utc_now()
        row.cache_json = {"access_expires_at": access_expires.isoformat()}
        row.checked_at = None
        session.flush()
        row.credential_digest = oauth.digest_credentials(session, settings, "tiktok")
        oauth.audit(session, "tiktok", "refreshed")
    return token


def status(session, settings):
    row = oauth.connection(session, "tiktok")
    configured = all(
        oauth.value(session, settings, n) for n in ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET")
    )
    linked = all(
        oauth.value(session, settings, n) for n in ("TIKTOK_OPEN_ID", "TIKTOK_REFRESH_TOKEN")
    )
    valid = bool(
        row and row.credential_digest == oauth.digest_credentials(session, settings, "tiktok")
    )
    granted_scopes = row.granted_scopes if valid else []
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
        granted=granted_scopes,
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
    credentials.require_admin(access)
    session = access.session
    token = oauth.value(session, settings, "TIKTOK_ACCESS_TOKEN")
    params = {**app(session, settings), "token": token}
    digest = oauth.digest_credentials(session, settings, "tiktok")
    session.commit()
    if token and params["client_key"] and params["client_secret"]:
        try:
            request(REVOKE_URL, data=params)
        except oauth.ProviderFailure as error:
            # 權杖已失效時 TikTok 那端早就沒有授權，照常清除本機資料；其他錯誤請使用者重試。
            if not error.info.get("invalid_grant"):
                raise HTTPException(422, "TikTok 撤銷授權失敗，請稍後重試") from None
    ensure_write(session)
    if oauth.digest_credentials(session, settings, "tiktok") != digest:
        raise HTTPException(409, "連結已變更，請重新整理")
    for name in SECRETS:
        oauth.put_secret(session, settings, name, "")
    row = oauth.connection(session, "tiktok")
    if row:
        row.account_name, row.cache_json, row.granted_scopes = "", {}, []
        row.expires_at = None
        session.flush()
        row.credential_digest = oauth.digest_credentials(session, settings, "tiktok")
    # 平台條款：授權撤銷或終止後刪除透過 API 取得的資料；
    # 帳號列保留給自己的發佈紀錄，名稱換成平台名。
    accounts = list(session.scalars(select(Account).where(Account.platform == "tiktok")))
    removed = data_retention.apply(
        session, data_retention.plan(session, account_ids=[a.id for a in accounts])
    )
    for account in accounts:
        account.name, account.status = "TikTok", "disconnected"
    oauth.audit(session, "tiktok", "disconnected", f"staff:{access.staff.id}")
    session.commit()
    return {"ok": True, "removed": {k: removed[k] for k in ("posts", "messages", "reports")}}


def maintain(factory, settings, now=None):
    """Daily: keep the access token fresh and warn on LINE before the refresh token expires."""
    now = now or utc_now()
    with factory() as session:
        row = oauth.connection(session, "tiktok")
        if not row or not status(session, settings)["linked"]:
            return
    try:
        access_token(factory, settings)
        failed = False
    except oauth.ProviderFailure:
        failed = True
    with factory.begin() as session:
        row = oauth.connection(session, "tiktok")
        item = status(session, settings)
        if not row or row.notified_at or not (failed or item["expiring"] or item["expired"]):
            return
        from app.services.notify import queue_oauth_notice

        if queue_oauth_notice(session, settings, "tiktok", now):
            row.notified_at = now

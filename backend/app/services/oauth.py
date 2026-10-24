"""OAuth credentials never leave the encrypted store; transport has fixed origins."""

import hashlib
import json
import re
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import HTTPException
from sqlalchemy import delete, select

from app.db import ensure_write
from app.models import (
    Account,
    AuditLog,
    Brand,
    OAuthConnection,
    OAuthState,
    PlatformCredential,
    Setting,
)
from app.models.base import utc_now
from app.services import auth, credentials, settings_store
from app.services.ai_keys import cipher
from app.services.graph_api import DIALOG, FB

# published_posts, media, comments/replies, followers_count and post insights;
# pages_manage_metadata retains the existing public-comment webhook subscription.
META_SCOPES = (
    "pages_show_list",
    "pages_read_engagement",
    "pages_read_user_content",
    "pages_manage_metadata",
    "read_insights",
    "instagram_basic",
    "instagram_manage_comments",
    "instagram_manage_insights",
    "pages_manage_posts",
    "instagram_content_publish",
)
# 選用權限：授權時一併請求，但缺少時不影響連結狀態與發佈就緒，只停用對應功能並提示重新連結。
# pages_manage_engagement：FB 影片／Reels 自訂封面（POST /{video-id}/thumbnails）。
META_OPTIONAL_SCOPES = ("pages_manage_engagement",)
# 發佈所需權限與數據（成效、回覆）權限分開：既有連結缺少數據權限時只提示重新連結，不影響發佈就緒。
# 串文的第 2 則起是回覆（reply_to_id），Meta 規定建立回覆需要 threads_manage_replies。
THREADS_PUBLISH_SCOPES = ("threads_basic", "threads_content_publish", "threads_manage_replies")
THREADS_DATA_SCOPES = ("threads_manage_insights", "threads_read_replies")
THREADS_SCOPES = THREADS_PUBLISH_SCOPES + THREADS_DATA_SCOPES
# 無法由授權範圍判斷時，以平台的權限錯誤標記；換權杖（重新連結）立即失效，否則一天後再試一次。
DATA_BLOCK_KEY = "oauth.threads.data_blocked"
DATA_BLOCK_RETRY = timedelta(hours=24)
TH = "https://graph.threads.net"
# YouTube 的範圍以 youtube_oauth.SCOPES 為準（測試比對兩者一致）；此處只供授權網址組合。
SCOPES = {"meta": META_SCOPES + META_OPTIONAL_SCOPES, "threads": THREADS_SCOPES, "youtube": (
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube.upload",
), "tiktok": ("user.info.basic", "user.info.stats", "video.list", "video.upload")}
# TikTok 的範圍以 tiktok_oauth.SCOPES 為準（測試比對兩者一致）。
RETURN_PATH = "/?view=settings&settings_tab=connections"
FACEBOOK_COVER_HINT = "自訂封面需要 pages_manage_engagement 權限，請重新連結 Meta"
RESULTS = {
    "linked": "帳號連結成功",
    "select": "請選擇粉絲專頁",
    "failed": "帳號連結失敗，請確認應用程式設定與授權後重試",
    "cancelled": "已取消帳號授權",
    "no_pages": "沒有可管理的粉絲專頁",
}


class ProviderFailure(Exception):
    """info 只放可安全記錄的診斷欄位：步驟、HTTP 狀態、平台錯誤代碼；不含權杖、code 或錯誤訊息。"""

    def __init__(self, info=None):
        super().__init__()
        self.info = info or {}


def safe_error(url, status, body):
    path = re.sub(r"/\d+", "/{id}", urlsplit(url).path)[:80]
    error = body.get("error") if isinstance(body, dict) else None
    info = {"stage": path, "status": status}
    if isinstance(error, dict):
        for key in ("code", "error_subcode"):
            if type(error.get(key)) is int:
                info[key] = error[key]
        if isinstance(error.get("type"), str):
            info["type"] = error["type"][:60]
    return info


def platform_check(platform):
    if platform not in SCOPES:
        raise HTTPException(404, "找不到平台")


def request_json(url, *, method="GET", params=None, data=None, token=None):
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.hostname not in {"graph.facebook.com", "graph.threads.net"}
        or parts.port not in {None, 443}
        or parts.username
        or parts.password
    ):
        raise ProviderFailure()
    try:
        with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
            response = client.request(
                method,
                url,
                params=params,
                data=data,
                headers={"Authorization": "Bearer " + token} if token else {},
            )
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.status_code != 200 or not isinstance(body, dict) or body.get("error"):
            raise ProviderFailure(safe_error(url, response.status_code, body))
        return body
    except ProviderFailure:
        raise
    except Exception as error:
        # Do not propagate URLs, request parameters or provider errors into logging.
        stage = re.sub(r"/\d+", "/{id}", urlsplit(url).path)[:80]
        raise ProviderFailure({"stage": stage, "exception": type(error).__name__}) from None


def value(session, settings, name):
    return credentials.raw(credentials.resolve(name, settings, session))


def audit(session, platform, result, actor="system:oauth", diagnostics=None):
    session.add(
        AuditLog(
            actor=actor,
            action="oauth." + result,
            target_type="oauth",
            detail_json={
                "platform": platform if platform in SCOPES else "unknown",
                **({"diagnostics": diagnostics} if diagnostics else {}),
            },
        )
    )


def current(access, cookie):
    credentials.require_admin(access)
    row = auth.find_session(access.session, cookie)
    if not row or row.staff_id != access.staff.id:
        raise HTTPException(401, "請先登入")
    return row.token_hash, access.staff.id


def origin_info(settings):
    origin = settings.backoffice_origin
    return {
        "backoffice_origin": origin,
        "callbacks": {p: origin + f"/api/oauth/{p}/callback" for p in SCOPES},
    }


def start(access, settings, cookie, platform, origin):
    platform_check(platform)
    if (
        not settings.backoffice_origin.startswith("https://")
        or origin != settings.backoffice_origin
    ):
        raise HTTPException(400, "請用內部 https 網址開啟工作檯後再連結")
    session_hash, staff_id = current(access, cookie)
    session = access.session
    prefix = (
        "YOUTUBE_CLIENT" if platform == "youtube"
        else "TIKTOK_CLIENT" if platform == "tiktok"
        else platform.upper() + "_APP"
    )
    app_id = value(session, settings, prefix + ("_KEY" if platform == "tiktok" else "_ID"))
    app_secret = value(session, settings, prefix + "_SECRET")
    if not app_id or not app_secret:
        raise HTTPException(422, "請先設定應用程式編號與密鑰")
    cipher(settings)
    nonce = secrets.token_urlsafe(32)
    ensure_write(session)
    session.execute(delete(OAuthState).where(OAuthState.expires_at <= utc_now()))
    session.add(
        OAuthState(
            state_hash=auth.token_hash(nonce),
            session_hash=session_hash,
            staff_id=staff_id,
            platform=platform,
            expires_at=utc_now() + timedelta(minutes=10),
        )
    )
    audit(session, platform, "start", f"staff:{staff_id}")
    session.commit()
    if platform == "tiktok":
        from app.services import tiktok_oauth

        # TikTok 用 client_key 而不是 client_id，範圍以逗號分隔。
        params = tiktok_oauth.authorize_params(session, settings, nonce)
        return {"url": tiktok_oauth.AUTHORIZE_URL + "?" + urlencode(params)}
    endpoint = (
        DIALOG
        if platform == "meta"
        else "https://accounts.google.com/o/oauth2/v2/auth"
        if platform == "youtube"
        else "https://threads.net/oauth/authorize"
    )
    return {
        "url": endpoint
        + "?"
        + urlencode(
            {
                "client_id": app_id,
                "redirect_uri": origin_info(settings)["callbacks"][platform],
                "scope": (" " if platform == "youtube" else ",").join(SCOPES[platform]),
                **(
                    {"access_type": "offline", "prompt": "consent"}
                    if platform == "youtube" else {}
                ),
                "state": nonce,
                "response_type": "code",
            }
        )
    }


def token_result(body):
    token = body.get("access_token")
    seconds = body.get("expires_in")
    if (
        not isinstance(token, str)
        or not token
        or len(token) > 4096
        or type(seconds) is not int
        or not 0 < seconds <= 366 * 86400
    ):
        raise ProviderFailure(
            {
                "stage": "token_result",
                "has_token": isinstance(token, str) and bool(token),
                "expires_in": type(seconds).__name__,
            }
        )
    return token, utc_now() + timedelta(seconds=seconds)


def identifier(body):
    result = body.get("id")
    if not isinstance(result, str) or not re.fullmatch(r"\d{1,64}", result):
        raise ProviderFailure()
    return result


def granted(session, settings, token):
    body = request_json(FB + "/me/permissions", token=token)
    rows = body.get("data")
    if not isinstance(rows, list):
        raise ProviderFailure()
    return sorted(
        {
            r.get("permission")
            for r in rows
            if isinstance(r, dict)
            and r.get("status") == "granted"
            and r.get("permission") in SCOPES["meta"]
        }
    )


def meta_token_lifetime(body, app):
    """回傳 (權杖, 到期時間, 是否永不過期)。

    交換結果未附 expires_in 時（商家專用 Facebook 登入常見），改以 debug_token 查實際到期：
    expires_at 為 0 代表不會過期；查不到則視為失敗，不猜測。
    """
    token = body.get("access_token")
    if type(body.get("expires_in")) is int:
        token, expires = token_result(body)
        return token, expires, False
    if not isinstance(token, str) or not token or len(token) > 4096:
        raise ProviderFailure({"stage": "token_result", "has_token": False})
    data = request_json(
        FB + "/debug_token",
        params={
            "input_token": token,
            "access_token": app["client_id"] + "|" + app["client_secret"],
        },
    ).get("data")
    if not isinstance(data, dict) or data.get("is_valid") is not True:
        raise ProviderFailure({"stage": "debug_token", "valid": False})
    expires_at = data.get("expires_at")
    if expires_at == 0:
        return token, None, True
    if type(expires_at) is not int:
        raise ProviderFailure({"stage": "debug_token", "expires_at": type(expires_at).__name__})
    expires = datetime.fromtimestamp(expires_at, UTC)
    if expires <= utc_now():
        raise ProviderFailure({"stage": "debug_token", "expired": True})
    return token, expires, False


def page_entry(page):
    pid = identifier(page)
    page_token = page.get("access_token")
    if not isinstance(page_token, str) or not page_token:
        raise ProviderFailure({"stage": "page_token", "has_token": False})
    ig = request_json(
        FB + "/" + pid,
        token=page_token,
        params={"fields": "instagram_business_account{id,username}"},
    ).get("instagram_business_account")
    return {
        "id": pid,
        "name": str(page.get("name", ""))[:255],
        "token": page_token,
        "ig_id": identifier(ig) if ig else "",
        "ig_username": str(ig.get("username", ""))[:255] if ig else "",
    }


def granted_page_ids(token, app):
    """從 debug_token 的 granular_scopes 取得授權時勾選的粉專編號（最多 50 個）。"""
    data = request_json(
        FB + "/debug_token",
        params={
            "input_token": token,
            "access_token": app["client_id"] + "|" + app["client_secret"],
        },
    ).get("data")
    scopes = data.get("granular_scopes") if isinstance(data, dict) else None
    ids = []
    for item in scopes if isinstance(scopes, list) else []:
        if not isinstance(item, dict) or item.get("scope") not in {
            "pages_show_list",
            "pages_manage_posts",
            "pages_read_engagement",
        }:
            continue
        for target in item.get("target_ids") or []:
            if isinstance(target, str) and re.fullmatch(r"\d{1,64}", target) and target not in ids:
                ids.append(target)
    return ids[:50]


def meta_exchange(session, settings, code):
    app = {
        "client_id": value(session, settings, "META_APP_ID"),
        "client_secret": value(session, settings, "META_APP_SECRET"),
    }
    redirect = origin_info(settings)["callbacks"]["meta"]
    session.commit()
    short = request_json(
        FB + "/oauth/access_token",
        method="POST",
        data={**app, "redirect_uri": redirect, "code": code},
    ).get("access_token")
    if not isinstance(short, str) or not short:
        raise ProviderFailure()
    exchanged = request_json(
        FB + "/oauth/access_token",
        method="POST",
        data={**app, "grant_type": "fb_exchange_token", "fb_exchange_token": short},
    )
    long, expires, never = meta_token_lifetime(exchanged, app)
    pages, after = [], None
    for _ in range(50):
        body = request_json(
            FB + "/me/accounts",
            token=long,
            params={
                "fields": "id,name,access_token",
                "limit": 100,
                **({"after": after} if after else {}),
            },
        )
        if not isinstance(body.get("data"), list):
            raise ProviderFailure()
        for page in body["data"]:
            pages.append(page_entry(page))
        paging = body.get("paging") or {}
        if not paging.get("next"):
            break
        cursor = (paging.get("cursors") or {}).get("after")
        if not isinstance(cursor, str) or not cursor or cursor == after or len(cursor) > 2048:
            raise ProviderFailure()
        after = cursor
    else:
        raise ProviderFailure()
    if not pages:
        # 粉專經商家資產組合授權時，/me/accounts 可能為空；改用授權時勾選的粉專編號逐一讀取。
        for pid in granted_page_ids(long, app):
            pages.append(
                page_entry(
                    request_json(
                        FB + "/" + pid, token=long, params={"fields": "id,name,access_token"}
                    )
                )
            )
    return {
        "token": long,
        "expires": expires.isoformat() if expires else None,
        "never_expires": never,
        "pages": pages,
        "scopes": granted(session, settings, long),
    }


def threads_exchange(session, settings, code):
    app = {
        "client_id": value(session, settings, "THREADS_APP_ID"),
        "client_secret": value(session, settings, "THREADS_APP_SECRET"),
    }
    redirect = origin_info(settings)["callbacks"]["threads"]
    session.commit()
    short = request_json(
        TH + "/oauth/access_token",
        method="POST",
        data={**app, "grant_type": "authorization_code", "redirect_uri": redirect, "code": code},
    )
    if not isinstance(short.get("access_token"), str) or not short["access_token"]:
        raise ProviderFailure()
    long = request_json(
        TH + "/access_token",
        params={
            "grant_type": "th_exchange_token",
            "client_secret": app["client_secret"],
            "access_token": short["access_token"],
        },
    )
    token, expires = token_result(long)
    me = request_json(TH + "/me", token=token, params={"fields": "id,username"})
    scope = long.get("scope", short.get("scope"))
    if scope is None:
        # Standard token responses may omit scope. Verify it at authorization time
        # using the official debugger rather than treating requested scopes as granted.
        try:
            debug = request_json(
                TH + "/debug_token", token=token, params={"input_token": token}
            ).get("data", {})
            scope = debug.get("scopes") if debug.get("is_valid") is True else None
        except ProviderFailure:
            scope = None
    # Missing scope is unknown, never infer grants solely from requested permissions.
    scopes = (
        scope.split(",") if isinstance(scope, str) else scope if isinstance(scope, list) else []
    )
    return {
        "token": token,
        "expires": expires.isoformat(),
        "id": identifier(me),
        "name": str(me.get("username", ""))[:255],
        "scopes": [s for s in scopes if s in THREADS_SCOPES],
    }


def put_secret(session, settings, name, text):
    row = credentials.row_for(session, name)
    encrypted = cipher(settings).encrypt(text.encode()).decode()
    if row:
        row.encrypted_key = encrypted
    else:
        session.add(PlatformCredential(provider=name, encrypted_key=encrypted))


def connection(session, platform):
    return session.scalar(select(OAuthConnection).where(OAuthConnection.platform == platform))


def digest_credentials(session, settings, platform):
    names = credentials.GROUPS[platform]
    return hashlib.sha256(
        json.dumps([value(session, settings, n) for n in names]).encode()
    ).hexdigest()


def threads_data_blocked(session, settings, now=None):
    """平台曾對成效或回覆呼叫回權限錯誤，且憑證沒換、距離上次不到一天。"""
    row = settings_store.get(session, DATA_BLOCK_KEY)
    if row is None:
        return False
    try:
        at = datetime.fromisoformat(row.value_json.get("at", ""))
    except (TypeError, ValueError):
        return False
    same = row.value_json.get("digest") == digest_credentials(session, settings, "threads")
    return same and (now or utc_now()) - at < DATA_BLOCK_RETRY


def threads_data_access(session, settings, now=None):
    """Threads 數據（成效與回覆）權限：ready 已授權、missing 已知缺少、unknown 無法判斷。"""
    row = connection(session, "threads")
    known = bool(
        row
        and row.credential_digest == digest_credentials(session, settings, "threads")
        and row.granted_scopes
    )
    if known and not set(THREADS_DATA_SCOPES) <= set(row.granted_scopes):
        return "missing"
    if threads_data_blocked(session, settings, now):
        return "missing"
    return "ready" if known else "unknown"


def mark_threads_data_blocked(session, settings):
    value_json = {
        "digest": digest_credentials(session, settings, "threads"),
        "at": utc_now().isoformat(),
    }
    row = settings_store.get(session, DATA_BLOCK_KEY)
    settings_store.put(session, DATA_BLOCK_KEY, value_json, row)


def persist(session, settings, platform, payload, staff_id, page=None):

    ensure_write(session)
    row = connection(session, platform)
    if not row:
        row = OAuthConnection(platform=platform)
        session.add(row)
    row.expires_at = datetime.fromisoformat(payload["expires"]) if payload["expires"] else None
    row.never_expires = bool(payload.get("never_expires"))
    row.refreshed_at, row.notified_at = utc_now(), None
    row.granted_scopes = payload["scopes"]
    row.checked_at, row.cache_json = None, {}
    if platform == "youtube":
        from app.services import youtube_oauth

        youtube_oauth.persist(session, settings, payload, row)
    elif platform == "tiktok":
        from app.services import tiktok_oauth

        tiktok_oauth.persist(session, settings, payload, row)
    elif platform == "meta":
        put_secret(session, settings, "META_USER_ACCESS_TOKEN", payload["token"])
        for name, key in [
            ("META_PAGE_ID", "id"),
            ("META_PAGE_ACCESS_TOKEN", "token"),
            ("META_IG_ACCOUNT_ID", "ig_id"),
        ]:
            put_secret(session, settings, name, page[key])
        row.account_name, row.ig_username = page["name"], page["ig_username"]
        register_account(session, "facebook", page["id"], page["name"])
        if page["ig_id"]:
            register_account(session, "instagram", page["ig_id"], page["ig_username"])
    else:
        put_secret(session, settings, "THREADS_USER_ID", payload["id"])
        put_secret(session, settings, "THREADS_ACCESS_TOKEN", payload["token"])
        row.account_name = payload["name"]
        register_account(session, "threads", payload["id"], payload["name"])
        # 重新連結即重新驗證數據權限，清除先前的權限錯誤標記。
        session.execute(delete(Setting).where(Setting.key == DATA_BLOCK_KEY))
    session.flush()
    row.credential_digest = digest_credentials(session, settings, platform)
    if platform in {"meta", "threads"}:
        # 權限剛在換發權杖時向平台查過，直接寫入快取。發佈頁只讀快取（不打平台），
        # 若這裡清空，重新連結後直接去發佈頁會把 FB／IG／Threads 全判成缺少權限。
        row.cache_json = {"granted": list(payload["scopes"]), "verified": True}
        row.checked_at = utc_now()
    audit(session, platform, "linked", f"staff:{staff_id}")


def register_account(session, platform, external_id, name):
    """授權成功後把帳號登記到品牌，發佈功能才找得到對應帳號。

    只在工作檯恰有一個品牌時自動登記；多品牌時無法判斷歸屬，維持由發佈頁提示。
    既有帳號只更新名稱與狀態，不動 send_enabled。
    """
    brands = list(session.scalars(select(Brand.id).limit(2)))
    if len(brands) != 1 or not external_id:
        return
    account = session.scalar(
        select(Account).where(
            Account.brand_id == brands[0],
            Account.platform == platform,
            Account.external_id == external_id,
        )
    )
    if account is None:
        account = Account(
            brand_id=brands[0],
            platform=platform,
            external_id=external_id,
            name=(name or platform)[:200],
        )
        session.add(account)
    elif name:
        account.name = name[:200]
    account.status = "connected"


def receive(session, settings, platform, state, code, denied=False):
    """平台導回的第一段：不依賴登入 cookie（SameSite=Strict 在跨站導回時不會送出）。

    只確認 state 是本工作檯發出、未過期、未使用，將 code 加密暫存於該 state；
    換取權杖留到第二段 complete()，由同一個已登入 session 觸發。
    """
    platform_check(platform)
    ensure_write(session)
    digest = auth.token_hash(state) if re.fullmatch(r"[A-Za-z0-9_-]{43}", state or "") else ""
    row = session.scalar(select(OAuthState).where(OAuthState.state_hash == digest))
    if (
        not row
        or row.platform != platform
        or row.consumed
        or row.encrypted_payload
        or row.expires_at <= utc_now()
        or (not denied and (not code or len(code) > 4096))
    ):
        audit(session, platform, "state_rejected")
        session.commit()
        return RETURN_PATH + "&oauth_result=failed"
    row.encrypted_payload = (
        cipher(settings)
        .encrypt(json.dumps({"code": "" if denied else code, "denied": bool(denied)}).encode())
        .decode()
    )
    session.commit()
    return RETURN_PATH + "&oauth_pending=" + platform


def complete(access, settings, cookie, platform):
    """第二段：由發起授權的同一個管理員 session 取回暫存的 code 並換取權杖。"""
    platform_check(platform)
    session_hash, staff_id = current(access, cookie)
    session = access.session
    ensure_write(session)
    row = session.scalar(
        select(OAuthState)
        .where(
            OAuthState.session_hash == session_hash,
            OAuthState.staff_id == staff_id,
            OAuthState.platform == platform,
            OAuthState.consumed.is_(False),
            OAuthState.encrypted_payload != "",
            OAuthState.expires_at > utc_now(),
        )
        .order_by(OAuthState.id.desc())
    )
    if not row:
        audit(session, platform, "state_rejected", f"staff:{staff_id}")
        session.commit()
        raise HTTPException(400, "授權驗證失敗或已過期，請重新連結")
    received = json.loads(cipher(settings).decrypt(row.encrypted_payload.encode()).decode())
    row.consumed, row.encrypted_payload = True, ""
    identity = row.id
    session.commit()
    return {
        "result": finish(access, settings, platform, identity, received["code"], received["denied"])
    }


def finish(access, settings, platform, identity, code, denied):
    session, staff_id = access.session, access.staff.id
    result = "failed"
    diagnostics = None
    try:
        if denied:
            result = "cancelled"
        elif not code or len(code) > 4096:
            result = "failed"
        else:
            from app.services import tiktok_oauth, youtube_oauth

            payload = (
                youtube_oauth.exchange(session, settings, code)
                if platform == "youtube"
                else tiktok_oauth.exchange(session, settings, code)
                if platform == "tiktok"
                else meta_exchange(session, settings, code)
                if platform == "meta"
                else threads_exchange(session, settings, code)
            )
            if platform == "meta" and not payload["pages"]:
                result = "no_pages"
                # 只記錄權限名稱，協助判斷是未勾選粉專還是缺少 pages_show_list。
                diagnostics = {"granted": payload["scopes"]}
            else:
                ensure_write(session)
                if platform == "meta" and len(payload["pages"]) > 1:
                    row = session.get(OAuthState, identity)
                    row.encrypted_payload = (
                        cipher(settings).encrypt(json.dumps(payload).encode()).decode()
                    )
                    result = "select"
                else:
                    persist(
                        session,
                        settings,
                        platform,
                        payload,
                        staff_id,
                        payload["pages"][0] if platform == "meta" else None,
                    )
                    result = "linked"
                session.commit()
    except (ProviderFailure, HTTPException, ValueError, TypeError, KeyError) as error:
        session.rollback()
        result = "failed"
        diagnostics = getattr(error, "info", None) or {"exception": type(error).__name__}
    ensure_write(session)
    audit(session, platform, result, f"staff:{staff_id}", diagnostics)
    session.commit()
    return result


def pending(access, settings, cookie):
    session_hash, staff_id = current(access, cookie)
    row = access.session.scalar(
        select(OAuthState)
        .where(
            OAuthState.session_hash == session_hash,
            OAuthState.staff_id == staff_id,
            OAuthState.platform == "meta",
            OAuthState.consumed.is_(True),
            OAuthState.encrypted_payload != "",
            OAuthState.expires_at > utc_now(),
        )
        .order_by(OAuthState.id.desc())
    )
    if not row:
        return None, None
    payload = json.loads(cipher(settings).decrypt(row.encrypted_payload.encode()).decode())
    return row, payload


def choose(access, settings, cookie, page_id):
    ensure_write(access.session)
    row, payload = pending(access, settings, cookie)
    page = next((p for p in payload["pages"] if p["id"] == page_id), None) if payload else None
    if not page:
        raise HTTPException(400, "粉絲專頁選擇已過期或不符，請重新連結")
    persist(access.session, settings, "meta", payload, access.staff.id, page)
    row.encrypted_payload = ""
    access.session.commit()
    return {"ok": True}


def status_item(session, settings, platform, row, scopes, verified=True):
    expires = row.expires_at if row else None
    changed = bool(row and row.credential_digest != digest_credentials(session, settings, platform))
    if changed:
        expires, scopes = None, []
    linked = bool(
        value(session, settings, "META_PAGE_ID" if platform == "meta" else "THREADS_USER_ID")
        and value(
            session,
            settings,
            "META_PAGE_ACCESS_TOKEN" if platform == "meta" else "THREADS_ACCESS_TOKEN",
        )
    )
    # Threads 的數據權限另列 data_missing：缺少時只提示重新連結，不影響連結狀態與發佈就緒。
    required = (
        THREADS_PUBLISH_SCOPES
        if platform == "threads"
        else META_SCOPES
        if platform == "meta"
        else SCOPES[platform]
    )
    missing = sorted(set(required) - set(scopes))
    data_missing = []
    if platform == "threads" and linked:
        data_missing = sorted(set(THREADS_DATA_SCOPES) - set(scopes))
        if not data_missing and threads_data_blocked(session, settings):
            data_missing = sorted(THREADS_DATA_SCOPES)
    soon = bool(expires and expires < utc_now() + timedelta(days=7))
    expired = bool(expires and expires <= utc_now())
    state = (
        "neutral"
        if not linked
        else "failed"
        if missing or expired or not verified
        else "pending"
        if soon
        else "ready"
    )
    return {
        "linked": linked,
        "name": row.account_name if row and not changed else "",
        "ig_username": row.ig_username if row and not changed else "",
        "ig_linked": bool(value(session, settings, "META_IG_ACCOUNT_ID"))
        if platform == "meta"
        else False,
        "expires_at": expires.isoformat() if expires else None,
        "never_expires": bool(row and row.never_expires and not changed),
        "granted": sorted(scopes),
        "missing": missing,
        "data_missing": data_missing,
        "state": state,
        "verified": verified,
        "expiring": soon,
        "expired": expired,
    }


def statuses(session, settings, force=False):
    result = {}
    for platform in SCOPES:
        if platform == "youtube":
            from app.services import youtube_oauth

            item = youtube_oauth.status(session, settings)
            if force and item["linked"] and item["verified"]:
                from app.db import session_factory

                factory = session_factory(session.get_bind())
                session.commit()
                try:
                    token = youtube_oauth.access_token(factory, settings)
                    identity, _ = youtube_oauth.channel(token)
                    if identity != value(session, settings, "YOUTUBE_CHANNEL_ID"):
                        raise ProviderFailure()
                except ProviderFailure:
                    session.expire_all()
                    item = youtube_oauth.status(session, settings)
                    item.update(verified=False, state="failed")
            result[platform] = item
            continue
        if platform == "tiktok":
            from app.services import tiktok_oauth

            item = tiktok_oauth.status(session, settings)
            if force and item["linked"] and item["verified"]:
                from app.db import session_factory

                factory = session_factory(session.get_bind())
                session.commit()
                try:
                    identity, _ = tiktok_oauth.profile(
                        tiktok_oauth.access_token(factory, settings)
                    )
                    if identity != value(session, settings, "TIKTOK_OPEN_ID"):
                        raise ProviderFailure()
                except ProviderFailure:
                    session.expire_all()
                    item = tiktok_oauth.status(session, settings)
                    item.update(verified=False, state="failed")
            result[platform] = item
            continue
        row = connection(session, platform)
        digest = digest_credentials(session, settings, platform)
        if not row or row.credential_digest != digest:
            ensure_write(session)
            row = connection(session, platform)
            digest = digest_credentials(session, settings, platform)
            if not row:
                row = OAuthConnection(platform=platform, credential_digest=digest)
                session.add(row)
            elif row.credential_digest != digest:
                # Manual credentials cannot inherit the former account's grants or expiry.
                row.account_name, row.ig_username = "", ""
                row.expires_at, row.refreshed_at, row.notified_at = None, None, None
                row.granted_scopes, row.cache_json, row.checked_at = [], {}, None
                row.credential_digest = digest
            session.commit()
        if (
            row
            and not force
            and row.checked_at
            and row.checked_at > utc_now() - timedelta(minutes=10)
            and row.credential_digest == digest
            and row.cache_json
        ):
            result[platform] = status_item(
                session,
                settings,
                platform,
                row,
                row.cache_json["granted"],
                row.cache_json["verified"],
            )
            continue
        scopes = row.granted_scopes if row else []
        verified = True
        checked_name = None
        if platform == "meta":
            token = value(session, settings, "META_USER_ACCESS_TOKEN")
            session.commit()
            if token:
                try:
                    scopes = granted(session, settings, token)
                except ProviderFailure:
                    scopes, verified = [], False
        else:
            token = value(session, settings, "THREADS_ACCESS_TOKEN")
            user_id = value(session, settings, "THREADS_USER_ID")
            session.commit()
            if token and user_id:
                try:
                    me = request_json(TH + "/me", token=token, params={"fields": "id,username"})
                    if identifier(me) != user_id:
                        raise ProviderFailure()
                    checked_name = str(me.get("username", ""))[:255]
                except ProviderFailure:
                    scopes, verified = [], False
        item = status_item(session, settings, platform, row, scopes, verified)
        result[platform] = item
        if row:
            ensure_write(session)
            row = connection(session, platform)
            # Reconnection or manual edit during HTTP must not be overwritten by stale results.
            if (
                row.credential_digest == digest
                and digest_credentials(session, settings, platform) == digest
            ):
                row.cache_json = {"granted": scopes, "verified": verified}
                row.checked_at = utc_now()
                if checked_name is not None:
                    row.account_name = checked_name
            session.commit()
    return result


def view(access, settings, cookie, force=False):
    credentials.require_admin(access)
    result = {**origin_info(settings), "platforms": statuses(access.session, settings, force)}
    _, payload = pending(access, settings, cookie)
    result["pages"] = (
        [{"id": p["id"], "name": p["name"]} for p in payload["pages"]] if payload else []
    )
    return result


def publish_readiness(session, settings, *, cached=False):
    if cached:
        states = {}
        for source in ("meta", "threads"):
            row = connection(session, source)
            valid = bool(
                row and row.credential_digest == digest_credentials(session, settings, source)
            )
            cache = row.cache_json if valid else {}
            states[source] = status_item(
                session,
                settings,
                source,
                row,
                cache.get("granted", []),
                cache.get("verified", False),
            )
    else:
        states = statuses(session, settings)
    if cached:
        # YouTube 狀態只讀本機資料（不打 Google），快取模式也可直接取得。
        from app.services import youtube_oauth

        states["youtube"] = youtube_oauth.status(session, settings)
        from app.services import tiktok_oauth

        states["tiktok"] = tiktok_oauth.status(session, settings)
    requirements = {
        "facebook": ("meta", {"pages_manage_posts", "pages_read_engagement"}),
        "instagram": (
            "meta",
            {"instagram_basic", "instagram_content_publish", "pages_read_engagement"},
        ),
        "threads": ("threads", set(THREADS_PUBLISH_SCOPES)),
        "youtube": ("youtube", set()),
        "tiktok": ("tiktok", set()),
    }
    result = {}
    for platform, (source, scopes) in requirements.items():
        item = states[source]
        reasons = []
        if platform == "tiktok":
            # 只需要 video.upload（送到收件匣）；連結但缺這個權限時提示重新連結。
            if not item["linked"]:
                reasons.append("未連結")
            elif item["state"] == "failed" or not item["verified"]:
                reasons.append("授權無效，請重新連結帳號")
            elif "video.upload" not in item["granted"]:
                reasons.append("需要重新連結以取得上傳權限")
            result[platform] = {"ready": not reasons, "reasons": reasons}
            continue
        if platform == "youtube":
            # 授權不過期（refresh token 自動換發）；上傳權限缺少時只提示重新連結。
            if not item["linked"]:
                reasons.append("未連結")
            elif item["state"] == "failed" or not item["verified"]:
                reasons.append("授權無效，請重新連結帳號")
            elif item["data_missing"]:
                reasons.append("需要重新連結以取得上傳權限")
            result[platform] = {
                "ready": not reasons,
                "reasons": reasons,
                **(
                    {"hint": "需要重新連結以取得上傳權限"}
                    if item["linked"] and item["data_missing"] and item["state"] != "failed"
                    else {}
                ),
            }
            continue
        if not item["linked"] or (platform == "instagram" and not item["ig_linked"]):
            reasons.append("未連結")
        missing = sorted(scopes - set(item["granted"]))
        if missing:
            reasons.append("缺少權限：" + ", ".join(missing))
        if not item["verified"]:
            reasons.append("權限檢查失敗")
        if item["expired"]:
            reasons.append("授權已過期")
        elif item["expiring"]:
            reasons.append("授權即將到期")
        if item["linked"] and not item["expires_at"] and not item["never_expires"]:
            reasons.append("授權到期時間未知，請重新連結")
        result[platform] = {"ready": not reasons, "reasons": reasons}
        if (
            platform == "facebook"
            and item["linked"]
            and "pages_manage_engagement" not in item["granted"]
        ):
            # 不影響發佈；只有自訂封面需要這個權限。
            result[platform]["cover_hint"] = FACEBOOK_COVER_HINT
    return result


def maintenance_due(factory, now):
    with factory() as session:
        return any(
            not row.maintenance_at or now - row.maintenance_at >= timedelta(days=1)
            for row in session.scalars(select(OAuthConnection).where(
                OAuthConnection.platform.in_(["meta", "threads", "tiktok"])))
        )


def maintain(factory, settings, now=None):
    now = now or utc_now()
    with factory.begin() as session:
        row = connection(session, "tiktok")
        tiktok_due = bool(
            row and (not row.maintenance_at or now - row.maintenance_at >= timedelta(days=1))
        )
        if tiktok_due:
            row.maintenance_at = now
    if tiktok_due:
        from app.services import tiktok_oauth

        tiktok_oauth.maintain(factory, settings, now)
    for platform in ("meta", "threads"):
        with factory.begin() as session:
            row = connection(session, platform)
            if not row or (row.maintenance_at and now - row.maintenance_at < timedelta(days=1)):
                continue
            row.maintenance_at = now
            if (
                not row.expires_at
                or row.expires_at >= now + timedelta(days=7)
                or row.credential_digest != digest_credentials(session, settings, platform)
            ):
                continue
            if (
                platform == "threads"
                and row.refreshed_at
                and now - row.refreshed_at < timedelta(hours=24)
            ):
                continue
            token = (
                value(session, settings, "THREADS_ACCESS_TOKEN") if platform == "threads" else None
            )
            digest = row.credential_digest
        refreshed = None
        if platform == "threads" and row.expires_at > now:
            try:
                refreshed = token_result(
                    request_json(
                        TH + "/refresh_access_token",
                        params={"grant_type": "th_refresh_token", "access_token": token},
                    )
                )
            except ProviderFailure:
                pass
        with factory.begin() as session:
            row = connection(session, platform)
            if (
                not row
                or row.credential_digest != digest
                or digest_credentials(session, settings, platform) != digest
            ):
                continue
            if refreshed:
                put_secret(session, settings, "THREADS_ACCESS_TOKEN", refreshed[0])
                row.expires_at, row.refreshed_at = refreshed[1], now
                row.checked_at, row.notified_at = None, None
                session.flush()
                row.credential_digest = digest_credentials(session, settings, platform)
                audit(session, platform, "refreshed")
            else:
                audit(session, platform, "refresh_failed" if platform == "threads" else "expiring")
                if not row.notified_at:
                    from app.services.notify import queue_oauth_notice

                    if queue_oauth_notice(session, settings, platform, now):
                        row.notified_at = now

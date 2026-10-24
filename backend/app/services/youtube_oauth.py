"""Single-channel read authorization; Google secrets only live in encrypted credentials."""

import sys
from datetime import timedelta

import httpx
from fastapi import HTTPException
from sqlalchemy import select

from app.db import ensure_write
from app.models import Account, Brand, CommentPoll
from app.models.base import utc_now
from app.services import credentials, oauth_tokens, settings_store
from app.services.oauth_core import (
    ProviderFailure,
    audit,
    origin_info,
    put_secret,
    register_account,
    token_result,
    value,
)

# 讀取（貼文、成效、留言）與上傳分開：既有連結只缺上傳範圍時，讀取照常，只提示重新連結。
READ_SCOPES = (
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
)
# videos.insert 與 thumbnails.set 都接受 youtube.upload；不需更廣的 youtube 或 force-ssl。
UPLOAD_SCOPES = ("https://www.googleapis.com/auth/youtube.upload",)
SCOPES = READ_SCOPES + UPLOAD_SCOPES
# 上傳用的統一類別（發佈頁不出現）。編號固定為 YouTube 可指派的類別，避免為了取清單多耗一次配額。
CATEGORIES = {
    "1": "電影與動畫",
    "2": "汽車與交通工具",
    "10": "音樂",
    "15": "寵物與動物",
    "17": "運動",
    "19": "旅遊與活動",
    "20": "遊戲",
    "22": "人物與網誌",
    "23": "喜劇",
    "24": "娛樂",
    "25": "新聞與政治",
    "26": "教學與風格",
    "27": "教育",
    "28": "科學與技術",
    "29": "非營利組織與社會運動",
}
DEFAULT_CATEGORY = "22"
CATEGORY_KEY = "youtube.upload_category"
AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
CHANNEL_URL = "https://www.googleapis.com/youtube/v3/channels"
SECRETS = ("YOUTUBE_CHANNEL_ID", "YOUTUBE_ACCESS_TOKEN", "YOUTUBE_REFRESH_TOKEN")


def request(url, *, data=None, token=None, params=None):
    if url not in {TOKEN_URL, CHANNEL_URL, REVOKE_URL}:
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
        if (
            url == REVOKE_URL
            and response.status_code == 400
            and isinstance(body, dict)
            and body.get("error") == "invalid_token"
        ):
            return {}
        if response.status_code != 200 or not isinstance(body, dict) or body.get("error"):
            reason = body.get("error") if isinstance(body, dict) else None
            raise ProviderFailure(
                {
                    "stage": "google",
                    "status": response.status_code,
                    "invalid_grant": reason == "invalid_grant",
                }
            )
        return body
    except ProviderFailure:
        raise
    except Exception:
        raise ProviderFailure({"stage": "google_transport"}) from None


def category(session):
    row = settings_store.get(session, CATEGORY_KEY)
    value = row.value_json.get("category_id") if row else None
    return value if value in CATEGORIES else DEFAULT_CATEGORY


def set_category(access, category_id):
    credentials.require_admin(access)
    if category_id not in CATEGORIES:
        raise HTTPException(422, "不支援的 YouTube 類別")
    session = access.session
    ensure_write(session)
    row = settings_store.get(session, CATEGORY_KEY)
    settings_store.put(session, CATEGORY_KEY, {"category_id": category_id}, row)
    audit(session, "youtube", "category", f"staff:{access.staff.id}")
    session.commit()
    return {"category_id": category_id}


def app(session, settings):
    return {
        "client_id": value(session, settings, "YOUTUBE_CLIENT_ID"),
        "client_secret": value(session, settings, "YOUTUBE_CLIENT_SECRET"),
    }


def channel(token):
    rows = request(
        CHANNEL_URL,
        token=token,
        params={
            "part": "snippet",
            "mine": "true",
            "maxResults": 2,
        },
    ).get("items")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ProviderFailure({"stage": "single_channel_required"})
    row = rows[0]
    from app.services.youtube import identifier

    try:
        return identifier(row.get("id")), str(row.get("snippet", {}).get("title", ""))[:200]
    except Exception:
        raise ProviderFailure({"stage": "channel_response"}) from None


def exchange(session, settings, code):
    params = {
        **app(session, settings),
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": origin_info(settings)["callbacks"]["youtube"],
    }
    session.commit()
    body = request(TOKEN_URL, data=params)
    token, expires = token_result(body)
    refresh = body.get("refresh_token")
    scope = body.get("scope", "")
    scopes = scope.split() if isinstance(scope, str) else []
    # 讀取範圍必備；使用者在授權畫面取消勾選上傳時仍可連結，只是不能發佈。
    if (
        not isinstance(refresh, str)
        or not refresh
        or len(refresh) > 4096
        or not set(READ_SCOPES) <= set(scopes)
    ):
        raise ProviderFailure({"stage": "offline_permissions_required"})
    identity, name = channel(token)
    return dict(
        token=token,
        refresh=refresh,
        expires=expires.isoformat(),
        id=identity,
        name=name,
        scopes=[scope for scope in SCOPES if scope in scopes],
    )


def persist(session, settings, payload, row):
    identity = payload["id"]
    accounts = list(session.scalars(select(Account).where(Account.platform == "youtube")))
    if accounts and any(a.external_id != identity for a in accounts):
        # Do not attach another channel's data to existing account/history.
        raise HTTPException(409, "已登記另一個 YouTube 頻道，請由管理員處理品牌帳號")
    for name, key in zip(SECRETS, ("id", "token", "refresh"), strict=True):
        put_secret(session, settings, name, payload[key])
    row.account_name = payload["name"]
    row.cache_json = {}
    if len(accounts) == 1:
        accounts[0].name, accounts[0].status = payload["name"], "connected"
    elif accounts or len(list(session.scalars(select(Brand.id).limit(2)))) != 1:
        raise HTTPException(409, "請先登記 YouTube 頻道的品牌歸屬")
    else:
        register_account(session, "youtube", identity, payload["name"])


def refreshed(body):
    token, expires = token_result(body)
    refresh = body.get("refresh_token")
    # Google 通常不換 refresh token；有給且格式合理才更新。
    rotated = refresh if isinstance(refresh, str) and 0 < len(refresh) <= 4096 else None
    return oauth_tokens.Refreshed(token=token, access_expires=expires, refresh=rotated)


def store(row, result):
    row.expires_at = result.access_expires
    # 只拿掉 reconnect 標記，其他快取（例如 subscriber_hidden）保留。
    row.cache_json = {k: v for k, v in row.cache_json.items() if k != "reconnect"}


SPEC = oauth_tokens.TokenPlatform(
    platform="youtube",
    module=sys.modules[__name__],
    token_url=TOKEN_URL,
    access_name="YOUTUBE_ACCESS_TOKEN",
    refresh_name="YOUTUBE_REFRESH_TOKEN",
    identity_names=("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_CHANNEL_ID"),
    app_names=("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET"),
    link_names=("YOUTUBE_CHANNEL_ID", "YOUTUBE_REFRESH_TOKEN"),
    secrets=SECRETS,
    skew=timedelta(minutes=2),
    reconnect_stage="youtube_reconnect",
    parse=refreshed,
    access_expires=lambda row: row.expires_at,
    store=store,
)


def access_token(factory, settings):
    return oauth_tokens.access_token(SPEC, factory, settings)


def verify_identity(factory, settings):
    """強制重新檢查時：換發權杖並確認仍是同一個頻道。"""
    return channel(access_token(factory, settings))[0]


def status(session, settings):
    row, configured, linked, valid, granted = oauth_tokens.link_state(SPEC, session, settings)
    missing = sorted(set(READ_SCOPES) - set(granted))
    # 上傳權限另列 data_missing：缺少時只提示重新連結，讀取功能與連結狀態不受影響。
    upload_missing = sorted(set(UPLOAD_SCOPES) - set(granted)) if linked else []
    reconnect = linked and (not valid or bool(row.cache_json.get("reconnect")) or bool(missing))
    return dict(
        configured=configured,
        linked=linked,
        name=row.account_name if valid else "",
        ig_username="",
        expires_at=row.expires_at.isoformat() if valid and row.expires_at else None,
        granted=list(granted),
        missing=missing if linked else [],
        state="failed" if reconnect else "ready" if linked else "neutral",
        verified=not reconnect,
        expiring=False,
        expired=False,
        data_missing=upload_missing,
        category_id=category(session),
        categories=[{"id": key, "name": name} for key, name in CATEGORIES.items()],
        subscriber_hidden=bool(row and row.cache_json.get("subscriber_hidden")),
    )


def disconnect(access, settings):
    def revoke(session):
        token = value(session, settings, "YOUTUBE_REFRESH_TOKEN")
        session.commit()
        if token:
            try:
                request(REVOKE_URL, data={"token": token})
            except ProviderFailure:
                raise HTTPException(422, "Google 撤銷授權失敗，請稍後重試") from None

    def finish_accounts(session, accounts):
        for account in accounts:
            account.status = "disconnected"
            states = session.scalars(
                select(CommentPoll).where(CommentPoll.account_id == account.id)
            )
            for state in states:
                state.run_id = state.lease_until = None
                state.manual_requested = False
                state.requested_at = None
                state.stopped_at = utc_now()
            # YouTube API 政策：撤銷授權後 7 天內刪除透過該授權取得的資料（已由共用流程刪除）；
            # 頻道名稱屬於 API 資料，一併換成平台名。
            account.name = "YouTube"

    return oauth_tokens.disconnect(SPEC, access, settings, revoke, finish_accounts)

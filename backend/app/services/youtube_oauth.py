"""Single-channel read authorization; Google secrets only live in encrypted credentials."""

from datetime import timedelta

import httpx
from fastapi import HTTPException
from sqlalchemy import select

from app.db import ensure_write
from app.models import Account, Brand, CommentPoll
from app.models.base import utc_now
from app.services import credentials, data_retention, oauth, settings_store

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
TOKEN_URL = "https://oauth2.googleapis.com/token"
CHANNEL_URL = "https://www.googleapis.com/youtube/v3/channels"


def request(url, *, data=None, token=None, params=None):
    if url not in {TOKEN_URL, CHANNEL_URL, "https://oauth2.googleapis.com/revoke"}:
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
        if (
            url == "https://oauth2.googleapis.com/revoke"
            and response.status_code == 400
            and isinstance(body, dict)
            and body.get("error") == "invalid_token"
        ):
            return {}
        if response.status_code != 200 or not isinstance(body, dict) or body.get("error"):
            reason = body.get("error") if isinstance(body, dict) else None
            raise oauth.ProviderFailure(
                {
                    "stage": "google",
                    "status": response.status_code,
                    "invalid_grant": reason == "invalid_grant",
                }
            )
        return body
    except oauth.ProviderFailure:
        raise
    except Exception:
        raise oauth.ProviderFailure({"stage": "google_transport"}) from None


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
    oauth.audit(session, "youtube", "category", f"staff:{access.staff.id}")
    session.commit()
    return {"category_id": category_id}


def app(session, settings):
    return {
        "client_id": oauth.value(session, settings, "YOUTUBE_CLIENT_ID"),
        "client_secret": oauth.value(session, settings, "YOUTUBE_CLIENT_SECRET"),
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
        raise oauth.ProviderFailure({"stage": "single_channel_required"})
    row = rows[0]
    from app.services.youtube import identifier

    try:
        return identifier(row.get("id")), str(row.get("snippet", {}).get("title", ""))[:200]
    except Exception:
        raise oauth.ProviderFailure({"stage": "channel_response"}) from None


def exchange(session, settings, code):
    params = {
        **app(session, settings),
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": oauth.origin_info(settings)["callbacks"]["youtube"],
    }
    session.commit()
    body = request(TOKEN_URL, data=params)
    token, expires = oauth.token_result(body)
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
        raise oauth.ProviderFailure({"stage": "offline_permissions_required"})
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
    for name, key in [
        ("YOUTUBE_CHANNEL_ID", "id"),
        ("YOUTUBE_ACCESS_TOKEN", "token"),
        ("YOUTUBE_REFRESH_TOKEN", "refresh"),
    ]:
        oauth.put_secret(session, settings, name, payload[key])
    row.account_name = payload["name"]
    row.cache_json = {}
    if len(accounts) == 1:
        accounts[0].name, accounts[0].status = payload["name"], "connected"
    elif accounts or len(list(session.scalars(select(Brand.id).limit(2)))) != 1:
        raise HTTPException(409, "請先登記 YouTube 頻道的品牌歸屬")
    else:
        oauth.register_account(session, "youtube", identity, payload["name"])


def identity_values(session, settings):
    # 換發只會改 access／refresh token；這些值不同代表憑證真的換了。
    names = ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_CHANNEL_ID")
    return [oauth.value(session, settings, name) for name in names]


def access_token(factory, settings):
    with factory() as session:
        row = oauth.connection(session, "youtube")
        if (
            not row
            or row.cache_json.get("reconnect")
            or row.credential_digest != oauth.digest_credentials(session, settings, "youtube")
        ):
            raise oauth.ProviderFailure({"stage": "youtube_reconnect"})
        token = oauth.value(session, settings, "YOUTUBE_ACCESS_TOKEN")
        if row.expires_at and row.expires_at > utc_now() + timedelta(minutes=2) and token:
            return token
        params = {
            **app(session, settings),
            "grant_type": "refresh_token",
            "refresh_token": oauth.value(session, settings, "YOUTUBE_REFRESH_TOKEN"),
        }
        digest, fixed = row.credential_digest, identity_values(session, settings)
    try:
        body = request(TOKEN_URL, data=params)
        token, expires = oauth.token_result(body)
    except oauth.ProviderFailure as error:
        if error.info.get("invalid_grant"):
            with factory.begin() as session:
                row = oauth.connection(session, "youtube")
                if (
                    row
                    and row.credential_digest == digest
                    and oauth.digest_credentials(session, settings, "youtube") == digest
                ):
                    row.cache_json = {**row.cache_json, "reconnect": True}
                    oauth.audit(session, "youtube", "refresh_failed")
        raise
    with factory.begin() as session:
        row = oauth.connection(session, "youtube")
        if (
            not row
            or row.credential_digest != digest
            or oauth.digest_credentials(session, settings, "youtube") != digest
        ):
            # 同時換發時，先完成的一方已存入新權杖而改變摘要；應用程式與頻道沒變且新權杖
            # 仍有效就沿用，不誤判成憑證變更。其餘情況（重新連結到別處、已失效）照常報錯。
            current = oauth.value(session, settings, "YOUTUBE_ACCESS_TOKEN")
            if (
                row
                and current
                and not row.cache_json.get("reconnect")
                and row.credential_digest == oauth.digest_credentials(session, settings, "youtube")
                and identity_values(session, settings) == fixed
                and row.expires_at
                and row.expires_at > utc_now() + timedelta(minutes=2)
            ):
                return current
            raise oauth.ProviderFailure({"stage": "credentials_changed"})
        oauth.put_secret(session, settings, "YOUTUBE_ACCESS_TOKEN", token)
        refresh = body.get("refresh_token")
        if isinstance(refresh, str) and 0 < len(refresh) <= 4096:
            oauth.put_secret(session, settings, "YOUTUBE_REFRESH_TOKEN", refresh)
        row.expires_at, row.refreshed_at = expires, utc_now()
        row.cache_json, row.checked_at = (
            {k: v for k, v in row.cache_json.items() if k != "reconnect"},
            None,
        )
        session.flush()
        row.credential_digest = oauth.digest_credentials(session, settings, "youtube")
        oauth.audit(session, "youtube", "refreshed")
    return token


def status(session, settings):
    row = oauth.connection(session, "youtube")
    configured = all(
        oauth.value(session, settings, n) for n in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET")
    )
    linked = all(
        oauth.value(session, settings, n) for n in ("YOUTUBE_CHANNEL_ID", "YOUTUBE_REFRESH_TOKEN")
    )
    valid = bool(
        row and row.credential_digest == oauth.digest_credentials(session, settings, "youtube")
    )
    granted = row.granted_scopes if valid else []
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
        granted=row.granted_scopes if valid else [],
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
    credentials.require_admin(access)
    session = access.session
    token = oauth.value(session, settings, "YOUTUBE_REFRESH_TOKEN")
    digest = oauth.digest_credentials(session, settings, "youtube")
    session.commit()
    if token:
        try:
            request("https://oauth2.googleapis.com/revoke", data={"token": token})
        except oauth.ProviderFailure:
            raise HTTPException(422, "Google 撤銷授權失敗，請稍後重試") from None
    ensure_write(session)
    if oauth.digest_credentials(session, settings, "youtube") != digest:
        raise HTTPException(409, "連結已變更，請重新整理")
    for name in ("YOUTUBE_ACCESS_TOKEN", "YOUTUBE_REFRESH_TOKEN", "YOUTUBE_CHANNEL_ID"):
        oauth.put_secret(session, settings, name, "")
    row = oauth.connection(session, "youtube")
    if row:
        row.account_name, row.cache_json, row.granted_scopes = "", {}, []
        row.expires_at = None
        session.flush()
        row.credential_digest = oauth.digest_credentials(session, settings, "youtube")
    for account in session.scalars(select(Account).where(Account.platform == "youtube")):
        account.status = "disconnected"
        states = session.scalars(select(CommentPoll).where(CommentPoll.account_id == account.id))
        for state in states:
            state.run_id = state.lease_until = None
            state.manual_requested = False
            state.requested_at = None
            state.stopped_at = utc_now()
    # YouTube API 政策：撤銷授權後 7 天內刪除透過該授權取得的資料，所以中斷時立即刪除。
    # 頻道帳號列保留給自己的發佈紀錄，但名稱屬於 API 資料，一併換成平台名。
    accounts = list(session.scalars(select(Account).where(Account.platform == "youtube")))
    removed = data_retention.apply(
        session, data_retention.plan(session, account_ids=[a.id for a in accounts])
    )
    for account in accounts:
        account.name = "YouTube"
    oauth.audit(session, "youtube", "disconnected", f"staff:{access.staff.id}")
    session.commit()
    return {"ok": True, "removed": {k: removed[k] for k in ("posts", "messages", "reports")}}

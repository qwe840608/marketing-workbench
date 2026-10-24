"""OAuth 各平台模組共用的基礎：失敗型別、憑證存取、連線列與稽核。

只放不依賴任何平台模組的東西，讓 oauth.py 與 youtube_oauth／tiktok_oauth 都能匯入而不形成循環。
"""

import hashlib
import json
from datetime import timedelta

from sqlalchemy import select

from app.models import Account, AuditLog, Brand, OAuthConnection, PlatformCredential
from app.models.base import utc_now
from app.services import credentials
from app.services.ai_keys import cipher

# 連結流程支援的平台；也是回呼網址與稽核紀錄接受的平台名稱。
PLATFORMS = ("meta", "threads", "youtube", "tiktok")


class ProviderFailure(Exception):
    """info 只放可安全記錄的診斷欄位：步驟、HTTP 狀態、平台錯誤代碼；不含權杖、code 或錯誤訊息。"""

    def __init__(self, info=None):
        super().__init__()
        self.info = info or {}


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


def value(session, settings, name):
    return credentials.raw(credentials.resolve(name, settings, session))


def audit(session, platform, result, actor="system:oauth", diagnostics=None):
    session.add(
        AuditLog(
            actor=actor,
            action="oauth." + result,
            target_type="oauth",
            detail_json={
                "platform": platform if platform in PLATFORMS else "unknown",
                **({"diagnostics": diagnostics} if diagnostics else {}),
            },
        )
    )


def origin_info(settings):
    origin = settings.backoffice_origin
    return {
        "backoffice_origin": origin,
        "callbacks": {p: origin + f"/api/oauth/{p}/callback" for p in PLATFORMS},
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

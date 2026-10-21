"""Hourly local thumbnail cache.

Platform CDN image links expire within hours, so each synced post keeps one small JPEG in
SQLite. Only official read APIs are used (Graph `GET /{id}`, Threads `GET /{id}`, TikTok Display
API `video/query`, and the public YouTube thumbnail host); nothing here writes to a platform.
"""

import hashlib
import io
import json
import logging
import re
import time
from datetime import timedelta
from urllib.parse import quote, urlsplit

import httpx
from fastapi import HTTPException
from fastapi.responses import Response
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import and_, or_, select

from app.logging_config import log_failure
from app.models import Account, Post, PostThumbnail
from app.models.base import utc_now
from app.schemas.meta import ApiCallFinish, ApiCallStart
from app.services import meta_api, oauth, tiktok, tiktok_oauth
from app.services.publish_platforms import FB, TH
from app.services.webhook_normalize import secret

logger = logging.getLogger("mwb.thumbnails")
# 每輪最多處理的貼文數；每篇 FB／IG 只花一次 Meta 呼叫，其餘下一輪接續。
BATCH = 20
SIDE = 480
SOURCE_BYTES = 8 * 1024 * 1024
PIXELS = 40_000_000
# 暫時失敗依序 1／6／24 小時後重試，第四次仍失敗就不再嘗試。
RETRY_HOURS = (1, 6, 24)
CDN_HOSTS = (
    "fbcdn.net",
    "cdninstagram.com",
    "ytimg.com",
    "tiktokcdn.com",
    "tiktokcdn-us.com",
    "tiktokcdn-eu.com",
)
YOUTUBE_IMAGE = "https://i.ytimg.com/vi/{}/hqdefault.jpg"
# video/query 需要 video.list 權限；cover_image_url 是幾小時就過期的簽章網址，取到後立刻下載。
TIKTOK_QUERY_URL = "https://open.tiktokapis.com/v2/video/query/"


class Unavailable(Exception):
    """平台沒有可用的圖片（純文字、已刪除、格式不支援），不再重試。"""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class Retry(Unavailable):
    """暫時失敗（網路、限流、平台錯誤），稍後重試。"""


class Budget(Exception):
    """Meta 呼叫配額或冷卻中，這一輪不再呼叫 Meta。"""


class Paused(Exception):
    """TikTok 連結失效、權限不足或限流，這一輪不再呼叫 TikTok，也不消耗重試次數。"""


def http_get(url, *, headers=None, params=None, timeout=15):
    with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        with client.stream("GET", url, headers=headers, params=params) as response:
            chunks, total = [], 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > SOURCE_BYTES:
                    raise Unavailable("image_too_large")
                chunks.append(chunk)
            return response.status_code, b"".join(chunks)


def http_post(url, *, headers=None, params=None, body=None, timeout=15):
    with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        response = client.post(url, headers=headers, params=params, json=body)
        return response.status_code, response.content


def parse(content):
    try:
        data = json.loads(content or b"{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def meta_object(factory, settings, get, platform, account, external_id, fields):
    with factory() as session:
        permit = meta_api.start_call(
            session,
            ApiCallStart(
                platform=platform,
                account_external_id=account,
                source="metrics",
                operation="post",
                resource_id=external_id,
            ),
            settings,
        )
    if not permit["allowed"]:
        raise Budget()
    started = time.monotonic()
    status, code = 0, None
    try:
        status, content = get(
            FB + "/" + quote(external_id, safe=""),
            headers={"Authorization": "Bearer " + secret(settings, "meta_page_access_token")},
            params={"fields": fields},
        )
        data = parse(content)
        error = data.get("error") if isinstance(data.get("error"), dict) else {}
        code = error.get("code") if type(error.get("code")) is int else None
    except Unavailable:
        raise
    except Exception as error:
        log_failure("mwb.thumbnails", "thumbnail_graph_failed", error)
        raise Retry(
            "meta_timeout" if isinstance(error, httpx.TimeoutException) else "network_error"
        ) from None
    finally:
        with factory() as session:
            meta_api.finish_call(
                session,
                ApiCallFinish(
                    call_id=permit["call_id"],
                    http_status=status,
                    error_code=code,
                    duration_ms=round((time.monotonic() - started) * 1000),
                ),
            )
    if status == 200 and code is None:
        return data
    # 100＝物件不存在或欄位不支援（多半是貼文已刪除），不必重試。
    if code == 100 or status == 404:
        raise Unavailable("not_found")
    raise Retry("meta_rate_limited" if code in (4, 17, 32, 613) or status == 429 else "meta_error")


def threads_object(get, token, external_id):
    try:
        status, content = get(
            TH + "/" + quote(external_id, safe=""),
            headers={"Authorization": "Bearer " + token},
            params={"fields": "media_type,media_url,thumbnail_url"},
        )
    except Unavailable:
        raise
    except Exception as error:
        log_failure("mwb.thumbnails", "thumbnail_threads_failed", error)
        raise Retry("network_error") from None
    data = parse(content)
    if status == 200 and not data.get("error"):
        return data
    if status in (400, 404):
        raise Unavailable("not_found")
    raise Retry("threads_error")


def tiktok_object(post, token, external_id):
    try:
        status, content = post(
            TIKTOK_QUERY_URL,
            headers={"Authorization": "Bearer " + token},
            params={"fields": "id,cover_image_url"},
            body={"filters": {"video_ids": [external_id]}},
        )
    except Exception as error:
        log_failure("mwb.thumbnails", "thumbnail_tiktok_failed", error)
        raise Retry("network_error") from None
    data = parse(content)
    error = data.get("error") if isinstance(data.get("error"), dict) else {}
    code = error.get("code")
    if status == 429 or code == "rate_limit_exceeded":
        raise Paused()
    if status == 401 or code in {"access_token_invalid", "invalid_token", "scope_not_authorized"}:
        raise Paused()
    payload = data.get("data") if isinstance(data.get("data"), dict) else {}
    if status != 200 or code not in {"ok", None}:
        raise Retry("tiktok_error")
    videos = payload.get("videos")
    if not isinstance(videos, list):
        raise Retry("tiktok_error")
    # video/query 只回這個帳號的公開影片；空清單代表已刪除或改為私人。
    for video in videos:
        if isinstance(video, dict) and str(video.get("id")) == external_id:
            return video
    raise Unavailable("not_found")


def source_url(factory, settings, get, platform, account, external_id, *, tiktok_cover=None):
    if platform == "youtube":
        if not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", external_id):
            raise Unavailable("no_image")
        return YOUTUBE_IMAGE.format(external_id)
    if platform == "facebook":
        data = meta_object(factory, settings, get, platform, account, external_id, "full_picture")
        url = data.get("full_picture")
    elif platform == "instagram":
        data = meta_object(
            factory,
            settings,
            get,
            platform,
            account,
            external_id,
            "media_type,media_url,thumbnail_url",
        )
        # 影片的 media_url 是影片檔，封面在 thumbnail_url。
        url = data.get("thumbnail_url") or (
            data.get("media_url") if data.get("media_type") != "VIDEO" else None
        )
    elif platform == "threads":
        data = threads_object(get, secret(settings, "threads_access_token"), external_id)
        url = data.get("thumbnail_url") or (
            data.get("media_url") if data.get("media_type") in ("IMAGE", "CAROUSEL_ALBUM") else None
        )
    elif platform == "tiktok" and tiktok_cover is not None:
        url = tiktok_cover(external_id).get("cover_image_url")
    else:
        raise Unavailable("no_image")
    if not isinstance(url, str) or not url:
        raise Unavailable("no_image")
    return url


def allowed(url):
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(
        host == suffix or host.endswith("." + suffix) for suffix in CDN_HOSTS
    )


def shrink(content):
    try:
        with Image.open(io.BytesIO(content)) as original:
            if original.format not in ("JPEG", "PNG", "WEBP", "GIF"):
                raise Unavailable("unsupported_image")
            if original.width * original.height > PIXELS:
                raise Unavailable("image_too_large")
            original.draft("RGB", (SIDE, SIDE))
            image = ImageOps.exif_transpose(original)
            image.thumbnail((SIDE, SIDE))
            if image.mode in ("RGBA", "LA", "P"):
                image = image.convert("RGBA")
                # 透明背景改白底，避免 JPEG 轉成黑底。
                background = Image.new("RGB", image.size, (255, 255, 255))
                background.paste(image, mask=image.getchannel("A"))
                image = background
            elif image.mode != "RGB":
                image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, "JPEG", quality=82, optimize=True)
            return output.getvalue(), image.width, image.height
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError):
        raise Retry("invalid_image") from None


def download(get, url, *, platform=None):
    if not allowed(url):
        # 只記主機名稱（不含簽章參數），平台換 CDN 時才知道要補哪個網域。
        logger.warning("thumbnail_untrusted_host host=%s", (urlsplit(url).hostname or "")[:100])
        # TikTok 文件沒寫封面 CDN 網域，先走重試，補上網域後不必手動重設。
        raise (Retry if platform == "tiktok" else Unavailable)("untrusted_host")
    try:
        status, content = get(url)
    except Unavailable:
        raise
    except Exception as error:
        log_failure("mwb.thumbnails", "thumbnail_download_failed", error)
        raise Retry("network_error") from None
    if status == 404:
        raise Unavailable("not_found")
    if status != 200 or not content:
        raise Retry("download_failed")
    return shrink(content)


def store(factory, post_id, now, *, image=None, failure=None):
    with factory.begin() as session:
        row = session.scalar(select(PostThumbnail).where(PostThumbnail.post_id == post_id))
        if row is None:
            row = PostThumbnail(post_id=post_id, attempts=0)
            session.add(row)
        row.attempts += 1
        if image is not None:
            data, width, height = image
            row.status, row.mime, row.width, row.height = "ready", "image/jpeg", width, height
            row.data, row.digest = data, hashlib.sha256(data).hexdigest()
            row.next_attempt_at = row.error = None
            return
        row.error = failure.code
        if isinstance(failure, Retry) and row.attempts <= len(RETRY_HOURS):
            row.status = "retry"
            row.next_attempt_at = now + timedelta(hours=RETRY_HOURS[row.attempts - 1])
        else:
            row.status, row.next_attempt_at = "unavailable", None


def ready_platforms(factory, settings):
    platforms = {"youtube"}
    if secret(settings, "meta_page_access_token"):
        platforms |= {"facebook", "instagram"}
    if secret(settings, "threads_access_token"):
        with factory() as session:
            if oauth.threads_data_access(session, settings) != "missing":
                platforms.add("threads")
    # 與 TikTok 同步相同條件：連結正常、有 video.list，且只對應一個已連線帳號。
    if tiktok.account(factory, settings):
        platforms.add("tiktok")
    return platforms


def due(factory, platforms, now, limit):
    with factory() as session:
        return session.execute(
            select(Post.id, Post.external_id, Account.platform, Account.external_id)
            .join(Account, Account.id == Post.account_id)
            .outerjoin(PostThumbnail, PostThumbnail.post_id == Post.id)
            .where(
                Post.deleted_at.is_(None),
                Account.platform.in_(platforms),
                or_(
                    PostThumbnail.id.is_(None),
                    and_(PostThumbnail.status == "retry", PostThumbnail.next_attempt_at <= now),
                ),
            )
            .order_by(Post.published_at.desc(), Post.id.desc())
            .limit(limit)
        ).all()


def tiktok_reader(factory, settings, post):
    token = None

    def cover(external_id):
        nonlocal token
        if token is None:
            try:
                token = tiktok_oauth.access_token(factory, settings)
            except oauth.ProviderFailure:
                raise Paused() from None
        return tiktok_object(post, token, external_id)

    return cover


def hourly(factory, settings, *, get=http_get, post=http_post, now=None, limit=BATCH):
    """隨每小時數據排程執行；回傳本輪新存的縮圖數，0 時排程視為空跑。"""
    now = now or utc_now()
    saved = 0
    try:
        blocked = set()
        tiktok_cover = tiktok_reader(factory, settings, post)
        for post_id, external_id, platform, account in due(
            factory, ready_platforms(factory, settings), now, limit
        ):
            if platform in blocked:
                continue
            try:
                url = source_url(
                    factory,
                    settings,
                    get,
                    platform,
                    account,
                    external_id,
                    tiktok_cover=tiktok_cover,
                )
                store(factory, post_id, now, image=download(get, url, platform=platform))
                saved += 1
            except Budget:
                blocked |= {"facebook", "instagram"}
            except Paused:
                blocked.add("tiktok")
            except Unavailable as failure:
                store(factory, post_id, now, failure=failure)
                if failure.code == "meta_rate_limited":
                    blocked |= {"facebook", "instagram"}
    except Exception as error:
        log_failure("mwb.thumbnails", "thumbnail_round_failed", error)
    return saved


def image(access, post_id):
    from app.services.catalog import get_record

    post = get_record(access, Post, post_id)
    row = access.session.scalar(
        select(PostThumbnail).where(
            PostThumbnail.post_id == post.id, PostThumbnail.status == "ready"
        )
    )
    if row is None or not row.data:
        raise HTTPException(404, "這篇貼文沒有縮圖")
    return Response(
        row.data,
        media_type=row.mime or "image/jpeg",
        headers={"X-Content-Type-Options": "nosniff"},
    )

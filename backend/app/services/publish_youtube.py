"""YouTube Data API adapter: resumable video upload and custom thumbnails.

呼叫端不持有資料庫寫入交易。HTTP 一律經 publish_platforms.client_factory（測試與隔離驗收以
MockTransport 取代），只允許官方 Google API 主機。
"""

import json
import re
import time
from urllib.parse import urlsplit

import httpx

from app.models.base import utc_now
from app.services import publish_platforms, publish_rules, settings_store
from app.services.publish_media import path_for

UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
THUMBNAIL_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
HOSTS = {"www.googleapis.com"}
# 分段大小必須是 256 KiB 的整數倍（最後一段除外）。
CHUNK = 8 * 1024 * 1024
# 中斷或 500／502／503／504 時最多重試的次數，以及每次重試前的等待秒數（指數退避）。
RETRY_LIMIT = 5
BACKOFF = (1, 2, 4, 8, 16)
RETRYABLE = {500, 502, 503, 504}
PRIVACY = {"public", "unlisted", "private"}
# videos.insert 每日 100 次（獨立額度）；thumbnails.set 約 50 單位，與讀取共用每日單位數。
UPLOAD_DAILY_LIMIT = 100
THUMBNAIL_UNITS = 50
UPLOADS_KEY = "youtube.uploads"
QUOTA_KEY = "youtube.quota"


class SessionExpired(Exception):
    """上傳工作階段已失效（404）；必須重新開始。"""


def fail(code):
    return publish_platforms.PlatformFailure(code)


def video_id(value):
    # YouTube 影片編號含 - 與 _，不能用 Meta 的 safe_id。
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise fail("unknown")
    return value


def official(url):
    """只接受官方 Google 上傳端點，禁止任意網址或轉址。"""
    try:
        parts = urlsplit(url)
    except ValueError:
        raise fail("unknown") from None
    if (
        parts.scheme != "https"
        or parts.hostname not in HOSTS
        or parts.username
        or parts.password
        or parts.port
        or not parts.path.startswith("/upload/youtube/v3/")
    ):
        raise fail("unknown")
    return url


def reason_of(response):
    try:
        body = response.json()
    except ValueError:
        return None
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return None
    errors = error.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        return errors[0].get("reason")
    return error.get("status")


METADATA_REASONS = {
    "invalidTitle",
    "invalidDescription",
    "invalidCategoryId",
    "invalidTags",
    "invalidVideoMetadata",
    "defaultLanguageNotSet",
    "invalidRecordingDetails",
}
QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded", "uploadLimitExceeded"}


def classify(response):
    """把 YouTube 錯誤回應對應到發佈錯誤代碼（建立工作階段與上傳位元組共用）。"""
    status, reason = response.status_code, reason_of(response)
    if status == 401:
        return "token_invalid"
    if reason in QUOTA_REASONS:
        return "quota_exceeded"
    if status == 429 or reason == "rateLimitExceeded":
        return "rate_limited"
    if status == 403:
        return "permission_missing"
    if status == 400:
        return "metadata_rejected" if reason in METADATA_REASONS else "media_rejected"
    return "unknown"


def thumbnail_failure(response):
    status, reason = response.status_code, reason_of(response)
    if status == 401:
        return "token_invalid"
    if reason in QUOTA_REASONS:
        return "quota_exceeded"
    if status == 429 or reason in {"uploadRateLimitExceeded", "rateLimitExceeded"}:
        return "rate_limited"
    if status == 403:
        return "forbidden"
    if status == 404:
        return "not_found"
    if status == 400:
        return "invalid_image"
    return "unknown"


def reserve(factory, kind):
    """在呼叫前先扣額度（失敗的呼叫同樣消耗額度）；超過每日上限就不送出。"""
    from app.services.youtube import DAILY_LIMIT, PACIFIC

    if kind == "upload":
        key, units, limit = UPLOADS_KEY, 1, UPLOAD_DAILY_LIMIT
    else:
        key, units, limit = QUOTA_KEY, THUMBNAIL_UNITS, DAILY_LIMIT
    day = utc_now().astimezone(PACIFIC).date().isoformat()
    with factory.begin() as session:
        row = settings_store.get(session, key)
        used = row.value_json.get("used", 0) if row and row.value_json.get("day") == day else 0
        if used + units > limit:
            raise fail("quota_exceeded")
        value = {"day": day, "used": used + units}
        settings_store.put(session, key, value, row)


def headers(token, **extra):
    return {"Authorization": "Bearer " + token, **extra}


def start_session(client, token, metadata, mime, total):
    body = json.dumps(metadata, ensure_ascii=False).encode("utf-8")
    for attempt in range(RETRY_LIMIT + 1):
        try:
            response = client.post(
                UPLOAD_URL,
                params={"uploadType": "resumable", "part": "snippet,status"},
                headers=headers(
                    token,
                    **{
                        "Content-Type": "application/json; charset=UTF-8",
                        "X-Upload-Content-Length": str(total),
                        "X-Upload-Content-Type": mime,
                    },
                ),
                content=body,
            )
        except httpx.TimeoutException:
            response = None
        except httpx.HTTPError:
            response = None
        if response is not None and response.status_code == 200:
            location = response.headers.get("location")
            if not location:
                raise fail("unknown")
            return official(location)
        if response is not None and response.status_code not in RETRYABLE:
            raise fail(classify(response))
        if attempt == RETRY_LIMIT:
            raise fail("unknown" if response is not None else "timeout")
        time.sleep(BACKOFF[attempt])
    raise fail("unknown")


def next_offset(response, total):
    """308 的 Range 標頭（bytes=0-N）表示已收到 N 位元組之前（含）；沒有標頭表示尚未收到。"""
    value = response.headers.get("range")
    if not value:
        return 0
    match = re.fullmatch(r"bytes=0-(\d+)", value.strip())
    if not match:
        raise fail("unknown")
    offset = int(match.group(1)) + 1
    if offset > total:
        raise fail("unknown")
    return offset


def completed(response):
    try:
        body = response.json()
    except ValueError:
        raise fail("unknown") from None
    if not isinstance(body, dict):
        raise fail("unknown")
    return body


def query_status(client, token, session, total):
    """詢問伺服器已收到多少；回傳 (offset, None) 或 (None, 已完成的影片資源)。"""
    try:
        response = client.put(
            session,
            headers=headers(token, **{"Content-Length": "0", "Content-Range": f"bytes */{total}"}),
            content=b"",
        )
    except httpx.HTTPError:
        return "retry", None
    if response.status_code in (200, 201):
        return None, completed(response)
    if response.status_code == 308:
        return next_offset(response, total), None
    if response.status_code == 404:
        raise SessionExpired
    if response.status_code in RETRYABLE:
        return "retry", None
    raise fail(classify(response))


def send(client, token, session, path, mime, total, offset):
    """從 offset 開始分段上傳；中斷或暫時錯誤時先問伺服器收到多少再續傳，不盲目重送。"""
    failures = 0
    with path.open("rb") as file:
        while True:
            file.seek(offset)
            chunk = file.read(min(CHUNK, total - offset))
            if not chunk:
                raise fail("unknown")
            end = offset + len(chunk) - 1
            try:
                response = client.put(
                    session,
                    headers=headers(
                        token,
                        **{"Content-Type": mime, "Content-Range": f"bytes {offset}-{end}/{total}"},
                    ),
                    content=chunk,
                )
            except httpx.HTTPError:
                response = None
            if response is not None and response.status_code in (200, 201):
                return completed(response)
            if response is not None and response.status_code == 308:
                offset, failures = next_offset(response, total), 0
                continue
            if response is not None and response.status_code == 404:
                raise SessionExpired
            if response is not None and response.status_code not in RETRYABLE:
                raise fail(classify(response))
            # 中斷或 5xx：退避後詢問伺服器實際收到的位元組數，再從那裡續傳。
            while True:
                failures += 1
                if failures > RETRY_LIMIT:
                    raise fail("timeout")
                time.sleep(BACKOFF[failures - 1])
                known, body = query_status(client, token, session, total)
                if body is not None:
                    return body
                if known != "retry":
                    offset = known
                    break


def upload_video(settings, token, item, metadata, progress, checkpoint, quota):
    """上傳影片並回傳完成後的影片資源。可由先前保存的工作階段續傳；失效時只重開一次。"""
    path = path_for(settings, item)
    try:
        actual = path.stat().st_size
    except OSError:
        raise fail("media_rejected") from None
    if actual != item.size or actual <= 0:
        raise fail("media_rejected")
    saved = progress.get("upload") or {}
    session = saved.get("session") if saved.get("media_id") == item.id else None
    if session is not None:
        session = official(session)
    restarts = 0
    with publish_platforms.client_factory() as client:
        while True:
            try:
                offset, body = 0, None
                if session is not None:
                    offset, body = query_status(client, token, session, item.size)
                    if offset == "retry":
                        raise fail("timeout")
                if body is None:
                    if session is None:
                        quota("upload")
                        session = start_session(client, token, metadata, item.mime, item.size)
                        saved = {"session": session, "media_id": item.id, "size": item.size}
                        checkpoint({"upload": saved}, None, None)
                        offset = 0
                    body = send(client, token, session, path, item.mime, item.size, offset)
                return body
            except SessionExpired:
                restarts += 1
                if restarts > 1:
                    raise fail("unknown") from None
                session = None


def apply_thumbnail(settings, token, identifier, thumbnail):
    """套用自訂縮圖；回傳 {"status": ..., "code": ...}，不丟例外（縮圖失敗不影響影片）。"""
    try:
        path = path_for(settings, thumbnail)
        data = path.read_bytes()
    except Exception:
        return {"status": "failed", "code": "file_missing"}
    try:
        with publish_platforms.client_factory() as client:
            response = client.post(
                THUMBNAIL_URL,
                params={"videoId": identifier, "uploadType": "media"},
                headers=headers(token, **{"Content-Type": thumbnail.mime}),
                content=data,
            )
    except httpx.HTTPError:
        return {"status": "failed", "code": "unknown"}
    if response.status_code == 200:
        return {"status": "applied"}
    return {"status": "failed", "code": thumbnail_failure(response)}


def metadata_for(post, category):
    options = publish_rules.platform_options(post)["youtube"]
    caption = publish_rules.youtube_caption(post)
    title = publish_rules.youtube_title(options, caption)
    rule = publish_rules.RULES["youtube"]
    # 送出前再擋一次：標題或說明不合規則時不上傳影片。
    if not title or len(title) > rule["title"] or len(caption.encode("utf-8")) > rule["caption"]:
        raise fail("metadata_rejected")
    return {
        "snippet": {"title": title, "description": caption, "categoryId": category},
        "status": {
            "privacyStatus": options["privacy"],
            "selfDeclaredMadeForKids": bool(options["made_for_kids"]),
        },
    }


def publish(
    settings,
    token,
    post,
    media,
    thumbnail,
    *,
    category,
    progress=None,
    checkpoint=None,
    quota=None,
):
    """回傳 (影片編號, 觀看網址)。影片已有編號（先前已完成上傳）時不再重傳。"""
    progress = progress or {}
    checkpoint = checkpoint or (lambda detail, first, link: None)
    quota = quota or (lambda kind: None)
    if len(media) != 1 or not media[0].mime.startswith("video/"):
        raise fail("media_rejected")
    saved = {key: progress[key] for key in ("video_id", "privacy_status") if key in progress}
    identifier = progress.get("video_id")
    if identifier is None:
        body = upload_video(
            settings, token, media[0], metadata_for(post, category), progress, checkpoint, quota
        )
        identifier = video_id(body.get("id"))
        # YouTube 回報的實際公開狀態：與選擇不同時（例如專案未通過稽核被鎖為私人）要讓使用者看見。
        status = body.get("status")
        actual = status.get("privacyStatus") if isinstance(status, dict) else None
        saved = {"video_id": identifier}
        if actual in PRIVACY:
            saved["privacy_status"] = actual
        # 影片編號先持久化，之後的縮圖步驟無論成敗都不會讓影片重傳。
        checkpoint(saved, identifier, watch_url(identifier))
    link = watch_url(identifier)
    previous = progress.get("thumbnail") or {}
    if thumbnail is not None and previous.get("status") != "applied":
        if publish_rules.is_short(media[0]):
            outcome = {"status": "skipped", "code": "shorts"}
        else:
            try:
                quota("thumbnail")
                outcome = apply_thumbnail(settings, token, identifier, thumbnail)
            except publish_platforms.PlatformFailure as failure:
                outcome = {"status": "failed", "code": failure.code}
        checkpoint({**saved, "thumbnail": outcome}, identifier, link)
    return identifier, link


def watch_url(identifier):
    return "https://www.youtube.com/watch?v=" + video_id(identifier)


"""X API v2 adapter: upload media with the v2 chunked endpoints, then create one post.

X bills every request against prepaid credits, so the adapter makes the fewest calls it can and
never repeats a post blindly: uploaded media IDs and the moment it started creating the post are
checkpointed first. A retry after an unanswered create reads the account's own recent posts
(an inexpensive owned read) to see whether it went through. HTTP always goes through
publish_platforms.client_factory (MockTransport in tests) and only reaches api.x.com.
Callers hold no database write transaction.
"""

import html
import re
import time
from datetime import datetime, timedelta

import httpx

from app.models.base import utc_now
from app.services import publish_platforms, publish_rules
from app.services.publish_media import path_for

API = "https://api.x.com/2"
INIT_URL = API + "/media/upload/initialize"
STATUS_URL = API + "/media/upload"
POST_URL = API + "/tweets"
CHUNK = 4 * 1024 * 1024
# 媒體編號官方保留 24 小時；超過 12 小時的舊上傳在重試時重新上傳，避免送出時已過期。
MEDIA_REUSE = timedelta(hours=12)
PROCESS_SECONDS = 300
RETRY_LIMIT = 3


def fail(code):
    return publish_platforms.PlatformFailure(code)


def media_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{1,30}", value):
        raise fail("unknown")
    return value


def failure_for(response, data, *, media=False):
    status = response.status_code
    detail = ""
    if isinstance(data, dict):
        detail = " ".join(
            str(data.get(key, "")) for key in ("detail", "title", "type") if data.get(key)
        ).lower()
    if status == 401:
        return fail("token_invalid")
    if status == 402 or "credits" in detail or "spend" in detail:
        return fail("credits_exhausted")
    if status == 403 and "duplicate" in detail:
        return fail("duplicate_content")
    if status == 403:
        return fail("permission_missing")
    if status == 429:
        return fail("rate_limited")
    if 400 <= status < 500:
        return fail("media_rejected" if media else "content_rejected")
    return fail("unknown")


def call(client, method, url, token, *, json=None, params=None, files=None, media=False):
    for attempt in range(RETRY_LIMIT + 1):
        try:
            response = client.request(
                method,
                url,
                headers={"Authorization": "Bearer " + token},
                json=json,
                params=params,
                files=files,
            )
        except httpx.TimeoutException:
            raise fail("timeout") from None
        except httpx.HTTPError:
            raise fail("unknown") from None
        # 媒體分段與查詢可以安全重試；建立貼文由 create() 自己處理，不在這裡重送。
        if response.status_code in {500, 502, 503, 504} and media and attempt < RETRY_LIMIT:
            time.sleep(2**attempt)
            continue
        break
    try:
        data = response.json() if response.content else {}
    except ValueError:
        data = None
    if response.status_code in {200, 201, 202, 204} and isinstance(data, dict):
        if data.get("errors") and not data.get("data"):
            raise failure_for(response, data["errors"][0] if data["errors"] else {}, media=media)
        return data
    raise failure_for(response, data, media=media)


def category(item):
    return "tweet_video" if item.mime.startswith("video/") else "tweet_image"


def upload(client, settings, token, item):
    path = path_for(settings, item)
    try:
        actual = path.stat().st_size
    except OSError:
        raise fail("media_rejected") from None
    if actual != item.size or actual <= 0:
        raise fail("media_rejected")
    data = call(
        client,
        "POST",
        INIT_URL,
        token,
        json={"media_type": item.mime, "total_bytes": item.size, "media_category": category(item)},
        media=True,
    )
    identity = media_id((data.get("data") or {}).get("id"))
    with path.open("rb") as file:
        index = 0
        while chunk := file.read(CHUNK):
            append(client, token, identity, index, chunk)
            index += 1
    data = call(client, "POST", f"{API}/media/upload/{identity}/finalize", token, media=True)
    wait(client, token, identity, (data.get("data") or {}).get("processing_info"))
    return identity


def append(client, token, identity, index, chunk):
    call(
        client,
        "POST",
        f"{API}/media/upload/{identity}/append",
        token,
        files={
            "media": ("chunk", chunk, "application/octet-stream"),
            "segment_index": (None, str(index)),
        },
        media=True,
    )


def wait(client, token, identity, info):
    """影片轉檔完成才可以附在貼文上；圖片通常沒有 processing_info。"""
    deadline = time.monotonic() + PROCESS_SECONDS
    while isinstance(info, dict) and info.get("state") in {"pending", "in_progress"}:
        if time.monotonic() > deadline:
            raise fail("timeout")
        delay = info.get("check_after_secs")
        time.sleep(min(delay, 30) if type(delay) is int and delay > 0 else 5)
        data = call(
            client,
            "GET",
            STATUS_URL,
            token,
            params={"command": "STATUS", "media_id": identity},
            media=True,
        )
        info = (data.get("data") or {}).get("processing_info")
    if isinstance(info, dict) and info.get("state") == "failed":
        raise fail("media_rejected")


def comparable(text):
    # X 會把網址換成 t.co、在附媒體時加上連結，並對 & < > 做 HTML 跳脫；比對時去掉這些差異。
    return " ".join(publish_rules.X_URL.sub(" ", html.unescape(text or "")).split())


def find_created(client, token, account, text, since):
    """上次建立貼文沒有收到回應：讀自己最近的貼文確認是否已經發出。"""
    data = call(
        client,
        "GET",
        f"{API}/users/{account}/tweets",
        token,
        params={
            "max_results": 5,
            "start_time": (since - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tweet.fields": "created_at",
        },
        media=True,
    )
    wanted = comparable(text)
    for item in data.get("data") or []:
        if isinstance(item, dict) and comparable(item.get("text")) == wanted:
            return media_id(item.get("id"))
    return None


def permalink(identity):
    return "https://x.com/i/web/status/" + identity


def publish(settings, token, account, post, media, *, progress=None, checkpoint=None):
    progress = dict(progress or {})
    checkpoint = checkpoint or (lambda detail, first, link: None)
    if progress.get("post_id"):
        identity = media_id(progress["post_id"])
        return identity, permalink(identity)
    text = publish_rules.platform_caption(post, "x")
    media_account = media_id(account)
    with publish_platforms.client_factory() as client:
        if progress.get("creating_at"):
            since = datetime.fromisoformat(progress["creating_at"])
            found = find_created(client, token, media_account, text, since)
            if found:
                checkpoint({**progress, "post_id": found}, found, permalink(found))
                return found, permalink(found)
            progress.pop("creating_at")
        ids = progress.get("media_ids") or []
        uploaded = progress.get("uploaded_at")
        if (
            not ids
            or len(ids) != len(media)
            or not uploaded
            or (utc_now() - datetime.fromisoformat(uploaded) > MEDIA_REUSE)
        ):
            ids = [upload(client, settings, token, item) for item in media]
            progress = {**progress, "media_ids": ids, "uploaded_at": utc_now().isoformat()}
            checkpoint(progress, None, None)
        body = {"text": text}
        if ids:
            body["media"] = {"media_ids": [media_id(i) for i in ids]}
        # 送出前先記下時間：沒收到回應時，下一次重試據此讀回確認，不會重複發文。
        progress = {**progress, "creating_at": utc_now().isoformat()}
        checkpoint(progress, None, None)
        try:
            data = call(client, "POST", POST_URL, token, json=body)
        except publish_platforms.PlatformFailure as failure:
            if failure.code not in {"timeout", "unknown"}:
                # X 明確拒絕（重複內容、點數不足等）：確定沒發出，重試時不必再讀回確認。
                progress.pop("creating_at")
                checkpoint(progress, None, None)
            raise
        identity = media_id((data.get("data") or {}).get("id"))
        progress.pop("creating_at")
        checkpoint({**progress, "post_id": identity}, identity, permalink(identity))
        return identity, permalink(identity)

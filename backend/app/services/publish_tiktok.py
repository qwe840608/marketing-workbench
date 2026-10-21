"""TikTok Content Posting API adapter: send one video to the creator's TikTok inbox.

The app stays unaudited (docs/TikTok規劃.md), so it never posts directly: the video lands in
the inbox and the creator adds the caption, sound and privacy in the TikTok app. The inbox
API takes no caption at all, which is why the publish page offers "copy caption". HTTP always
goes through publish_platforms.client_factory (MockTransport in tests) and only reaches
official TikTok hosts. Callers hold no database write transaction.
"""

import re
import time
from datetime import timedelta
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select

from app.models import PublishPost, PublishTarget
from app.models.base import utc_now
from app.services import oauth, publish_platforms, tiktok_oauth
from app.services.publish_media import path_for

INIT_URL = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
MB = 1024 * 1024
# 官方規則：每段 5–64 MB、最後一段可到 128 MB、未滿 5 MB 整檔一次、最多 1000 段、依序上傳。
CHUNK = 10 * MB
SINGLE = 64 * MB
RETRY_LIMIT = 3
RETRYABLE = {500, 502, 503, 504}
# 上傳完成後等 TikTok 處理到收件匣；超過就先記為處理中，之後由 refresh() 接續查詢。
SETTLE_SECONDS = 60
POLL_SECONDS = 3
# 送到收件匣後追蹤 7 天，看使用者是否在 App 內發佈；每 10 分鐘最多查一次（官方 30 次／分）。
FOLLOW_DAYS = 7
REFRESH_GAP = timedelta(minutes=10)
FINAL = {"PUBLISH_COMPLETE", "FAILED"}
ERROR_CODES = {
    "spam_risk_too_many_pending_share": "inbox_full",
    "spam_risk_user_banned_from_posting": "posting_banned",
    "access_token_invalid": "token_invalid",
    "scope_not_authorized": "permission_missing",
    "rate_limit_exceeded": "rate_limited",
    "invalid_param": "media_rejected",
}
MEDIA_FAILURES = {
    "file_format_check_failed",
    "duration_check_failed",
    "frame_rate_check_failed",
    "picture_size_check_failed",
}
# 狀態查詢的 fail_reason（官方 get-video-status）：只有 internal（TikTok 暫時故障）重新上傳。
# 規格不符用同一個檔案重傳仍會被拒，只會多耗每日發文次數；spam_risk 類、帳號禁發與撤銷授權
# 官方明示不要重試。這些情況重試時直接回報原因、不再上傳。
FAIL_REASONS = {
    "internal": "platform_busy",
    "auth_removed": "token_invalid",
    "spam_risk_too_many_posts": "posting_limited",
    "spam_risk_user_banned_from_posting": "posting_banned",
    "spam_risk": "spam_risk",
    "spam_risk_text": "spam_risk",
}
REUPLOAD_REASONS = {"internal"}


def fail(code):
    return publish_platforms.PlatformFailure(code)


def failure_code(reason):
    return "media_rejected" if reason in MEDIA_FAILURES else FAIL_REASONS.get(reason, "unknown")


def publish_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._~-]{1,64}", value):
        raise fail("unknown")
    return value


def upload_url(value):
    """Only TikTok's own upload hosts, https, no credentials or ports."""
    try:
        parts = urlsplit(value) if isinstance(value, str) else None
    except ValueError:
        parts = None
    if (
        not parts
        or len(value) > 2048
        or parts.scheme != "https"
        or not (parts.hostname or "").endswith(".tiktokapis.com")
        or parts.username
        or parts.password
        or parts.port
    ):
        raise fail("unknown")
    return value


def plan(size):
    """(chunk_size, total_chunk_count) following the media transfer guide."""
    if size <= 0:
        raise fail("media_rejected")
    if size <= SINGLE:
        # 未滿 5 MB 必須整檔；64 MB 以內一段即可（chunk_size 等於檔案大小）。
        return size, 1
    # 10 MB 一段，最後一段吸收餘數（不超過 20 MB）；1 GB 上限時最多約 100 段。
    return CHUNK, size // CHUNK


def call(client, url, token, body):
    try:
        response = client.post(
            url,
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json; charset=UTF-8",
            },
            json=body,
        )
    except httpx.TimeoutException:
        raise fail("timeout") from None
    except httpx.HTTPError:
        raise fail("unknown") from None
    try:
        data = response.json()
    except ValueError:
        data = None
    error = data.get("error") if isinstance(data, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    if response.status_code == 200 and code in {"ok", None} and isinstance(data.get("data"), dict):
        return data["data"]
    if code in ERROR_CODES:
        raise fail(ERROR_CODES[code])
    if response.status_code == 401:
        raise fail("token_invalid")
    if response.status_code == 429:
        raise fail("rate_limited")
    failure = fail("unknown")
    # TikTok 明確拒絕這個請求（4xx），不是網路或伺服器問題；重試時據此判斷 publish_id 已失效。
    failure.rejected = 400 <= response.status_code < 500
    raise failure


def status(client, token, identity):
    data = call(client, STATUS_URL, token, {"publish_id": identity})
    value = data.get("status")
    if value not in {
        "PROCESSING_UPLOAD",
        "PROCESSING_DOWNLOAD",
        "SEND_TO_USER_INBOX",
        "PUBLISH_COMPLETE",
        "FAILED",
    }:
        raise fail("unknown")
    ids = data.get("publicaly_available_post_id")
    posted = [str(i) for i in ids if type(i) is int and i > 0] if isinstance(ids, list) else []
    reason = data.get("fail_reason")
    return {
        "inbox_state": value,
        "post_ids": posted[:5],
        **({"fail_reason": reason[:60]} if isinstance(reason, str) and reason else {}),
    }


def send(client, url, path, mime, size):
    chunk, count = plan(size)
    with path.open("rb") as file:
        for index in range(count):
            start = index * chunk
            # 最後一段吸收餘下位元組（最多 128 MB），與 TikTok 的切分規則一致。
            end = size - 1 if index == count - 1 else start + chunk - 1
            file.seek(start)
            data = file.read(end - start + 1)
            for attempt in range(RETRY_LIMIT + 1):
                try:
                    response = client.put(
                        url,
                        headers={
                            "Content-Type": mime,
                            "Content-Length": str(len(data)),
                            "Content-Range": f"bytes {start}-{end}/{size}",
                        },
                        content=data,
                    )
                except httpx.HTTPError:
                    response = None
                if response is not None and response.status_code in {200, 201, 206}:
                    break
                if response is not None and response.status_code not in RETRYABLE:
                    # 403 網址過期、404 找不到工作、416 進度不符：都要重新開始，不盲目續傳。
                    raise fail("media_rejected" if response.status_code == 400 else "unknown")
                if attempt == RETRY_LIMIT:
                    raise fail("timeout" if response is None else "unknown")
                time.sleep(2**attempt)
            if index == count - 1 and response.status_code not in {200, 201}:
                raise fail("unknown")


def publish(settings, token, post, media, *, progress=None, checkpoint=None):
    """Upload the single video to the inbox; returns (None, None) since no post exists yet.

    A retry never uploads twice: an inbox delivery, or a finished upload TikTok is still
    processing, is followed instead of re-sent. Only an unfinished upload, an unknown
    publish_id or TikTok's retryable internal failure starts a new one.
    """
    progress = progress or {}
    checkpoint = checkpoint or (lambda detail, first, link: None)
    if len(media) != 1 or not media[0].mime.startswith("video/"):
        raise fail("media_rejected")
    item = media[0]
    path = path_for(settings, item)
    try:
        actual = path.stat().st_size
    except OSError:
        raise fail("media_rejected") from None
    if actual != item.size or actual <= 0:
        raise fail("media_rejected")
    with publish_platforms.client_factory() as client:
        previous = progress.get("publish_id")
        state = None
        if previous:
            try:
                state = status(client, token, publish_id(previous))
            except publish_platforms.PlatformFailure as failure:
                # TikTok 明確回報查不到這個 publish_id（例如未完成的上傳被清掉）才重新上傳。
                # 網路、5xx、授權或限流錯誤照常回報：狀態不明時重送可能讓影片進收件匣兩次。
                if not getattr(failure, "rejected", False):
                    raise
        if state and state["inbox_state"] in {"SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"}:
            checkpoint({**progress, **state, "checked_at": utc_now().isoformat()}, None, None)
            return None, None
        if state and state["inbox_state"] == "FAILED":
            reason = state.get("fail_reason", "")
            if reason not in REUPLOAD_REASONS:
                raise fail(failure_code(reason))
        elif state and progress.get("uploaded"):
            # 已上傳完、TikTok 仍在處理：接續追蹤同一個 publish_id，不再佔用收件匣名額。
            detail = {**progress, **state}
            return settle(client, token, previous, detail, checkpoint)
        chunk, count = plan(item.size)
        data = call(
            client,
            INIT_URL,
            token,
            {
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": item.size,
                    "chunk_size": chunk,
                    "total_chunk_count": count,
                }
            },
        )
        identity = publish_id(data.get("publish_id"))
        url = upload_url(data.get("upload_url"))
        # publish_id 先持久化：之後中斷重試可以先查狀態，不會重複送到收件匣。
        detail = {"publish_id": identity, "inbox_state": "PROCESSING_UPLOAD"}
        checkpoint(detail, None, None)
        send(client, url, path, item.mime, item.size)
        # 全部分段送完才標記：之後重試看到這個標記就只追蹤，不重新上傳。
        detail = {**detail, "uploaded": True}
        checkpoint(detail, None, None)
        return settle(client, token, identity, detail, checkpoint)


def settle(client, token, identity, detail, checkpoint):
    """Wait up to SETTLE_SECONDS for the inbox; still processing is left to refresh()."""
    deadline = time.monotonic() + SETTLE_SECONDS
    state = status(client, token, identity)
    while state["inbox_state"] == "PROCESSING_UPLOAD" and time.monotonic() < deadline:
        time.sleep(POLL_SECONDS)
        state = status(client, token, identity)
    # 失敗也先保存狀態與原因，重試時才知道能不能重新上傳。
    checkpoint({**detail, **state, "checked_at": utc_now().isoformat()}, None, None)
    if state["inbox_state"] == "FAILED":
        raise fail(failure_code(state.get("fail_reason", "")))
    return None, None


def refresh(factory, settings, now=None, failed=None):
    """Follow inbox deliveries for 7 days: did the creator post it from the TikTok app?

    A delivery TikTok later reports FAILED turns the target failed (so it can be retried) and
    calls failed(session, post) to recompute the post status and send the notice again.
    """
    now = now or utc_now()
    with factory() as session:
        rows = [
            (t.id, t.detail_json.get("publish_id"))
            for t in session.scalars(
                select(PublishTarget)
                .join(PublishPost, PublishPost.id == PublishTarget.post_id)
                .where(
                    PublishTarget.platform == "tiktok",
                    PublishTarget.status == "succeeded",
                    PublishTarget.last_attempt_at >= now - timedelta(days=FOLLOW_DAYS),
                )
            )
            if t.detail_json.get("publish_id")
            and t.detail_json.get("inbox_state") not in FINAL
            and (t.detail_json.get("checked_at") or "") <= (now - REFRESH_GAP).isoformat()
        ]
    if not rows:
        return 0
    try:
        token = tiktok_oauth.access_token(factory, settings)
    except oauth.ProviderFailure:
        return 0
    updated = 0
    with publish_platforms.client_factory() as client:
        for target_id, identity in rows:
            try:
                state = status(client, token, publish_id(identity))
            except publish_platforms.PlatformFailure:
                continue
            with factory.begin() as session:
                target = session.get(PublishTarget, target_id)
                if not target or target.status != "succeeded":
                    continue
                target.detail_json = {**target.detail_json, **state, "checked_at": now.isoformat()}
                if state["post_ids"] and not target.platform_post_id:
                    target.platform_post_id = state["post_ids"][0]
                if state["inbox_state"] == "FAILED":
                    target.status = "failed"
                    target.error_code = failure_code(state.get("fail_reason", ""))
                    post = session.get(PublishPost, target.post_id)
                    # 已排程重試或發佈中的貼文由那一輪結算；這裡改狀態會蓋掉排程、取消重試。
                    if failed and post.status in {"done", "partial", "failed"}:
                        failed(session, post)
            updated += 1
    return updated

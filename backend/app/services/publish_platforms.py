"""Official API adapters. Tests replace client_factory with MockTransport."""

import json
import logging
import re
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

from app.services import publish_rules
from app.services.graph_api import FB, RUPLOAD, TH, VIDEO
from app.services.publish_media import path_for

HOSTS = {"graph.facebook.com", "graph-video.facebook.com", "graph.threads.net"}

logger = logging.getLogger("mwb.publish")


class PlatformFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def client_factory():
    return httpx.Client(
        follow_redirects=False, trust_env=False, timeout=httpx.Timeout(60, connect=10, write=120)
    )


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,128}", value):
        raise PlatformFailure("unknown")
    return value


def safe_permalink(value):
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if (
        parts.scheme == "https"
        and parts.hostname
        in {
            "www.facebook.com",
            "facebook.com",
            "www.instagram.com",
            "instagram.com",
            "www.threads.net",
            "threads.net",
            "www.threads.com",
            "threads.com",
        }
        and not parts.username
        and not parts.password
        and not parts.query
        and not parts.fragment
    ):
        return value
    return None


def request(client, base, path, token, *, data=None, params=None, files=None):
    url = base + "/" + path
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in HOSTS or parts.username or parts.port:
        raise PlatformFailure("unknown")
    response = None
    try:
        response = client.request(
            "POST" if data is not None or files else "GET",
            url,
            headers={"Authorization": "Bearer " + token},
            data=data,
            params=params,
            files=files,
        )
        body = response.json()
    except httpx.TimeoutException:
        raise PlatformFailure("timeout") from None
    except (httpx.HTTPError, ValueError) as exc:
        # 記錄例外類型、狀態碼與回應前 200 字（Meta 回應不含權杖）。
        logger.warning(
            "platform_request_failed",
            extra={
                "path": path.split("/")[-1],
                "error_type": type(exc).__name__,
                "http_status": response.status_code if response is not None else None,
                "meta_message": response.text[:200] if response is not None else None,
            },
        )
        raise PlatformFailure("unknown") from None
    if not isinstance(body, dict):
        raise PlatformFailure("unknown")
    if response.is_error or response.is_redirect or "error" in body:
        error = body.get("error")
        if isinstance(error, dict):
            # Meta 的錯誤碼與訊息（不含權杖）寫入日誌，方便查出 unknown 的真正原因。
            logger.warning(
                "platform_request_error",
                extra={
                    "path": path.split("/")[-1],
                    "http_status": response.status_code,
                    "meta_code": error.get("code"),
                    "meta_subcode": error.get("error_subcode"),
                    "meta_type": error.get("type"),
                    "meta_message": str(error.get("message", ""))[:300],
                    "fbtrace_id": error.get("fbtrace_id"),
                },
            )
        code = error.get("code") if isinstance(error, dict) else None
        category = (
            "token_invalid"
            if code == 190 or response.status_code == 401
            else "permission_missing"
            if code in (10, 200) or response.status_code == 403
            else "rate_limited"
            if code in (4, 17, 32, 613) or response.status_code == 429
            else "media_rejected"
            if code in (100, 36003, 2207006, 2207052)
            else "unknown"
        )
        raise PlatformFailure(category)
    return body


def wait_container(client, base, container, token, settings, *, threads=False, text=False):
    deadline = time.monotonic() + settings.publish_poll_timeout
    while time.monotonic() < deadline:
        body = request(
            client,
            base,
            safe_id(container),
            token,
            params={"fields": "status" if threads else "status_code"},
        )
        status = body.get("status" if threads else "status_code")
        if status == "FINISHED":
            return
        if status in {"ERROR", "EXPIRED"}:
            raise PlatformFailure("media_rejected")
        interval = (
            max(60, settings.publish_poll_seconds)
            if threads and not text
            else settings.publish_poll_seconds
        )
        time.sleep(min(interval, max(0, deadline - time.monotonic())))
    raise PlatformFailure("timeout")


def offsets(body, size, previous=-1):
    """分段上傳的下一段範圍；必須是 0 ≤ 起點 ≤ 終點 ≤ 檔案大小，且起點要前進。"""
    try:
        begin, end = int(body.get("start_offset")), int(body.get("end_offset"))
    except (TypeError, ValueError):
        raise PlatformFailure("unknown") from None
    if not 0 <= begin <= end <= size or (begin < end and begin <= previous):
        raise PlatformFailure("unknown")
    return begin, end


def publish_feed_video(client, settings, account, token, item, data):
    """粉專一般影片用分段上傳：單次 multipart 上傳較大的檔案時 Meta 會回 413。"""
    edge = account + "/videos"
    start = request(
        client, VIDEO, edge, token, data={"upload_phase": "start", "file_size": str(item.size)}
    )
    session_id = safe_id(str(start.get("upload_session_id", "")))
    identity = safe_id(str(start.get("video_id", "")))
    begin, end = offsets(start, item.size)
    with path_for(settings, item).open("rb") as file:
        while begin < end:
            file.seek(begin)
            chunk = file.read(end - begin)
            body = request(
                client,
                VIDEO,
                edge,
                token,
                data={
                    "upload_phase": "transfer",
                    "upload_session_id": session_id,
                    "start_offset": str(begin),
                },
                files={"video_file_chunk": ("chunk", chunk, "application/octet-stream")},
            )
            begin, end = offsets(body, item.size, begin)
    finished = request(
        client,
        VIDEO,
        edge,
        token,
        data={"upload_phase": "finish", "upload_session_id": session_id, **data},
    )
    if finished.get("success") is not True:
        raise PlatformFailure("unknown")
    return identity


def apply_facebook_cover(settings, token, video, cover):
    """POST /{video-id}/thumbnails；回傳 {status, code?}，不丟例外（影片已成功）。

    需要 pages_manage_engagement；一般影片與 Reels 都用這支（Reels 發佈文件指向它）。
    """
    try:
        with client_factory() as client, path_for(settings, cover).open("rb") as file:
            body = request(
                client,
                FB,
                safe_id(video) + "/thumbnails",
                token,
                data={"is_preferred": "true"},
                files={"source": ("cover", file, cover.mime)},
            )
    except PlatformFailure as failure:
        return {"status": "failed", "code": failure.code}
    except (FileNotFoundError, HTTPException):
        return {"status": "failed", "code": "file_missing"}
    if body.get("success") is not True:
        return {"status": "failed", "code": "unknown"}
    return {"status": "applied"}


def publish_reel(client, settings, account, token, post, media):
    value = request(client, FB, account + "/video_reels", token, data={"upload_phase": "start"})
    identity = safe_id(value.get("video_id"))
    # 僅允許本次 ID 的官方 rupload endpoint，禁止任意 URL 或重新導向。
    upload_url = RUPLOAD + identity
    if value.get("upload_url") != upload_url:
        raise PlatformFailure("unknown")
    item = media[0]
    try:
        with path_for(settings, item).open("rb") as file:
            response = client.post(
                upload_url,
                headers={
                    "Authorization": "OAuth " + token,
                    "offset": "0",
                    "file_size": str(item.size),
                    "Content-Type": "application/octet-stream",
                },
                content=file,
            )
        uploaded = response.json()
    except httpx.TimeoutException:
        raise PlatformFailure("timeout") from None
    except (httpx.HTTPError, ValueError):
        raise PlatformFailure("unknown") from None
    if response.is_error or response.is_redirect or not isinstance(uploaded, dict):
        raise PlatformFailure("media_rejected")
    if uploaded.get("success") is not True:
        raise PlatformFailure("media_rejected")
    finished = request(
        client,
        FB,
        account + "/video_reels",
        token,
        data={
            "upload_phase": "finish",
            "video_id": identity,
            "video_state": "DRAFT" if post.facebook_unpublished else "PUBLISHED",
            "description": publish_rules.platform_caption(post, "facebook"),
        },
    )
    if finished.get("success") is not True:
        raise PlatformFailure("unknown")
    return identity, "https://www.facebook.com/reel/" + identity


def publish(
    settings,
    platform,
    account,
    token,
    post,
    media,
    urls,
    media_ready,
    *,
    progress=None,
    checkpoint=None,
    story_url=None,
    thumbnail=None,
    cover_url=None,
    category=None,
    quota=None,
):
    if platform == "tiktok":
        # 影片以 FILE_UPLOAD 分段送到收件匣，不使用公開媒體連結；收件匣不收文案。
        from app.services import publish_tiktok

        return publish_tiktok.publish(
            settings, token, post, media, progress=progress, checkpoint=checkpoint
        )
    if platform == "youtube":
        # 影片直接以官方 resumable upload 送出位元組，不使用公開媒體連結。
        from app.services import publish_youtube

        return publish_youtube.publish(
            settings,
            token,
            post,
            media,
            thumbnail,
            category=category,
            progress=progress,
            checkpoint=checkpoint,
            quota=quota,
        )
    if post.format == "story":
        return publish_stories(
            settings, platform, account, token, media, urls, progress, checkpoint, story_url
        )
    segments = publish_rules.threads_segments(post) if platform == "threads" else []
    progress = progress or {}
    if platform != "threads" or (len(segments) <= 1 and not progress.get("segment_ids")):
        if platform == "threads" and segments:
            post = SimpleNamespace(
                format=post.format,
                caption=segments[0],
                captions_json={"threads": segments[0]},
                facebook_unpublished=post.facebook_unpublished,
                platform_options_json=post.platform_options_json,
            )
        return publish_single(
            settings, platform, account, token, post, media, urls, media_ready, cover_url=cover_url
        )
    ids = list(progress.get("segment_ids", []))
    if ids and progress.get("segments") != segments:
        raise PlatformFailure("interrupted")
    permalink = progress.get("first_permalink")
    tags = publish_rules.HASHTAGS.findall("\n".join(segments))

    def persist(failed=None):
        detail = {
            "segments": segments,
            "segment_ids": ids.copy(),
            "successful_segments": len(ids),
            "total_segments": len(segments),
            "first_permalink": permalink,
            "failed_segment": failed,
        }
        if checkpoint:
            checkpoint(detail, ids[0] if ids else None, permalink)

    for index in range(len(ids), len(segments)):
        current = SimpleNamespace(
            format=post.format if index == 0 else "text",
            caption=segments[index],
            captions_json={"threads": segments[index]},
            facebook_unpublished=False,
            platform_options_json=post.platform_options_json,
        )

        def confirmed(identity):
            ids.append(identity)
            persist()

        try:
            identity, link = publish_single(
                settings,
                "threads",
                account,
                token,
                current,
                media if index == 0 else [],
                urls if index == 0 else [],
                media_ready if index == 0 else lambda: None,
                reply_to_id=ids[-1] if ids else None,
                topic_tag=tags[0][1:] if index == 0 and tags else "",
                lookup=index == 0,
                confirmed=confirmed,
            )
        except PlatformFailure:
            persist(index + 1)
            raise
        if index == 0:
            permalink = link
            persist()
    return ids[0], permalink


def publish_single(
    settings,
    platform,
    account,
    token,
    post,
    media,
    urls,
    media_ready,
    *,
    reply_to_id=None,
    topic_tag=None,
    lookup=True,
    confirmed=None,
    cover_url=None,
):
    account = safe_id(account)
    caption = publish_rules.platform_caption(post, platform)
    with client_factory() as client:
        if platform == "facebook":
            # 「存成 FB 草稿」只影響 Facebook：貼文進 Business Suite 草稿匣、不發佈；
            # 未勾選時請求維持原樣。
            hidden = (
                {"published": "false", "unpublished_content_type": "DRAFT"}
                if post.facebook_unpublished
                else {}
            )
            if (
                post.format == "video"
                and publish_rules.effective_options(post)["facebook"]["video_format"] == "reels"
            ):
                return publish_reel(client, settings, account, token, post, media)
            if post.format == "text":
                body = request(
                    client, FB, account + "/feed", token, data={"message": caption, **hidden}
                )
            elif post.format == "carousel" or (hidden and post.format == "image"):
                # 單圖直接 POST /photos 只會得到未發佈的照片而不是貼文，所以和多圖一樣
                # 先上傳 published=false 的照片，再用 /feed 的 attached_media 建立貼文。
                ids = []
                for item in media:
                    with path_for(settings, item).open("rb") as file:
                        photo = request(
                            client,
                            FB,
                            account + "/photos",
                            token,
                            data={"published": "false"},
                            files={"source": ("media", file, item.mime)},
                        )
                    ids.append({"media_fbid": safe_id(photo.get("id"))})
                body = request(
                    client,
                    FB,
                    account + "/feed",
                    token,
                    data={"message": caption, "attached_media": json.dumps(ids), **hidden},
                )
            elif post.format == "video":
                identity = publish_feed_video(
                    client, settings, account, token, media[0], {"description": caption, **hidden}
                )
                return identity, "https://www.facebook.com/" + identity
            else:
                item = media[0]
                with path_for(settings, item).open("rb") as file:
                    body = request(
                        client,
                        FB,
                        account + "/photos",
                        token,
                        data={"caption": caption, **hidden},
                        files={"source": ("media", file, item.mime)},
                    )
            identity = safe_id(body.get("post_id", body.get("id")))
            return identity, "https://www.facebook.com/" + identity
        threads = platform == "threads"
        base, edge = (TH, "/threads") if threads else (FB, "/media")
        tags = re.findall(r"(?<!\w)#([^\s#]+)", caption) if threads else []
        if topic_tag is not None:
            tags = [topic_tag] if topic_tag else []

        def container(item=None, url=None, child=False, wait=True):
            data = {}
            if item is None:
                data["media_type"] = "TEXT"
            elif item.mime.startswith("video/"):
                data.update(media_type="VIDEO" if threads else "REELS", video_url=url)
            else:
                data["image_url"] = url
                if threads:
                    data["media_type"] = "IMAGE"
            if not threads and item and item.mime.startswith("video/") and not child:
                # true 沿用既有省略參數的請求；false 才覆寫平台預設。
                if not publish_rules.platform_options(post)["instagram"]["share_to_feed"]:
                    data["share_to_feed"] = "false"
                if cover_url:
                    # 有封面時 Meta 會忽略 thumb_offset；沒有封面就維持平台預設（第一格）。
                    data["cover_url"] = cover_url
            if reply_to_id:
                data["reply_to_id"] = safe_id(reply_to_id)
            if child:
                data["is_carousel_item"] = "true"
            else:
                data["text" if threads else "caption"] = caption
                if tags:
                    data["topic_tag"] = tags[0]
            value = request(client, base, account + edge, token, data=data)
            identity = safe_id(value.get("id"))
            if wait:
                wait_container(
                    client, base, identity, token, settings, threads=threads, text=item is None
                )
            return identity

        if post.format == "carousel":
            # 先建立全部子容器再逐一等待：平台同時處理各張，總等待約等於最慢的一張。
            children = [
                container(item, url, True, wait=False)
                for item, url in zip(media, urls, strict=True)
            ]
            for child in children:
                wait_container(client, base, child, token, settings, threads=threads)
            body = request(
                client,
                base,
                account + edge,
                token,
                data={
                    "media_type": "CAROUSEL",
                    "children": ",".join(children),
                    "text" if threads else "caption": caption,
                    **({"topic_tag": tags[0]} if tags else {}),
                },
            )
            creation = safe_id(body.get("id"))
            wait_container(client, base, creation, token, settings, threads=threads)
        else:
            creation = container(media[0], urls[0]) if media else container()
        media_ready()
        body = request(
            client,
            base,
            account + ("/threads_publish" if threads else "/media_publish"),
            token,
            data={"creation_id": creation},
        )
        identity = safe_id(body.get("id"))
        if confirmed:
            confirmed(identity)
        if not lookup:
            return identity, None
        # A permalink lookup failure must never turn a published target into a retryable failure.
        try:
            result = request(client, base, identity, token, params={"fields": "permalink"})
            permalink = safe_permalink(result.get("permalink"))
        except Exception:
            # The publish response already confirmed its ID; ancillary reads cannot undo it.
            permalink = None
        return identity, permalink


def publish_stories(
    settings, platform, account, token, media, urls, progress, checkpoint, story_url
):
    account = safe_id(account)
    stories = list((progress or {}).get("stories", []))
    media_ids = [item.id for item in media]
    if stories and (progress or {}).get("media_ids") != media_ids:
        raise PlatformFailure("interrupted")

    def persist(failed=None):
        detail = {
            "stories": stories.copy(),
            "media_ids": media_ids,
            "successful_stories": len(stories),
            "total_stories": len(media),
            "failed_story": failed,
        }
        if checkpoint:
            checkpoint(detail, stories[0]["platform_post_id"] if stories else None, None)

    for index in range(len(stories), len(media)):
        item = media[index]
        try:
            with client_factory() as client:
                if platform == "facebook":
                    identity = facebook_story(client, settings, account, token, item)
                elif platform == "instagram":
                    url = story_url(item) if story_url else urls[index]
                    data = {
                        "media_type": "STORIES",
                        "video_url" if item.mime.startswith("video/") else "image_url": url,
                    }
                    body = request(client, FB, account + "/media", token, data=data)
                    creation = safe_id(body.get("id"))
                    wait_container(client, FB, creation, token, settings)
                    body = request(
                        client,
                        FB,
                        account + "/media_publish",
                        token,
                        data={"creation_id": creation},
                    )
                    identity = safe_id(body.get("id"))
                else:
                    raise PlatformFailure("media_rejected")
            stories.append(
                {
                    "position": index + 1,
                    "media_id": item.id,
                    "platform_post_id": identity,
                    "published_at": datetime.now(UTC).isoformat(),
                }
            )
            persist()
        except PlatformFailure:
            persist(index + 1)
            raise
    return stories[0]["platform_post_id"], None


def facebook_story(client, settings, account, token, item):
    if item.mime.startswith("image/"):
        with path_for(settings, item).open("rb") as file:
            photo = request(
                client,
                FB,
                account + "/photos",
                token,
                data={"published": "false"},
                files={"source": ("media", file, item.mime)},
            )
        body = request(
            client,
            FB,
            account + "/photo_stories",
            token,
            data={"photo_id": safe_id(photo.get("id"))},
        )
        if body.get("success") is False:
            raise PlatformFailure("media_rejected")
        return safe_id(body.get("post_id", body.get("id")))
    start = request(client, FB, account + "/video_stories", token, data={"upload_phase": "start"})
    identity = safe_id(start.get("video_id"))
    upload_url = RUPLOAD + identity
    if start.get("upload_url") != upload_url:
        raise PlatformFailure("unknown")
    try:
        with path_for(settings, item).open("rb") as file:
            response = client.post(
                upload_url,
                headers={
                    "Authorization": "OAuth " + token,
                    "offset": "0",
                    "file_size": str(item.size),
                    "Content-Type": "application/octet-stream",
                },
                content=file,
            )
        body = response.json()
    except httpx.TimeoutException:
        raise PlatformFailure("timeout") from None
    except (httpx.HTTPError, ValueError):
        raise PlatformFailure("unknown") from None
    if (
        response.is_error
        or response.is_redirect
        or not isinstance(body, dict)
        or body.get("success") is not True
    ):
        raise PlatformFailure("media_rejected")
    body = request(
        client,
        FB,
        account + "/video_stories",
        token,
        data={"upload_phase": "finish", "video_id": identity},
    )
    if body.get("success") is not True:
        raise PlatformFailure("unknown")
    return safe_id(body.get("post_id", identity))

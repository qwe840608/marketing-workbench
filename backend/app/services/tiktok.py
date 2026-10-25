"""Read-only TikTok sync: the owner's public videos with their counts, and the follower count.

Display API video.list returns only public videos and already carries view/like/comment/share
counts, so one listing both upserts posts and feeds the due metric snapshots. A complete listing
(first page to last) also hides videos that disappeared, which on TikTok means deleted or made
private; an incomplete or empty listing never judges anything. See docs/en/tiktok-plan.md.
"""

import re
from datetime import UTC, datetime

from sqlalchemy import select

from app.models import Account
from app.models.base import utc_now
from app.schemas.followers import FollowerInput
from app.schemas.posts import MetricsInput, PostsInput
from app.services import followers, oauth, tiktok_oauth
from app.services import posts as post_service

VIDEO_URL = "https://open.tiktokapis.com/v2/video/list/"
USER_URL = tiktok_oauth.USER_URL
VIDEO_FIELDS = (
    "id,title,video_description,create_time,share_url,duration,"
    "view_count,like_count,comment_count,share_count"
)
PAGE_SIZE = 20
PAGE_LIMIT = 50


def fail(code):
    from app.services.workers import WorkerError

    raise WorkerError(code)


def identifier(value):
    if isinstance(value, int) and value > 0:
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", value):
        fail("invalid_response")
    return value


def count(value):
    return value if type(value) is int and 0 <= value <= 2**53 - 1 else None


def account(factory, settings):
    """The linked open_id, only when the link is healthy and registered to exactly one account.

    TikTok returns only the scopes the creator agreed to, so a link may lack user.info.stats or
    video.upload; video sync still runs and only followers (or publishing) stop.
    """
    if factory is None:
        return None
    with factory() as session:
        state = tiktok_oauth.status(session, settings)
        open_id = oauth.value(session, settings, "TIKTOK_OPEN_ID")
        registered = list(
            session.scalars(
                select(Account).where(
                    Account.platform == "tiktok",
                    Account.external_id == open_id,
                    Account.status == "connected",
                )
            )
        )
        healthy = state["state"] in {"ready", "pending"}
        readable = tiktok_oauth.READ_SCOPES <= set(state["granted"])
        return open_id if healthy and readable and len(registered) == 1 else None


def granted(factory, settings):
    with factory() as session:
        return set(tiktok_oauth.status(session, settings)["granted"])


class Sync:
    def __init__(self, worker):
        self.worker = worker
        self.open_id = account(worker.factory, worker.settings)
        if not self.open_id:
            fail("tiktok_auth_error")
        try:
            self.token = tiktok_oauth.access_token(worker.factory, worker.settings)
        except oauth.ProviderFailure:
            fail("tiktok_auth_error")

    def call(self, method, url, qs, body=None):
        try:
            response = self.worker.request(
                method, url, headers={"Authorization": "Bearer " + self.token}, qs=qs, body=body
            )
        except Exception:
            fail("network_error")
        status, data = response.get("statusCode"), response.get("body")
        error = data.get("error") if isinstance(data, dict) else None
        code = error.get("code") if isinstance(error, dict) else None
        # TikTok 有自己的錯誤碼，不沿用 Meta 的，免得排程結果與收訊健康誤導成 Meta 限流。
        if status == 429 or code == "rate_limit_exceeded":
            fail("tiktok_rate_limited")
        if isinstance(status, int) and status >= 500:
            fail("tiktok_server_error")
        if status == 401 or code in {"access_token_invalid", "invalid_token"}:
            fail("tiktok_auth_error")
        if code == "scope_not_authorized":
            fail("tiktok_permission_missing")
        if status != 200 or not isinstance(data, dict) or code not in {"ok", None}:
            fail("invalid_response")
        payload = data.get("data")
        if not isinstance(payload, dict):
            fail("invalid_response")
        return payload

    @staticmethod
    def post(row):
        stamp = row.get("create_time")
        if type(stamp) is not int or stamp <= 0:
            fail("invalid_response")
        link = row.get("share_url")
        title = row.get("title") or row.get("video_description") or ""
        return dict(
            external_id=identifier(row.get("id")),
            caption=str(title)[:20000],
            media_type="VIDEO",
            # video.list 只回公開影片，清單內的影片一律是公開。
            visibility="public",
            published_at=datetime.fromtimestamp(stamp, UTC),
            permalink=link if isinstance(link, str) and link.startswith("https://") else None,
        )

    def listing(self, result):
        """Upsert every listed video; returns all IDs and counts, ids only when complete."""
        listed, counts, cursor, seen = set(), {}, None, set()
        for _ in range(PAGE_LIMIT):
            body = {"max_count": PAGE_SIZE, **({"cursor": cursor} if cursor is not None else {})}
            data = self.call("POST", VIDEO_URL, {"fields": VIDEO_FIELDS}, body)
            rows = data.get("videos", [])
            if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
                fail("invalid_response")
            posts = [self.post(row) for row in rows]
            for row, post in zip(rows, posts, strict=True):
                listed.add(post["external_id"])
                counts[post["external_id"]] = {
                    "views": count(row.get("view_count")),
                    "likes": count(row.get("like_count")),
                    "comments": count(row.get("comment_count")),
                    "shares": count(row.get("share_count")),
                    "duration": count(row.get("duration")),
                }
            if posts:
                self.worker.service(
                    post_service.upsert_posts,
                    PostsInput.model_validate(
                        dict(platform="tiktok", account_external_id=self.open_id, posts=posts)
                    ),
                )
                result["posts"] += len(posts)
            more, cursor = data.get("has_more"), data.get("cursor")
            if more is not True:
                return listed, counts, True
            if type(cursor) is not int or cursor in seen:
                fail("invalid_pagination")
            seen.add(cursor)
        return listed, counts, False

    def snapshots(self, result, counts):
        """Due snapshots straight from the listing's counts; no extra API call per video."""
        due = self.worker.service(post_service.due_metrics, "tiktok", self.open_id, 1000)["posts"]
        metrics = []
        for post in due:
            values = counts.get(post["external_id"])
            if values is None:
                # 不在這次清單裡（已刪除、改為私人或清單未完整）：不寫空快照，避免把數字歸零。
                continue
            metrics.append(
                dict(
                    post_external_id=post["external_id"],
                    captured_at=utc_now(),
                    sync_slot=post["sync_slot"],
                    views=values["views"],
                    likes=values["likes"],
                    comments=values["comments"],
                    shares=values["shares"],
                    extra_json={
                        "duration_seconds": values["duration"],
                        "unavailable": {
                            "reach": "not_available",
                            "saves": "not_available",
                            "avg_watch_time": "not_available",
                            "completion_rate": "not_available",
                        },
                    },
                )
            )
        for start in range(0, len(metrics), 100):
            result["snapshots"] += self.worker.service(
                post_service.upsert_metrics,
                MetricsInput.model_validate(
                    dict(
                        platform="tiktok",
                        account_external_id=self.open_id,
                        metrics=metrics[start : start + 100],
                    )
                ),
            )["inserted"]

    def sync(self, result):
        listed, counts, complete = self.listing(result)
        # 只有完整且非空的清單才判定消失；TikTok 上消失代表已刪除或改為私人。
        if complete and listed and self.worker.factory is not None:
            with self.worker.factory.begin() as session:
                post_service.mark_missing(session, "tiktok", self.open_id, listed)
        self.snapshots(result, counts)

    def followers(self, result):
        if not self.worker.service(followers.due, "tiktok", self.open_id)["due"]:
            return
        # 粉絲數需要 user.info.stats；使用者授權時取消勾選就記錯誤，不呼叫 TikTok。
        if "user.info.stats" not in granted(self.worker.factory, self.worker.settings):
            fail("tiktok_permission_missing")
        data = self.call("GET", USER_URL, {"fields": "open_id,follower_count"})
        user = data.get("user")
        total = count(user.get("follower_count")) if isinstance(user, dict) else None
        if not isinstance(user, dict) or user.get("open_id") != self.open_id or total is None:
            fail("invalid_response")
        result["inserted"] += self.worker.service(
            followers.record,
            FollowerInput.model_validate(
                dict(
                    platform="tiktok",
                    account_external_id=self.open_id,
                    followers_count=total,
                    captured_at=utc_now(),
                )
            ),
        )["inserted"]

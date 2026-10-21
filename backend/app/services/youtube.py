"""Bounded read-only YouTube sync, sharing post snapshots and comment leases."""

import math
import re
from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.models import Account, OAuthConnection, Post
from app.models.base import utc_now
from app.schemas.followers import FollowerInput
from app.schemas.posts import MetricsInput, PostsInput
from app.services import followers, oauth, settings_store, youtube_oauth
from app.services import posts as post_service
from app.services.webhook_normalize import instant

DATA = "https://www.googleapis.com/youtube/v3/"
ANALYTICS = "https://youtubeanalytics.googleapis.com/v2/reports"
PAGE_LIMIT = 50
METRIC_LIMIT = 300
ROUND_LIMIT = 420
DAILY_LIMIT = 8000
ANALYTICS_METRICS = (
    "averageViewDuration",
    "estimatedMinutesWatched",
    "shares",
    "subscribersGained",
)
PACIFIC = ZoneInfo("America/Los_Angeles")


def fail(code):
    from app.services.gateway_workers import WorkerError

    raise WorkerError(code)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        fail("invalid_response")
    return value


def number(value):
    if isinstance(value, str) and re.fullmatch(r"\d+", value):
        value = int(value)
    if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 2**53 - 1:
        return None
    return value


def duration(value):
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", value or "")
    if not match or not any(match.groups()):
        fail("invalid_response")
    return sum(float(v or 0) * unit for v, unit in zip(match.groups(), (3600, 60, 1), strict=True))


def visibility(row):
    value = row.get("status", {}).get("privacyStatus")
    return value if value in {"public", "unlisted", "private"} else None


def short(row):
    seconds = duration(row.get("contentDetails", {}).get("duration"))
    # fileDetails.videoStreams requires an extra owner scope; readonly cannot obtain aspect ratio.
    return seconds <= 180


def account(factory, settings):
    if factory is None:
        return None
    with factory() as session:
        state = youtube_oauth.status(session, settings)
        channel = oauth.value(session, settings, "YOUTUBE_CHANNEL_ID")
        registered = list(
            session.scalars(
                select(Account).where(
                    Account.platform == "youtube",
                    Account.external_id == channel,
                    Account.status == "connected",
                )
            )
        )
        return channel if state["state"] == "ready" and len(registered) == 1 else None


class Sync:
    def __init__(self, worker):
        self.worker = worker
        self.calls = 0
        self.channel_id = account(worker.factory, worker.settings)
        if not self.channel_id:
            fail("youtube_auth_error")
        try:
            self.token = youtube_oauth.access_token(worker.factory, worker.settings)
        except oauth.ProviderFailure:
            fail("youtube_auth_error")

    def state(self, key):
        with self.worker.factory() as session:
            row = settings_store.get(session, key)
            return dict(row.value_json) if row else {}

    def store(self, key, value):
        with self.worker.factory.begin() as session:
            row = settings_store.get(session, key)
            settings_store.put(session, key, value, row)

    def get(self, edge, query, work=None):
        if edge not in {
            "channels",
            "playlistItems",
            "videos",
            "commentThreads",
            "comments",
            "reports",
        }:
            fail("invalid_response")
        if self.calls >= ROUND_LIMIT:
            fail("work_budget")
        # Reserve before HTTP; failures cost quota too. Persist across workers and restarts.
        with self.worker.factory.begin() as session:
            connection = oauth.connection(session, "youtube")
            if (
                not connection
                or connection.cache_json.get("reconnect")
                or connection.credential_digest
                != oauth.digest_credentials(session, self.worker.settings, "youtube")
            ):
                fail("youtube_auth_error")
            if account_id := self.channel_id:
                registered = session.scalar(
                    select(Account).where(
                        Account.platform == "youtube",
                        Account.external_id == account_id,
                        Account.status == "connected",
                    )
                )
                if not registered:
                    fail("youtube_auth_error")
            if work:
                from app.services.meta_api import require_run

                require_run(session, work["run_id"], utc_now())
            key = "youtube.quota"
            row = settings_store.get(session, key)
            day = utc_now().astimezone(PACIFIC).date().isoformat()
            used = row.value_json.get("used", 0) if row and row.value_json.get("day") == day else 0
            if used >= DAILY_LIMIT:
                fail("meta_rate_limited")
            value = {"day": day, "used": used + 1}
            settings_store.put(session, key, value, row)
        self.calls += 1
        try:
            response = self.worker.request(
                "GET",
                ANALYTICS if edge == "reports" else DATA + edge,
                headers={"Authorization": "Bearer " + self.token},
                qs=query,
            )
        except Exception:
            fail("network_error")
        body = response.get("body")
        status = response.get("statusCode")
        if status == 429:
            fail("meta_rate_limited")
        if isinstance(status, int) and status >= 500:
            fail("meta_server_error")
        if status == 401:
            fail("youtube_auth_error")
        if status == 403:
            reasons = body.get("error", {}).get("errors", []) if isinstance(body, dict) else []
            if any(r.get("reason") in {"quotaExceeded", "dailyLimitExceeded"} for r in reasons):
                fail("meta_rate_limited")
            fail("youtube_permission_missing")
        if status != 200 or not isinstance(body, dict) or body.get("error"):
            fail("invalid_response")
        return body

    def page(self, edge, query, after=None, work=None):
        body = self.get(edge, {**query, **({"pageToken": after} if after else {})}, work)
        rows = body.get("items")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            fail("invalid_response")
        cursor = body.get("nextPageToken")
        if cursor is not None and (
            not isinstance(cursor, str) or not cursor or len(cursor) > 2048 or cursor == after
        ):
            fail("invalid_pagination")
        return rows, cursor

    def channel(self):
        rows, _ = self.page(
            "channels",
            {
                "part": "contentDetails,statistics",
                "id": self.channel_id,
            },
        )
        if len(rows) != 1 or rows[0].get("id") != self.channel_id:
            fail("invalid_response")
        return rows[0]

    def followers(self, result):
        today = utc_now().astimezone(ZoneInfo("Asia/Taipei")).date().isoformat()
        with self.worker.factory() as session:
            connection = oauth.connection(session, "youtube")
            if connection.cache_json.get("subscriber_hidden_on") == today:
                return
        due = self.worker.service(followers.due, "youtube", self.channel_id)["due"]
        if not due:
            return
        row = self.channel()
        stats = row.get("statistics", {})
        hidden = stats.get("hiddenSubscriberCount") is True
        with self.worker.factory.begin() as session:
            connection = session.scalar(
                select(OAuthConnection).where(OAuthConnection.platform == "youtube")
            )
            connection.cache_json = {
                **connection.cache_json,
                "subscriber_hidden": hidden,
                "subscriber_hidden_on": today if hidden else None,
            }
        if hidden:
            return
        count = number(stats.get("subscriberCount"))
        if count is None or int(count) != count:
            fail("invalid_response")
        result["inserted"] += self.worker.service(
            followers.record,
            FollowerInput.model_validate(
                dict(
                    platform="youtube",
                    account_external_id=self.channel_id,
                    followers_count=int(count),
                    captured_at=utc_now(),
                )
            ),
        )["inserted"]

    def listing(self, result):
        uploads = identifier(
            self.channel().get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
        )
        key = "youtube.listing." + self.channel_id
        after = self.state(key).get("after")
        # 只有從第一頁開始並走到最後一頁，累積的 ID 才是完整清單，可供已刪除判定重用。
        fresh = after is None
        listed, seen = set(), set()
        for _ in range(PAGE_LIMIT):
            entries, cursor = self.page(
                "playlistItems",
                {
                    "part": "contentDetails",
                    "playlistId": uploads,
                    "maxResults": 50,
                },
                after,
            )
            ids = [identifier(r.get("contentDetails", {}).get("videoId")) for r in entries]
            listed.update(ids)
            if ids:
                videos, _ = self.page(
                    "videos",
                    {
                        "part": "snippet,contentDetails,status",
                        "id": ",".join(ids),
                    },
                )
                posts = []
                for row in videos:
                    identity = identifier(row.get("id"))
                    snippet = row.get("snippet", {})
                    stamp = instant(snippet.get("publishedAt"))
                    if (
                        identity not in ids
                        or not stamp
                        or snippet.get("channelId") != self.channel_id
                    ):
                        fail("invalid_response")
                    posts.append(
                        dict(
                            external_id=identity,
                            caption=str(snippet.get("title", ""))[:20000],
                            media_type="SHORTS" if short(row) else "VIDEO",
                            visibility=visibility(row),
                            published_at=stamp,
                            permalink="https://www.youtube.com/watch?v=" + identity,
                        )
                    )
                if posts:
                    self.worker.service(
                        post_service.upsert_posts,
                        PostsInput.model_validate(
                            dict(
                                platform="youtube",
                                account_external_id=self.channel_id,
                                posts=posts,
                            )
                        ),
                    )
                    result["posts"] += len(posts)
            if cursor in seen:
                fail("invalid_pagination")
            if cursor:
                seen.add(cursor)
            self.store(key, {"after": cursor})
            if not cursor:
                return listed if fresh else None
            after = cursor
        return None

    def uploaded_ids(self):
        """完整的 uploads 清單 ID（不寫入貼文、不動分頁進度）；分頁異常或過長則失敗。"""
        uploads = identifier(
            self.channel().get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
        )
        ids, after, seen = set(), None, set()
        for _ in range(PAGE_LIMIT):
            entries, cursor = self.page(
                "playlistItems",
                {"part": "contentDetails", "playlistId": uploads, "maxResults": 50},
                after,
            )
            ids.update(identifier(r.get("contentDetails", {}).get("videoId")) for r in entries)
            if not cursor:
                return ids
            if cursor in seen:
                fail("invalid_pagination")
            seen.add(cursor)
            after = cursor
        fail("discovery_limit")

    def analytics(self, post):
        with self.worker.factory() as session:
            row = session.scalar(
                select(Post)
                .join(Account)
                .where(
                    Account.platform == "youtube",
                    Account.external_id == self.channel_id,
                    Post.external_id == post["external_id"],
                )
            )
            start = row.published_at.astimezone(PACIFIC).date()
        end = (utc_now().astimezone(PACIFIC) - timedelta(days=2)).date()
        if start > end:
            return {}
        data = self.get(
            "reports",
            {
                "ids": "channel==" + self.channel_id,
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "filters": "video==" + identifier(post["external_id"]),
                "metrics": ",".join(ANALYTICS_METRICS),
            },
        )
        headers = data.get("columnHeaders")
        rows = data.get("rows", [])
        if not isinstance(headers, list) or not isinstance(rows, list) or len(rows) > 1:
            fail("invalid_response")
        if not rows:
            return {}
        names = [r.get("name") for r in headers]
        if not set(ANALYTICS_METRICS) <= set(names) or len(rows[0]) != len(names):
            fail("invalid_response")
        return dict(zip(names, rows[0], strict=True))

    def snapshots(self, result):
        remaining = METRIC_LIMIT
        while remaining:
            due = self.worker.service(
                post_service.due_metrics, "youtube", self.channel_id, 100
            )["posts"][: min(50, remaining)]
            if not due:
                return
            remaining -= len(due)
            videos, _ = self.page(
                "videos",
                {
                    "part": "statistics",
                    "id": ",".join(identifier(p["external_id"]) for p in due),
                },
            )
            stats = {identifier(row.get("id")): row.get("statistics", {}) for row in videos}
            for post in due:
                extra = {
                    "analytics_delay_days": 2,
                    "shorts_basis": "duration",
                    "unavailable": {"reach": "not_available", "saves": "not_available"},
                }
                values = stats.get(post["external_id"], {})
                metric = dict(
                    post_external_id=post["external_id"],
                    captured_at=utc_now(),
                    sync_slot=post["sync_slot"],
                    extra_json=extra,
                )
                for field, name in [
                    ("views", "viewCount"),
                    ("likes", "likeCount"),
                    ("comments", "commentCount"),
                ]:
                    value = number(values.get(name))
                    metric[field] = (
                        int(value) if value is not None and int(value) == value else None
                    )
                try:
                    delayed = self.analytics(post)
                except Exception as error:
                    from app.services.gateway_workers import WorkerError

                    if not isinstance(error, WorkerError) or error.code not in {
                        "youtube_permission_missing",
                        "invalid_response",
                    }:
                        raise
                    delayed = {}
                    extra["analytics_error"] = error.code
                metric["avg_watch_time"] = number(delayed.get("averageViewDuration"))
                share = number(delayed.get("shares"))
                metric["shares"] = int(share) if share is not None and int(share) == share else None
                minutes = number(delayed.get("estimatedMinutesWatched"))
                extra["watch_hours"] = minutes / 60 if minutes is not None else None
                gained = number(delayed.get("subscribersGained"))
                extra["subscribers_gained"] = gained
                result["snapshots"] += self.worker.service(
                    post_service.upsert_metrics,
                    MetricsInput.model_validate(
                        dict(
                            platform="youtube",
                            account_external_id=self.channel_id,
                            metrics=[metric],
                        )
                    ),
                )["inserted"]

    @staticmethod
    def comment(row, parent=None):
        snippet = row.get("snippet", {})
        identity = identifier(row.get("id"))
        stamp = instant(snippet.get("publishedAt"))
        text = snippet.get("textOriginal", snippet.get("textDisplay"))
        author = snippet.get("authorChannelId", {}).get("value")
        if not stamp or not isinstance(text, str):
            fail("invalid_response")
        return dict(
            id=identity,
            timestamp=stamp,
            text=text[:20000],
            username=snippet.get("authorDisplayName") or None,
            author_id=author or "unknown:" + identity,
            parent_id=parent or snippet.get("parentId"),
        )

    def comments_page(self, work, progress):
        if progress["replies"]:
            pending = progress["replies"][0]
            rows, cursor = self.page(
                "comments",
                dict(
                    part="snippet",
                    parentId=identifier(pending["id"]),
                    maxResults=50,
                    textFormat="plainText",
                ),
                pending.get("after"),
                work,
            )
            return [self.comment(row, pending["id"]) for row in rows], cursor, None
        rows, cursor = self.page(
            "commentThreads",
            dict(
                part="snippet,replies",
                videoId=identifier(work["resource_id"]),
                maxResults=50,
                order="time",
                textFormat="plainText",
            ),
            progress["after"],
            work,
        )
        comments, replies = [], []
        for row in rows:
            snippet = row.get("snippet", {})
            top = self.comment(snippet.get("topLevelComment", {}))
            comments.append(top)
            nested = row.get("replies", {}).get("comments", [])
            total = number(snippet.get("totalReplyCount"))
            if not isinstance(nested, list) or total is None:
                fail("invalid_response")
            comments.extend(self.comment(reply, top["id"]) for reply in nested)
            if total > len(nested):
                # Embedded replies are a subset; fetch all replies from their own edge.
                replies.append({"id": top["id"], "after": None})
        return comments, cursor, replies

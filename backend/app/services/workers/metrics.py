"""貼文清單、已刪除偵測清單與成效快照（FB／IG／Threads；YouTube、TikTok 各由自己的 Sync 讀取）。"""

import logging
import math
import re

from app.logging_config import log_failure
from app.schemas.posts import MetricsInput, PostsInput
from app.services import credentials, graph_api, posts
from app.services.webhook_normalize import instant, secret, valid_id
from app.services.workers.base import WorkerError

logger = logging.getLogger("mwb.gateway_workers")
# Threads 不經 Meta 呼叫配額，改以每輪上限保護：貼文清單最多 50 頁、成效最多 300 篇，其餘下輪接續。
THREADS_PAGE_LIMIT = 50
THREADS_INSIGHT_LIMIT = 300
THREADS_POST_FIELDS = "id,text,permalink,timestamp,media_type"
THREADS_METRICS = ("views", "likes", "replies", "reposts", "quotes", "shares")


def metric_count(value):
    return value if type(value) is int and 0 <= value <= 9007199254740991 else None


def insight_value(data, name):
    """Insights 回應中指定指標的值；缺少、格式不符或空陣列（例如轉發）回傳 None。"""
    rows = data.get("data") if isinstance(data.get("data"), list) else []
    row = next((r for r in rows if isinstance(r, dict) and r.get("name") == name), {})
    values = row.get("values")
    first = values[0] if isinstance(values, list) and values and isinstance(values[0], dict) else {}
    total = row.get("total_value")
    return first.get("value", total.get("value") if isinstance(total, dict) else None)


# 影片觀看指標合併成一次 insights 呼叫，不多耗 Meta 每小時配額；
# 新指標（IG 前 3 秒滑走率標示為開發中）若讓整批被拒，退回只讀平均觀看時長，多花一次呼叫。
VIDEO_METRICS = {
    "instagram": dict(
        avg_watch_time="ig_reels_avg_watch_time",
        watch_hours="ig_reels_video_view_total_time",
        skip_rate="reels_skip_rate",
    ),
    "facebook": dict(
        avg_watch_time="post_video_avg_time_watched",
        watch_hours="post_video_view_time",
        retention="post_video_retention_graph",
    ),
}


def finite(value, high=None):
    ok = type(value) in (int, float) and math.isfinite(value) and value >= 0
    return value if ok and (high is None or value <= high) else None


def retention_curve(value):
    """FB 留存曲線：{"0": 1.0, "1": 0.83, …} 依區間排序後換成百分比；格式不符回傳 None。"""
    if not isinstance(value, dict) or not 2 <= len(value) <= 101:
        return None
    try:
        points = sorted((int(key), finite(rate)) for key, rate in value.items())
    except (TypeError, ValueError):
        return None
    rates = [rate for _, rate in points]
    if any(rate is None for rate in rates) or max(rates) > 100:
        return None
    scale = 100 if max(rates) <= 1.5 else 1
    return [round(rate * scale, 1) for rate in rates]


def video_insights(platform, post, graph, metric, extra, value):
    names = VIDEO_METRICS[platform]
    path = post["external_id"] + "/insights"
    data = graph(path, dict(metric=",".join(names.values()), period="lifetime"))
    if data.get("unavailable"):
        data = graph(path, dict(metric=names["avg_watch_time"], period="lifetime"))
    extra["metric_units"] = {"avg_watch_time": "milliseconds"}
    for field, name in names.items():
        raw = value(data, name)
        if field == "avg_watch_time":
            metric[field] = finite(raw)
            parsed = metric[field]
        elif field == "watch_hours":
            parsed = extra[field] = (
                round(raw / 3_600_000, 4) if finite(raw) is not None else None
            )
        elif field == "skip_rate":
            parsed = extra[field] = finite(raw, 100)
        else:
            parsed = extra[field] = retention_curve(raw)
        extra["metric_names"][field] = name
        if parsed is None:
            extra["unavailable"][field] = data.get("code") or "not_returned"


class MetricsMixin:
    def metrics(self):
        meta_ready = bool(secret(self.settings, "meta_page_access_token")) and not any(
            not re.fullmatch(r"\d+", value)
            for value in (
                credentials.resolve("META_PAGE_ID", self.settings),
                credentials.resolve("META_IG_ACCOUNT_ID", self.settings),
            )
        )
        threads = self.threads_account(registered=True)
        youtube = self.youtube_account()
        tiktok = self.tiktok_account()
        if not meta_ready and not threads and not youtube and not tiktok:
            return {"ok": False, "error": "meta_configuration_missing"}
        result = dict(ok=True, posts=0, snapshots=0, errors=[])
        if not meta_ready and not youtube and not tiktok:
            result.update(ok=False, error="meta_configuration_missing")
        for platform, account in (
            [
                ("facebook", credentials.resolve("META_PAGE_ID", self.settings)),
                ("instagram", credentials.resolve("META_IG_ACCOUNT_ID", self.settings)),
            ]
            if meta_ready
            else []
        ):
            context = dict(platform=platform, account_external_id=account, source="metrics")

            def graph(path, query, context=context):
                response = self.graph(path, query, context)
                data = response.get("body") or {}
                if response["statusCode"] != 200 or data.get("error"):
                    code = (data.get("error") or {}).get("code")
                    if (
                        code in (4, 17, 32, 613, 190)
                        or response["statusCode"] >= 500
                        or response["statusCode"] == 429
                    ):
                        raise WorkerError("meta_retry_required")
                    return dict(
                        unavailable=True, code=code if type(code) is int else response["statusCode"]
                    )
                return data

            try:
                after = None
                listed = set()
                for page in range(50):
                    data = graph(
                        account + ("/published_posts" if platform == "facebook" else "/media"),
                        dict(
                            fields="id,message,permalink_url,created_time,attachments{media_type}"
                            if platform == "facebook"
                            else "id,caption,media_type,media_product_type,permalink,timestamp",
                            limit=100,
                            **({"after": after} if after else {}),
                        ),
                    )
                    if not isinstance(data.get("data"), list):
                        raise WorkerError("posts_unavailable")
                    rows = [self.post(p) for p in data["data"]]
                    listed.update(row["external_id"] for row in rows)
                    if rows:
                        self.service(
                            posts.upsert_posts,
                            PostsInput.model_validate(
                                dict(platform=platform, account_external_id=account, posts=rows)
                            ),
                        )
                    result["posts"] += len(rows)
                    paging = data.get("paging") or {}
                    after = (
                        (paging.get("cursors") or {}).get("after") if paging.get("next") else None
                    )
                    if paging.get("next") and (not isinstance(after, str) or len(after) > 4096):
                        raise WorkerError("invalid_pagination")
                    if not after:
                        break
                    if page == 49:
                        raise WorkerError("discovery_limit")
                # 只有完整分頁成功才會執行到這裡；重用此清單判定平台上已刪除的發佈貼文。
                try:
                    if self.factory is not None:
                        from app.services import publish_presence

                        publish_presence.record(self.factory, platform, account, listed)
                except Exception as error:
                    log_failure("mwb.gateway_workers", "gateway_workers_presence_failed", error)
                for batch in range(50):
                    due = self.service(posts.due_metrics, platform, account, 100).get("posts")
                    if not due:
                        break
                    for post in due:
                        metric = self.snapshot(platform, post, graph)
                        result["snapshots"] += self.service(
                            posts.upsert_metrics,
                            MetricsInput.model_validate(
                                dict(
                                    platform=platform, account_external_id=account, metrics=[metric]
                                )
                            ),
                        )["inserted"]
                    if batch == 49:
                        raise WorkerError("snapshot_limit")
            except Exception as error:
                log_failure("mwb.gateway_workers", "gateway_workers_metrics_failed", error)
                result["ok"] = False
                result["errors"].append(
                    dict(
                        platform=platform,
                        code=error.code if isinstance(error, WorkerError) else "sync_failed",
                    )
                )
        if threads:
            self.threads_metrics(result, *threads)
        if youtube:
            try:
                reader = self.youtube_sync()
                listed = reader.listing(result)
                # 只有從第一頁走到最後一頁的完整清單才重用於已刪除判定。
                if listed and self.factory is not None:
                    try:
                        from app.services import publish_presence

                        publish_presence.record(self.factory, "youtube", reader.channel_id, listed)
                    except Exception as error:
                        log_failure(
                            "mwb.gateway_workers", "gateway_workers_presence_failed", error
                        )
                reader.snapshots(result)
            except Exception as error:
                # 與 TikTok 相同：非預期錯誤（資料庫忙碌等）只記在 YouTube，不中斷整批。
                if not isinstance(error, WorkerError):
                    log_failure("mwb.gateway_workers", "gateway_workers_youtube_failed", error)
                result["ok"] = False
                result["errors"].append(
                    dict(
                        platform="youtube",
                        code=error.code if isinstance(error, WorkerError) else "sync_failed",
                    )
                )
        if tiktok:
            try:
                self.tiktok_sync().sync(result)
            except Exception as error:
                # 非預期錯誤也只記在 TikTok，不讓整批工作失敗、丟掉其他平台已取得的結果。
                if not isinstance(error, WorkerError):
                    log_failure("mwb.gateway_workers", "gateway_workers_tiktok_failed", error)
                result["ok"] = False
                result["errors"].append(
                    dict(
                        platform="tiktok",
                        code=error.code if isinstance(error, WorkerError) else "sync_failed",
                    )
                )
        return result

    def threads_metrics(self, result, account, token):
        """Threads 貼文清單與成效快照：規則、分級與保留沿用 FB／IG，不經 Meta 呼叫配額。"""
        self.listed.add("threads")
        try:
            listed = self.threads_listing(result, account, token)
            # 只有完整分頁成功才會執行到這裡；重用此清單判定平台上已刪除的發佈貼文。
            try:
                if self.factory is not None:
                    from app.services import publish_presence

                    publish_presence.record(self.factory, "threads", account, listed)
            except Exception as error:
                log_failure("mwb.gateway_workers", "gateway_workers_presence_failed", error)
            self.threads_snapshots(result, account, token)
        except Exception as error:
            log_failure("mwb.gateway_workers", "gateway_workers_threads_metrics_failed", error)
            result["ok"] = False
            result["errors"].append(
                dict(
                    platform="threads",
                    code=error.code if isinstance(error, WorkerError) else "sync_failed",
                )
            )

    @staticmethod
    def threads_post(row):
        identity, stamp = row["id"], instant(row.get("timestamp"))
        if not stamp:
            raise WorkerError("invalid_response")
        link, text = row.get("permalink"), row.get("text")
        return dict(
            external_id=identity,
            caption=text[:20000] if isinstance(text, str) else "",
            permalink=link if isinstance(link, str) and link.startswith("https://") else None,
            media_type=str(row.get("media_type") or "POST")[:40],
            published_at=stamp,
        )

    def threads_listing(self, result, account, token):
        after, listed = None, set()
        for _ in range(THREADS_PAGE_LIMIT):
            rows, cursor = self.threads_edge(
                account + "/threads",
                dict(fields=THREADS_POST_FIELDS, limit=100),
                token,
                after,
                "posts_unavailable",
            )
            if not all(valid_id(row.get("id")) for row in rows):
                raise WorkerError("invalid_response")
            listed.update(row["id"] for row in rows)
            # 轉發別人的貼文（REPOST_FACADE）沒有自己的成效與回覆，只算進完整清單、不寫入貼文。
            own = [
                self.threads_post(row) for row in rows if row.get("media_type") != "REPOST_FACADE"
            ]
            if own:
                self.service(
                    posts.upsert_posts,
                    PostsInput.model_validate(
                        dict(platform="threads", account_external_id=account, posts=own)
                    ),
                )
            result["posts"] += len(own)
            if not cursor:
                return listed
            after = cursor
        raise WorkerError("discovery_limit")

    def threads_snapshots(self, result, account, token):
        if self.threads_access() == "missing":
            logger.info(
                "threads_data_skipped",
                extra={"reason": "permission_missing", "operation": "insights"},
            )
            return
        calls = 0
        for _ in range(50):
            due = self.service(posts.due_metrics, "threads", account, 100).get("posts")
            if not due:
                return
            for post in due:
                if calls >= THREADS_INSIGHT_LIMIT:
                    return
                calls += 1
                try:
                    metric = self.threads_snapshot(post, token)
                except WorkerError as error:
                    if error.code != "threads_permission_missing":
                        raise
                    self.threads_block()
                    return
                result["snapshots"] += self.service(
                    posts.upsert_metrics,
                    MetricsInput.model_validate(
                        dict(platform="threads", account_external_id=account, metrics=[metric])
                    ),
                )["inserted"]

    def threads_snapshot(self, post, token):
        extra = dict(api_version=graph_api.THREADS_VERSION, unavailable={}, metric_names={})
        metric = dict(
            post_external_id=post["external_id"],
            captured_at=instant(self.clock() * 1000, True),
            sync_slot=post["sync_slot"],
            extra_json=extra,
        )
        try:
            data = self.threads_get(
                post["external_id"] + "/insights", dict(metric=",".join(THREADS_METRICS)), token
            )
        except WorkerError as error:
            if error.code != "meta_api_error":
                raise
            # 這篇貼文不支援成效（例如轉發）：照 FB／IG 保存全空快照並記錄原因，下個時槽再試。
            data = {"code": error.detail}
        names = dict(views="views", likes="likes", comments="replies", shares="shares")
        names.update(reposts="reposts", quotes="quotes")
        for field, name in names.items():
            number = metric_count(insight_value(data, name))
            if field in {"reposts", "quotes"}:
                extra[field] = number
            else:
                metric[field] = number
            extra["metric_names"][field] = name
            if number is None:
                extra["unavailable"][field] = data.get("code") or "not_returned"
        for field in ("reach", "saves", "avg_watch_time", "completion_rate"):
            extra["unavailable"][field] = "not_available"
        return metric

    def snapshot(self, platform, post, graph):
        extra = dict(api_version=graph_api.GRAPH_VERSION, unavailable={}, metric_names={})
        metric = dict(
            post_external_id=post["external_id"],
            captured_at=instant(self.clock() * 1000, True),
            sync_slot=post["sync_slot"],
            extra_json=extra,
        )
        names = (
            dict(
                views="views",
                reach="reach",
                likes="likes",
                comments="comments",
                shares="shares",
                saves="saved",
            )
            if platform == "instagram"
            else dict(views="post_media_view", reach="post_total_media_view_unique")
        )

        def count(v):
            return v if type(v) is int and 0 <= v <= 9007199254740991 else None

        def value(data, name):
            row = next(
                (
                    r
                    for r in data.get("data", [])
                    if r.get("name") == name and r.get("period") == "lifetime"
                ),
                {},
            )
            values = row.get("values") or [{}]
            return values[0].get("value", (row.get("total_value") or {}).get("value"))

        for field, name in names.items():
            data = graph(post["external_id"] + "/insights", dict(metric=name, period="lifetime"))
            metric[field] = count(value(data, name))
            extra["metric_names"][field] = name
            if metric[field] is None:
                extra["unavailable"][field] = data.get("code") or "not_returned"
        if platform == "facebook":
            data = graph(
                post["external_id"],
                dict(
                    fields="reactions.type(LIKE).limit(0).summary(true),comments.limit(0).summary(true),shares"
                ),
            )
            for field, val in dict(
                likes=((data.get("reactions") or {}).get("summary") or {}).get("total_count"),
                comments=((data.get("comments") or {}).get("summary") or {}).get("total_count"),
                shares=(data.get("shares") or {}).get("count"),
            ).items():
                metric[field] = count(val)
                if metric[field] is None:
                    extra["unavailable"][field] = data.get("code") or "not_returned"
            extra["unavailable"]["saves"] = "not_available"
        if re.search("video|reels", post.get("media_type") or "", re.I):
            video_insights(platform, post, graph, metric, extra, value)
        else:
            extra["unavailable"]["avg_watch_time"] = "not_applicable"
        extra["unavailable"]["completion_rate"] = "not_available"
        return metric


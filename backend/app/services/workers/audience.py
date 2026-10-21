"""受眾分布每日一份：IG／Threads 追蹤者人口統計、IG 上線時段、FB 追蹤者地區、YouTube 觀眾。

TikTok Display API 與 LINE 通知用途都沒有受眾資料，介面另以提示說明，不在這裡呼叫。
"""

import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.logging_config import log_failure
from app.services import audience
from app.services.date_ranges import TAIPEI
from app.services.workers.base import WorkerError
from app.services.workers.metrics import metric_count

logger = logging.getLogger("mwb.gateway_workers")
PACIFIC = ZoneInfo("America/Los_Angeles")
DEMOGRAPHICS = ("age", "gender", "country", "city")
# IG 追蹤者分布用 timeframe=this_month；last_30_days 等舊值自 v20 起逐步停用。
IG_TIMEFRAME = "this_month"
# online_followers 只保留 30 天；取 7 天平均，降低單日波動又不必拉長回應。
ONLINE_DAYS = 7
# Meta 限流代碼；與 Threads 讀取的判斷相同。
RATE_CODES = (4, 17, 32, 613, 80001, 80002, 80004)


class Missing(Exception):
    """平台明確表示沒有這項資料（權限不足、追蹤者太少、指標不支援），存成提示，當天不重試。"""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def breakdown_items(body, metric, breakdown):
    """Graph／Threads 的 total_value.breakdowns 轉成 [{key, value}]；空的 data 代表沒有資料。"""
    rows = body.get("data")
    if not isinstance(rows, list):
        raise WorkerError("invalid_response")
    row = next((r for r in rows if isinstance(r, dict) and r.get("name") == metric), None)
    if row is None:
        if rows:
            raise WorkerError("invalid_response")
        return []
    total = row.get("total_value")
    groups = total.get("breakdowns") if isinstance(total, dict) else None
    if not isinstance(groups, list):
        return []
    sums = defaultdict(int)
    for group in groups:
        if not isinstance(group, dict):
            raise WorkerError("invalid_response")
        keys = group.get("dimension_keys")
        keys = keys if isinstance(keys, list) else []
        index = keys.index(breakdown) if breakdown in keys else len(keys) - 1
        for result in group.get("results") or []:
            values = result.get("dimension_values") if isinstance(result, dict) else None
            count = metric_count(result.get("value")) if isinstance(result, dict) else None
            if not isinstance(values, list) or not 0 <= index < len(values) or count is None:
                raise WorkerError("invalid_response")
            sums[str(values[index])] += count
    return [{"key": key, "value": value} for key, value in sums.items()]


def online_items(body):
    """IG online_followers：每天一組 0–23 時（太平洋時間）的人數，轉成台北時段的平均人數。"""
    rows = body.get("data")
    if not isinstance(rows, list):
        raise WorkerError("invalid_response")
    row = next(
        (r for r in rows if isinstance(r, dict) and r.get("name") == "online_followers"), None
    )
    values = row.get("values") if row else None
    if not isinstance(values, list):
        return []
    sums, days = defaultdict(int), 0
    for entry in values:
        hours = entry.get("value") if isinstance(entry, dict) else None
        if not isinstance(hours, dict) or not hours:
            continue
        try:
            end = datetime.fromisoformat(str(entry.get("end_time")).replace("+0000", "+00:00"))
        except ValueError:
            raise WorkerError("invalid_response") from None
        if end.tzinfo is None:
            raise WorkerError("invalid_response")
        # 每組涵蓋 end_time 前一個太平洋日；以當地午夜為起點換算，夏令時間也正確。
        day = (end.astimezone(PACIFIC) - timedelta(hours=12)).date()
        start = datetime(day.year, day.month, day.day, tzinfo=PACIFIC)
        for hour, count in hours.items():
            number = metric_count(count)
            if not str(hour).isdigit() or not 0 <= int(hour) <= 23 or number is None:
                raise WorkerError("invalid_response")
            local = (start + timedelta(hours=int(hour))).astimezone(TAIPEI).hour
            sums[local] += number
        days += 1
    if not days:
        return []
    return [{"key": str(hour), "value": round(sums[hour] / days)} for hour in range(24)]


def page_items(body, metric):
    """FB 粉專地區指標（period=day）：取最新一天的 {地區: 人數}。"""
    rows = body.get("data")
    if not isinstance(rows, list):
        raise WorkerError("invalid_response")
    row = next((r for r in rows if isinstance(r, dict) and r.get("name") == metric), None)
    values = row.get("values") if row else None
    if not isinstance(values, list) or not values:
        return []
    latest = values[-1].get("value") if isinstance(values[-1], dict) else None
    if not isinstance(latest, dict):
        return []
    items = []
    for key, count in latest.items():
        number = metric_count(count)
        if number is None:
            raise WorkerError("invalid_response")
        items.append({"key": str(key), "value": number})
    return items


def report_items(body, dimensions, metric):
    """YouTube Analytics 報表的 columnHeaders／rows 轉成字典列。"""
    headers = body.get("columnHeaders")
    rows = body.get("rows", [])
    if not isinstance(headers, list) or not isinstance(rows, list):
        raise WorkerError("invalid_response")
    names = [h.get("name") if isinstance(h, dict) else None for h in headers]
    if names != [*dimensions, metric]:
        raise WorkerError("invalid_response")
    result = []
    for row in rows:
        if not isinstance(row, list) or len(row) != len(names):
            raise WorkerError("invalid_response")
        value = row[-1]
        if type(value) not in (int, float) or value < 0:
            raise WorkerError("invalid_response")
        result.append(dict(zip(names, row, strict=True)))
    return result


def ranked(items, limit=None, breakdown=None):
    rows = audience.clean(items, limit)
    # 年齡依分群順序排列較好讀；其他依人數由多到少。
    return sorted(rows, key=lambda row: row["key"]) if breakdown == "age" else rows


class AudienceMixin:
    def audience(self):
        """每小時隨 metrics 排程呼叫；每帳號每天抓一次。回傳 0 代表沒事做（排程視為空跑）。"""
        result = dict(saved=0, errors=[])
        now = datetime.fromtimestamp(self.clock(), UTC)
        meta_blocked = False
        try:
            meta = self.accounts()
        except WorkerError:
            meta = []
        for platform, external_id in meta:
            if meta_blocked:
                break
            try:
                account_id = self.audience_due(platform, external_id, now)
                if account_id is None:
                    continue
                context = dict(platform=platform, account_external_id=external_id, source="metrics")
                rows = (
                    self.instagram_audience(external_id, context)
                    if platform == "instagram"
                    else self.facebook_audience(external_id, context)
                )
                result["saved"] += audience.save(self.factory, account_id, rows, now)
            except Exception as error:
                self.audience_failed(result, platform, error)
                meta_blocked = isinstance(error, WorkerError) and error.code == "meta_rate_limited"
        threads = self.threads_account(registered=True)
        if threads:
            try:
                account_id = self.audience_due("threads", threads[0], now)
                if account_id is not None:
                    rows = self.threads_audience(*threads)
                    if rows is not None:
                        result["saved"] += audience.save(self.factory, account_id, rows, now)
            except Exception as error:
                self.audience_failed(result, "threads", error)
        youtube = self.youtube_account()
        if youtube:
            try:
                account_id = self.audience_due("youtube", youtube, now)
                if account_id is not None:
                    rows = self.youtube_audience(now)
                    result["saved"] += audience.save(self.factory, account_id, rows, now)
            except Exception as error:
                self.audience_failed(result, "youtube", error)
        return result if result["saved"] or result["errors"] else 0

    def audience_due(self, platform, external_id, now):
        with self.factory() as session:
            account_id = audience.registered(session, platform, external_id)
            return account_id if account_id and audience.due(session, account_id, now) else None

    @staticmethod
    def audience_failed(result, platform, error):
        if not isinstance(error, WorkerError):
            log_failure("mwb.gateway_workers", "gateway_workers_audience_failed", error)
        code = error.code if isinstance(error, WorkerError) else "sync_failed"
        result["errors"].append(dict(platform=platform, code=code))

    def audience_graph(self, path, qs, context):
        response = self.graph(path, qs, context)
        body = response.get("body")
        body = body if isinstance(body, dict) else {}
        error = body.get("error") if isinstance(body.get("error"), dict) else None
        status = response.get("statusCode")
        if status == 200 and not error:
            return body
        code = error.get("code") if error and type(error.get("code")) is int else None
        if status == 429 or code in RATE_CODES:
            raise WorkerError("meta_rate_limited")
        if code == 190 or status == 401:
            raise WorkerError("meta_auth_error")
        if status == 403 or code == 10 or (code is not None and 200 <= code < 300):
            raise Missing("permission_missing")
        if code == 100:
            # 無效參數：指標已停用或帳號未達門檻（例如追蹤者少於 100 人）。
            raise Missing("not_available")
        if type(status) is int and status >= 500:
            raise WorkerError("meta_server_error")
        raise WorkerError("meta_api_error")

    def instagram_audience(self, account, context):
        rows = []
        for breakdown in DEMOGRAPHICS:
            row = dict(metric="followers", breakdown=breakdown, period=IG_TIMEFRAME)
            try:
                body = self.audience_graph(
                    account + "/insights",
                    dict(
                        metric="follower_demographics",
                        period="lifetime",
                        timeframe=IG_TIMEFRAME,
                        breakdown=breakdown,
                        metric_type="total_value",
                    ),
                    context,
                )
                limit = audience.TOP_LOCATIONS if breakdown in ("country", "city") else None
                row["items"] = ranked(
                    breakdown_items(body, "follower_demographics", breakdown), limit, breakdown
                )
            except Missing as missing:
                row["error"] = missing.code
            rows.append(row)
        row = dict(metric="online", breakdown="hour", period="last_7_days")
        until = int(self.clock())
        try:
            body = self.audience_graph(
                account + "/insights",
                dict(
                    metric="online_followers",
                    period="lifetime",
                    since=str(until - ONLINE_DAYS * 86400),
                    until=str(until),
                ),
                context,
            )
            items = online_items(body)
            # 時段依 0–23 時排列，不依人數排序。
            row["items"] = items if any(item["value"] for item in items) else []
        except Missing as missing:
            row["error"] = missing.code
        rows.append(row)
        return rows

    def facebook_audience(self, page, context):
        # 年齡／性別指標 Meta 已於 2024-03 停用、無替代；只剩追蹤者的國家與城市。
        rows = []
        try:
            body = self.audience_graph(
                page + "/insights",
                dict(metric="page_follows_country,page_follows_city", period="day"),
                context,
            )
        except Missing as missing:
            return [
                dict(metric="followers", breakdown=b, period="day", error=missing.code)
                for b in ("country", "city")
            ]
        for breakdown, metric in (
            ("country", "page_follows_country"),
            ("city", "page_follows_city"),
        ):
            rows.append(
                dict(
                    metric="followers",
                    breakdown=breakdown,
                    period="day",
                    items=ranked(page_items(body, metric), audience.TOP_LOCATIONS),
                )
            )
        return rows

    def threads_audience(self, account, token):
        if self.threads_access() == "missing":
            return [
                dict(metric="followers", breakdown=b, period="lifetime", error="permission_missing")
                for b in DEMOGRAPHICS
            ]
        rows = []
        for breakdown in DEMOGRAPHICS:
            row = dict(metric="followers", breakdown=breakdown, period="lifetime")
            try:
                body = self.threads_get(
                    account + "/threads_insights",
                    dict(metric="follower_demographics", breakdown=breakdown),
                    token,
                )
                limit = audience.TOP_LOCATIONS if breakdown in ("country", "city") else None
                row["items"] = ranked(
                    breakdown_items(body, "follower_demographics", breakdown), limit, breakdown
                )
            except WorkerError as error:
                if error.code == "threads_permission_missing":
                    self.threads_block()
                    return None
                if error.code != "meta_api_error":
                    raise
                # 一般 API 錯誤（多半是追蹤者未滿 100 人）存成提示，隔天再試。
                row["error"] = "not_available"
            rows.append(row)
        return rows

    def youtube_audience(self, now):
        sync = self.youtube_sync()
        end = (now.astimezone(PACIFIC) - timedelta(days=2)).date()
        start = end - timedelta(days=27)
        base = {
            "ids": "channel==" + sync.channel_id,
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
        }
        period = "last_28_days"
        try:
            demo = report_items(
                sync.get(
                    "reports",
                    {**base, "dimensions": "ageGroup,gender", "metrics": "viewerPercentage"},
                ),
                ["ageGroup", "gender"],
                "viewerPercentage",
            )
            country = report_items(
                sync.get(
                    "reports",
                    {
                        **base,
                        "dimensions": "country",
                        "metrics": "views",
                        "sort": "-views",
                        "maxResults": audience.TOP_LOCATIONS,
                    },
                ),
                ["country"],
                "views",
            )
        except WorkerError as error:
            if error.code != "youtube_permission_missing":
                raise
            return [
                dict(metric="viewers", breakdown=b, period=period, error="permission_missing")
                for b in ("age", "gender", "country")
            ]
        ages, genders = defaultdict(float), defaultdict(float)
        for row in demo:
            ages[str(row["ageGroup"]).removeprefix("age")] += row["viewerPercentage"]
            genders[str(row["gender"])] += row["viewerPercentage"]

        def percent(values):
            return [{"key": k, "value": round(v, 1)} for k, v in values.items()]

        return [
            dict(
                metric="viewers",
                breakdown="age",
                period=period,
                unit="percent",
                items=ranked(percent(ages), breakdown="age"),
            ),
            dict(
                metric="viewers",
                breakdown="gender",
                period=period,
                unit="percent",
                items=ranked(percent(genders)),
            ),
            dict(
                metric="viewers",
                breakdown="country",
                period=period,
                items=ranked(
                    [{"key": str(r["country"]), "value": int(r["views"])} for r in country]
                ),
            ),
        ]

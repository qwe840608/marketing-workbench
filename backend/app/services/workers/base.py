"""Worker 共用基礎：錯誤、平台 HTTP、Meta 呼叫配額與 Threads 讀取、帳號解析。"""

import logging
import math
import re
import time
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import httpx
from sqlalchemy import select

from app.logging_config import log_failure
from app.models import Account
from app.schemas import meta as schemas
from app.services import credentials, ingest, meta_api, oauth
from app.services.publish_platforms import TH as THREADS_API
from app.services.webhook_normalize import dump, secret

logger = logging.getLogger("mwb.gateway_workers")


class WorkerError(Exception):
    def __init__(self, code, permissions=None, detail=None):
        self.code, self.permissions, self.detail = code, permissions or [], detail
        super().__init__(code)


def usage_headers(headers):
    import json

    headers = {k.lower(): v for k, v in headers.items()}

    def parse(key):
        try:
            raw = headers.get(key)
            return json.loads(raw) if isinstance(raw, str) and len(raw) <= 32768 else None
        except ValueError:
            return None

    def usage(value):
        if not isinstance(value, dict):
            return None
        result = {
            k: min(v, 10000)
            for k, v in value.items()
            if k in ("call_count", "total_time", "total_cputime", "estimated_time_to_regain_access")
            and type(v) in (int, float)
            and math.isfinite(v)
            and v >= 0
        }
        return result or None

    business = parse("x-business-use-case-usage")
    rows = []
    if isinstance(business, dict):
        for value in business.values():
            rows.extend(value if isinstance(value, list) else [value])
    retry = headers.get("retry-after", "")
    try:
        seconds = (
            float(retry)
            if re.fullmatch(r"\d+", str(retry))
            else parsedate_to_datetime(retry).timestamp() - time.time()
        )
    except (ValueError, TypeError, OverflowError):
        seconds = 0
    return dict(
        app_usage=usage(parse("x-app-usage")),
        business_usage=[u for row in rows if (u := usage(row))][:32],
        retry_after_seconds=max(0, min(seconds, 604800)),
    )


class WorkerBase:
    """各 worker mixin 共用的狀態與平台／service 呼叫；Workers 由 gateway_workers 組合。"""

    def __init__(self, factory, settings, request=None, clock=time.time, sleep=time.sleep):
        self.settings, self.clock = settings, clock
        self.request = request or self.http
        self.sleep = sleep
        self.factory = factory
        # 本輪已嘗試取得完整貼文清單的平台；排程據此略過另外一次的已刪除偵測清單。
        self.listed = set()

    def service(self, function, *args):
        """在自己的 session 呼叫既有 service，交易邊界與舊內部路由相同（由 service 自行開交易）。"""
        with self.factory() as session:
            return function(session, *args)

    def save_poll_events(self, body):
        """留言輪詢事件沿用 ingest.events 的原始位元組入口（與 Webhook 相同的正規化與冪等）。"""
        with self.factory() as session:
            outcome = ingest.events(session, dump(body).encode(), "poll", settings=self.settings)
        # 舊內部路由以 HTTP 狀態回報；直呼後保留同一判斷：非 200 或未處理即視為後端失敗。
        if outcome.status != 200 or not outcome.result.processed:
            raise WorkerError("backend_failed")
        return outcome.result.model_dump(mode="json")

    @staticmethod
    def http(method, url, *, headers=None, qs=None, body=None, timeout=15):
        with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            response = client.request(method, url, headers=headers, params=qs, json=body)
            try:
                data = response.json()
            except ValueError:
                data = {}
            return dict(statusCode=response.status_code, body=data, headers=dict(response.headers))

    def graph(self, path, qs, context):
        if not re.fullmatch(
            r"[a-zA-Z0-9_][a-zA-Z0-9_.$:=+\-]{0,254}(?:/(?:media|published_posts|videos|comments|replies|insights))?",
            path,
        ):
            raise WorkerError("invalid_response")
        parts = path.split("/")
        permit = self.service(
            meta_api.start_call,
            schemas.ApiCallStart.model_validate(
                {
                    **context,
                    "resource_id": parts[0],
                    "operation": parts[1] if len(parts) > 1 else "post",
                }
            ),
            self.settings,
        )
        if not permit["allowed"]:
            raise WorkerError("meta_rate_limited")
        started = self.clock()
        try:
            response = self.request(
                "GET",
                "https://graph.facebook.com/v26.0/" + "/".join(quote(p, safe="") for p in parts),
                qs=qs,
                headers={
                    "Authorization": "Bearer " + secret(self.settings, "meta_page_access_token")
                },
            )
        except Exception as error:
            log_failure("mwb.gateway_workers", "gateway_workers_graph_failed", error)
            self.service(
                meta_api.finish_call,
                schemas.ApiCallFinish.model_validate(
                    dict(
                        call_id=permit["call_id"],
                        http_status=0,
                        error_code=None,
                        duration_ms=round((self.clock() - started) * 1000),
                    )
                ),
            )
            raise WorkerError(
                "meta_timeout" if isinstance(error, httpx.TimeoutException) else "network_error"
            ) from None
        code = (response.get("body", {}).get("error") or {}).get("code")
        self.service(
            meta_api.finish_call,
            schemas.ApiCallFinish.model_validate(
                dict(
                    call_id=permit["call_id"],
                    http_status=response["statusCode"],
                    error_code=code if type(code) is int else None,
                    **(
                        {"error_subcode": response["body"]["error"]["error_subcode"]}
                        if type((response.get("body", {}).get("error") or {}).get("error_subcode"))
                        is int
                        else {}
                    ),
                    duration_ms=round((self.clock() - started) * 1000),
                    **usage_headers(response.get("headers", {})),
                )
            ),
        )
        return {
            **response,
            "call_id": permit["call_id"],
            **({"observed_at": permit["observed_at"]} if "observed_at" in permit else {}),
        }

    def youtube_account(self):
        from app.services import youtube

        return youtube.account(self.factory, self.settings)

    def youtube_sync(self):
        from app.services.youtube import Sync

        return Sync(self)

    def tiktok_account(self):
        from app.services import tiktok

        return tiktok.account(self.factory, self.settings)

    def tiktok_sync(self):
        from app.services.tiktok import Sync

        return Sync(self)

    def accounts(self, comments=False):
        rows = [
            ("facebook", credentials.resolve("META_PAGE_ID", self.settings)),
            ("instagram", credentials.resolve("META_IG_ACCOUNT_ID", self.settings)),
        ]
        if comments:
            rows.reverse()
        rows = [r for r in rows if r[1]]
        # Threads 回覆與 FB／IG 輪流讀取；只有留言排程會帶入，粉絲數另由 threads_followers 處理。
        threads = self.threads_account(registered=True) if comments else None
        youtube = self.youtube_account() if comments else None
        if (
            not secret(self.settings, "meta_page_access_token")
            or not rows
            or any(not re.fullmatch(r"\d+", a) for _, a in rows)
        ):
            if not threads and not youtube:
                raise WorkerError("meta_configuration_missing")
            rows = []
        if threads:
            rows.append(("threads", threads[0]))
        if youtube:
            rows.append(("youtube", youtube))
        offset = int(self.clock() // 60) % len(rows)
        return rows[offset:] + rows[:offset]

    def threads_account(self, registered=False):
        """已設定且（需要時）已登記的 Threads 帳號與權杖；否則回傳 None，不呼叫平台。"""
        user = credentials.resolve("THREADS_USER_ID", self.settings)
        token = secret(self.settings, "threads_access_token")
        if not token or not isinstance(user, str) or not re.fullmatch(r"\d+", user):
            return None
        if registered and self.factory is not None:
            with self.factory() as session:
                found = list(
                    session.scalars(
                        select(Account.id)
                        .where(Account.platform == "threads", Account.external_id == user)
                        .limit(2)
                    )
                )
            if len(found) != 1:
                return None
        return user, token

    def threads_access(self):
        if self.factory is None:
            return "unknown"
        with self.factory() as session:
            return oauth.threads_data_access(session, self.settings)

    def threads_block(self):
        """平台回權限錯誤：記下來，換權杖（重新連結）或一天後才再試，設定頁據此提示。"""
        logger.info("threads_data_blocked", extra={"reason": "permission_missing"})
        if self.factory is not None:
            with self.factory.begin() as session:
                oauth.mark_threads_data_blocked(session, self.settings)

    def threads_get(self, path, query, token):
        if not re.fullmatch(
            r"[A-Za-z0-9_]{1,128}/(?:threads|insights|conversation|threads_insights)", path
        ):
            raise WorkerError("invalid_response")
        try:
            response = self.request(
                "GET",
                THREADS_API + "/" + path,
                qs=query,
                headers={"Authorization": "Bearer " + token},
            )
        except Exception as error:
            log_failure("mwb.gateway_workers", "gateway_workers_threads_request_failed", error)
            raise WorkerError(
                "meta_timeout" if isinstance(error, httpx.TimeoutException) else "network_error"
            ) from None
        status = response.get("statusCode")
        data = response.get("body")
        data = data if isinstance(data, dict) else {}
        if status != 200 or data.get("error"):
            error = data.get("error") if isinstance(data.get("error"), dict) else {}
            code = error.get("code") if type(error.get("code")) is int else None
            if status == 429 or code in (4, 17, 32, 613, 80004):
                raise WorkerError("meta_rate_limited")
            if code == 190 or status == 401:
                raise WorkerError("meta_auth_error")
            if status == 403 or code in (10, 200) or (code is not None and 200 <= code < 300):
                raise WorkerError("threads_permission_missing")
            if type(status) is int and status >= 500:
                raise WorkerError("meta_server_error")
            raise WorkerError("meta_api_error", detail=code if code is not None else status)
        return data

    def threads_edge(self, path, query, token, after, bad):
        """讀 Threads 一頁清單；格式或分頁異常以 bad 代碼中止，不寫入任何東西。"""
        data = self.threads_get(path, {**query, **({"after": after} if after else {})}, token)
        rows = data.get("data")
        if (
            not isinstance(rows, list)
            or len(rows) > 100
            or any(not isinstance(row, dict) for row in rows)
        ):
            raise WorkerError(bad)
        paging = data.get("paging") if isinstance(data.get("paging"), dict) else {}
        cursor = None
        if paging.get("next"):
            cursors = paging.get("cursors")
            cursor = cursors.get("after") if isinstance(cursors, dict) else None
            if not isinstance(cursor, str) or not cursor or len(cursor) > 4096 or cursor == after:
                raise WorkerError("invalid_pagination")
        return rows, cursor

    @staticmethod
    def post(row):
        attachments = (row.get("attachments") or {}).get("data") or [{}]
        return dict(
            external_id=row["id"],
            caption=row.get("message", row.get("caption", "")),
            permalink=row.get("permalink_url", row.get("permalink")),
            media_type="REELS"
            if row.get("media_product_type") == "REELS"
            else row.get("media_type") or attachments[0].get("media_type") or "POST",
            published_at=row.get("created_time") or row.get("timestamp"),
        )


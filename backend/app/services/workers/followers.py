"""FB／IG／Threads／YouTube／TikTok 粉絲數每日快照。"""

import logging

from app.logging_config import log_failure
from app.schemas.followers import FollowerInput
from app.services import followers
from app.services.webhook_normalize import instant
from app.services.workers.base import WorkerError
from app.services.workers.metrics import metric_count

logger = logging.getLogger("mwb.gateway_workers")


class FollowersMixin:
    def followers(self):
        result = dict(ok=True, inserted=0, errors=[])
        threads = self.threads_account(registered=True)
        youtube = self.youtube_account()
        tiktok = self.tiktok_account()
        try:
            accounts = self.accounts()
        except WorkerError as error:
            if not threads and not youtube and not tiktok:
                return dict(ok=False, inserted=0, errors=[{"code": error.code}])
            accounts = []
        for platform, account in accounts:
            context = dict(platform=platform, account_external_id=account, source="metrics")
            try:
                if not self.service(followers.due, platform, account)["due"]:
                    continue
                response = self.graph(account, dict(fields="id,followers_count"), context)
                data = response.get("body") or {}
                if response["statusCode"] != 200 or data.get("error"):
                    raise WorkerError("followers_unavailable")
                count = data.get("followers_count")
                if (
                    data.get("id") != account
                    or type(count) is not int
                    or not 0 <= count <= 2**53 - 1
                ):
                    raise WorkerError("invalid_response")
                # Capture the response time, not a platform insight's historical date.
                result["inserted"] += self.service(
                    followers.record,
                    FollowerInput.model_validate(
                        dict(
                            platform=platform,
                            account_external_id=account,
                            captured_at=instant(self.clock() * 1000, True),
                            followers_count=count,
                        )
                    ),
                )["inserted"]
            except Exception as error:
                log_failure("mwb.gateway_workers", "gateway_workers_followers_failed", error)
                result["ok"] = False
                code = error.code if isinstance(error, WorkerError) else "sync_failed"
                result["errors"].append(dict(platform=platform, code=code))
                if code == "meta_rate_limited":
                    break
        # Threads 不經 Meta 呼叫配額，Meta 被限流時仍照常讀取。
        if threads:
            self.threads_followers(result, *threads)
        if youtube:
            try:
                self.youtube_sync().followers(result)
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
                self.tiktok_sync().followers(result)
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

    def threads_followers(self, result, account, token):
        """Threads 使用者層級 insights 的 followers_count（lifetime 總數），頻率沿用每日一次。"""
        try:
            if self.threads_access() == "missing":
                logger.info(
                    "threads_data_skipped",
                    extra={"reason": "permission_missing", "operation": "followers"},
                )
                return
            if not self.service(followers.due, "threads", account)["due"]:
                return
            try:
                data = self.threads_get(
                    account + "/threads_insights", dict(metric="followers_count"), token
                )
            except WorkerError as error:
                if error.code != "threads_permission_missing":
                    raise
                self.threads_block()
                return
            rows = data.get("data")
            if (
                not isinstance(rows, list) or len(rows) != 1
                or not isinstance(rows[0], dict) or rows[0].get("name") != "followers_count"
            ):
                raise WorkerError("invalid_response")
            row = rows[0]
            if "values" in row:
                values = row["values"]
                if (
                    not isinstance(values, list) or len(values) != 1
                    or not isinstance(values[0], dict)
                ):
                    raise WorkerError("invalid_response")
                value = values[0].get("value")
            else:
                total = row.get("total_value")
                value = total.get("value") if isinstance(total, dict) else None
            count = metric_count(value)
            if count is None:
                raise WorkerError("invalid_response")
            result["inserted"] += self.service(
                followers.record,
                FollowerInput.model_validate(
                    dict(
                        platform="threads",
                        account_external_id=account,
                        captured_at=instant(self.clock() * 1000, True),
                        followers_count=count,
                    )
                ),
            )["inserted"]
        except Exception as error:
            log_failure("mwb.gateway_workers", "gateway_workers_followers_failed", error)
            result["ok"] = False
            code = error.code if isinstance(error, WorkerError) else "sync_failed"
            result["errors"].append(dict(platform="threads", code=code))


"""LINE 通知群組的 Push 派送與結果回寫。"""

import re

from app.logging_config import log_failure
from app.schemas.notify import DeliveryResult
from app.services import notify
from app.services.webhook_normalize import secret


class NotifyMixin:
    def notifications(self):
        if not secret(self.settings, "notify_line_channel_access_token"):
            return dict(ok=False, error="notify_configuration_missing")
        deliveries = notify.dispatch(self.factory, self.settings).get("deliveries")
        accepted = failed = 0
        if not isinstance(deliveries, list):
            return dict(ok=False, error="notify_dispatch_failed")
        for job in deliveries:

            def uuid(v):
                return isinstance(v, str) and bool(re.fullmatch(r"[a-f0-9-]{36}", v))

            if (
                type(job.get("id")) is not int
                or job["id"] < 1
                or not re.fullmatch(r"C[a-f0-9]{32}", job.get("to", ""))
                or not uuid(job.get("retry_key"))
                or not uuid(job.get("lease_id"))
                or not isinstance(job.get("messages"), list)
                or not 1 <= len(job["messages"]) <= 5
                or any(
                    m.get("type") != "text"
                    or not isinstance(m.get("text"), str)
                    or not 1 <= len(m["text"]) <= 5000
                    for m in job["messages"]
                )
            ):
                failed += 1
                continue
            status = 0
            already = False
            try:
                response = self.request(
                    "POST",
                    "https://api.line.me/v2/bot/message/push",
                    headers={
                        "Authorization": "Bearer "
                        + secret(self.settings, "notify_line_channel_access_token"),
                        "X-Line-Retry-Key": job["retry_key"],
                    },
                    body={"to": job["to"], "messages": job["messages"]},
                    timeout=10,
                )
                status = response["statusCode"]
                already = status == 409 and bool(
                    re.fullmatch(
                        r"[a-f0-9-]{36}",
                        response.get("headers", {}).get("x-line-accepted-request-id", ""),
                        re.I,
                    )
                )
            except Exception as error:
                log_failure("mwb.gateway_workers", "gateway_workers_notifications_failed", error)
                pass
            try:
                result = notify.finish(
                    self.factory,
                    job["id"],
                    DeliveryResult.model_validate(
                        dict(lease_id=job["lease_id"], status_code=status, already_accepted=already)
                    ),
                )
                if result.get("status") == "sent":
                    accepted += 1
                else:
                    failed += 1
            except Exception as error:
                log_failure("mwb.gateway_workers", "gateway_workers_notifications_failed", error)
                failed += 1
        return dict(ok=failed == 0, accepted=accepted, failed=failed)


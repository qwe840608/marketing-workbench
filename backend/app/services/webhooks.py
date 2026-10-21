"""Public comments persist before ACK; signed retired DM transports are discarded."""

import re

from fastapi import HTTPException

from app.logging_config import log_failure
from app.services import credentials, ingest, notify, receive_health
from app.services.webhook_normalize import (
    GatewayError,
    dump,
    iter_meta_envelopes,
    parse,
    secret,
    verify_signature,
)


def receive(factory, settings, name, raw, headers):
    platform = "line" if name == "line-inbound" else "meta" if name == "meta-inbound" else "notify"
    try:
        if len(raw) > 1024 * 1024:
            raise GatewayError(413, "payload_too_large")
        key = secret(
            settings,
            {
                "line": "line_channel_secret",
                "meta": "meta_app_secret",
                "notify": "notify_line_channel_secret",
            }[platform],
        )
        if not key:
            raise GatewayError(503, platform + "_configuration_missing")
        if platform == "meta" and any(
            not re.fullmatch(r"\d+", v)
            for v in (
                credentials.resolve("META_PAGE_ID", settings),
                credentials.resolve("META_IG_ACCOUNT_ID", settings),
            )
        ):
            raise GatewayError(503, "meta_configuration_missing")
        supplied = headers.get("x-hub-signature-256" if platform == "meta" else "x-line-signature")
        if not verify_signature(raw, supplied, key, "meta" if platform == "meta" else "line"):
            raise GatewayError(401, "signature_invalid")
        if platform == "notify":
            with factory() as session:
                notify.capture_groups(session, settings, raw, supplied)
            return 200, {"ok": True}, []
        if platform == "line":
            return 200, {"ok": True, "events": 0}, []
        payload = parse(raw)
        envelopes = iter_meta_envelopes(
            payload,
            credentials.resolve("META_PAGE_ID", settings),
            credentials.resolve("META_IG_ACCOUNT_ID", settings),
        )
        failed = False
        count = 0
        for envelope in envelopes:
            if envelope is None:
                failed = True
                continue
            count += 1
            try:
                with factory() as session:
                    event = envelope["payload"]["entry"][0]["changes"][0]
                    if (
                        envelope["platform"] == "instagram"
                        and event.get("field") == "story_insights"
                    ):
                        from app.db import ensure_write
                        from app.services import publish_story_insights

                        ensure_write(session)
                        publish_story_insights.webhook(session, envelope)
                        session.commit()
                        continue
                    outcome = ingest.events(session, dump(envelope).encode(), settings=settings)
                failed |= outcome.status != 200 or not outcome.result.processed
            except Exception as error:
                log_failure("mwb.webhooks", "webhooks_receive_failed", error)
                failed = True
        result = (
            {"ok": False, "error": "ingest_failed"} if failed else {"ok": True, "events": count}
        )
        return (503 if failed else 200), result, []
    except (GatewayError, HTTPException) as error:
        status = error.status if isinstance(error, GatewayError) else error.status_code
        if status == 401:
            try:
                with factory() as session:
                    receive_health.signature_failure(session, platform)
            except Exception as error:
                log_failure("mwb.webhooks", "webhooks_receive_failed", error)
                pass
        return (
            status,
            {
                "ok": False,
                "error": error.code if isinstance(error, GatewayError) else "invalid_event",
            },
            [],
        )


def request_sync(factory, settings, name, raw):
    from fastapi.responses import JSONResponse

    from app.services.scheduler import scheduler_for

    scheduler = scheduler_for(settings)
    if not scheduler or not scheduler.healthy():
        return JSONResponse({"ok": False, "error": "scheduler_unavailable"}, status_code=503)
    if name == "meta-comments-sync":
        try:
            body = parse(raw)
            if type(body.get("requested_only")) is not bool or (
                body.get("post_id") is not None
                and (type(body["post_id"]) is not int or body["post_id"] < 1)
            ):
                raise ValueError()
        except (GatewayError, ValueError):
            return JSONResponse({"ok": False, "error": "invalid_input"}, status_code=400)
        # The UI already persisted requested_at; the native minute worker claims that queue.
        scheduler.request(
            "comments", {"requested_only": body["requested_only"], "post_id": body.get("post_id")}
        )
        return JSONResponse({"ok": True, "completed": 0, "paused": False, "queued": True})
    scheduler.request("metrics")
    return JSONResponse({"ok": True, "posts": 0, "snapshots": 0, "errors": [], "queued": True})

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.concurrency import run_in_threadpool

from app.services import webhooks
from app.services.webhook_normalize import (
    secret,
    verify_challenge,
    verify_control,
)

router = APIRouter(prefix="/webhook")


@router.get("/mwb-gateway-probe")
def probe(request: Request):
    valid = verify_control(
        request.headers,
        secret(request.app.state.settings, "webhook_probe_secret"),
        request.url.path,
    )
    return JSONResponse(
        {"ok": True, "service": "backend", "purpose": "tunnel-check"}
        if valid
        else {"error": "簽章驗證失敗"},
        status_code=200 if valid else 401,
    )


@router.get("/meta-inbound")
def challenge(request: Request):
    valid = verify_challenge(
        request.query_params, secret(request.app.state.settings, "meta_verify_token")
    )
    return PlainTextResponse(
        request.query_params["hub.challenge"] if valid else "verification_failed",
        status_code=200 if valid else 403,
    )


@router.post("/{name}")
async def receive(name: str, request: Request):
    if name not in (
        "line-inbound",
        "meta-inbound",
        "line-notify",
        "meta-comments-sync",
        "meta-sync",
    ):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    body = bytearray()
    limit = 1024 if name == "meta-comments-sync" else 1024 * 1024
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            return JSONResponse({"ok": False, "error": "payload_too_large"}, status_code=413)
    raw = bytes(body)
    settings = request.app.state.settings
    if name in ("meta-comments-sync", "meta-sync"):
        if not verify_control(
            request.headers,
            secret(settings, "webhook_probe_secret"),
            request.url.path,
            raw if name == "meta-comments-sync" else None,
        ):
            return JSONResponse({"ok": False, "error": "signature_invalid"}, status_code=401)
        return await run_in_threadpool(
            webhooks.request_sync, request.app.state.session_factory, settings, name, raw
        )
    status, result, _ = await run_in_threadpool(
        webhooks.receive, request.app.state.session_factory, settings, name, raw, request.headers
    )
    return JSONResponse(result, status_code=status)

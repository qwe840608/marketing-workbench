"""D-07: proxy markers and public sources can reach only strict webhook paths."""

import ipaddress
import re

from starlette.responses import JSONResponse


def internal(address):
    if address in ("testclient", "testserver"):
        return True
    try:
        ip = ipaddress.ip_address(address)
        return (
            ip.is_loopback
            or ip in ipaddress.ip_network("100.64.0.0/10")
            or ip in ipaddress.ip_network("fd7a:115c:a1e0::/48")
        )
    except ValueError:
        return False


class PublicBoundary:
    def __init__(self, app, settings):
        self.app, self.settings = app, settings

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = {}
        for k, v in scope.get("headers", []):
            headers.setdefault(k.lower(), []).append(v.decode("latin1"))
        host = headers.get(b"host", [""])[0].split(":")[0].lower()
        forwarded = ",".join(headers.get(b"x-forwarded-host", [])).lower()
        source = (scope.get("client") or ("", 0))[0]
        public = (
            b"x-mwb-public" in headers
            or ".ngrok" in host
            or ".ngrok" in forwarded
            or not internal(source)
        )
        # A forwarded public address remains public even with a spoofed internal Host.
        for addresses in headers.get(b"x-forwarded-for", []):
            if any(not internal(a.strip()) for a in addresses.split(",")):
                public = True
        raw = scope.get("raw_path", scope["path"].encode()).decode("ascii", "replace")
        if scope["type"] == "http" and scope["path"].startswith("/plugin/"):
            from fastapi import HTTPException, Request

            from app.services.agent_auth import origin_for

            try:
                origin_for(Request(scope))
            except HTTPException:
                return await JSONResponse({"detail": "Not Found"}, status_code=404)(
                    scope, receive, send
                )

        def valid(p):
            return bool(
                re.fullmatch(
                    r"(?:/webhook/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*/?"
                    r"|/media/[A-Za-z0-9_-]{43}(?:\.jpg)?)",
                    p,
                )
            )

        if public and (not valid(raw) or not valid(scope["path"])):
            if scope["type"] == "websocket":
                return await send({"type": "websocket.close", "code": 1008})
            return await JSONResponse({"detail": "Not Found"}, status_code=404)(
                scope, receive, send
            )
        return await self.app(scope, receive, send)

"""D-07: proxy markers and public sources can reach only strict webhook paths."""

import ipaddress
import re
from urllib.parse import urlsplit

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
    def __init__(self, app, settings, verifier=None):
        from app.services.cf_access import verifier_for

        self.app, self.settings = app, settings
        self.verifier = verifier or verifier_for(settings)
        self.backoffice_host = urlsplit(settings.backoffice_origin).hostname or ""

    async def access_granted(self, headers, host, forwarded):
        """經 Cloudflare Tunnel、帶有效 Access JWT，且打的是後台網址，才算內部。"""
        if self.verifier is None or not self.backoffice_host:
            return False
        # ngrok 標記與 ngrok 網址一律公開；只有 Cloudflare 邊緣送來的請求才看 JWT。
        if b"x-mwb-public" in headers or ".ngrok" in host or ".ngrok" in forwarded:
            return False
        if b"cf-connecting-ip" not in headers or host != self.backoffice_host:
            return False
        if forwarded and forwarded != self.backoffice_host:
            return False
        tokens = headers.get(b"cf-access-jwt-assertion", [])
        return len(tokens) == 1 and await self.verifier.verify(tokens[0]) is not None

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
            # Cloudflare 邊緣一定會加上這兩個標頭，用戶端無法移除；經 Tunnel 進來的一律先視為公開。
            or b"cf-connecting-ip" in headers
            or b"cf-ray" in headers
            or not internal(source)
        )
        # A forwarded public address remains public even with a spoofed internal Host.
        for addresses in headers.get(b"x-forwarded-for", []):
            if any(not internal(a.strip()) for a in addresses.split(",")):
                public = True
        if public and await self.access_granted(headers, host, forwarded):
            public = False
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

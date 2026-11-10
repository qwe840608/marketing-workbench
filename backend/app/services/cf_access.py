"""Cloudflare Access：驗證 Cf-Access-Jwt-Assertion，通過才把經 Tunnel 進來的連線當成內部。

經 Cloudflare Tunnel 進來的連線，對後端來說來源都是本機的 cloudflared，所以不能用來源 IP 判斷。
Access 登入成功後，Cloudflare 會在每個請求加上簽章過的 JWT；這裡只接受由設定的團隊網域簽發、
受眾（AUD）相符、未過期、信箱在允許清單內的 RS256 權杖。任何一項不符或取不到公鑰都當成公開連線
（只放行 Webhook 與媒體權杖路徑），寧可遠端打不開，也不放行。
"""

import asyncio
import base64
import json
import re
import time

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

TEAM_DOMAIN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.cloudflareaccess\.com")
AUDIENCE = re.compile(r"[a-f0-9]{64}")
MAX_TOKEN = 8192
LEEWAY_SECONDS = 60
# 公鑰每小時重抓；遇到不認得的 kid（Cloudflare 輪替金鑰）時最快每分鐘重抓一次，
# 避免被拿來大量打外部請求。
KEYS_TTL_SECONDS = 3600
KEYS_RETRY_SECONDS = 60


def _b64(value: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]*", value):
        raise ValueError("not base64url")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _int(value: str) -> int:
    return int.from_bytes(_b64(value), "big")


async def fetch_certs(team_domain: str) -> dict:
    async with httpx.AsyncClient(timeout=5, follow_redirects=False, trust_env=False) as http:
        response = await http.get(f"https://{team_domain}/cdn-cgi/access/certs")
        response.raise_for_status()
        return response.json()


class AccessVerifier:
    def __init__(self, team_domain, audience, emails, *, fetch=None, clock=time.time):
        self.team_domain, self.audience = team_domain, audience
        self.issuer = f"https://{team_domain}"
        self.emails = frozenset(e.strip().lower() for e in emails if e.strip())
        self.fetch, self.clock = fetch, clock
        self.keys: dict[str, rsa.RSAPublicKey] = {}
        self.fetched_at = None
        self.lock = asyncio.Lock()

    async def key(self, kid):
        now = self.clock()
        stale = self.fetched_at is None or now - self.fetched_at > KEYS_TTL_SECONDS
        retry = self.fetched_at is None or now - self.fetched_at > KEYS_RETRY_SECONDS
        if stale or (kid not in self.keys and retry):
            async with self.lock:
                if self.fetched_at is None or self.clock() - self.fetched_at > KEYS_RETRY_SECONDS:
                    await self.refresh()
        return self.keys.get(kid)

    async def refresh(self):
        # 先記時間：抓取失敗也要等下一個重試窗，不讓每個請求都打一次 Cloudflare。
        self.fetched_at = self.clock()
        try:
            body = await (self.fetch or fetch_certs)(self.team_domain)
        except (httpx.HTTPError, ValueError):
            return
        keys = {}
        for item in body.get("keys", []) if isinstance(body, dict) else []:
            try:
                if item.get("kty") != "RSA" or item.get("alg", "RS256") != "RS256":
                    continue
                numbers = rsa.RSAPublicNumbers(_int(item["e"]), _int(item["n"]))
                keys[str(item["kid"])] = numbers.public_key()
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
        if keys:
            self.keys = keys

    async def verify(self, token: str) -> dict | None:
        try:
            if not token or len(token) > MAX_TOKEN or token.count(".") != 2:
                return None
            head, body, signature = token.split(".")
            header = json.loads(_b64(head))
            # 只接受 RS256；拒絕 none 與對稱演算法，避免偽造。
            if not isinstance(header, dict) or header.get("alg") != "RS256":
                return None
            kid = header.get("kid")
            if not isinstance(kid, str) or not kid:
                return None
            key = await self.key(kid)
            if key is None:
                return None
            key.verify(
                _b64(signature),
                f"{head}.{body}".encode("ascii"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
            claims = json.loads(_b64(body))
        except (ValueError, TypeError, InvalidSignature, UnicodeError):
            return None
        return claims if self.accept(claims) else None

    def accept(self, claims) -> bool:
        if not isinstance(claims, dict) or claims.get("iss") != self.issuer:
            return False
        audience = claims.get("aud")
        audiences = audience if isinstance(audience, list) else [audience]
        if self.audience not in audiences:
            return False
        now = self.clock()
        exp, nbf, iat = claims.get("exp"), claims.get("nbf"), claims.get("iat")
        if not isinstance(exp, (int, float)) or exp < now - LEEWAY_SECONDS:
            return False
        for value in (nbf, iat):
            if value is not None and (
                not isinstance(value, (int, float)) or value > now + LEEWAY_SECONDS
            ):
                return False
        # 服務權杖沒有 email；工作檯只開放給允許清單裡的人。
        email = claims.get("email")
        return isinstance(email, str) and email.lower() in self.emails


def verifier_for(settings):
    if not settings.cf_access_team_domain:
        return None
    return AccessVerifier(
        settings.cf_access_team_domain, settings.cf_access_aud, settings.cf_access_emails.split(",")
    )

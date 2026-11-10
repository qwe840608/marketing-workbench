"""Cloudflare Access：只有有效 JWT 能把經 Tunnel 的連線變成內部，其餘一律只到 Webhook／媒體。"""

import asyncio
import base64
import json
import time

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from app.services import cf_access

TEAM = "example-team.cloudflareaccess.com"
AUD = "a" * 64
HOST = "mwb.example.com"
EMAIL = "owner@example.com"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def jwk(key, kid="kid-1"):
    numbers = key.public_key().public_numbers()
    size = (numbers.n.bit_length() + 7) // 8
    return {
        "kid": kid,
        "kty": "RSA",
        "alg": "RS256",
        "n": b64(numbers.n.to_bytes(size, "big")),
        "e": b64(numbers.e.to_bytes(3, "big")),
    }


def token(claims=None, *, key=KEY, header=None, **override):
    now = int(time.time())
    body = {
        "iss": f"https://{TEAM}",
        "aud": [AUD],
        "email": EMAIL,
        "iat": now,
        "nbf": now,
        "exp": now + 600,
        "type": "app",
        **(claims or {}),
    }
    for name, value in override.items():
        if value is None:
            body.pop(name, None)
        else:
            body[name] = value
    head = {"alg": "RS256", "kid": "kid-1", "typ": "JWT", **(header or {})}
    signing = f"{b64(json.dumps(head).encode())}.{b64(json.dumps(body).encode())}"
    signature = key.sign(signing.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{signing}.{b64(signature)}"


@pytest.fixture
def certs(monkeypatch):
    state = {"calls": 0, "body": {"keys": [jwk(KEY)]}, "error": None}

    async def fake(domain):
        assert domain == TEAM
        state["calls"] += 1
        if state["error"]:
            raise state["error"]
        return state["body"]

    monkeypatch.setattr(cf_access, "fetch_certs", fake)
    return state


@pytest.fixture
def access_client(migrated, certs):
    migrated.webhook_gateway = "cloudflare"
    migrated.webhook_public_url = f"https://{HOST}"
    migrated.app_origin = f"http://testserver,https://{HOST}"
    migrated.allowed_hosts = ["testserver", HOST]
    migrated.cf_access_team_domain = TEAM
    migrated.cf_access_aud = AUD
    migrated.cf_access_emails = EMAIL
    with TestClient(create_app(migrated)) as client:
        yield client


def tunnel(jwt=None, host=HOST, **extra):
    # cloudflared 從本機連進後端；Cloudflare 邊緣加上真實來源 IP 與 Cf-Ray。
    headers = {
        "host": host,
        "cf-connecting-ip": "203.0.113.9",
        "cf-ray": "0123-TPE",
        "x-forwarded-for": "203.0.113.9",
        "x-forwarded-proto": "https",
        **extra,
    }
    if jwt is not None:
        headers["cf-access-jwt-assertion"] = jwt
    return headers


def test_valid_access_jwt_reaches_backoffice(access_client):
    assert access_client.get("/api/health", headers=tunnel(token())).status_code == 200


@pytest.mark.parametrize(
    "jwt",
    [
        None,
        "",
        "not.a.jwt",
        token(key=OTHER),
        token(header={"alg": "none"}),
        token(header={"alg": "HS256"}),
        token(header={"kid": "unknown"}),
        token(iss="https://evil.cloudflareaccess.com"),
        token(aud=["b" * 64]),
        token(aud=None),
        token(exp=int(time.time()) - 3600),
        token(exp=None),
        token(nbf=int(time.time()) + 3600),
        token(email="someone-else@example.com"),
        token(email=None, common_name="service-token-id"),
        token()[:-4] + "AAAA",
    ],
    # 權杖內含時間戳；平行測試各 worker 收集到的參數要一致，所以用固定名稱。
    ids=[
        "missing",
        "empty",
        "garbage",
        "other-key",
        "alg-none",
        "alg-hs256",
        "unknown-kid",
        "wrong-iss",
        "wrong-aud",
        "no-aud",
        "expired",
        "no-exp",
        "not-yet",
        "other-email",
        "service-token",
        "bad-signature",
    ],
)
def test_invalid_or_missing_jwt_stays_public(access_client, jwt):
    assert access_client.get("/api/health", headers=tunnel(jwt)).status_code == 404


def test_access_jwt_only_counts_for_the_backoffice_host(access_client):
    good = token()
    # ngrok 標記、別的 Host／X-Forwarded-Host、沒有 Cloudflare 邊緣標頭時都不採信 JWT。
    for headers in (
        tunnel(good, **{"x-mwb-public": "1"}),
        tunnel(good, **{"x-forwarded-host": "other.example.com"}),
        {"host": HOST, "x-forwarded-for": "203.0.113.9", "cf-access-jwt-assertion": good},
    ):
        assert access_client.get("/api/health", headers=headers).status_code == 404


def test_duplicate_jwt_headers_rejected(access_client):
    headers = [(k, v) for k, v in tunnel(token()).items()] + [("cf-access-jwt-assertion", token())]
    request = access_client.build_request("GET", "/api/health")
    request.headers = httpx.Headers(headers)
    assert access_client.send(request).status_code == 404


def test_public_paths_still_open_without_jwt(access_client):
    response = access_client.get("/webhook/mwb-gateway-probe", headers=tunnel())
    # 簽章探測沒有簽章時由後端回 401，代表路徑有放行到後端（不是被邊界擋成 404）。
    assert response.status_code == 401


def test_certs_unreachable_fails_closed(access_client, certs):
    certs["error"] = httpx.ConnectError("offline")
    assert access_client.get("/api/health", headers=tunnel(token())).status_code == 404


def test_unknown_kid_refetch_is_rate_limited(certs):
    clock = [1000.0]
    verifier = cf_access.AccessVerifier(TEAM, AUD, [EMAIL], clock=lambda: clock[0])
    stranger = token(header={"kid": "rotated"})

    async def run():
        assert await verifier.verify(token(iat=None, nbf=None, exp=10_000)) is not None
        for _ in range(5):
            assert await verifier.verify(stranger) is None
        assert certs["calls"] == 1
        # 金鑰輪替：一分鐘後才重抓，抓到新 kid 就接受。
        certs["body"] = {"keys": [jwk(KEY), jwk(KEY, "rotated")]}
        clock[0] += 61
        rotated = token(header={"kid": "rotated"}, iat=None, nbf=None, exp=10_000)
        assert await verifier.verify(rotated) is not None
        assert certs["calls"] == 2

    asyncio.run(run())


def test_failed_refresh_keeps_previous_keys(certs):
    clock = [1000.0]
    verifier = cf_access.AccessVerifier(TEAM, AUD, [EMAIL], clock=lambda: clock[0])
    good = token(iat=None, nbf=None, exp=100_000)

    async def run():
        assert await verifier.verify(good) is not None
        certs["error"] = httpx.ConnectError("offline")
        clock[0] += 4000
        assert await verifier.verify(good) is not None

    asyncio.run(run())


@pytest.mark.parametrize(
    "values",
    [
        {"cf_access_team_domain": TEAM},
        {
            "cf_access_team_domain": "evil.example.com",
            "cf_access_aud": AUD,
            "cf_access_emails": EMAIL,
        },
        {"cf_access_team_domain": TEAM, "cf_access_aud": "short", "cf_access_emails": EMAIL},
        {"cf_access_team_domain": TEAM, "cf_access_aud": AUD, "cf_access_emails": " , "},
        {
            "cf_access_team_domain": TEAM,
            "cf_access_aud": AUD,
            "cf_access_emails": EMAIL,
            "webhook_gateway": "ngrok",
        },
        {
            "cf_access_team_domain": TEAM,
            "cf_access_aud": AUD,
            "cf_access_emails": EMAIL,
            "webhook_gateway": "cloudflare",
            "app_origin": "http://127.0.0.1:8000",
        },
    ],
)
def test_incomplete_access_settings_refuse_to_start(values):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_complete_access_settings_accepted():
    settings = Settings(
        _env_file=None,
        cf_access_team_domain=TEAM,
        cf_access_aud=AUD,
        cf_access_emails=EMAIL,
        webhook_gateway="cloudflare",
        app_origin=f"http://127.0.0.1:8000,https://{HOST}",
        session_cookie_secure=True,
    )
    assert cf_access.verifier_for(settings).emails == {EMAIL}


def test_private_key_never_needed():
    # 只用公鑰驗章；測試金鑰序列化確認 jwk 是公開部分。
    assert "d" not in jwk(KEY)
    assert KEY.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )

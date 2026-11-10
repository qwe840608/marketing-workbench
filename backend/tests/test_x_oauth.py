"""X 帳號連結：全部以假 HTTP 驗證，不連平台。

X：PKCE（S256 challenge 與 verifier 對得上、verifier 加密保存且用後即清）、Basic 驗證換權杖、
refresh token 每次換新、失效要求重新連結並提醒、撤銷時清除資料。
"""

import base64
import hashlib
import json
import secrets
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from conftest import login as shared_login
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select

from app.models import Account, Brand, NotificationDelivery, OAuthState, Post, Staff
from app.models.base import utc_now
from app.services import notify, oauth, x_oauth
from app.services.passwords import hasher

X_USER = "1234567890"
X_ACCESS = "isolated-x-access"
X_REFRESH = "isolated-x-refresh"
X_SECRET = "isolated-x-secret"


@pytest.fixture
def env(client, settings, monkeypatch):
    settings.account_encryption_key = SecretStr(Fernet.generate_key().decode())
    settings.x_client_id = "isolated-x-client"
    settings.x_client_secret = SecretStr(X_SECRET)
    settings.app_origin = "http://testserver,https://office.example.test"
    factory = client.app.state.session_factory
    password = secrets.token_urlsafe(32)
    with factory.begin() as session:
        session.add(Brand(slug="xl-test", name="[測試] X"))
        session.add(
            Staff(
                username="xl-admin",
                display_name="[測試]",
                role="admin",
                password_hash=hasher.hash(password),
            )
        )
    client.headers.update(
        shared_login(client, "xl-admin", password) | {"Origin": settings.backoffice_origin}
    )
    calls = []
    options = {
        "x_invalid": False,
        "x_scope": " ".join(x_oauth.SCOPES),
        "rotated": 0,
        "challenge": None,
        "revoke_status": 200,
    }
    original = httpx.Client

    def x_handler(request):
        assert request.url.host == "api.x.com"
        calls.append(("x", request.url.path, request.content.decode(), dict(request.headers)))
        if request.url.path == "/2/oauth2/token":
            data = parse_qs(request.content.decode())
            # 密鑰只在 Basic 標頭，不在表單內容。
            expected = base64.b64encode(f"isolated-x-client:{X_SECRET}".encode()).decode()
            assert request.headers["authorization"] == "Basic " + expected
            assert "client_secret" not in data
            if options["x_invalid"]:
                return httpx.Response(400, json={"error": "invalid_request"})
            if data["grant_type"] == ["authorization_code"]:
                verifier = data["code_verifier"][0]
                digest = hashlib.sha256(verifier.encode()).digest()
                challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
                assert challenge == options["challenge"]
                assert data["redirect_uri"] == [oauth.origin_info(settings)["callbacks"]["x"]]
                refresh = X_REFRESH
            else:
                options["rotated"] += 1
                refresh = X_REFRESH + "-rotated-" + str(options["rotated"])
            return httpx.Response(
                200,
                json={
                    "access_token": X_ACCESS,
                    "expires_in": 7200,
                    "refresh_token": refresh,
                    "scope": options["x_scope"],
                    "token_type": "bearer",
                },
            )
        if request.url.path == "/2/oauth2/revoke":
            return httpx.Response(options["revoke_status"], json={"revoked": True})
        assert request.url.path == "/2/users/me"
        assert request.headers["authorization"] == "Bearer " + X_ACCESS
        return httpx.Response(
            200, json={"data": {"id": X_USER, "name": "[測試] X", "username": "isolated_x"}}
        )

    for module, handler in ((x_oauth, x_handler),):
        monkeypatch.setattr(
            module,
            "httpx",
            SimpleNamespace(
                Client=lambda handler=handler, **kwargs: original(
                    transport=httpx.MockTransport(handler), **kwargs
                ),
                TimeoutException=httpx.TimeoutException,
            ),
        )
    return SimpleNamespace(
        client=client, settings=settings, factory=factory, calls=calls, options=options
    )


def begin(env, platform):
    response = env.client.post(f"/api/oauth/{platform}/start", json={})
    assert response.status_code == 200, response.text
    url = urlsplit(response.json()["url"])
    args = parse_qs(url.query)
    assert args["redirect_uri"] == [f"https://office.example.test/api/oauth/{platform}/callback"]
    assert args["response_type"] == ["code"]
    assert platform == "x"
    if platform == "x":
        assert f"{url.scheme}://{url.netloc}{url.path}" == x_oauth.AUTHORIZE_URL
        assert args["client_id"] == ["isolated-x-client"]
        assert args["scope"] == [" ".join(x_oauth.SCOPES)]
        assert args["code_challenge_method"] == ["S256"]
        env.options["challenge"] = args["code_challenge"][0]
        with env.factory() as session:
            row = session.scalars(select(OAuthState)).all()[-1]
            # verifier 加密保存，不以明文出現在資料庫。
            assert row.encrypted_verifier and len(row.encrypted_verifier) > 100
    return args["state"][0]


def link(env, platform):
    state = begin(env, platform)
    cookies = dict(env.client.cookies)
    env.client.cookies.clear()
    try:
        response = env.client.get(
            f"/api/oauth/{platform}/callback",
            params={"state": state, "code": "isolated-code"},
            follow_redirects=False,
        )
    finally:
        env.client.cookies.update(cookies)
    assert response.status_code == 303
    assert f"oauth_pending={platform}" in response.headers["location"]
    return env.client.post(f"/api/oauth/{platform}/complete", json={})


def status(env, platform, force=False):
    return env.client.get("/api/oauth/status" + ("?force=true" if force else "")).json()[
        "platforms"
    ][platform]


def rows(env, model):
    with env.factory() as session:
        return list(session.scalars(select(model)))


def test_x_link_uses_pkce_and_stores_encrypted_tokens(env):
    assert status(env, "x")["state"] == "neutral"
    done = link(env, "x")
    assert done.json()["result"] == "linked", done.text
    item = status(env, "x")
    assert item["linked"] and item["state"] == "ready" and item["name"] == "@isolated_x"
    # refresh token 沒有公布的期限：不顯示到期日。
    assert item["expires_at"] is None
    assert all(not r.encrypted_verifier for r in rows(env, OAuthState))
    with env.factory() as session:
        account = session.scalar(select(Account).where(Account.platform == "x"))
        assert (account.external_id, account.status) == (X_USER, "connected")
    raw = env.settings.database_path.read_bytes()
    for value in (X_ACCESS, X_REFRESH, X_SECRET):
        assert value.encode() not in raw
    assert X_ACCESS not in env.client.get("/api/credentials").text
    ready = oauth.publish_readiness(env.factory(), env.settings, cached=True)["x"]
    assert ready == {"ready": True, "reasons": []}


def test_x_missing_offline_access_fails(env):
    env.options["x_scope"] = "tweet.read tweet.write users.read"
    assert link(env, "x").json()["result"] == "failed"
    assert not status(env, "x")["linked"]


def test_x_refresh_rotates_and_invalid_refresh_requires_reconnect(env, monkeypatch):
    link(env, "x")
    assert x_oauth.access_token(env.factory, env.settings) == X_ACCESS
    with env.factory.begin() as session:
        oauth.connection(session, "x").cache_json = {"access_expires_at": "2000-01-01"}
    x_oauth.access_token(env.factory, env.settings)
    assert parse_qs(env.calls[-1][2])["refresh_token"] == [X_REFRESH]
    with env.factory.begin() as session:
        oauth.connection(session, "x").cache_json = {"access_expires_at": "2000-01-01"}
        assert oauth.value(session, env.settings, "X_REFRESH_TOKEN") == X_REFRESH + "-rotated-1"
    monkeypatch.setattr(
        notify,
        "load_policy",
        lambda session, brand_id: (
            SimpleNamespace(enabled=True, group_id="isolated-group"),
            None,
            None,
        ),
    )
    env.options["x_invalid"] = True
    with pytest.raises(oauth.ProviderFailure):
        x_oauth.access_token(env.factory, env.settings)
    assert status(env, "x")["state"] == "failed"
    ready = oauth.publish_readiness(env.factory(), env.settings, cached=True)["x"]
    assert not ready["ready"]
    oauth.maintain(env.factory, env.settings)
    oauth.maintain(env.factory, env.settings)
    texts = [d.messages_json for d in rows(env, NotificationDelivery)]
    assert texts == [[{"type": "text", "text": notify.OAUTH_NOTICES["x"]}]]


def test_x_disconnect_revokes_and_deletes_data(env):
    link(env, "x")
    with env.factory.begin() as session:
        account = session.scalar(select(Account).where(Account.platform == "x"))
        session.add(
            Post(
                account_id=account.id,
                external_id="x-post",
                caption="說明",
                media_type="TEXT",
                published_at=utc_now(),
            )
        )
    env.options["revoke_status"] = 500
    assert env.client.post("/api/oauth/x/disconnect", json={}).status_code == 422
    env.options["revoke_status"] = 200
    response = env.client.post("/api/oauth/x/disconnect", json={})
    assert response.status_code == 200 and response.json()["removed"]["posts"] == 1
    revoke = [c for c in env.calls if c[1] == "/2/oauth2/revoke"][-1]
    assert parse_qs(revoke[2])["token"] == [X_REFRESH]
    assert not status(env, "x")["linked"]


def test_permissions_and_csrf(env):
    bad = {"X-CSRF-Token": "bad"}
    for platform in ("x",):
        assert (
            env.client.post(f"/api/oauth/{platform}/start", json={}, headers=bad).status_code == 403
        )
        assert (
            env.client.post(f"/api/oauth/{platform}/disconnect", json={}, headers=bad).status_code
            == 403
        )
    with env.factory.begin() as session:
        session.scalar(select(Staff).where(Staff.username == "xl-admin")).role = "viewer"
    for platform in ("x",):
        assert env.client.post(f"/api/oauth/{platform}/start", json={}).status_code == 403
        assert env.client.post(f"/api/oauth/{platform}/disconnect", json={}).status_code == 403


def test_secrets_never_reach_audit(env):
    link(env, "x")
    from app.models import AuditLog

    serial = json.dumps([a.detail_json for a in rows(env, AuditLog)])
    for value in (X_ACCESS, X_REFRESH, "isolated-code"):
        assert value not in serial

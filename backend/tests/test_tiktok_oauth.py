"""TikTok 帳號連結：全部以假 HTTP 驗證，不連 TikTok。

授權網址參數、兩段式導回、換權杖與身分核對、權杖自動續期（含換新 refresh token）、
失效後要求重新連結、到期前 LINE 提醒、中斷連結撤銷並刪除資料、權限與 CSRF。
"""

import json
import secrets
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from conftest import login as shared_login
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select

from app.models import (
    Account,
    AuditLog,
    Brand,
    NotificationDelivery,
    PlatformCredential,
    Post,
    Staff,
)
from app.models.base import utc_now
from app.services import notify, oauth, tiktok_oauth
from app.services.passwords import hasher

OPEN_ID = "isolated-open-id"
ACCESS = "isolated-tiktok-access"
REFRESH = "isolated-tiktok-refresh"
SECRET = "isolated-tiktok-secret"


@pytest.fixture
def tt(client, settings, monkeypatch):
    settings.account_encryption_key = SecretStr(Fernet.generate_key().decode())
    settings.tiktok_client_key = SecretStr("isolated-client-key")
    settings.tiktok_client_secret = SecretStr(SECRET)
    settings.app_origin = "http://testserver,https://office.example.test"
    factory = client.app.state.session_factory
    password = secrets.token_urlsafe(32)
    with factory.begin() as session:
        session.add(Brand(slug="tt-test", name="[測試] TikTok"))
        session.add(Staff(username="tt-admin", display_name="[測試]", role="admin",
                          password_hash=hasher.hash(password)))
    client.headers.update(
        shared_login(client, "tt-admin", password) | {"Origin": settings.backoffice_origin}
    )
    calls = []
    options = {"invalid": False, "scope": ",".join(tiktok_oauth.SCOPES), "rotated": 0,
               "open_id": OPEN_ID, "revoke_status": 200}
    original = httpx.Client

    def handler(request):
        assert request.url.host == "open.tiktokapis.com"
        calls.append((request.url.path, request.method, request.content.decode()))
        if request.url.path == "/v2/oauth/token/":
            data = parse_qs(request.content.decode())
            assert data["client_key"] == ["isolated-client-key"]
            assert data["client_secret"] == [SECRET]
            if options["invalid"]:
                return httpx.Response(400, json={"error": "invalid_grant"})
            if data["grant_type"] == ["authorization_code"]:
                assert data["redirect_uri"] == [oauth.origin_info(settings)["callbacks"]["tiktok"]]
                refresh = REFRESH
            else:
                options["rotated"] += 1
                refresh = REFRESH + "-rotated-" + str(options["rotated"])
            return httpx.Response(200, json={
                "access_token": ACCESS, "expires_in": 86400, "open_id": options["open_id"],
                "refresh_token": refresh,
                "refresh_expires_in": options.get("refresh_expires_in", 31536000),
                "scope": options["scope"], "token_type": "Bearer",
            })
        if request.url.path == "/v2/oauth/revoke/":
            if options["revoke_status"] != 200:
                return httpx.Response(options["revoke_status"], json={"error": "server_error"})
            return httpx.Response(200, json={})
        assert request.url.path == "/v2/user/info/"
        assert request.headers["authorization"] == "Bearer " + ACCESS
        return httpx.Response(200, json={
            "data": {"user": {"open_id": OPEN_ID, "display_name": "[測試] TikTok 帳號"}},
            "error": {"code": "ok", "message": "", "log_id": "x"},
        })

    monkeypatch.setattr(tiktok_oauth, "httpx", SimpleNamespace(
        Client=lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    ))
    return SimpleNamespace(client=client, settings=settings, factory=factory,
                           calls=calls, options=options)


def begin(tt):
    response = tt.client.post("/api/oauth/tiktok/start", json={})
    assert response.status_code == 200, response.text
    url = urlsplit(response.json()["url"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == tiktok_oauth.AUTHORIZE_URL
    args = parse_qs(url.query)
    assert args["client_key"] == ["isolated-client-key"] and "client_id" not in args
    assert args["scope"] == ["user.info.basic,user.info.stats,video.list,video.upload"]
    # 第一版不送審、不直接發佈：不要求 video.publish。
    assert "video.publish" not in args["scope"][0]
    assert args["redirect_uri"] == ["https://office.example.test/api/oauth/tiktok/callback"]
    assert args["response_type"] == ["code"]
    return args["state"][0]


def receive(tt, state, **params):
    cookies = dict(tt.client.cookies)
    tt.client.cookies.clear()
    try:
        response = tt.client.get("/api/oauth/tiktok/callback",
                                 params={"state": state, "code": "isolated-code", **params},
                                 follow_redirects=False)
        assert response.status_code == 303
        return response
    finally:
        tt.client.cookies.update(cookies)


def link(tt):
    response = receive(tt, begin(tt))
    assert "oauth_pending=tiktok" in response.headers["location"]
    return tt.client.post("/api/oauth/tiktok/complete", json={})


def tiktok_status(tt, force=False):
    return tt.client.get("/api/oauth/status" + ("?force=true" if force else "")).json()[
        "platforms"]["tiktok"]


def test_link_stores_encrypted_tokens_and_registers_account(tt):
    assert tiktok_status(tt)["state"] == "neutral"
    done = link(tt)
    assert done.status_code == 200 and done.json()["result"] == "linked", done.text
    status = tiktok_status(tt)
    assert status["linked"] and status["state"] == "ready" and status["missing"] == []
    assert status["name"] == "[測試] TikTok 帳號"
    # 使用者看到的到期日是 refresh token 的一年期限，不是 24 小時的 access token。
    assert status["expires_at"] > (utc_now() + timedelta(days=360)).isoformat()
    with tt.factory() as session:
        account = session.scalar(select(Account).where(Account.platform == "tiktok"))
        assert (account.external_id, account.status) == (OPEN_ID, "connected")
        stored = {r.provider: r.encrypted_key for r in session.scalars(select(PlatformCredential))}
    for name in tiktok_oauth.SECRETS:
        assert stored[name] and stored[name] not in (ACCESS, REFRESH, OPEN_ID)
    raw = tt.settings.database_path.read_bytes()
    for value in (ACCESS, REFRESH, SECRET, "isolated-code"):
        assert value.encode() not in raw
    serial = json.dumps([a.detail_json for a in session_rows(tt, AuditLog)])
    serial += tt.client.get("/api/credentials").text
    assert ACCESS not in serial and REFRESH not in serial
    assert tiktok_status(tt, force=True)["verified"] is True


def session_rows(tt, model):
    with tt.factory() as session:
        return list(session.scalars(select(model)))


def test_scopes_match_and_missing_read_scope_fails(tt):
    assert oauth.SCOPES["tiktok"] == tiktok_oauth.SCOPES
    tt.options["scope"] = "user.info.basic"
    assert link(tt).json()["result"] == "failed"
    assert not tiktok_status(tt)["linked"]


def test_denied_and_replayed_state_are_rejected(tt):
    state = begin(tt)
    receive(tt, state, error="access_denied")
    assert tt.client.post("/api/oauth/tiktok/complete", json={}).json()["result"] == "cancelled"
    assert "oauth_result=failed" in receive(tt, state).headers["location"]
    assert "oauth_result=failed" in receive(tt, "wrong").headers["location"]
    assert not any(path == "/v2/oauth/token/" for path, *_ in tt.calls)


def test_access_token_refreshes_and_keeps_the_rotated_refresh_token(tt):
    link(tt)
    assert tiktok_oauth.access_token(tt.factory, tt.settings) == ACCESS
    token_calls = [c for c in tt.calls if c[0] == "/v2/oauth/token/"]
    assert len(token_calls) == 1  # 還沒過期不換發。
    with tt.factory.begin() as session:
        row = oauth.connection(session, "tiktok")
        row.cache_json = {"access_expires_at": (utc_now() - timedelta(seconds=1)).isoformat()}
    assert tiktok_oauth.access_token(tt.factory, tt.settings) == ACCESS
    assert parse_qs(tt.calls[-1][2])["refresh_token"] == [REFRESH]
    with tt.factory.begin() as session:
        oauth.connection(session, "tiktok").cache_json = {"access_expires_at": "2000-01-01"}
    tiktok_oauth.access_token(tt.factory, tt.settings)
    # 第二次換發必須用上一次 TikTok 給的新 refresh token。
    assert parse_qs(tt.calls[-1][2])["refresh_token"] == [REFRESH + "-rotated-1"]
    assert tiktok_status(tt)["state"] == "ready"


def test_concurrent_refresh_reuses_winner_token_but_real_change_still_fails(tt, monkeypatch):
    link(tt)
    original = tiktok_oauth.request

    def expire():
        with tt.factory.begin() as session:
            oauth.connection(session, "tiktok").cache_json = {"access_expires_at": "2000-01-01"}

    def racing(url, **kwargs):
        # 另一個工作在這次 HTTP 進行中先換發並存檔，摘要因此改變。
        monkeypatch.setattr(tiktok_oauth, "request", original)
        tiktok_oauth.access_token(tt.factory, tt.settings)
        return original(url, **kwargs)

    expire()
    monkeypatch.setattr(tiktok_oauth, "request", racing)
    assert tiktok_oauth.access_token(tt.factory, tt.settings) == ACCESS
    with tt.factory() as session:
        # 後完成的一方不覆蓋先完成者存的 refresh token。
        assert oauth.value(session, tt.settings, "TIKTOK_REFRESH_TOKEN") == REFRESH + "-rotated-1"

    def relinked(url, **kwargs):
        with tt.factory.begin() as session:
            oauth.put_secret(session, tt.settings, "TIKTOK_OPEN_ID", "isolated-other-open-id")
        return original(url, **kwargs)

    expire()
    monkeypatch.setattr(tiktok_oauth, "request", relinked)
    with pytest.raises(oauth.ProviderFailure) as error:
        tiktok_oauth.access_token(tt.factory, tt.settings)
    assert error.value.info["stage"] == "credentials_changed"


def test_invalid_refresh_requires_reconnect_and_notifies_once(tt, monkeypatch):
    link(tt)
    monkeypatch.setattr(notify, "load_policy", lambda session, brand_id: (
        SimpleNamespace(enabled=True, group_id="isolated-group"), None, None))
    with tt.factory.begin() as session:
        oauth.connection(session, "tiktok").cache_json = {"access_expires_at": "2000-01-01"}
    tt.options["invalid"] = True
    with pytest.raises(oauth.ProviderFailure):
        tiktok_oauth.access_token(tt.factory, tt.settings)
    assert tiktok_status(tt)["state"] == "failed"
    count = len(tt.calls)
    with pytest.raises(oauth.ProviderFailure):
        tiktok_oauth.access_token(tt.factory, tt.settings)
    assert len(tt.calls) == count  # 已知失效就不再打 TikTok。
    oauth.maintain(tt.factory, tt.settings)
    oauth.maintain(tt.factory, tt.settings)
    texts = [d.messages_json for d in session_rows(tt, NotificationDelivery)]
    assert texts == [[{"type": "text", "text": notify.OAUTH_NOTICES["tiktok"]}]]


def test_expiring_refresh_token_is_pending_and_reminded(tt, monkeypatch):
    link(tt)
    monkeypatch.setattr(notify, "load_policy", lambda session, brand_id: (
        SimpleNamespace(enabled=True, group_id="isolated-group"), None, None))
    monkeypatch.setattr(tiktok_oauth, "access_token", lambda factory, settings: ACCESS)
    with tt.factory.begin() as session:
        oauth.connection(session, "tiktok").expires_at = utc_now() + timedelta(days=10)
    assert tiktok_status(tt)["state"] == "pending"
    oauth.maintain(tt.factory, tt.settings)
    assert len(session_rows(tt, NotificationDelivery)) == 1


def test_expiring_reminder_is_sent_once_despite_daily_refresh(tt, monkeypatch):
    link(tt)
    monkeypatch.setattr(notify, "load_policy", lambda session, brand_id: (
        SimpleNamespace(enabled=True, group_id="isolated-group"), None, None))
    tt.options["refresh_expires_in"] = 10 * 86400

    def next_day():
        # access token 每天到期，維護時就會換發一次。
        with tt.factory.begin() as session:
            oauth.connection(session, "tiktok").cache_json = {"access_expires_at": "2000-01-01"}
        tiktok_oauth.maintain(tt.factory, tt.settings)

    for _ in range(3):
        next_day()
    assert len(session_rows(tt, NotificationDelivery)) == 1
    # 重新取得完整效期的 refresh token 後，下次快到期時會再提醒。
    tt.options["refresh_expires_in"] = 31536000
    next_day()
    with tt.factory() as session:
        assert oauth.connection(session, "tiktok").notified_at is None


def test_disconnect_revokes_and_deletes_tiktok_data(tt):
    link(tt)
    with tt.factory.begin() as session:
        account = session.scalar(select(Account).where(Account.platform == "tiktok"))
        session.add(Post(account_id=account.id, external_id="tt-video", caption="說明",
                         media_type="VIDEO", published_at=utc_now()))
    tt.options["revoke_status"] = 500
    assert tt.client.post("/api/oauth/tiktok/disconnect", json={}).status_code == 422
    assert tiktok_status(tt)["linked"]
    tt.options["revoke_status"] = 200
    response = tt.client.post("/api/oauth/tiktok/disconnect", json={})
    assert response.status_code == 200 and response.json()["removed"]["posts"] == 1
    revoke = [c for c in tt.calls if c[0] == "/v2/oauth/revoke/"][-1]
    assert parse_qs(revoke[2])["token"] == [ACCESS]
    assert not tiktok_status(tt)["linked"]
    with tt.factory() as session:
        account = session.scalar(select(Account).where(Account.platform == "tiktok"))
        assert (account.name, account.status) == ("TikTok", "disconnected")
        assert not session.scalars(select(Post).where(Post.account_id == account.id)).all()


def test_permissions_and_csrf(tt):
    bad = {"X-CSRF-Token": "bad"}
    assert tt.client.post("/api/oauth/tiktok/start", json={}, headers=bad).status_code == 403
    assert tt.client.post("/api/oauth/tiktok/disconnect", json={}, headers=bad).status_code == 403
    with tt.factory.begin() as session:
        session.scalar(select(Staff).where(Staff.username == "tt-admin")).role = "viewer"
    assert tt.client.post("/api/oauth/tiktok/start", json={}).status_code == 403
    assert tt.client.post("/api/oauth/tiktok/disconnect", json={}).status_code == 403

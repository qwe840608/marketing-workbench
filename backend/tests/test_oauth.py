"""Synthetic credentials and HTTP responses; never contacts a provider."""

import json
import time
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from test_ai_settings_batch3 import keys as keys  # noqa: F401
from test_classify import classified_data as classified_data  # noqa: F401

from app.models import AuditLog, NotificationDelivery, OAuthState, Setting, Staff
from app.models.base import utc_now
from app.services import auth, credentials, notify, oauth

PRIVATE = [
    "private-oauth-code",
    "private-app-secret",
    "private-short-token",
    "private-long-token",
    "private-page-token",
    "private-refreshed-token",
]


@pytest.fixture
def linked_setup(client, keys, settings, monkeypatch):
    settings.app_origin = "http://testserver,https://office.example.test"
    settings.meta_app_id = settings.threads_app_id = "12345"
    settings.meta_app_secret = settings.threads_app_secret = SecretStr(PRIVATE[1])
    client.headers["Origin"] = settings.backoffice_origin
    calls = []
    options = {
        "pages": 1,
        "ig": True,
        "missing": [],
        "fail": None,
        "scope": True,
        "debug": False,
        # Facebook 長期權杖：int＝附 expires_in；never／dated＝不附，由 debug_token 回報。
        "meta_expiry": "int",
        # 模擬商家資產組合授權：/me/accounts 為空，粉專只出現在 debug_token 的 granular_scopes。
        "granular": False,
    }
    original = httpx.Client

    def handler(request):
        calls.append((request.method, request.url.path))
        path = request.url.path
        if options["fail"] and options["fail"] in path:
            return httpx.Response(400, json={"error": {"message": " ".join(PRIVATE)}})
        if path.endswith("/oauth/access_token"):
            exchange = b"fb_exchange_token" in request.content
            body = {
                "access_token": PRIVATE[3] if exchange else PRIVATE[2],
                "expires_in": 60 * 86400,
            }
            if exchange and options["meta_expiry"] != "int":
                del body["expires_in"]
            if options["scope"]:
                body["scope"] = ",".join(oauth.THREADS_SCOPES)
        elif path == "/access_token":
            body = {"access_token": PRIVATE[3], "expires_in": 60 * 86400}
        elif path == "/refresh_access_token":
            assert request.url.params["grant_type"] == "th_refresh_token"
            body = {"access_token": PRIVATE[5], "expires_in": 60 * 86400}
        elif path.endswith("/debug_token") and path != "/debug_token":
            assert request.url.params["access_token"] == "12345|" + PRIVATE[1]
            expiry = 0 if options["meta_expiry"] == "never" else int(time.time()) + 30 * 86400
            body = {"data": {"is_valid": True, "expires_at": expiry}}
            if options["granular"]:
                body["data"]["granular_scopes"] = [
                    {"scope": "pages_show_list", "target_ids": ["100"]},
                    {"scope": "pages_manage_posts", "target_ids": ["100", "bad-id"]},
                    {"scope": "instagram_basic", "target_ids": ["200"]},
                ]
        elif path == "/debug_token":
            body = (
                {"data": {"is_valid": True, "scopes": list(oauth.THREADS_SCOPES)}}
                if options["debug"]
                else {}
            )
        elif path.endswith("/me/accounts"):
            body = {
                "data": []
                if options["granular"]
                else [
                    {"id": str(100 + i), "name": f"隔離粉專 {i}", "access_token": PRIVATE[4]}
                    for i in range(options["pages"])
                ]
            }
        elif request.url.params.get("fields") == "id,name,access_token":
            body = {"id": path.rsplit("/", 1)[1], "name": "隔離粉專 0", "access_token": PRIVATE[4]}
        elif path.endswith("/me/permissions"):
            body = {
                "data": [
                    {
                        "permission": s,
                        "status": "declined" if s in options["missing"] else "granted",
                    }
                    for s in oauth.META_SCOPES
                ]
            }
        elif path.endswith("/me"):
            body = {"id": "300", "username": "isolated_threads"}
        else:
            body = (
                {"instagram_business_account": {"id": "200", "username": "isolated_ig"}}
                if options["ig"]
                else {}
            )
        return httpx.Response(200, json=body)

    def fake_client(**kwargs):
        assert kwargs == {"timeout": 15, "follow_redirects": False, "trust_env": False}
        return original(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(oauth.httpx, "Client", fake_client)
    return options, calls


def begin(client, platform="meta"):
    response = client.post(f"/api/oauth/{platform}/start", json={})
    assert response.status_code == 200, response.text
    url = urlsplit(response.json()["url"])
    args = parse_qs(url.query)
    assert args["response_type"] == ["code"]
    assert args["redirect_uri"] == [f"https://office.example.test/api/oauth/{platform}/callback"]
    assert set(args["scope"][0].split(",")) == set(oauth.SCOPES[platform])
    assert url.hostname == ("www.facebook.com" if platform == "meta" else "threads.net")
    return args["state"][0]


def finish(client, state, platform="meta", **extra):
    """模擬真實導回：第一段不帶登入 cookie（SameSite=Strict 跨站導回），第二段由原 session 完成。"""
    saved = dict(client.cookies)
    client.cookies.clear()
    try:
        landing = client.get(
            f"/api/oauth/{platform}/callback",
            params={"state": state, "code": PRIVATE[0], **extra},
            follow_redirects=False,
        )
    finally:
        client.cookies.update(saved)
    assert landing.status_code == 303
    location = landing.headers["location"]
    if f"oauth_pending={platform}" not in location:
        assert "oauth_result=failed" in location
        return SimpleNamespace(status_code=400, headers=dict(landing.headers), text=landing.text)
    done = client.post(f"/api/oauth/{platform}/complete", json={})
    if done.status_code != 200:
        return done
    target = location.replace(f"oauth_pending={platform}", "oauth_result=" + done.json()["result"])
    return SimpleNamespace(status_code=303, headers={"location": target}, text=done.text)


def no_secrets(client, settings, responses):
    with client.app.state.session_factory() as session:
        serialized = json.dumps([r.detail_json for r in session.scalars(select(AuditLog))])
    serialized += "".join(r.text + json.dumps(dict(r.headers)) for r in responses)
    serialized += settings.log_path.read_text(encoding="utf-8")
    for secret in PRIVATE:
        assert secret not in serialized
        assert secret.encode() not in settings.database_path.read_bytes()


@pytest.mark.parametrize("case", ["missing", "expired", "replay", "session", "staff", "platform"])
def test_state_rejection(client, keys, settings, linked_setup, case):
    state = begin(client)
    if case == "replay":
        assert finish(client, state).status_code == 303
    with client.app.state.session_factory.begin() as session:
        row = session.scalar(select(OAuthState))
        if case == "expired":
            row.expires_at = utc_now() - timedelta(seconds=1)
        elif case == "session":
            row.session_hash = "other-session"
        elif case == "staff":
            row.staff_id += 1
        elif case == "platform":
            row.platform = "threads"
    calls_before = len(linked_setup[1])
    response = finish(client, "invalid" if case == "missing" else state)
    assert response.status_code == 400
    assert len(linked_setup[1]) == calls_before
    with client.app.state.session_factory() as session:
        assert session.scalar(select(AuditLog).where(AuditLog.action == "oauth.state_rejected"))
    no_secrets(client, settings, [response])


@pytest.mark.parametrize("pages,ig", [(1, True), (1, False), (2, True), (0, False)])
def test_meta_flow(client, keys, settings, linked_setup, pages, ig):
    linked_setup[0].update(pages=pages, ig=ig)
    response = finish(client, begin(client))
    assert response.status_code == 303
    status = client.get("/api/oauth/status")
    if pages > 1:
        assert len(status.json()["pages"]) == 2
        assert not status.json()["platforms"]["meta"]["linked"]
        assert client.post("/api/oauth/meta/page", json={"page_id": "999"}).status_code == 400
        chosen = client.post("/api/oauth/meta/page", json={"page_id": "101"})
        assert chosen.status_code == 200
        assert client.post("/api/oauth/meta/page", json={"page_id": "101"}).status_code == 400
        status = client.get("/api/oauth/status")
        assert not status.json()["pages"]
    if pages:
        item = status.json()["platforms"]["meta"]
        assert item["state"] == "ready" and item["ig_linked"] == ig
        with client.app.state.session_factory() as session:
            readiness = oauth.publish_readiness(session, settings)
            assert readiness["facebook"]["ready"]
            assert readiness["instagram"]["ready"] == ig
            assert not readiness["threads"]["ready"]
            assert (
                credentials.raw(credentials.resolve("META_PAGE_ACCESS_TOKEN", settings, session))
                == PRIVATE[4]
            )
    else:
        assert "no_pages" in response.headers["location"]
        assert not status.json()["platforms"]["meta"]["linked"]
    no_secrets(client, settings, [response, status])


def test_permissions_cache_refresh_and_readiness(client, keys, settings, linked_setup):
    finish(client, begin(client))
    first = client.get("/api/oauth/status")
    count = len(linked_setup[1])
    assert client.get("/api/oauth/status").json() == first.json()
    assert len(linked_setup[1]) == count
    linked_setup[0]["missing"] = ["pages_manage_posts"]
    refreshed = client.get("/api/oauth/status?force=true")
    assert refreshed.json()["platforms"]["meta"]["missing"] == ["pages_manage_posts"]
    with client.app.state.session_factory() as session:
        readiness = oauth.publish_readiness(session, settings)
        assert not readiness["facebook"]["ready"] and readiness["instagram"]["ready"]
    with client.app.state.session_factory.begin() as session:
        row = oauth.connection(session, "meta")
        row.expires_at = utc_now() + timedelta(days=6)
    with client.app.state.session_factory() as session:
        assert "授權即將到期" in oauth.publish_readiness(session, settings)["instagram"]["reasons"]
    with client.app.state.session_factory.begin() as session:
        oauth.connection(session, "meta").expires_at = utc_now() - timedelta(seconds=1)
    assert client.get("/api/oauth/status").json()["platforms"]["meta"]["state"] == "failed"
    no_secrets(client, settings, [first, refreshed])


@pytest.mark.parametrize("platform", ["meta", "threads"])
def test_relinking_keeps_publish_readiness_without_a_status_check(
    client, keys, settings, linked_setup, platform
):
    # 2026-10-17：重新連結後直接去發佈頁，快取被清空，FB／IG 全顯示缺少權限與權限檢查失敗。
    finish(client, begin(client, platform), platform)
    with client.app.state.session_factory() as session:
        readiness = oauth.publish_readiness(session, settings, cached=True)
    publishing = ["facebook", "instagram"] if platform == "meta" else ["threads"]
    for name in publishing:
        assert readiness[name] == {**readiness[name], "ready": True, "reasons": []}, name
    # 快取是新的：接著看設定頁也不必再打一次平台。
    count = len(linked_setup[1])
    client.get("/api/oauth/status")
    assert len(linked_setup[1]) == count


@pytest.mark.parametrize("fail", ["oauth/access_token", "me/accounts", "me/permissions"])
def test_provider_failure_consumes_state(client, keys, settings, linked_setup, fail):
    state = begin(client)
    linked_setup[0]["fail"] = fail
    response = finish(client, state)
    assert response.status_code == 303 and "failed" in response.headers["location"]
    assert finish(client, state).status_code == 400
    no_secrets(client, settings, [response])


def test_cancel_origin_roles_csrf_public_boundary(client, keys, settings, linked_setup):
    assert (
        client.post("/api/oauth/meta/start", headers={"Origin": "http://testserver"}).status_code
        == 400
    )
    assert (
        client.post("/api/oauth/meta/start", headers={"X-CSRF-Token": "invalid"}).status_code == 403
    )
    state = begin(client)
    before = len(linked_setup[1])
    response = finish(client, state, error="raw-provider-private-error")
    assert "cancelled" in response.headers["location"] and len(linked_setup[1]) == before
    assert client.get("/api/oauth/meta/callback", headers={"X-MWB-Public": "1"}).status_code == 404
    for role in ["viewer", "marketing"]:
        with client.app.state.session_factory.begin() as session:
            session.get(Staff, keys["staff_id"]).role = role
        for method, path in [
            ("GET", "/api/oauth/status"),
            ("POST", "/api/oauth/meta/complete"),
            ("POST", "/api/oauth/meta/start"),
            ("POST", "/api/oauth/meta/page"),
        ]:
            assert client.request(method, path, json={"page_id": "100"}).status_code == 403


@pytest.mark.parametrize("scope", [True, False])
def test_threads_flow(client, keys, settings, linked_setup, scope):
    linked_setup[0]["scope"] = scope
    response = finish(client, begin(client, "threads"), "threads")
    assert response.status_code == 303
    status = client.get("/api/oauth/status")
    item = status.json()["platforms"]["threads"]
    assert item["name"] == "isolated_threads"
    assert item["state"] == ("ready" if scope else "failed")
    with client.app.state.session_factory() as session:
        assert oauth.publish_readiness(session, settings)["threads"]["ready"] == scope
    no_secrets(client, settings, [response, status])


def test_threads_standard_response_debugger_and_force_failure(client, keys, settings, linked_setup):
    linked_setup[0].update(scope=False, debug=True)
    finish(client, begin(client, "threads"), "threads")
    assert client.get("/api/oauth/status").json()["platforms"]["threads"]["state"] == "ready"
    linked_setup[0]["fail"] = "/me"
    status = client.get("/api/oauth/status?force=true")
    assert status.json()["platforms"]["threads"]["state"] == "failed"
    assert not status.json()["platforms"]["threads"]["verified"]
    no_secrets(client, settings, [status])


def test_distinct_active_session_cannot_use_state(client, keys, settings, linked_setup):
    state = begin(client)
    original = client.cookies.get(auth.COOKIE_NAME)
    with client.app.state.session_factory.begin() as session:
        alternate = auth.issue_session(session, settings, keys["staff_id"])
    original_csrf = client.headers.get("X-CSRF-Token")
    client.cookies.set(auth.COOKIE_NAME, alternate.token, domain="testserver.local", path="/")
    client.headers["X-CSRF-Token"] = alternate.csrf_token
    assert finish(client, state).status_code == 400
    # 同一個 state 不能再被導回第二次；暫存的 code 只交給發起授權的原 session。
    assert finish(client, state).status_code == 400
    client.cookies.set(auth.COOKIE_NAME, original, domain="testserver.local", path="/")
    client.headers["X-CSRF-Token"] = original_csrf
    done = client.post("/api/oauth/meta/complete", json={})
    assert done.status_code == 200 and done.json()["result"] == "linked"


@pytest.mark.parametrize(
    "platform,age,days,fail,expected",
    [
        ("threads", 48, 6, False, "refresh"),
        ("threads", 23, 6, False, "skip"),
        ("threads", 48, 8, False, "skip"),
        ("threads", 48, 6, True, "notice"),
        ("meta", 48, 6, False, "notice"),
    ],
)
def test_daily_maintenance(
    client, keys, settings, linked_setup, platform, age, days, fail, expected
):
    finish(client, begin(client, platform), platform)
    factory = client.app.state.session_factory
    now = utc_now()
    with factory.begin() as session:
        row = oauth.connection(session, platform)
        row.expires_at, row.refreshed_at = now + timedelta(days=days), now - timedelta(hours=age)
        session.add(
            Setting(
                key=notify.policy_key(keys["brand_id"]),
                value_json={"enabled": True, "group_id": "C" + "a" * 32},
            )
        )
    linked_setup[0]["fail"] = "refresh_access_token" if fail else None
    calls = len(linked_setup[1])
    oauth.maintain(factory, settings, now)
    with factory() as session:
        row = oauth.connection(session, platform)
        notices = list(session.scalars(select(NotificationDelivery)))
        assert bool(notices) == (expected == "notice")
        if notices:
            assert notices[0].messages_json == [
                {"type": "text", "text": notify.OAUTH_NOTICES[platform]}
            ]
        if expected == "refresh":
            assert row.expires_at > now + timedelta(days=59)
            assert (
                credentials.raw(credentials.resolve("THREADS_ACCESS_TOKEN", settings, session))
                == PRIVATE[5]
            )
        elif expected == "skip":
            assert len(linked_setup[1]) == calls
    calls = len(linked_setup[1])
    oauth.maintain(factory, settings, now + timedelta(hours=1))
    assert len(linked_setup[1]) == calls
    if expected == "notice":
        claims = notify.claim_deliveries(factory, settings, now)
        assert len(claims) == 1
        assert claims[0]["messages"] == [{"type": "text", "text": notify.OAUTH_NOTICES[platform]}]
    no_secrets(client, settings, [client.get("/api/oauth/status")])


def test_manual_changes_invalidate_scopes_and_readiness(client, keys, settings, linked_setup):
    finish(client, begin(client, "threads"), "threads")
    client.get("/api/oauth/status")
    assert (
        client.put(
            "/api/credentials/THREADS_ACCESS_TOKEN",
            json={"value": "manual-replacement-private-token", "version": 1},
        ).status_code
        == 200
    )
    status = client.get("/api/oauth/status").json()["platforms"]["threads"]
    # 數據權限（成效、回覆）另列 data_missing，發佈所需權限仍在 missing；兩者合起來等同全部權限。
    assert status["missing"] == sorted(oauth.THREADS_PUBLISH_SCOPES)
    assert status["data_missing"] == sorted(oauth.THREADS_DATA_SCOPES)
    assert sorted(status["missing"] + status["data_missing"]) == sorted(oauth.THREADS_SCOPES)
    with client.app.state.session_factory() as session:
        assert not oauth.publish_readiness(session, settings)["threads"]["ready"]


def test_manual_meta_status_is_cached_without_inheriting_expiry(
    client, keys, settings, linked_setup
):
    with client.app.state.session_factory.begin() as session:
        oauth.put_secret(session, settings, "META_USER_ACCESS_TOKEN", PRIVATE[3])
        oauth.put_secret(session, settings, "META_PAGE_ACCESS_TOKEN", PRIVATE[4])
        oauth.put_secret(session, settings, "META_PAGE_ID", "100")
    status = client.get("/api/oauth/status").json()["platforms"]["meta"]
    assert status["linked"] and not status["missing"]
    assert status["expires_at"] is None
    calls = len(linked_setup[1])
    client.get("/api/oauth/status")
    assert len(linked_setup[1]) == calls
    client.get("/api/oauth/status?force=true")
    assert len(linked_setup[1]) == calls + 1
    with client.app.state.session_factory() as session:
        assert not oauth.publish_readiness(session, settings)["facebook"]["ready"]


def test_pending_session_binding_and_expiry(client, keys, settings, linked_setup):
    linked_setup[0]["pages"] = 2
    finish(client, begin(client))
    with client.app.state.session_factory.begin() as session:
        row = session.scalar(select(OAuthState))
        row.session_hash = "other-session"
    assert not client.get("/api/oauth/status").json()["pages"]
    assert client.post("/api/oauth/meta/page", json={"page_id": "100"}).status_code == 400
    with client.app.state.session_factory.begin() as session:
        row = session.scalar(select(OAuthState))
        row.session_hash = auth.token_hash(client.cookies.get(auth.COOKIE_NAME))
        row.expires_at = utc_now() - timedelta(seconds=1)
    assert client.post("/api/oauth/meta/page", json={"page_id": "100"}).status_code == 400


def test_refresh_does_not_overwrite_concurrent_manual_edit(
    client, keys, settings, linked_setup, monkeypatch
):
    finish(client, begin(client, "threads"), "threads")
    factory = client.app.state.session_factory
    now = utc_now()
    with factory.begin() as session:
        row = oauth.connection(session, "threads")
        row.expires_at = now + timedelta(days=6)
        row.refreshed_at = now - timedelta(days=2)
    original = oauth.request_json

    def concurrently_changed(url, **kwargs):
        result = original(url, **kwargs)
        if url.endswith("/refresh_access_token"):
            with factory.begin() as session:
                oauth.put_secret(
                    session, settings, "THREADS_ACCESS_TOKEN", "concurrent-manual-private"
                )
        return result

    monkeypatch.setattr(oauth, "request_json", concurrently_changed)
    oauth.maintain(factory, settings, now)
    with factory() as session:
        assert (
            credentials.raw(credentials.resolve("THREADS_ACCESS_TOKEN", settings, session))
            == "concurrent-manual-private"
        )


def test_state_can_only_be_consumed_once_concurrently(client, keys, settings, linked_setup):
    from concurrent.futures import ThreadPoolExecutor

    from fastapi import HTTPException

    from app.services.access import BrandAccess

    state = begin(client)
    cookie = client.cookies.get(auth.COOKIE_NAME)
    factory = client.app.state.session_factory

    def receive():
        with factory() as session:
            return oauth.receive(session, settings, "meta", state, "isolated-code")

    def complete():
        with factory() as session:
            access = BrandAccess(session, session.get(Staff, keys["staff_id"]))
            try:
                oauth.complete(access, settings, cookie, "meta")
                return 200
            except HTTPException as error:
                return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        landed = sorted(pool.map(lambda _: receive(), range(2)))
    assert sum("oauth_pending=meta" in x for x in landed) == 1
    assert sum("oauth_result=failed" in x for x in landed) == 1
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: complete(), range(2))) == [200, 400]


@pytest.mark.parametrize("expiry", ["never", "dated"])
def test_meta_long_token_without_expires_in(client, keys, settings, linked_setup, expiry):
    """商家專用 Facebook 登入的長期權杖常不附 expires_in；改以 debug_token 判斷實際到期。"""
    linked_setup[0]["meta_expiry"] = expiry
    response = finish(client, begin(client))
    assert "oauth_result=linked" in response.headers["location"]
    meta = client.get("/api/oauth/status").json()["platforms"]["meta"]
    assert meta["linked"] and meta["state"] == "ready"
    assert meta["never_expires"] is (expiry == "never")
    assert (meta["expires_at"] is None) is (expiry == "never")
    with client.app.state.session_factory() as session:
        readiness = oauth.publish_readiness(session, settings)
    for platform in ("facebook", "instagram"):
        assert readiness[platform]["ready"], readiness
    no_secrets(client, settings, [response])


def test_meta_pages_from_granular_scopes(client, keys, settings, linked_setup):
    """粉專經商家資產組合授權時 /me/accounts 為空，改由 granular_scopes 取得並讀取粉專。"""
    linked_setup[0]["granular"] = True
    response = finish(client, begin(client))
    assert "oauth_result=linked" in response.headers["location"]
    meta = client.get("/api/oauth/status").json()["platforms"]["meta"]
    assert meta["linked"] and meta["name"] == "隔離粉專 0" and meta["ig_username"] == "isolated_ig"
    no_secrets(client, settings, [response])


def test_linking_registers_brand_accounts(client, keys, settings, linked_setup):
    """授權成功即把帳號登記到唯一品牌，發佈功能才能對應；多品牌時不自動登記。"""
    from app.models import Account, Brand

    factory = client.app.state.session_factory
    with factory() as session:
        single = len(list(session.scalars(select(Brand.id).limit(2)))) == 1
    finish(client, begin(client, "threads"), "threads")
    finish(client, begin(client))
    with factory() as session:
        found = {
            (a.platform, a.external_id, a.status)
            for a in session.scalars(select(Account).where(Account.brand_id == keys["brand_id"]))
        }
    expected = {
        ("threads", "300", "connected"),
        ("facebook", "100", "connected"),
        ("instagram", "200", "connected"),
    }
    assert expected <= found if single else not (expected & found)


def old_threads_connection(client, scopes):
    """模擬加入數據權限之前連結的 Threads：授權範圍只有發佈權限，快取清空後重新檢查。"""
    from app.models import OAuthConnection

    with client.app.state.session_factory.begin() as session:
        row = session.scalar(select(OAuthConnection).where(OAuthConnection.platform == "threads"))
        row.granted_scopes = list(scopes)
        row.cache_json, row.checked_at = {}, None


def test_threads_data_permissions_do_not_block_publishing(client, keys, settings, linked_setup):
    assert set(oauth.THREADS_SCOPES) == {
        "threads_basic",
        "threads_content_publish",
        "threads_manage_replies",
        "threads_manage_insights",
        "threads_read_replies",
    }
    finish(client, begin(client, "threads"), "threads")
    fresh = client.get("/api/oauth/status?force=true").json()["platforms"]["threads"]
    assert fresh["state"] == "ready" and fresh["missing"] == [] and fresh["data_missing"] == []
    old_threads_connection(client, oauth.THREADS_PUBLISH_SCOPES)
    status = client.get("/api/oauth/status?force=true").json()["platforms"]["threads"]
    # 既有連結缺少數據權限：連結狀態與發佈就緒不變，只列出需要重新連結的數據權限。
    assert status["state"] == "ready" and status["missing"] == []
    assert status["data_missing"] == sorted(oauth.THREADS_DATA_SCOPES)
    with client.app.state.session_factory() as session:
        assert oauth.publish_readiness(session, settings)["threads"]["ready"]
        assert oauth.threads_data_access(session, settings) == "missing"
    assert client.get("/api/oauth/status").json()["platforms"]["meta"]["data_missing"] == []
    # 重新連結取得新權限後，提示消失。
    finish(client, begin(client, "threads"), "threads")
    renewed = client.get("/api/oauth/status?force=true").json()["platforms"]["threads"]
    assert renewed["data_missing"] == []
    with client.app.state.session_factory() as session:
        assert oauth.threads_data_access(session, settings) == "ready"


def test_threads_permission_error_marks_data_blocked_until_relinked(
    client, keys, settings, linked_setup
):
    finish(client, begin(client, "threads"), "threads")
    factory = client.app.state.session_factory
    with factory.begin() as session:
        oauth.mark_threads_data_blocked(session, settings)
    status = client.get("/api/oauth/status?force=true").json()["platforms"]["threads"]
    assert status["state"] == "ready" and status["missing"] == []
    assert status["data_missing"] == sorted(oauth.THREADS_DATA_SCOPES)
    with factory() as session:
        assert oauth.threads_data_access(session, settings) == "missing"
        # 超過一天會再試一次；換權杖（憑證摘要改變）則立即解除。
        later = utc_now() + oauth.DATA_BLOCK_RETRY + timedelta(minutes=1)
        assert oauth.threads_data_access(session, settings, later) == "ready"
    finish(client, begin(client, "threads"), "threads")
    with factory() as session:
        assert not session.scalar(select(Setting).where(Setting.key == oauth.DATA_BLOCK_KEY))
        assert oauth.threads_data_access(session, settings) == "ready"
    with factory.begin() as session:
        oauth.mark_threads_data_blocked(session, settings)
        oauth.put_secret(session, settings, "THREADS_ACCESS_TOKEN", "manual-replacement-token")
    with factory() as session:
        assert oauth.threads_data_access(session, settings) == "unknown"

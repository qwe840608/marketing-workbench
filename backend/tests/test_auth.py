import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import pytest
from conftest import seed_records
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import delete, select

from app.api.dependencies import Access
from app.config import Settings
from app.main import create_app
from app.models import (
    Account,
    AdMetricDaily,
    AIRun,
    AuditLog,
    AuthSession,
    Brand,
    Classification,
    Contact,
    Draft,
    InboundJob,
    Message,
    MetricSnapshot,
    Notification,
    Post,
    PriceItem,
    PriceItemHistory,
    RawEvent,
    Setting,
    Staff,
    StaffBrand,
    Thread,
)
from app.models.base import utc_now
from app.services import auth
from app.services.access import BrandAccess
from app.services.auth import COOKIE_NAME
from app.services.passwords import hash_password, set_password, verify_password


@pytest.fixture(scope="session")
def password():
    return SecretStr(secrets.token_urlsafe(24))


@pytest.mark.parametrize("correct", [True, False])
def test_login_remains_valid_while_background_worker_writes(
    client, auth_data, password, monkeypatch, correct
):
    factory = client.app.state.session_factory
    attempted, completed = Event(), Event()
    original = auth.verify_password
    futures = []
    with ThreadPoolExecutor(max_workers=1) as pool:

        def background_write():
            attempted.set()
            with factory.begin() as session:
                session.add(
                    AuditLog(actor="test:background", action="test.concurrent", target_type="test")
                )
            completed.set()

        def verifying(*args):
            futures.append(pool.submit(background_write))
            assert attempted.wait(2)
            completed.wait(0.2)
            return original(*args)

        monkeypatch.setattr(auth, "verify_password", verifying)
        csrf = client.get("/api/auth/csrf").json()["csrf_token"]
        result = client.post(
            "/api/auth/login",
            json={
                "username": "admin",
                "password": password.get_secret_value() if correct else secrets.token_urlsafe(24),
            },
            headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
        )
        assert result.status_code == (200 if correct else 401)
        for future in futures:
            future.result(timeout=5)


@pytest.fixture(scope="session")
def password_digest(password):
    return SecretStr(hash_password(password))


@pytest.fixture
def auth_data(client, settings, password_digest):
    factory = client.app.state.session_factory
    with factory.begin() as session:
        seed_records(session, settings)
        people = {person.username: person for person in session.scalars(select(Staff))}
        for person in people.values():
            person.password_hash = password_digest.get_secret_value()
        demo = session.scalar(select(Brand).where(Brand.slug == "TEST"))
        other = Brand(slug="other-test", name="其他測試品牌")
        session.add(other)
        session.flush()
        ids = {"demo": demo.id, "other": other.id, **{name: p.id for name, p in people.items()}}
        now = utc_now()
        for label, brand in (("demo", demo), ("other", other)):
            account = Account(
                brand_id=brand.id,
                platform="facebook",
                external_id="permission-test-account",
                name="[測試] 權限驗證帳號",
            )
            contact = Contact(
                brand_id=brand.id,
                platform="facebook",
                external_id="permission-test-contact",
                display_name="權限測試用戶",
            )
            session.add_all([account, contact])
            session.flush()
            post = Post(
                account_id=account.id,
                external_id="permission-test-post",
                media_type="video",
                caption="[測試] 權限驗證貼文",
                published_at=now,
            )
            session.add(post)
            session.flush()
            thread = Thread(
                account_id=account.id,
                brand_id=brand.id,
                contact_id=contact.id,
                post_id=post.id,
                external_id="permission-test-thread",
                kind="comment_thread",
            )
            session.add(thread)
            session.flush()
            message = Message(
                thread_id=thread.id,
                external_id="permission-test-message",
                direction="in",
                author_type="fan",
                text=f"[測試資料] {label} 專屬訊息",
                sent_at=now,
            )
            price = PriceItem(
                brand_id=brand.id,
                category="測試需求類型",
                price=1234,
                unit="台",
                notes="範例，未核定",
            )
            session.add_all([message, price])
            session.flush()
            session.add_all(
                [
                    MetricSnapshot(post_id=post.id, captured_at=now),
                    Draft(thread_id=thread.id, text="[測試] 草稿", provider="test", model="test"),
                    Classification(
                        message_id=message.id,
                        engine="keyword",
                        intent="other",
                        sentiment="neutral",
                        sensitive=False,
                        action="human",
                        confidence=0.5,
                    ),
                    InboundJob(message_id=message.id, task="classify"),
                    PriceItemHistory(price_item_id=price.id, before_json={}, after_json={}),
                    AdMetricDaily(account_id=account.id, date=now.date(), campaign_id="test"),
                    AIRun(
                        task="test",
                        provider="test",
                        model="test",
                        mode="api",
                        trigger="manual",
                        brand_id=brand.id,
                        ok=True,
                    ),
                    Notification(brand_id=brand.id, thread_id=thread.id, kind="new", due_at=now),
                    RawEvent(
                        platform="facebook", brand_id=brand.id, signature_ok=True, payload_json={}
                    ),
                    AuditLog(brand_id=brand.id, actor="test", action="test", target_type="test"),
                ]
            )
            ids.update(
                {
                    f"{label}_thread": thread.id,
                    f"{label}_post": post.id,
                    f"{label}_contact": contact.id,
                }
            )
    return ids


def sign_in(client, password, username="admin"):
    csrf = client.get("/api/auth/csrf")
    assert csrf.status_code == 200
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password.get_secret_value()},
        headers={"X-CSRF-Token": csrf.json()["csrf_token"]},
    )
    assert response.status_code == 200
    return SecretStr(response.json()["csrf_token"])


@pytest.mark.parametrize(
    "path",
    [
        "/api/auth/me",
        "/api/dashboard",
        "/api/threads/1/messages",
        "/api/brands",
        "/api/accounts",
        "/api/contacts",
        "/api/contacts/1",
        "/api/threads",
        "/api/threads/1",
        "/api/threads/1/messages",
        "/api/posts",
        "/api/posts/1",
        "/api/posts/1/metrics",
    ],
)
def test_business_apis_require_login(client, path):
    assert client.get(path).status_code == 401


def test_login_cookie_rotation_logout_and_safe_logs(client, settings, auth_data, password):
    response = client.get("/api/auth/csrf")
    before = SecretStr(client.cookies.get(COOKIE_NAME))
    old_csrf = SecretStr(response.json()["csrf_token"])
    cookie_header = response.headers["set-cookie"].lower()
    assert "httponly" in cookie_header and "samesite=strict" in cookie_header
    assert response.headers["cache-control"] == "no-store"
    new_csrf = sign_in(client, password)
    after = SecretStr(client.cookies.get(COOKIE_NAME))
    assert before != after and old_csrf != new_csrf
    response = client.get("/api/auth/me")
    assert response.json()["username"] == "admin"
    assert "password_hash" not in response.json()
    response = client.get("/api/auth/csrf")
    assert SecretStr(response.json()["csrf_token"]) == new_csrf
    assert client.post("/api/auth/logout").status_code == 403
    assert (
        client.post(
            "/api/auth/logout", headers={"X-CSRF-Token": old_csrf.get_secret_value()}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/auth/logout", headers={"X-CSRF-Token": new_csrf.get_secret_value()}
        ).status_code
        == 204
    )
    assert client.get("/api/auth/me").status_code == 401
    client.cookies.set(COOKIE_NAME, after.get_secret_value())
    assert client.get("/api/auth/me").status_code == 401
    contents = settings.log_path.read_text(encoding="utf-8")
    for secret in (password, before, after, old_csrf, new_csrf):
        if secret.get_secret_value() in contents:
            pytest.fail("日誌包含敏感值")


def test_login_csrf_origin_and_untrusted_cookie(client, auth_data, password):
    body = {"username": "admin", "password": password.get_secret_value()}
    assert client.post("/api/auth/login", json=body).status_code == 403
    csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    assert (
        client.post(
            "/api/auth/login",
            json=body,
            headers={
                "X-CSRF-Token": csrf,
                "Origin": "https://outside.example",
            },
        ).status_code
        == 403
    )
    assert client.get("/api/auth/csrf", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, secrets.token_urlsafe(32))
    assert (
        client.post("/api/auth/login", json=body, headers={"X-CSRF-Token": csrf}).status_code == 403
    )


def test_password_failures_do_not_disclose_account_existence(client, auth_data, password):
    csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    responses = []
    for username in ("missing", "admin"):
        response = client.post(
            "/api/auth/login",
            headers={"X-CSRF-Token": csrf},
            json={"username": username, "password": secrets.token_urlsafe(24)},
        )
        assert response.status_code == 401
        responses.append(response.json())
    assert responses[0] == responses[1]
    with client.app.state.session_factory.begin() as session:
        session.get(Staff, auth_data["admin"]).password_hash = None
    response = client.post(
        "/api/auth/login",
        headers={"X-CSRF-Token": csrf},
        json={"username": "admin", "password": password.get_secret_value()},
    )
    assert response.status_code == 401


def test_invalid_login_input_is_not_reflected(client, password):
    response = client.post("/api/auth/login", json={"password": password.get_secret_value()})
    assert response.status_code == 422
    assert response.json() == {"detail": "輸入格式錯誤"}


def test_admin_sees_all_brands_without_explicit_assignments(client, auth_data, password):
    sign_in(client, password)
    assert {item["slug"] for item in client.get("/api/brands").json()} == {"TEST", "other-test"}
    assert client.get(f"/api/threads/{auth_data['other_thread']}/messages").status_code == 200
    assert client.get(f"/api/posts/{auth_data['other_post']}/metrics").status_code == 200
    with client.app.state.session_factory() as session:
        assert (
            session.scalar(select(StaffBrand).where(StaffBrand.staff_id == auth_data["admin"]))
            is None
        )


def test_marketer_only_sees_assigned_brand_in_lists_and_direct_ids(client, auth_data, password):
    sign_in(client, password, "marketing_test")
    assert [item["slug"] for item in client.get("/api/brands").json()] == ["TEST"]
    for path in ("accounts", "contacts", "threads"):
        rows = client.get(f"/api/{path}").json()
        assert rows and all(row["brand_id"] == auth_data["demo"] for row in rows)
        assert client.get(f"/api/{path}?brand_id={auth_data['other']}").status_code == 404
    assert client.get(f"/api/threads/{auth_data['demo_thread']}/messages").status_code == 200
    assert client.get(f"/api/posts/{auth_data['demo_post']}/metrics").status_code == 200
    for path in (
        f"contacts/{auth_data['other_contact']}",
        f"threads/{auth_data['other_thread']}",
        f"threads/{auth_data['other_thread']}/messages",
        f"posts/{auth_data['other_post']}",
        f"posts/{auth_data['other_post']}/metrics",
    ):
        assert client.get(f"/api/{path}").status_code == 404
    assert auth_data["other_post"] not in {p["id"] for p in client.get("/api/posts").json()}
    assert all("token_ref" not in row for row in client.get("/api/accounts").json())


def test_viewer_without_assignments_has_no_brand_data(client, auth_data, password):
    sign_in(client, password, "viewer_test")
    for path in ("brands", "accounts", "contacts", "threads", "posts"):
        response = client.get(f"/api/{path}")
        assert response.status_code == 200 and response.json() == []
    assert client.get(f"/api/threads/{auth_data['demo_thread']}").status_code == 404


def test_permissions_are_reloaded_after_login(client, auth_data, password):
    sign_in(client, password, "marketing_test")
    with client.app.state.session_factory.begin() as session:
        session.execute(
            delete(StaffBrand).where(StaffBrand.staff_id == auth_data["marketing_test"])
        )
    assert client.get("/api/brands").json() == []
    assert client.get(f"/api/threads/{auth_data['demo_thread']}").status_code == 404


@pytest.mark.parametrize(
    "model",
    [
        Account,
        Contact,
        Thread,
        Post,
        Message,
        MetricSnapshot,
        Draft,
        Classification,
        InboundJob,
        PriceItem,
        PriceItemHistory,
        AdMetricDaily,
        AIRun,
        Notification,
        RawEvent,
        AuditLog,
    ],
)
def test_service_scope_covers_all_brand_owned_tables(client, auth_data, model):
    with client.app.state.session_factory() as session:
        staff = session.get(Staff, auth_data["marketing_test"])
        access = BrandAccess(session, staff)
        assert list(session.scalars(access.statement(model, auth_data["demo"])))
        assert list(session.scalars(access.statement(model, auth_data["other"]))) == []
        with pytest.raises(ValueError):
            access.statement(Setting)


def test_write_guard_checks_csrf_and_readonly_role(client, auth_data, password, monkeypatch):
    from app.api.permissions import ROUTE_POLICY

    monkeypatch.setitem(ROUTE_POLICY, ("POST", "/api/test-write"), "ideation.edit")

    @client.app.post("/api/test-write")
    def test_write(access: Access):
        access.require_brand(auth_data["demo"], write=True)
        return {"ok": True}

    csrf = sign_in(client, password, "marketing_test")
    assert client.post("/api/test-write").status_code == 403
    assert (
        client.post(
            "/api/test-write", headers={"X-CSRF-Token": csrf.get_secret_value()}
        ).status_code
        == 200
    )
    with client.app.state.session_factory.begin() as session:
        session.add(StaffBrand(staff_id=auth_data["viewer_test"], brand_id=auth_data["demo"]))
    csrf = sign_in(client, password, "viewer_test")
    assert client.get("/api/brands").json()
    assert (
        client.post(
            "/api/test-write", headers={"X-CSRF-Token": csrf.get_secret_value()}
        ).status_code
        == 403
    )
    with client.app.state.session_factory() as session:
        viewer = session.get(Staff, auth_data["viewer_test"])
        with pytest.raises(HTTPException) as error:
            BrandAccess(session, viewer).require_brand(auth_data["demo"], write=True)
        assert error.value.status_code == 403


def test_sessions_survive_app_restart_but_expire_and_revoke(client, settings, auth_data, password):
    sign_in(client, password)
    token = SecretStr(client.cookies.get(COOKIE_NAME))
    with TestClient(create_app(settings)) as restarted:
        restarted.cookies.set(COOKIE_NAME, token.get_secret_value())
        assert restarted.get("/api/auth/me").status_code == 200
    with client.app.state.session_factory.begin() as session:
        current = session.scalar(
            select(AuthSession).where(AuthSession.staff_id == auth_data["admin"])
        )
        assert current.token_hash != token.get_secret_value()
        current.expires_at = utc_now() - timedelta(seconds=1)
    assert client.get("/api/auth/me").status_code == 401
    sign_in(client, password)
    with client.app.state.session_factory.begin() as session:
        session.get(Staff, auth_data["admin"]).active = False
    assert client.get("/api/auth/me").status_code == 401


def test_password_reset_uses_argon2_and_revokes_sessions(client, auth_data, password):
    sign_in(client, password)
    new_password = SecretStr(secrets.token_urlsafe(24))
    with client.app.state.session_factory.begin() as session:
        set_password(session, "admin", new_password)
    assert client.get("/api/auth/me").status_code == 401
    with client.app.state.session_factory() as session:
        staff = session.get(Staff, auth_data["admin"])
        assert staff.password_hash.startswith("$argon2id$")
        assert verify_password(new_password, staff.password_hash)
        assert not verify_password(password, staff.password_hash)
    sign_in(client, new_password)


def test_env_bootstrap_sets_only_uninitialized_passwords(client, settings, password):
    factory = client.app.state.session_factory
    with factory.begin() as session:
        configured = settings.model_copy(update={"admin_initial_password": password})
        seed_records(session, configured)
    with factory.begin() as session:
        admin = session.scalar(select(Staff).where(Staff.username == "admin"))
        original_hash = SecretStr(admin.password_hash)
        assert verify_password(password, admin.password_hash)
        configured = settings.model_copy(
            update={"admin_initial_password": SecretStr(secrets.token_urlsafe(24))}
        )
        seed_records(session, configured)
        assert SecretStr(admin.password_hash) == original_hash
        assert (
            session.scalar(select(Staff).where(Staff.username == "marketing_test")).password_hash
            is None
        )


def test_https_requires_secure_cookie(migrated):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_origin="https://example.ts.net", session_cookie_secure=False)
    secure = migrated.model_copy(
        update={
            "app_origin": "https://testserver",
            "session_cookie_secure": True,
        }
    )
    with TestClient(create_app(secure), base_url="https://testserver") as client:
        response = client.get("/api/auth/csrf")
        assert "; secure" in response.headers["set-cookie"].lower()


def test_line_account_registration_removed():
    from app.services import accounts, credentials

    assert not hasattr(accounts, "register_line_test_account")
    assert "line" not in credentials.GROUPS
    for name in ("LINE_CHANNEL_SECRET", "LINE_CHANNEL_ACCESS_TOKEN", "LINE_BOT_USER_ID"):
        with pytest.raises(HTTPException) as error:
            credentials.checked_name(name)
        assert error.value.status_code == 422

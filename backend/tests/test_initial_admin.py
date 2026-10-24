import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select

from app.models import Account, Brand, Message, PriceItem, Staff
from app.services.passwords import (
    create_admin,
    create_first_brand,
    set_password,
    verify_password,
)


def test_initial_admin_creates_no_business_records(client):
    factory = client.app.state.session_factory
    password = SecretStr("isolated-admin-password")
    with factory.begin() as session:
        create_admin(session, "test-admin", password)
    with factory() as session:
        staff = session.scalar(select(Staff))
        assert staff.username == "test-admin" and staff.role == "admin"
        assert verify_password(password, staff.password_hash)
        for model in (Account, Brand, Message, PriceItem):
            assert session.scalar(select(func.count()).select_from(model)) == 0
    with pytest.raises(ValueError, match="空白使用者"):
        with factory.begin() as session:
            create_admin(session, "another-admin", SecretStr("another-test-password"))
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Staff)) == 1
        assert verify_password(password, session.scalar(select(Staff)).password_hash)


def test_initial_admin_invalid_password_leaves_installation_empty(client):
    factory = client.app.state.session_factory
    with pytest.raises(ValueError, match="密碼長度"):
        with factory.begin() as session:
            create_admin(session, "test-admin", SecretStr("short"))
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Staff)) == 0


def test_initial_admin_username_matches_login_and_reset(client):
    factory = client.app.state.session_factory
    with factory.begin() as session:
        staff = create_admin(session, "  Boss ", SecretStr("isolated-admin-password"))
        assert staff.username == "Boss"
    new_password = SecretStr("another-test-password")
    with factory.begin() as session:
        set_password(session, " boss", new_password)
    with factory() as session:
        assert verify_password(new_password, session.scalar(select(Staff)).password_hash)


def test_initial_admin_rejects_blank_username(client):
    factory = client.app.state.session_factory
    with pytest.raises(ValueError, match="1–80"):
        with factory.begin() as session:
            create_admin(session, "   ", SecretStr("isolated-admin-password"))


def test_first_brand_is_created_once(client):
    factory = client.app.state.session_factory
    with pytest.raises(ValueError, match="品牌名稱"):
        with factory.begin() as session:
            create_first_brand(session, "   ")
    with factory.begin() as session:
        assert create_first_brand(session, " 測試品牌 ").name == "測試品牌"
    with factory.begin() as session:
        assert create_first_brand(session, "另一個品牌") is None
    with factory() as session:
        assert session.scalars(select(Brand.name)).all() == ["測試品牌"]


def setup_headers(client):
    token = client.get("/api/auth/csrf").json()["csrf_token"]
    return {"X-CSRF-Token": token, "Origin": "http://testserver"}


SETUP = {"username": "web-admin", "password": "isolated-setup-password", "brand_name": "測試品牌"}


def test_web_setup_creates_admin_and_brand_then_logs_in(client):
    assert client.get("/api/auth/setup").json() == {"needed": True, "local": True}
    response = client.post("/api/auth/setup", json=SETUP, headers=setup_headers(client))
    assert response.status_code == 200, response.text
    assert response.json()["user"]["role"] == "admin"
    assert client.get("/api/auth/me").json()["username"] == "web-admin"
    assert client.get("/api/auth/setup").json()["needed"] is False
    with client.app.state.session_factory() as session:
        assert [brand.name for brand in session.scalars(select(Brand))] == ["測試品牌"]
    again = client.post(
        "/api/auth/setup", json=SETUP | {"username": "second"}, headers=setup_headers(client)
    )
    assert again.status_code == 409
    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Staff)) == 1


def test_web_setup_refuses_remote_hosts_and_missing_csrf(client):
    # Tailscale 代理經 proxy headers 還原成 100.x 的裝置 IP。
    with TestClient(client.app, client=("100.101.102.103", 50000)) as remote:
        assert remote.get("/api/auth/setup").json() == {"needed": True, "local": False}
        refused = remote.post("/api/auth/setup", json=SETUP, headers=setup_headers(remote))
        assert refused.status_code == 403
    headers = setup_headers(client)
    assert client.post("/api/auth/setup", json=SETUP).status_code == 403
    short = client.post("/api/auth/setup", json=SETUP | {"password": "short"}, headers=headers)
    assert short.status_code == 422
    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Staff)) == 0
        assert session.scalar(select(func.count()).select_from(Brand)) == 0


def test_local_request_needs_loopback_source_and_host():
    from app.services.auth import local_request

    assert local_request("127.0.0.1", "127.0.0.1:8010")
    assert local_request("::1", "localhost:8000")
    assert not local_request("100.101.102.103", "127.0.0.1:8000")
    assert not local_request("127.0.0.1", "mwb.example.ts.net")
    assert not local_request("127.0.0.1", "gateway.example.com")
    assert not local_request(None, None)

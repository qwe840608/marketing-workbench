"""Member lifecycle and complete route inventory on synthetic databases."""

import json
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, inspect, select

from app import config
from app.api.agent_auth import get_agent_access
from app.api.dependencies import enforce_password_change, get_access
from app.api.permissions import ROLE_SETS, ROUTE_POLICY, require_role
from app.main import create_app
from app.models import AuditLog, Brand, Staff, StaffBrand
from app.models.auth import LoginGuard
from app.models.base import utc_now
from app.services import auth
from app.services.passwords import hash_password, set_password, verify_password


@pytest.fixture(scope="module")
def member_password():
    return SecretStr(secrets.token_urlsafe(24))


@pytest.fixture(scope="module")
def member_digest(member_password):
    return SecretStr(hash_password(member_password))


def sign_in(client, username, password):
    csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    result = client.post(
        "/api/auth/login",
        headers={"X-CSRF-Token": csrf},
        json={"username": username, "password": password.get_secret_value()},
    )
    if result.status_code == 200:
        client.headers["X-CSRF-Token"] = result.json()["csrf_token"]
    return result


@pytest.fixture
def people(client, member_digest, member_password):
    with client.app.state.session_factory.begin() as session:
        brands = [Brand(slug=f"member-{n}", name=f"測試品牌 {n}") for n in range(2)]
        users = [
            Staff(
                username=name,
                display_name=name,
                role=role,
                password_hash=member_digest.get_secret_value(),
            )
            for name, role in [("owner", "admin"), ("assistant", "marketing"), ("reader", "viewer")]
        ]
        session.add_all(brands + users)
        session.flush()
        for staff in users[1:]:
            session.add(StaffBrand(staff_id=staff.id, brand_id=brands[0].id))
        result = {staff.username: staff.id for staff in users}
        result["brands"] = [brand.id for brand in brands]
    assert sign_in(client, "owner", member_password).status_code == 200
    return result


def member_input(people, **overrides):
    return {
        "username": "new-person",
        "display_name": "新成員",
        "role": "marketing",
        "brand_ids": [people["brands"][0]],
        **overrides,
    }


def audit_text(client):
    with client.app.state.session_factory() as session:
        return json.dumps(
            [
                {"actor": row.actor, "action": row.action, "detail": row.detail_json}
                for row in session.scalars(select(AuditLog))
            ],
            ensure_ascii=False,
        )


def test_create_unique_validation_and_one_time_password(client, people):
    response = client.post("/api/members", json=member_input(people))
    assert response.status_code == 201
    result = response.json()
    password = SecretStr(result["temporary_password"])
    identity = result["member"]["id"]
    assert len(password.get_secret_value()) >= 16
    assert result["member"]["must_change_password"] is True
    assert result["member"]["brand_ids"] == people["brands"][:1]
    listing = client.get("/api/members")
    assert "temporary_password" not in listing.text and "password_hash" not in listing.text
    assert password.get_secret_value() not in listing.text + audit_text(client)
    with client.app.state.session_factory() as session:
        staff = session.get(Staff, identity)
        assert verify_password(password, staff.password_hash)
        assert staff.password_hash not in audit_text(client)
    assert (
        client.post("/api/members", json=member_input(people, username="NEW-PERSON")).status_code
        == 409
    )
    for changes in (
        {"username": ""},
        {"username": " "},
        {"username": "x" * 81},
        {"display_name": " "},
        {"role": "other"},
        {"brand_ids": [99999]},
    ):
        assert (
            client.post(
                "/api/members",
                json=member_input(people, **{"username": secrets.token_hex(6), **changes}),
            ).status_code
            == 422
        )
    created = client.post(
        "/api/members",
        json=member_input(people, username="second-admin", role="admin", brand_ids=[99999]),
    )
    assert created.status_code == 201
    assert created.json()["member"]["brand_ids"] == people["brands"]


def test_edit_state_reset_sessions_and_audit(client, people, member_password):
    factory = client.app.state.session_factory
    identity = people["assistant"]
    with factory.begin() as session:
        tokens = [
            auth.issue_session(session, client.app.state.settings, identity).token for _ in range(2)
        ]
    response = client.put(
        f"/api/members/{identity}",
        json={"display_name": "行銷同事", "role": "viewer", "brand_ids": [people["brands"][1]]},
    )
    assert response.status_code == 200 and response.json()["brand_ids"] == people["brands"][1:]
    reset = client.post(f"/api/members/{identity}/reset-password")
    assert reset.status_code == 200
    secret = SecretStr(reset.json()["temporary_password"])
    assert secret.get_secret_value() not in audit_text(client)
    with factory() as session:
        assert all(auth.find_session(session, token) is None for token in tokens)
        assert session.get(Staff, identity).must_change_password
    assert client.put(f"/api/members/{identity}/state", json={"active": False}).status_code == 200
    assert client.put(f"/api/members/{identity}/state", json={"active": True}).status_code == 200
    with factory.begin() as session:
        token = auth.issue_session(session, client.app.state.settings, identity).token
    assert client.put(f"/api/members/{identity}/state", json={"active": False}).status_code == 200
    with factory() as session:
        assert auth.find_session(session, token) is None
    with TestClient(create_app(client.app.state.settings)) as other:
        other.cookies.set(auth.COOKIE_NAME, token)
        assert other.get("/api/auth/me").status_code == 401
        assert sign_in(other, "assistant", secret).status_code == 401
    assert client.put(f"/api/members/{identity}/state", json={"active": True}).status_code == 200
    assert client.get("/api/members").json()[0]["last_login_at"] is not None
    assert (
        client.put(
            "/api/members/99999", json={"display_name": "test", "role": "viewer"}
        ).status_code
        == 404
    )


def test_last_admin_and_self_protection(client, people):
    owner = people["owner"]
    response = client.put(f"/api/members/{owner}/state", json={"active": False})
    assert response.status_code == 409 and response.json()["detail"] == "管理員不可停用自己"
    assert (
        client.put(
            f"/api/members/{owner}", json={"display_name": "Owner", "role": "marketing"}
        ).status_code
        == 409
    )
    with client.app.state.session_factory.begin() as session:
        disabled = Staff(
            username="disabled-admin", display_name="停用管理員", role="admin", active=False
        )
        session.add(disabled)
    assert (
        client.put(
            f"/api/members/{owner}", json={"display_name": "Owner", "role": "viewer"}
        ).status_code
        == 409
    )
    with client.app.state.session_factory.begin() as session:
        admin = Staff(username="another-admin", display_name="另一管理員", role="admin")
        session.add(admin)
        session.flush()
        identity = admin.id
    assert client.put(f"/api/members/{identity}/state", json={"active": False}).status_code == 200
    assert (
        client.put(
            f"/api/members/{owner}", json={"display_name": "Owner", "role": "viewer"}
        ).status_code
        == 409
    )
    with client.app.state.session_factory.begin() as session:
        session.get(Staff, identity).active = True
    assert (
        client.put(
            f"/api/members/{owner}",
            json={"display_name": "Owner", "role": "marketing", "brand_ids": people["brands"][:1]},
        ).status_code
        == 200
    )
    assert client.get("/api/members").status_code == 403


def route_url(path):
    values = {
        "kind": "reports",
        "format": "md",
        "name": "test",
        "provider": "gemini_api",
        "group": "meta",
    }
    import re

    return re.sub(r"\{([^}]+)\}", lambda match: values.get(match[1], "1"), path)


def test_concurrent_admin_demotions_keep_one_active_admin(client, people, member_password):
    with client.app.state.session_factory.begin() as session:
        second = session.get(Staff, people["assistant"])
        second.role = "admin"
    barrier = Barrier(2)
    with TestClient(create_app(client.app.state.settings)) as other:
        assert sign_in(other, "assistant", member_password).status_code == 200

        def demote(connection, identity):
            barrier.wait(timeout=5)
            return connection.put(
                f"/api/members/{identity}",
                json={"display_name": "同事", "role": "marketing", "brand_ids": []},
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            attempts = [
                pool.submit(demote, client, people["owner"]),
                pool.submit(demote, other, people["assistant"]),
            ]
            assert sorted(attempt.result() for attempt in attempts) == [200, 409]
    with client.app.state.session_factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Staff)
                .where(Staff.active.is_(True), Staff.role == "admin")
            )
            == 1
        )


def test_required_password_blocks_every_other_api(client, people):
    result = client.post("/api/members", json=member_input(people)).json()
    with TestClient(create_app(client.app.state.settings)) as other:
        assert (
            sign_in(other, "new-person", SecretStr(result["temporary_password"])).status_code == 200
        )
        assert other.get("/api/auth/me").json()["must_change_password"]
        for (method, path), _policy in ROUTE_POLICY.items():
            if not path.startswith("/api/") or path in {
                "/api/auth/me",
                "/api/auth/csrf",
                "/api/auth/logout",
                "/api/auth/change-password",
            }:
                continue
            response = other.request(method, route_url(path))
            assert response.status_code == 403, (method, path, response.status_code)
            assert response.json()["detail"] == "請先變更密碼"
        assert other.get("/api/auth/csrf").status_code == 200
        assert other.post("/api/auth/logout").status_code == 204


@pytest.mark.parametrize("username", ["owner", "assistant", "reader"])
def test_change_password_all_roles_preserves_only_current_session(
    client, people, member_password, username
):
    identity = people[username]
    assert sign_in(client, username, member_password).status_code == 200
    token = client.cookies.get(auth.COOKIE_NAME)
    with client.app.state.session_factory.begin() as session:
        session.get(Staff, identity).must_change_password = True
        other = auth.issue_session(session, client.app.state.settings, identity).token
    secret = SecretStr(secrets.token_urlsafe(24))

    def change(current, new):
        return client.post(
            "/api/auth/change-password", json={"current_password": current, "new_password": new}
        )

    assert change("incorrect", secret.get_secret_value()).status_code == 422
    assert change(member_password.get_secret_value(), "short").status_code == 422
    assert (
        change(member_password.get_secret_value(), member_password.get_secret_value()).status_code
        == 422
    )
    assert (
        client.post(
            "/api/auth/change-password",
            headers={"X-CSRF-Token": "invalid"},
            json={
                "current_password": member_password.get_secret_value(),
                "new_password": secret.get_secret_value(),
            },
        ).status_code
        == 403
    )
    response = change(member_password.get_secret_value(), secret.get_secret_value())
    assert response.status_code == 200 and response.json()["must_change_password"] is False
    assert client.cookies.get(auth.COOKIE_NAME) == token
    with client.app.state.session_factory() as session:
        assert auth.find_session(session, token) is not None
        assert auth.find_session(session, other) is None
    assert client.get("/api/brands").status_code == 200
    assert secret.get_secret_value() not in audit_text(client)


@pytest.mark.parametrize("username", ["owner", "missing-account"])
def test_login_lock_five_failures_and_expiry(
    client, people, member_password, monkeypatch, username
):
    now = utc_now()
    monkeypatch.setattr(auth, "utc_now", lambda: now)
    bad = SecretStr(secrets.token_urlsafe(24))
    for _ in range(5):
        assert sign_in(client, username.upper(), bad).status_code == 401
    with client.app.state.session_factory() as session:
        guard = session.scalar(select(LoginGuard).where(LoginGuard.locked_until.is_not(None)))
        assert guard.failures == 5 and guard.locked_until == now + timedelta(minutes=15)
    locked = sign_in(client, username, member_password)
    assert locked.status_code == 401 and locked.json()["detail"] == "帳號或密碼不正確"
    with TestClient(create_app(client.app.state.settings)) as restarted:
        locked_again = sign_in(restarted, username, member_password)
        assert locked_again.status_code == 401
        assert locked_again.json()["detail"] == locked.json()["detail"]
    text = audit_text(client)
    assert text.count("auth.login_locked") == 1
    now += timedelta(minutes=14, seconds=59)
    assert sign_in(client, username, member_password).status_code == 401
    now += timedelta(seconds=1)
    assert sign_in(client, username, member_password).status_code == (
        200 if username == "owner" else 401
    )
    assert audit_text(client).count("auth.login_unlocked") == 1


def test_successful_login_breaks_consecutive_failures(client, people, member_password):
    for _ in range(4):
        assert sign_in(client, "owner", SecretStr("wrong")).status_code == 401
    assert sign_in(client, "OWNER", member_password).status_code == 200
    assert sign_in(client, "owner", SecretStr("wrong")).status_code == 401
    with client.app.state.session_factory() as session:
        assert max(session.scalars(select(LoginGuard.failures))) == 1


@pytest.mark.parametrize("username", ["assistant", "reader"])
def test_nonadmins_routes_and_brand_visibility(client, people, member_password, username):
    assert sign_in(client, username, member_password).status_code == 200
    own = client.get("/api/auth/me").json()
    assert own["brand_ids"] == people["brands"][:1]
    assert [b["id"] for b in client.get("/api/brands").json()] == people["brands"][:1]
    for (method, path), policy in ROUTE_POLICY.items():
        if policy == "admin" or policy == "edit" and username == "reader":
            response = client.request(method, route_url(path))
            assert response.status_code == 403, (method, path, response.status_code)
    assert client.get(f"/api/ideation/reports?brand_id={people['brands'][1]}").status_code == 404
    with client.app.state.session_factory.begin() as session:
        from sqlalchemy import delete

        session.execute(delete(StaffBrand).where(StaffBrand.staff_id == people[username]))
    assert client.get("/api/brands").json() == []


def dependency_calls(dependency):
    return {dependency.call} | set().union(
        *(dependency_calls(child) for child in dependency.dependencies)
    )


def test_every_route_has_explicit_role_and_guard(client, people):
    routes = [
        route
        for route in iter_route_contexts(client.app.routes)
        if isinstance(route.original_route, APIRoute)
        and (route.path.startswith(("/api/", "/webhook/", "/media/", "/oauth/", "/plugin/",
                                    "/.well-known/")) or route.path == "/mcp")
    ]
    inventory = {(method, route.path) for route in routes for method in route.methods}
    assert inventory == set(ROUTE_POLICY), "New or removed API must update explicit policy"
    for route in routes:
        calls = dependency_calls(route.dependant)
        assert enforce_password_change in calls
        for method in route.methods:
            policy = ROUTE_POLICY[(method, route.path)]
            if policy in ROLE_SETS and not route.path.startswith("/api/auth/"):
                expected = get_agent_access if route.path.startswith("/api/agent/") or (
                    route.path == "/api/members/{identity}/revoke-connections"
                ) else get_access
                assert expected in calls, (method, route.path)
            for role in ("admin", "marketing", "viewer"):
                if role in ROLE_SETS.get(policy, set()):
                    require_role(route.path, method, role)
                else:
                    with pytest.raises(HTTPException):
                        require_role(route.path, method, role)
    with pytest.raises(HTTPException):
        require_role("/api/forgotten", "POST", "admin")


def test_all_member_writes_require_csrf_and_origin(client, people):
    for method, path, body in [
        ("POST", "/api/members", member_input(people)),
        ("PUT", f"/api/members/{people['reader']}", {"display_name": "Read", "role": "viewer"}),
        ("PUT", f"/api/members/{people['reader']}/state", {"active": False}),
        ("POST", f"/api/members/{people['reader']}/reset-password", None),
    ]:
        assert (
            client.request(method, path, json=body, headers={"X-CSRF-Token": "invalid"}).status_code
            == 403
        )
        assert (
            client.request(
                method, path, json=body, headers={"Origin": "https://untrusted.invalid"}
            ).status_code
            == 403
        )


@pytest.mark.migration
def test_members_migration_roundtrip(settings, monkeypatch, member_digest):
    from app.db import build_engine, session_factory

    monkeypatch.setattr(config, "Settings", lambda: settings)
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "0031")
    engine = build_engine(settings)
    factory = session_factory(engine)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO staff (username, display_name, role, active, version, "
                "created_at, updated_at) VALUES ('legacy', 'Legacy', 'admin', 1, 1, ?, ?)",
                (utc_now().isoformat(), utc_now().isoformat()),
            )
        command.upgrade(cfg, "head")
        with factory() as session:
            assert not session.scalar(select(Staff)).must_change_password
        command.downgrade(cfg, "0031")
        assert "must_change_password" not in [
            c["name"] for c in inspect(engine).get_columns("staff")
        ]
        assert "login_guards" not in inspect(engine).get_table_names()
        command.upgrade(cfg, "head")
        with factory.begin() as session:
            staff = session.scalar(select(Staff))
            assert not staff.must_change_password
            staff.must_change_password = True
            session.add(
                LoginGuard(account_key=secrets.token_hex(32), failures=5, locked_until=utc_now())
            )
        with factory.begin() as session:
            set_password(session, "legacy", SecretStr(secrets.token_urlsafe(24)))
        with factory() as session:
            assert not session.scalar(select(Staff)).must_change_password
            assert session.scalar(select(func.count()).select_from(Staff)) == 1
    finally:
        engine.dispose()

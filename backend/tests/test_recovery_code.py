"""Administrator recovery codes: one-time use, shared lockout, no account disclosure."""

from datetime import timedelta

import test_members
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from test_members import audit_text, sign_in

from app.main import create_app
from app.models import AuthSession, Staff
from app.models.auth import LoginGuard
from app.models.base import utc_now

# 共用成員測試的帳號與品牌；以變數引用，參數同名不算重複匯入。
member_password = test_members.member_password
member_digest = test_members.member_digest
people = test_members.people

NEW_PASSWORD = "recovered-password-0001"


def create_code(client, password):
    return client.post(
        "/api/auth/recovery-code", json={"current_password": password.get_secret_value()}
    )


def recover(client, username, code, new_password=NEW_PASSWORD):
    csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    return client.post(
        "/api/auth/recover",
        headers={"X-CSRF-Token": csrf},
        json={"username": username, "recovery_code": code, "new_password": new_password},
    )


def anonymous(client):
    return TestClient(create_app(client.app.state.settings))


def test_admin_recovers_with_one_time_code(client, people, member_password):
    assert client.get("/api/auth/recovery-code").json() == {
        "configured": False,
        "created_at": None,
    }
    assert create_code(client, SecretStr("wrong-password")).status_code == 422
    result = create_code(client, member_password)
    assert result.status_code == 200
    code = result.json()["recovery_code"]
    assert len(code) == 23 and code.count("-") == 3
    assert client.get("/api/auth/recovery-code").json()["configured"] is True
    with client.app.state.session_factory() as session:
        stored = session.get(Staff, people["owner"]).recovery_code_hash
        assert stored and code not in stored
    assert code not in audit_text(client)
    with anonymous(client) as other:
        # 抄寫時用小寫、去掉分隔線也能使用。
        assert recover(other, " OWNER ", code.replace("-", "").lower()).status_code == 204
        assert sign_in(other, "owner", SecretStr(NEW_PASSWORD)).status_code == 200
        assert recover(other, "owner", code).status_code == 401
    # 原本的登入全部失效，復原碼已用掉。
    assert client.get("/api/auth/me").status_code == 401
    with client.app.state.session_factory() as session:
        staff = session.get(Staff, people["owner"])
        assert staff.recovery_code_hash is None
    assert "auth.password_recovered" in audit_text(client)
    assert NEW_PASSWORD not in audit_text(client)


def test_new_code_replaces_old_one(client, people, member_password):
    first = create_code(client, member_password).json()["recovery_code"]
    second = create_code(client, member_password).json()["recovery_code"]
    with anonymous(client) as other:
        assert recover(other, "owner", first).status_code == 401
        assert recover(other, "owner", second).status_code == 204


def test_only_active_admins_can_create_or_use_codes(client, people, member_password):
    code = create_code(client, member_password).json()["recovery_code"]
    with anonymous(client) as other:
        assert sign_in(other, "assistant", member_password).status_code == 200
        assert other.get("/api/auth/recovery-code").status_code == 403
        assert create_code(other, member_password).status_code == 403
    with client.app.state.session_factory.begin() as session:
        session.get(Staff, people["owner"]).active = False
    with anonymous(client) as other:
        response = recover(other, "owner", code)
        assert response.status_code == 401
        assert response.json()["detail"] == recover(other, "nobody", code).json()["detail"]


def test_recovery_shares_login_lockout(client, people, member_password):
    code = create_code(client, member_password).json()["recovery_code"]
    with anonymous(client) as other:
        for _ in range(5):
            assert recover(other, "owner", "AAAAA-AAAAA-AAAAA-AAAAA").status_code == 401
        # 鎖定期間正確的復原碼與密碼都無效，避免兩個入口疊加猜測次數。
        assert recover(other, "owner", code).status_code == 401
        assert sign_in(other, "owner", member_password).status_code == 401
    with client.app.state.session_factory.begin() as session:
        guard = session.scalar(select(LoginGuard))
        guard.locked_until = utc_now() - timedelta(seconds=1)
    with anonymous(client) as other:
        assert recover(other, "owner", code).status_code == 204
    with client.app.state.session_factory() as session:
        assert session.scalar(select(LoginGuard)).failures == 0


def test_recovery_requires_csrf_origin_and_valid_password(client, people, member_password):
    code = create_code(client, member_password).json()["recovery_code"]
    with anonymous(client) as other:
        body = {"username": "owner", "recovery_code": code, "new_password": NEW_PASSWORD}
        assert other.post("/api/auth/recover", json=body).status_code == 403
        csrf = other.get("/api/auth/csrf").json()["csrf_token"]
        assert other.post(
            "/api/auth/recover",
            json=body,
            headers={"X-CSRF-Token": csrf, "Origin": "https://untrusted.invalid"},
        ).status_code == 403
        assert recover(other, "owner", code, "short").status_code == 422
        # 新密碼不合格不會耗用復原碼。
        assert recover(other, "owner", code).status_code == 204
    with client.app.state.session_factory() as session:
        assert not session.scalars(
            select(AuthSession).where(AuthSession.staff_id == people["owner"])
        ).all()

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from app.models import Account, Brand, Message, PriceItem, Staff
from app.services.passwords import create_admin, set_password, verify_password


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

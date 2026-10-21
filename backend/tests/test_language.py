"""Interface language preference: every role can set its own, nothing else changes."""

import pytest
import test_members
from fastapi.testclient import TestClient
from test_members import sign_in

from app.main import create_app

member_password = test_members.member_password
member_digest = test_members.member_digest
people = test_members.people


def test_language_defaults_to_empty_and_is_returned_on_login(client, people, member_password):
    assert client.get("/api/auth/me").json()["language"] is None
    assert client.put("/api/auth/language", json={"language": "ja"}).json()["language"] == "ja"
    with TestClient(create_app(client.app.state.settings)) as other:
        assert sign_in(other, "owner", member_password).json()["user"]["language"] == "ja"


@pytest.mark.parametrize("username", ["owner", "assistant", "reader"])
def test_every_role_sets_only_its_own_language(client, people, member_password, username):
    with TestClient(create_app(client.app.state.settings)) as other:
        assert sign_in(other, username, member_password).status_code == 200
        result = other.put("/api/auth/language", json={"language": "en"})
        assert result.status_code == 200 and result.json()["language"] == "en"
    assert client.get("/api/auth/me").json()["language"] == ("en" if username == "owner" else None)


def test_language_rejects_unknown_values_and_requires_csrf(client, people):
    assert client.put("/api/auth/language", json={"language": "fr"}).status_code == 422
    assert client.put("/api/auth/language", json={"language": "en", "x": 1}).status_code == 422
    assert (
        client.put(
            "/api/auth/language", json={"language": "en"}, headers={"X-CSRF-Token": "invalid"}
        ).status_code
        == 403
    )
    assert (
        client.put(
            "/api/auth/language", json={"language": "en"},
            headers={"Origin": "https://untrusted.invalid"},
        ).status_code
        == 403
    )
    with TestClient(create_app(client.app.state.settings)) as anonymous:
        result = anonymous.put("/api/auth/language", json={"language": "en"})
        assert result.status_code in {401, 403}
    assert client.get("/api/auth/me").json()["language"] is None

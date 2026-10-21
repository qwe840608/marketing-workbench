import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_auth import auth_data as auth_data
from test_auth import password as password
from test_auth import password_digest as password_digest

from app.config import Settings
from app.main import create_app
from app.services.auth import secure_cookie

LOCAL = "http://127.0.0.1:8000"
REMOTE = "https://mwb.example.ts.net"


@pytest.mark.parametrize("origin", [LOCAL, REMOTE])
def test_allowed_origin_login_logout_and_cookie(migrated, client, auth_data, password, origin):
    config = migrated.model_copy(
        update={
            "app_origin": f"{LOCAL},{REMOTE}",
            "allowed_hosts": ["127.0.0.1", "mwb.example.ts.net"],
            "session_cookie_secure": True,
        }
    )
    with TestClient(create_app(config), base_url=origin) as browser:
        initial = browser.get("/api/auth/csrf", headers={"Origin": origin})
        assert initial.status_code == 200
        cookie = initial.headers["set-cookie"].lower()
        assert ("; secure" in cookie) == origin.startswith("https")
        assert "httponly" in cookie and "samesite=strict" in cookie and "domain=" not in cookie
        credentials = {"username": "admin", "password": password.get_secret_value()}
        assert browser.post("/api/auth/login", json=credentials).status_code == 403
        assert (
            browser.post(
                "/api/auth/login",
                json=credentials,
                headers={"Origin": origin, "X-CSRF-Token": "wrong"},
            ).status_code
            == 403
        )
        logged = browser.post(
            "/api/auth/login",
            json=credentials,
            headers={"Origin": origin, "X-CSRF-Token": initial.json()["csrf_token"]},
        )
        assert logged.status_code == 200
        assert browser.get("/api/auth/me").status_code == 200
        csrf = logged.json()["csrf_token"]
        for bad in ("https://mwb.example.ts.net.evil.test", "https://other.ts.net", "null"):
            assert (
                browser.post(
                    "/api/auth/logout",
                    headers={"Origin": bad, "X-CSRF-Token": csrf},
                ).status_code
                == 403
            )
        assert (
            browser.post(
                "/api/auth/logout",
                headers={"Origin": origin, "X-CSRF-Token": csrf, "Sec-Fetch-Site": "cross-site"},
            ).status_code
            == 403
        )
        logged_out = browser.post(
            "/api/auth/logout",
            headers={"Origin": origin, "X-CSRF-Token": csrf},
        )
        assert logged_out.status_code == 204
        assert ("; secure" in logged_out.headers["set-cookie"].lower()) == origin.startswith(
            "https"
        )
        assert browser.get("/api/auth/me").status_code == 401
        assert browser.get("/api/health", headers={"Host": "evil.test"}).status_code == 400


def test_origin_normalization_and_primary_link():
    config = Settings(
        _env_file=None,
        app_origin=f" {LOCAL}/ , https://MWB.example.ts.net:443/, {LOCAL}",
        session_cookie_secure=True,
    )
    assert config.app_origins == (LOCAL, REMOTE)
    assert config.backoffice_origin == REMOTE
    assert not secure_cookie(config, LOCAL)
    assert secure_cookie(config, "http://127.0.0.1:9000")
    assert secure_cookie(config, "http://mwb.example.ts.net")
    assert secure_cookie(config, REMOTE)
    assert Settings(_env_file=None, app_origin=LOCAL).app_origins == (LOCAL,)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_origin=f"{LOCAL},{REMOTE}", session_cookie_secure=False)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "*",
        f"{LOCAL},",
        f"{LOCAL},https://*.ts.net",
        "https://user:pass@example.ts.net",
        "https://example.ts.net/path",
        "https://example.ts.net?token=x",
        "https://example.ts.net#x",
        "https://example.ts.net:bad",
        "https://exa\nmple.ts.net",
        "https://example.ts.net:0",
    ],
)
def test_invalid_origin_configuration_rejected(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_origin=value, session_cookie_secure=True)

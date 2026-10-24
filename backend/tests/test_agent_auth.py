"""Synthetic OAuth, authorization boundary and real SDK transport acceptance."""

import asyncio
import base64
import hashlib
import json
import secrets
import socket
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest
import uvicorn
from alembic import command
from alembic.config import Config
from conftest import login as shared_login
from fastapi.testclient import TestClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import SecretStr
from sqlalchemy import inspect, select

from app.db import build_engine
from app.main import create_app
from app.models import AuditLog, Brand, Staff, StaffBrand
from app.models.agent_auth import AgentCode, AgentCredential, AgentGrant, OAuthClient, OAuthRequest
from app.models.base import utc_now
from app.services import agent_auth
from app.services.passwords import hash_password

ORIGIN = "http://127.0.0.1:8123"
OFFICE = "https://office.example.test"
REDIRECT = "http://localhost:41231/callback"


def login(client, username, password):
    client.headers.update(shared_login(client, username, password, origin=None))


@pytest.fixture
def agent_client(migrated):
    migrated.app_origin = ORIGIN + ",http://localhost:8123," + OFFICE
    migrated.allowed_hosts = ["127.0.0.1", "localhost", "office.example.test", "other.example.test"]
    password = secrets.token_urlsafe(24)
    with TestClient(create_app(migrated), base_url=ORIGIN) as client:
        with client.app.state.session_factory.begin() as session:
            brand = Brand(slug="agent-brand", name="隔離品牌")
            users = [Staff(username=name, display_name="隔離" + name, role=role,
                           password_hash=hash_password(SecretStr(password)))
                     for name, role in (("agent-owner", "admin"), ("agent-reader", "viewer"),
                                        ("agent-marketer", "marketing"))]
            session.add_all([brand, *users])
            session.flush()
            for user in users[1:]:
                session.add(StaffBrand(staff_id=user.id, brand_id=brand.id))
            client.ids = {user.username: user.id for user in users}
            client.brand_id = brand.id
        client.password = password
        login(client, "agent-owner", password)
        yield client


def register(client, **changes):
    body = {"client_name": "隔離 Agent", "redirect_uris": [REDIRECT], **changes}
    return client.post("/oauth/register", json=body)


def authorize(client, **changes):
    client_id = register(client).json()["client_id"]
    verifier = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    params = {"client_id": client_id, "redirect_uri": REDIRECT,
              "response_type": "code", "code_challenge": challenge.decode(),
              "code_challenge_method": "S256", "state": "原樣 state + / ?", "resource": ORIGIN +
              "/mcp", **changes}
    response = client.get("/oauth/authorize?" + urlencode(params), follow_redirects=False)
    return params, verifier, response


def approved(client, **changes):
    params, verifier, response = authorize(client, **changes)
    assert response.status_code == 303
    handle = parse_qs(urlsplit(response.headers["location"]).query)["agent_authorize"][0]
    approval = client.get("/api/agent/authorization", params={"request_id": handle})
    assert approval.status_code == 200
    assert approval.headers["x-frame-options"] == "DENY"
    decision = client.post("/api/agent/authorization/decision", data={"request_id": handle,
        "approve": "true", "csrf_token": client.headers["X-CSRF-Token"]},
        follow_redirects=False)
    assert decision.status_code == 200, decision.text
    assert decision.headers["cache-control"] == "no-store"
    location = decision.json()["location"]
    assert location.startswith(REDIRECT + "?")
    query = parse_qs(urlsplit(location).query)
    assert query["state"] == [params["state"]]
    return {"grant_type": "authorization_code", "client_id": params["client_id"],
            "redirect_uri": params["redirect_uri"], "code_verifier": verifier,
            "code": query["code"][0], "resource": ORIGIN + "/mcp"}


def exchange(client):
    values = approved(client)
    response = client.post("/oauth/token", data=values)
    assert response.status_code == 200, response.text
    return values, response.json()


def mcp_call(client, token, method="tools/call", **params):
    response = client.post("/mcp", headers={"Authorization": "Bearer " + token,
        "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"},
        json={"jsonrpc": "2.0", "id": 1, "method": method,
              "params": params or {"name": "get_server_info", "arguments": {}}})
    return response


@pytest.mark.parametrize("origin", [ORIGIN, "http://localhost:8123", OFFICE])
def test_metadata_and_origins(agent_client, origin):
    response = agent_client.get(origin + "/.well-known/oauth-protected-resource/mcp")
    assert response.status_code == 200
    assert response.json()["resource"] == origin + "/mcp"
    assert response.json()["authorization_servers"] == [origin]
    root = agent_client.get(origin + "/.well-known/oauth-protected-resource")
    assert root.json() == response.json()
    metadata = agent_client.get(origin + "/.well-known/oauth-authorization-server").json()
    assert metadata["issuer"] == origin
    assert metadata["code_challenge_methods_supported"] == ["S256"]
    assert metadata["token_endpoint_auth_methods_supported"] == ["none"]
    assert agent_client.get(origin + "/mcp").status_code == 401
    assert agent_client.get(origin + "/mcp").headers["www-authenticate"] == (
        'Bearer resource_metadata="' + origin + '/.well-known/oauth-protected-resource/mcp"')


@pytest.mark.parametrize("path", ["/mcp", "/oauth/authorize", "/oauth/register", "/oauth/token",
    "/oauth/revoke", "/.well-known/oauth-protected-resource/mcp",
    "/.well-known/oauth-protected-resource", "/.well-known/oauth-authorization-server"])
def test_bad_host(agent_client, path):
    response = agent_client.request("POST" if path in {"/oauth/register", "/oauth/token",
        "/oauth/revoke"} else "GET", "http://other.example.test" + path,
        json={"redirect_uris": [REDIRECT]} if path == "/oauth/register" else None)
    assert response.status_code in {400, 404}


@pytest.mark.parametrize("uri", ["https://localhost:123/cb", "http://example.test:123/cb",
    "http://localhost/cb", "http://127.0.0.2:123/cb", "http://user@localhost:123/cb",
    "http://localhost:123/cb#fragment", "http://localhost:123/cb\n", "http://localhost:99999/cb"])
def test_dcr_rejects_nonloopback(agent_client, uri):
    response = register(agent_client, redirect_uris=[REDIRECT, uri])
    assert response.status_code == 400
    assert response.json() == {"error": "invalid_redirect_uri"}


@pytest.mark.parametrize("changes", [{"redirect_uris": []},
    {"token_endpoint_auth_method": "client_secret_basic"}, {"grant_types": ["implicit"]},
    {"response_types": ["token"]}])
def test_dcr_metadata_errors_are_standard_and_secret_free(agent_client, changes):
    response = register(agent_client, **changes)
    assert response.status_code == 400
    assert response.json() == {"error": "invalid_client_metadata"}


@pytest.mark.parametrize("uri", [REDIRECT, "http://127.0.0.1:32112/cb", "http://[::1]:32112/cb"])
def test_dcr_loopback_and_name(agent_client, uri):
    response = register(agent_client, redirect_uris=[uri], client_name="A\n\u0000B" + "c" * 150)
    assert response.status_code == 201
    assert len(response.json()["client_name"]) == 100
    assert "\n" not in response.json()["client_name"]


@pytest.mark.parametrize("changes", [{"code_challenge_method": "plain"}, {"state": ""},
    {"resource": OFFICE + "/other"}, {"redirect_uri": "http://localhost:7777/other"},
    {"response_type": "token"}, {"code_challenge": "bad"}])
def test_authorize_rejects_invalid(agent_client, changes):
    assert authorize(agent_client, **changes)[2].status_code in {400, 422}


def test_redirect_variable_port_and_exact_other_parts(agent_client):
    response = register(agent_client)
    verifier = secrets.token_urlsafe(32)
    params = {"client_id": response.json()["client_id"], "redirect_uri": REDIRECT.replace(
        "41231", "52222"), "response_type": "code", "state": "port-state",
        "code_challenge_method": "S256", "code_challenge": base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")}
    response = agent_client.get("/oauth/authorize", params=params, follow_redirects=False)
    assert response.status_code == 303
    for suffix in ("?query=1", "/", "#fragment", "?", "#"):
        params["redirect_uri"] = REDIRECT + suffix
        assert agent_client.get("/oauth/authorize", params=params,
                                follow_redirects=False).status_code == 400


def test_concurrent_code_and_refresh_are_atomic(agent_client):
    values = approved(agent_client)
    # Independent requests compete for the same SQLite write lock.
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: agent_client.post("/oauth/token", data=values), range(2)))
    assert sorted(response.status_code for response in results) == [200, 400]
    pair = next(response.json() for response in results if response.status_code == 200)
    body = {"client_id": values["client_id"], "grant_type": "refresh_token",
            "refresh_token": pair["refresh_token"]}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: agent_client.post("/oauth/token", data=body), range(2)))
    assert sorted(response.status_code for response in results) == [200, 400]
    newer = next(response.json() for response in results if response.status_code == 200)
    assert mcp_call(agent_client, newer["access_token"]).status_code == 401


def test_flow_code_replay_wrong_pkce_redirect_and_client(agent_client):
    values = approved(agent_client)
    for changes in ({"code_verifier": "x" * 43}, {"redirect_uri": REDIRECT + "/"},
                    {"client_id": register(agent_client).json()["client_id"]}):
        assert agent_client.post("/oauth/token", data={**values, **changes}).json()["error"] == (
            "invalid_grant")
    response = agent_client.post("/oauth/token", data=values)
    assert response.status_code == 200
    assert response.json()["expires_in"] == 3600
    assert agent_client.post("/oauth/token", data=values).status_code == 400
    token = response.json()["access_token"]
    for origin in (ORIGIN, "http://localhost:8123", OFFICE):
        response = agent_client.post(origin + "/mcp", headers={"Authorization": "Bearer " + token,
            "Accept": "application/json, text/event-stream"}, json={"jsonrpc": "2.0", "id": 1,
            "method": "tools/call", "params": {"name": "get_server_info", "arguments": {}}})
        assert response.status_code == 200, response.text
        assert response.json()["result"]["structuredContent"]["connection"]["kind"] == "oauth"


def test_code_expiry(agent_client):
    values = approved(agent_client)
    with agent_client.app.state.session_factory.begin() as session:
        session.scalar(select(AgentCode)).expires_at = utc_now() - timedelta(seconds=1)
    assert agent_client.post("/oauth/token", data=values).status_code == 400


def test_refresh_rotation_reuse_and_revoke(agent_client):
    values, tokens = exchange(agent_client)
    body = {"grant_type": "refresh_token", "client_id": values["client_id"],
            "refresh_token": tokens["refresh_token"]}
    newer = agent_client.post("/oauth/token", data=body).json()
    assert newer["refresh_token"] != tokens["refresh_token"]
    assert mcp_call(agent_client, newer["access_token"]).status_code == 200
    assert agent_client.post("/oauth/token", data=body).status_code == 400
    for token in (tokens["access_token"], newer["access_token"]):
        assert mcp_call(agent_client, token).status_code == 401
    assert agent_client.post("/oauth/token", data={**body,
        "refresh_token": newer["refresh_token"]}).status_code == 400
    _, other = exchange(agent_client)
    assert agent_client.post("/oauth/revoke", data={"client_id": values["client_id"],
        "token": other["access_token"]}).status_code == 200
    assert mcp_call(agent_client, other["access_token"]).status_code == 200
    with agent_client.app.state.session_factory() as session:
        client_id = session.scalars(select(OAuthClient.client_id).order_by(
            OAuthClient.id.desc())).first()
    assert agent_client.post("/oauth/revoke", data={"client_id": client_id,
        "token": other["refresh_token"]}).status_code == 200
    assert mcp_call(agent_client, other["access_token"]).status_code == 401


def test_idle_and_access_expiry(agent_client):
    _, pair = exchange(agent_client)
    connection = agent_client.post("/api/agent/connections", json={"name": "隔離桌面"}).json()
    with agent_client.app.state.session_factory.begin() as session:
        for grant in session.scalars(select(AgentGrant)):
            grant.last_used_at = utc_now() - timedelta(days=30)
    assert mcp_call(agent_client, pair["access_token"]).status_code == 401
    assert mcp_call(agent_client, connection["token"]).status_code == 401
    values, pair = exchange(agent_client)
    with agent_client.app.state.session_factory.begin() as session:
        for row in session.scalars(select(AgentCredential).where(
                AgentCredential.token_hash.in_([agent_auth.digest(pair["access_token"]),
                                                agent_auth.digest(pair["refresh_token"])]))):
            row.expires_at = utc_now() - timedelta(seconds=1)
    assert mcp_call(agent_client, pair["access_token"]).status_code == 401
    assert agent_client.post("/oauth/token", data={"client_id": values["client_id"],
        "grant_type": "refresh_token", "refresh_token": pair["refresh_token"]}).status_code == 400


def test_token_once_isolation_revocation_and_throttle(agent_client):
    token = agent_client.post("/api/agent/connections", json={"name": "隔離桌面"}).json()["token"]
    assert token.startswith("mwb_") and len(token) == 47
    listing = agent_client.get("/api/agent/connections")
    assert token not in listing.text
    identity = listing.json()[0]["id"]
    factory = agent_client.app.state.session_factory
    with factory.begin() as session:
        session.get(AgentGrant, identity).last_used_at -= timedelta(minutes=2)
    info = mcp_call(agent_client, token).json()["result"]["structuredContent"]
    assert info["server_version"] == "0.1.0" and info["mcp_api_version"] == "1"
    assert info["connection"] == {"kind": "token", "name": "隔離桌面"}
    with factory() as session:
        previous = session.get(AgentGrant, identity).last_used_at
        assert session.scalar(select(AgentCredential)).token_hash != token
    assert mcp_call(agent_client, token).status_code == 200
    with factory() as session:
        assert session.get(AgentGrant, identity).last_used_at == previous
    login(agent_client, "agent-reader", agent_client.password)
    assert agent_client.get("/api/agent/connections").json() == []
    assert agent_client.delete(f"/api/agent/connections/{identity}").status_code == 404
    response = agent_client.post("/api/agent/connections", json={"name": "唯讀"})
    viewer_token = response.json()["token"]
    assert mcp_call(agent_client, viewer_token).json()["result"]["structuredContent"]["user"][
        "role"] == "viewer"
    agent_client.cookies.clear()
    for path in ("/api/auth/me", "/api/brands", "/api/agent/connections", "/api/members"):
        response = agent_client.get(path, headers={"Authorization": "Bearer " + token})
        assert response.status_code == 401
    login(agent_client, "agent-owner", agent_client.password)
    assert agent_client.delete(f"/api/agent/connections/{identity}").status_code == 204
    assert mcp_call(agent_client, token).status_code == 401


@pytest.mark.parametrize("action", ["disable", "reset", "admin-revoke", "change-password"])
def test_member_lifecycle_revokes(agent_client, action):
    login(agent_client, "agent-reader", agent_client.password)
    _, pair = exchange(agent_client)
    token = agent_client.post("/api/agent/connections", json={"name": "隔離"}).json()["token"]
    identity = agent_client.ids["agent-reader"]
    if action == "change-password":
        assert agent_client.post("/api/auth/change-password", json={
            "current_password": agent_client.password, "new_password": secrets.token_urlsafe(24)
        }).status_code == 200
    else:
        login(agent_client, "agent-owner", agent_client.password)
        path = f"/api/members/{identity}/"
        response = agent_client.put(path + "state", json={"active": False}) if action == (
            "disable") else agent_client.post(path + (
                "reset-password" if action == "reset" else "revoke-connections"))
        assert response.status_code in {200, 204}
    assert mcp_call(agent_client, pair["access_token"]).status_code == 401
    assert mcp_call(agent_client, token).status_code == 401


def test_current_role_and_brands_and_disabled_directly(agent_client):
    login(agent_client, "agent-marketer", agent_client.password)
    token = agent_client.post("/api/agent/connections", json={"name": "隔離"}).json()["token"]
    identity = agent_client.ids["agent-marketer"]
    info = mcp_call(agent_client, token).json()["result"]["structuredContent"]
    assert info["user"]["role"] == "marketing" and len(info["brands"]) == 1
    login(agent_client, "agent-owner", agent_client.password)
    assert agent_client.put(f"/api/members/{identity}", json={"display_name": "新名稱",
        "role": "viewer", "brand_ids": []}).status_code == 200
    info = mcp_call(agent_client, token).json()["result"]["structuredContent"]
    assert info["user"] == {"display_name": "新名稱", "role": "viewer", "role_name": None,
                            "permissions": []}
    assert info["brands"] == []
    with agent_client.app.state.session_factory.begin() as session:
        session.get(Staff, identity).active = False
    assert mcp_call(agent_client, token).status_code == 401


def test_consent_deny_csrf_origin_and_viewer(agent_client):
    params, _, response = authorize(agent_client)
    handle = parse_qs(urlsplit(response.headers["location"]).query)["agent_authorize"][0]
    login(agent_client, "agent-reader", agent_client.password)
    values = {"request_id": handle, "approve": "false", "csrf_token": "bad"}
    assert agent_client.post("/api/agent/authorization/decision", data=values).status_code == 403
    values["csrf_token"] = agent_client.headers["X-CSRF-Token"]
    assert agent_client.post("/api/agent/authorization/decision", data=values,
        headers={"Origin": "https://untrusted.invalid"}).status_code == 403
    response = agent_client.post("/api/agent/authorization/decision", data=values,
                                 follow_redirects=False)
    assert response.status_code == 200
    query = parse_qs(urlsplit(response.json()["location"]).query)
    assert query == {"state": [params["state"]], "error": ["access_denied"]}
    assert agent_client.post("/api/agent/authorization/decision", data=values,
                             follow_redirects=False).status_code == 400
    values, pair = exchange(agent_client)
    assert mcp_call(agent_client, pair["access_token"]).json()["result"]["structuredContent"][
        "user"]["role"] == "viewer"
    for method, path in [("POST", "/api/agent/connections"),
                         ("DELETE", "/api/agent/connections/1")]:
        assert agent_client.request(method, path, json={"name": "隔離"},
            headers={"X-CSRF-Token": "bad"}).status_code == 403
    assert agent_client.post("/api/members/1/revoke-connections").status_code == 403


@pytest.mark.parametrize("headers", [{"Host": "public.ngrok.example"}, {"x-mwb-public": "1"},
    {"x-forwarded-for": "203.0.113.8"}])
def test_public_boundary(agent_client, headers):
    for path in ("/mcp", "/oauth/authorize", "/oauth/token", "/oauth/register", "/oauth/revoke",
                 "/.well-known/oauth-authorization-server", "/.well-known/oauth-protected-resource",
                 "/.well-known/oauth-protected-resource/mcp", "/api/agent/authorization/decision"):
        for method in ("GET", "POST"):
            assert agent_client.request(method, path, headers=headers).status_code == 404


def test_public_peer(agent_client):
    with TestClient(create_app(agent_client.app.state.settings), base_url=ORIGIN,
                    client=("203.0.113.8", 53222)) as public:
        for path in ("/mcp", "/oauth/authorize", "/oauth/token", "/oauth/register",
                     "/.well-known/oauth-authorization-server",
                     "/api/agent/authorization/decision"):
            assert public.post(path).status_code == 404


def test_prune_retains_refresh_reuse_and_cleans_stale(agent_client):
    values, pair = exchange(agent_client)
    body = {"client_id": values["client_id"], "grant_type": "refresh_token",
            "refresh_token": pair["refresh_token"]}
    agent_client.post("/oauth/token", data=body)
    stale = register(agent_client).json()["client_id"]
    factory = agent_client.app.state.session_factory
    with factory.begin() as session:
        session.scalar(select(OAuthClient).where(OAuthClient.client_id == stale)).last_used_at -= (
            timedelta(days=31))
        session.scalar(select(AgentCode)).expires_at -= timedelta(days=31)
        query = select(AgentCredential).where(AgentCredential.token_hash == agent_auth.digest(
            pair["refresh_token"]))
        session.scalar(query).expires_at -= timedelta(days=31)
        session.add(OAuthRequest(handle_hash=agent_auth.digest("expired"),
            client_id=session.scalar(select(OAuthClient.id).where(OAuthClient.client_id == stale)),
            redirect_uri=REDIRECT, state="old", challenge="x" * 43,
            expires_at=utc_now() - timedelta(seconds=1)))
    agent_auth.maintain(factory)
    with factory() as session:
        assert session.scalar(select(OAuthClient).where(OAuthClient.client_id == stale)) is None
        assert session.scalar(select(AgentCode)) is None
        assert session.scalar(select(OAuthRequest)) is None
        assert session.scalar(select(AgentCredential).where(AgentCredential.token_hash == (
            agent_auth.digest(pair["refresh_token"])))) is not None
    assert agent_client.post("/oauth/token", data=body).status_code == 400


def test_prune_revokes_approved_but_unredeemed_grants(agent_client):
    exchange(agent_client)
    approved(agent_client)
    factory = agent_client.app.state.session_factory
    agent_auth.maintain(factory)
    assert len(agent_client.get("/api/agent/connections").json()) == 2
    with factory.begin() as session:
        for code in session.scalars(select(AgentCode)):
            code.expires_at = utc_now() - timedelta(seconds=1)
    agent_auth.maintain(factory)
    assert len(agent_client.get("/api/agent/connections").json()) == 1


def test_secret_serialization_logs_audit_and_database(agent_client, caplog):
    values, pair = exchange(agent_client)
    token = agent_client.post("/api/agent/connections", json={"name": "隔離"}).json()["token"]
    responses = [agent_client.get(path).text for path in ("/api/agent/connections", "/api/members",
        "/.well-known/oauth-authorization-server", "/.well-known/oauth-protected-resource/mcp")]
    responses.append(mcp_call(agent_client, token).text)
    responses.append(agent_client.post("/oauth/token", data={**values,
                                                           "code_verifier": "bad"}).text)
    factory = agent_client.app.state.session_factory
    with factory() as session:
        responses.append(json.dumps([row.detail_json for row in session.scalars(select(AuditLog))]))
        for table in (AgentCredential, AgentCode):
            for row in session.scalars(select(table)):
                responses.append(str(row.__dict__))
        assert "agent_grants" in inspect(session.get_bind()).get_table_names()
    responses.append(caplog.text)
    responses.append(agent_client.app.state.settings.log_path.read_text(encoding="utf-8"))
    serialized = "\n".join(responses)
    for secret in (values["code"], values["code_verifier"], pair["access_token"],
                   pair["refresh_token"], token):
        assert secret not in serialized


def test_sdk_end_to_end_random_port(agent_client):
    token = agent_client.post("/api/agent/connections", json={"name": "隔離 SDK"}).json()["token"]
    bound = socket.socket()
    bound.bind(("127.0.0.1", 0))
    port = bound.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(agent_client.app.state.settings),
        log_level="warning", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [bound]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started

        async def exercise():
            async with httpx.AsyncClient(headers={"Authorization": "Bearer " + token}) as http:
                async with streamable_http_client(f"http://127.0.0.1:{port}/mcp",
                                                   http_client=http) as (read, write, _):
                    async with ClientSession(read, write) as sdk:
                        initialized = await sdk.initialize()
                        assert initialized.serverInfo.name == "marketing-workbench"
                        assert initialized.serverInfo.version == agent_auth.SERVER_VERSION
                        tools = await sdk.list_tools()
                        from app.services.agent_tools import SPECS

                        assert {tool.name for tool in tools.tools} == set(SPECS)
                        assert len(tools.tools) == len(SPECS)
                        assert tools.tools[0].annotations.readOnlyHint is True
                        result = await sdk.call_tool("get_server_info", {})
                        assert not result.isError
                        assert result.structuredContent["connection"]["name"] == "隔離 SDK"
        asyncio.run(exercise())
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        bound.close()
        assert not thread.is_alive()


@pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
@pytest.mark.parametrize("authorization", [None, "Bearer invalid", "Basic invalid"])
def test_mcp_always_requires_bearer(agent_client, method, authorization):
    headers = {"Authorization": authorization} if authorization else {}
    response = agent_client.request(method, "/mcp", headers=headers)
    assert response.status_code == 401
    assert "resource_metadata=" in response.headers["www-authenticate"]


def test_mcp_origin_guard_and_no_cookie_fallback(agent_client):
    token = agent_client.post("/api/agent/connections", json={"name": "隔離"}).json()["token"]
    assert agent_client.get("/mcp").status_code == 401
    response = agent_client.post("/mcp", headers={"Authorization": "Bearer " + token,
        "Accept": "application/json, text/event-stream", "Origin": "https://untrusted.invalid"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 403


def test_mcp_invalid_tool_input_never_reflects_secrets(agent_client):
    token = agent_client.post("/api/agent/connections", json={"name": "隔離"}).json()["token"]
    for name, arguments in (("get_server_info", {token: token}), (token, {})):
        response = agent_client.post("/mcp", headers={"Authorization": "Bearer " + token,
            "Accept": "application/json, text/event-stream"}, json={"jsonrpc": "2.0", "id": 1,
            "method": "tools/call", "params": {"name": name, "arguments": arguments}})
        assert response.status_code == 200
        assert response.json()["result"]["isError"] is True
        assert token not in response.text


def test_registration_audit_identity_and_consent_csrf_bound_to_session(agent_client):
    params, verifier, response = authorize(agent_client)
    handle = parse_qs(urlsplit(response.headers["location"]).query)["agent_authorize"][0]
    previous_csrf = agent_client.headers["X-CSRF-Token"]
    agent_client.cookies.clear()
    response = agent_client.get("/api/agent/authorization", params={"request_id": handle})
    assert response.status_code == 401
    login(agent_client, "agent-reader", agent_client.password)
    assert agent_client.post("/api/agent/authorization/decision", data={"request_id": handle,
        "approve": "true", "csrf_token": previous_csrf}, follow_redirects=False).status_code == 403
    with agent_client.app.state.session_factory() as session:
        registration = session.scalar(select(AuditLog).where(AuditLog.action == "agent.register"))
        assert registration.actor == f"staff:{agent_client.ids['agent-owner']}"
    agent_client.cookies.clear()
    assert register(agent_client).status_code == 201
    with agent_client.app.state.session_factory() as session:
        last = session.scalars(select(AuditLog).where(AuditLog.action == "agent.register")
                               .order_by(AuditLog.id.desc())).first()
        assert last.actor == "anonymous"



@pytest.mark.parametrize("endpoint", ["token", "decision"])
def test_form_writes_wait_for_lock_off_event_loop(agent_client, endpoint):
    if endpoint == "token":
        path, data = "/oauth/token", approved(agent_client)
    else:
        _, _, response = authorize(agent_client)
        handle = parse_qs(urlsplit(response.headers["location"]).query)["agent_authorize"][0]
        path, data = "/api/agent/authorization/decision", {"request_id": handle,
            "approve": "true", "csrf_token": agent_client.headers["X-CSRF-Token"]}
    holder = sqlite3.connect(str(agent_client.app.state.settings.database_path),
                             autocommit=True)
    holder.execute("BEGIN IMMEDIATE")

    async def release():
        # The lock holder needs this loop; a route waiting for the lock on it would deadlock.
        await asyncio.sleep(0.5)
        holder.execute("COMMIT")

    async def scenario():
        transport = httpx.ASGITransport(app=agent_client.app)
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN,
                                     cookies=dict(agent_client.cookies),
                                     headers={"X-CSRF-Token": agent_client.headers[
                                         "X-CSRF-Token"]}) as client:
            response, _ = await asyncio.gather(client.post(path, data=data), release())
        return response

    try:
        started = time.monotonic()
        response = asyncio.run(scenario())
    finally:
        holder.close()
    assert response.status_code == 200, response.text
    assert time.monotonic() - started < 5


@pytest.mark.migration
def test_agent_migration_upgrade_downgrade_and_schema(migrated):
    configuration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    engine = build_engine(migrated)
    tables = {"agent_oauth_clients", "agent_grants", "agent_oauth_requests", "agent_codes",
              "agent_credentials"}
    try:
        assert tables.issubset(inspect(engine).get_table_names())
        command.downgrade(configuration, "0036")
        assert tables.isdisjoint(inspect(engine).get_table_names())
        command.upgrade(configuration, "head")
        assert tables.issubset(inspect(engine).get_table_names())
        for name in tables:
            assert all(column["type"].length == 64 for column in inspect(engine).get_columns(name)
                       if column["name"] in {"token_hash", "code_hash", "handle_hash"})
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    finally:
        engine.dispose()

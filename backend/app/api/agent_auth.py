from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import Database
from app.schemas.agent_auth import (
    ApprovalDecision,
    AuthorizationParams,
    ClientRegistration,
    ConnectionCreate,
)
from app.services import agent_auth as service
from app.services.agent_mcp import MCPResponse


def check_internal_origin(request: Request):
    if request.url.path.startswith(("/oauth/", "/.well-known/")) or request.url.path == "/mcp":
        service.origin_for(request)


router = APIRouter(dependencies=[Depends(check_internal_origin)])


async def form_values(request):
    if hasattr(request.state, "agent_form"):
        return request.state.agent_form
    if request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
        raise HTTPException(400, "invalid_request")
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 16384:
            raise HTTPException(413, "invalid_request")
    try:
        values = parse_qs(data.decode("utf-8"), keep_blank_values=True, max_num_fields=20)
    except (UnicodeDecodeError, ValueError):
        raise HTTPException(400, "invalid_request") from None
    if any(len(value) != 1 for value in values.values()):
        raise HTTPException(400, "invalid_request")
    request.state.agent_form = {key: value[0] for key, value in values.items()}
    return request.state.agent_form


async def get_agent_access(request: Request, session: Database):
    csrf = None
    if request.url.path == "/api/agent/authorization/decision":
        csrf = (await form_values(request)).get("csrf_token", "")
    # A write check waits for the SQLite lock; off the loop so the holder can still release it.
    return await run_in_threadpool(service.web_staff, request, session,
                                   write=request.method != "GET", csrf=csrf)


member_guard = [Depends(get_agent_access)]


@router.get("/.well-known/oauth-protected-resource")
@router.get("/.well-known/oauth-protected-resource/mcp")
def resource_metadata(request: Request):
    origin = service.origin_for(request)
    return {"resource": origin + "/mcp", "authorization_servers": [origin],
            "bearer_methods_supported": ["header"], "scopes_supported": ["mcp"]}


@router.get("/.well-known/oauth-authorization-server")
def authorization_metadata(request: Request):
    origin = service.origin_for(request)
    return {"issuer": origin, "authorization_endpoint": origin + "/oauth/authorize",
            "token_endpoint": origin + "/oauth/token", "registration_endpoint": origin +
            "/oauth/register", "revocation_endpoint": origin + "/oauth/revoke",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_methods_supported": ["none"],
            "revocation_endpoint_auth_methods_supported": ["none"],
            "code_challenge_methods_supported": ["S256"], "scopes_supported": ["mcp"]}


@router.post("/oauth/register", status_code=201)
def register(request: Request, session: Database, body: ClientRegistration):
    try:
        return service.register(request, session, body)
    except HTTPException as error:
        if error.status_code != 400:
            raise
        return JSONResponse({"error": error.detail}, status_code=400)


@router.get("/oauth/authorize")
def authorize(request: Request, session: Database,
              params: Annotated[AuthorizationParams, Depends()]):
    if any(len(request.query_params.getlist(k)) != 1 for k in request.query_params):
        raise HTTPException(400, "invalid_request")
    return RedirectResponse(service.authorization(request, session, params), status_code=303)


@router.post("/oauth/token")
async def token(request: Request, session: Database):
    service.origin_for(request)
    try:
        values = await form_values(request)
        result = await run_in_threadpool(service.token_exchange, request, session, values)
        return JSONResponse(result, headers={"Pragma": "no-cache"})
    except HTTPException as error:
        # RFC 6749 errors have a machine-readable error field and never echo input.
        return JSONResponse({"error": error.detail if error.detail in {
            "invalid_client", "invalid_grant", "unsupported_grant_type", "invalid_request"
        } else "invalid_request"}, status_code=error.status_code)


@router.post("/oauth/revoke", status_code=200)
async def revoke(request: Request, session: Database):
    values = await form_values(request)
    await run_in_threadpool(service.oauth_revoke, request, session, values)
    return {}


@router.get("/api/agent/authorization", dependencies=member_guard)
def approval(request: Request, session: Database, request_id: str = Query(max_length=43)):
    return service.approval_view(request, session, request_id)


@router.post("/api/agent/authorization/decision", dependencies=member_guard)
async def decision(request: Request, session: Database):
    values = await form_values(request)
    try:
        body = ApprovalDecision(request_id=values.get("request_id"),
                                approve=values.get("approve"))
    except ValidationError:
        raise HTTPException(422, "輸入格式錯誤") from None
    # The approval page hands the loopback callback to the client itself so the browser can
    # finish on the workbench's own completion page instead of the client's English one.
    location = await run_in_threadpool(service.decide, request, session, body,
                                       values.get("csrf_token", ""))
    return JSONResponse({"location": location}, headers={"Cache-Control": "no-store"})


@router.get("/api/agent/connections", dependencies=member_guard)
def connections(request: Request, session: Database):
    staff = service.web_staff(request, session)
    return service.connections(session, staff.id)


@router.post("/api/agent/connections", status_code=201, dependencies=member_guard)
def create_connection(request: Request, session: Database, body: ConnectionCreate):
    return service.create_connection(request, session, body)


@router.delete("/api/agent/connections/{identity}", status_code=204, dependencies=member_guard)
def revoke_connection(request: Request, session: Database, identity: int):
    service.revoke_connection(request, session, identity)


@router.post("/api/members/{identity}/revoke-connections", status_code=204,
             dependencies=member_guard)
def revoke_member(request: Request, session: Database, identity: int):
    service.admin_revoke(request, session, identity)


@router.get("/mcp", include_in_schema=False)
@router.post("/mcp", include_in_schema=False)
@router.delete("/mcp", include_in_schema=False)
async def mcp(request: Request):
    origin = service.origin_for(request)
    header = request.headers.get("authorization", "")
    parts = header.split(" ")
    token = parts[1] if len(parts) == 2 and parts[0].lower() == "bearer" else None
    if len(request.headers.getlist("authorization")) > 1:
        token = None
    factory = request.app.state.session_factory
    identity = await run_in_threadpool(service.authenticate, factory, token)
    if identity is None:
        return JSONResponse({"detail": "連線已失效，請重新授權"}, status_code=401,
            headers={"WWW-Authenticate": 'Bearer resource_metadata="' + origin +
                     '/.well-known/oauth-protected-resource/mcp"'})
    versions = request.headers.getlist("x-mwb-plugin-version")
    plugin_version = versions[0] if len(versions) == 1 else "invalid" if versions else None
    return MCPResponse(request.app.state.agent_mcp, factory, identity, origin, plugin_version)


@router.put("/api/agent/uploads/{token}")
async def upload(token: str, request: Request):
    from app.services import agent_publish

    return await agent_publish.upload(request, token)

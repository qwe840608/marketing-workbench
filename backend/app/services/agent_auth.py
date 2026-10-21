"""Internal OAuth 2.1 and connection tokens, independent from browser sessions."""

import base64
import hashlib
import hmac
import re
import secrets
import unicodedata
from datetime import timedelta
from urllib.parse import urlencode, urlsplit

from fastapi import HTTPException
from sqlalchemy import delete, exists, func, select, update

from app.db import ensure_write
from app.models import AuditLog, Brand, Staff
from app.models.agent_auth import AgentCode, AgentCredential, AgentGrant, OAuthClient, OAuthRequest
from app.models.base import utc_now
from app.services import auth
from app.services.access import BrandAccess

SERVER_VERSION = "0.1.0"
MCP_API_VERSION = "1"
IDLE = timedelta(days=30)
TOKEN_PATTERN = re.compile(r"(?:mwb_)?[A-Za-z0-9_-]{43}")


def origin_for(request):
    try:
        origin = str(request.base_url).rstrip("/")
        parts = urlsplit(origin)
        local = (parts.scheme == "http" and parts.hostname in {"127.0.0.1", "localhost"}
                 and parts.port is not None and parts.port > 0
                 and not parts.username and not parts.password)
    except ValueError:
        raise HTTPException(404, "Not Found") from None
    if not local and origin != request.app.state.settings.backoffice_origin:
        raise HTTPException(404, "Not Found")
    return origin


def resource_check(resource, origin):
    if resource is not None and resource != origin + "/mcp":
        raise HTTPException(400, "無效的 MCP 資源")


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def name_for(value):
    return "".join(c for c in value if not unicodedata.category(c).startswith("C")).strip()[:100]


def redirect_parts(uri):
    try:
        parts = urlsplit(uri)
        if (not isinstance(uri, str) or len(uri) > 2048 or parts.scheme != "http"
                or parts.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parts.port is None or parts.port == 0
                or parts.username or parts.password or "#" in uri
                or any(ord(c) < 33 or ord(c) > 126 for c in uri) or "\\" in uri):
            raise ValueError()
        # Exclude the port only; every other URI byte must match the registration.
        match = re.fullmatch(r"(http://(?:127\.0\.0\.1|localhost|\[::1\])):[0-9]+(.*)", uri)
        if match is None:
            raise ValueError()
        return match[1] + ":*" + match[2]
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, "回呼位址必須是含埠號的本機迴路 HTTP 位址") from None


def audit(session, action, staff_id, name, grant_id=None):
    session.add(AuditLog(actor=f"staff:{staff_id}" if staff_id else "anonymous",
                         action="agent." + action, target_type="agent_grant",
                         target_id=grant_id,
                         detail_json={"client_name": name, "grant_id": grant_id}))


def web_staff(request, session, *, write=False, csrf=None):
    if write:
        ensure_write(session)
    staff = auth.current_staff(session, request.cookies.get(auth.COOKIE_NAME))
    if staff.must_change_password:
        raise HTTPException(403, "請先變更密碼")
    from app.api.permissions import require_role

    require_role(request.scope["route"].path, request.method, staff.role)
    if write:
        auth.validate_origin(request.headers.get("origin"), request.headers.get("sec-fetch-site"),
                             request.app.state.settings)
        auth.require_csrf(session, request.cookies.get(auth.COOKIE_NAME),
                          csrf if csrf is not None else request.headers.get("x-csrf-token"))
    return staff


def register(request, session, body):
    origin_for(request)
    if (body.token_endpoint_auth_method != "none"
            or "authorization_code" not in body.grant_types
            or set(body.grant_types) - {"authorization_code", "refresh_token"}
            or body.response_types != ["code"]):
        raise HTTPException(400, "invalid_client_metadata")
    for uri in body.redirect_uris:
        try:
            redirect_parts(uri)
        except HTTPException:
            raise HTTPException(400, "invalid_redirect_uri") from None
    ensure_write(session)
    client = OAuthClient(client_id=secrets.token_urlsafe(24),
                         name=name_for(body.client_name) or "Agent",
                         redirect_uris=body.redirect_uris)
    session.add(client)
    current = auth.find_session(session, request.cookies.get(auth.COOKIE_NAME))
    audit(session, "register", current.staff_id if current else None, client.name)
    session.commit()
    return {"client_id": client.client_id, "client_name": client.name,
            "redirect_uris": client.redirect_uris, "token_endpoint_auth_method": "none",
            "grant_types": body.grant_types, "response_types": ["code"]}


def authorization(request, session, params):
    origin = origin_for(request)
    resource_check(params.resource, origin)
    if (params.response_type != "code" or params.code_challenge_method != "S256"
            or re.fullmatch(r"[A-Za-z0-9_-]{43}", params.code_challenge) is None
            or not params.state or params.scope not in {None, "mcp"}):
        raise HTTPException(400, "需要 state 與 S256 PKCE 授權碼流程")
    canonical = redirect_parts(params.redirect_uri)
    ensure_write(session)
    client = session.scalar(select(OAuthClient).where(OAuthClient.client_id == params.client_id))
    if client is None or canonical not in [redirect_parts(uri) for uri in client.redirect_uris]:
        raise HTTPException(400, "用戶端或回呼位址不符")
    handle = secrets.token_urlsafe(32)
    session.add(OAuthRequest(handle_hash=digest(handle), client_id=client.id,
                             redirect_uri=params.redirect_uri, state=params.state,
                             challenge=params.code_challenge,
                             expires_at=utc_now() + timedelta(minutes=10)))
    client.last_used_at = utc_now()
    session.commit()
    return "/?" + urlencode({"agent_authorize": handle})


def pending(session, handle):
    row = session.scalar(select(OAuthRequest).where(OAuthRequest.handle_hash == digest(handle),
                                                   OAuthRequest.expires_at > utc_now()))
    if row is None:
        raise HTTPException(400, "授權請求已失效，請從應用程式重新連線")
    return row, session.get(OAuthClient, row.client_id)


def approval_view(request, session, handle):
    origin_for(request)
    staff = web_staff(request, session)
    row, client = pending(session, handle)
    return {"client_name": client.name, "redirect_uri": row.redirect_uri,
            "display_name": staff.display_name, "role": staff.role}


def decide(request, session, body, csrf):
    origin_for(request)
    staff = web_staff(request, session, write=True, csrf=csrf)
    row, client = pending(session, body.request_id)
    query = {"state": row.state}
    if body.approve:
        grant = AgentGrant(staff_id=staff.id, client_id=client.id, kind="oauth", name=client.name)
        session.add(grant)
        session.flush()
        code = secrets.token_urlsafe(32)
        session.add(AgentCode(code_hash=digest(code), grant_id=grant.id,
                             redirect_uri=row.redirect_uri, challenge=row.challenge,
                             expires_at=utc_now() + timedelta(minutes=5)))
        query["code"] = code
        audit(session, "approve", staff.id, client.name, grant.id)
    else:
        query["error"] = "access_denied"
        audit(session, "deny", staff.id, client.name)
    # The decision response is the sole authorization-code disclosure, to the approving browser.
    location = row.redirect_uri + ("&" if "?" in row.redirect_uri else "?") + urlencode(query)
    session.delete(row)
    client.last_used_at = utc_now()
    session.commit()
    return location


def valid_grant(session, grant):
    if grant is None or grant.revoked_at is not None or grant.last_used_at <= utc_now() - IDLE:
        return None
    staff = session.get(Staff, grant.staff_id)
    if (staff is None or not staff.active or not staff.password_hash or staff.must_change_password
            or staff.role not in {"admin", "marketing", "viewer"}):
        return None
    return staff


def revoke_grant(session, grant, actor=None, action="revoke"):
    if grant.revoked_at is None:
        grant.revoked_at = utc_now()
        audit(session, action, actor or grant.staff_id, grant.name, grant.id)


def issue_pair(session, grant):
    now = utc_now()
    access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    for kind, value, ttl in (("access", access, timedelta(hours=1)), ("refresh", refresh, IDLE)):
        session.add(AgentCredential(token_hash=digest(value), grant_id=grant.id,
                                    kind=kind, expires_at=now + ttl))
    grant.last_used_at = now
    session.get(OAuthClient, grant.client_id).last_used_at = now
    return {"access_token": access, "refresh_token": refresh, "token_type": "Bearer",
            "expires_in": 3600, "scope": "mcp"}


def token_exchange(request, session, values):
    origin = origin_for(request)
    resource_check(values.get("resource"), origin)
    ensure_write(session)
    client = session.scalar(select(OAuthClient).where(
        OAuthClient.client_id == values.get("client_id")))
    if client is None:
        raise HTTPException(400, "invalid_client")
    kind = values.get("grant_type")
    if kind == "authorization_code":
        row = session.scalar(select(AgentCode).where(
            AgentCode.code_hash == digest(values.get("code", ""))))
        grant = session.get(AgentGrant, row.grant_id) if row else None
        verifier = values.get("code_verifier", "")
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
        if (row is None or row.used_at is not None or row.expires_at <= utc_now()
                or grant.client_id != client.id or not valid_grant(session, grant)
                or row.redirect_uri != values.get("redirect_uri")
                or re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier) is None
                or not hmac.compare_digest(row.challenge.encode(), challenge)):
            raise HTTPException(400, "invalid_grant")
        row.used_at = utc_now()
    elif kind == "refresh_token":
        row = session.scalar(select(AgentCredential).where(
            AgentCredential.token_hash == digest(values.get("refresh_token", "")),
            AgentCredential.kind == "refresh"))
        grant = session.get(AgentGrant, row.grant_id) if row else None
        if row is None or grant.client_id != client.id:
            raise HTTPException(400, "invalid_grant")
        if row.used_at is not None:
            revoke_grant(session, grant, action="refresh_reuse")
            session.commit()
            raise HTTPException(400, "invalid_grant")
        if row.expires_at <= utc_now() or not valid_grant(session, grant):
            raise HTTPException(400, "invalid_grant")
        row.used_at = utc_now()
    else:
        raise HTTPException(400, "unsupported_grant_type")
    result = issue_pair(session, grant)
    session.commit()
    return result


def oauth_revoke(request, session, values):
    origin_for(request)
    ensure_write(session)
    row = session.scalar(select(AgentCredential).where(
        AgentCredential.token_hash == digest(values.get("token", ""))))
    grant = session.get(AgentGrant, row.grant_id) if row else None
    client = session.get(OAuthClient, grant.client_id) if grant and grant.client_id else None
    if client and client.client_id == values.get("client_id"):
        revoke_grant(session, grant)
    session.commit()


def connections(session, staff_id):
    rows = session.scalars(select(AgentGrant).where(AgentGrant.staff_id == staff_id,
        AgentGrant.revoked_at.is_(None), AgentGrant.last_used_at > utc_now() - IDLE)
        .order_by(AgentGrant.id.desc()))
    return [{"id": row.id, "name": row.name, "kind": row.kind,
             "created_at": row.created_at, "last_used_at": row.last_used_at,
             "expires_at": row.last_used_at + IDLE} for row in rows]


def connection_count(session, staff_id):
    return session.scalar(select(func.count()).select_from(AgentGrant).where(
        AgentGrant.staff_id == staff_id, AgentGrant.revoked_at.is_(None),
        AgentGrant.last_used_at > utc_now() - IDLE))


def create_connection(request, session, body):
    staff = web_staff(request, session, write=True)
    name = name_for(body.name)
    if not name:
        raise HTTPException(422, "請輸入連線名稱")
    grant = AgentGrant(staff_id=staff.id, kind="token", name=name)
    session.add(grant)
    session.flush()
    token = "mwb_" + secrets.token_urlsafe(32)
    session.add(AgentCredential(token_hash=digest(token), grant_id=grant.id,
                                kind="token", expires_at=utc_now() + IDLE))
    audit(session, "token_create", staff.id, name, grant.id)
    session.commit()
    return {"token": token}


def revoke_connection(request, session, identity):
    staff = web_staff(request, session, write=True)
    grant = session.get(AgentGrant, identity)
    if grant is None or grant.staff_id != staff.id:
        raise HTTPException(404, "找不到連線")
    revoke_grant(session, grant)
    session.commit()


def revoke_all(session, staff_id, actor=None):
    for grant in session.scalars(select(AgentGrant).where(
            AgentGrant.staff_id == staff_id, AgentGrant.revoked_at.is_(None))):
        revoke_grant(session, grant, actor)


def admin_revoke(request, session, identity):
    staff = web_staff(request, session, write=True)
    if session.get(Staff, identity) is None:
        raise HTTPException(404, "找不到成員")
    revoke_all(session, identity, staff.id)
    session.commit()


def authenticate(factory, value):
    if value is None or TOKEN_PATTERN.fullmatch(value) is None:
        return None
    def lookup(session):
        credential = session.scalar(select(AgentCredential).where(
            AgentCredential.token_hash == digest(value),
            AgentCredential.kind.in_(["access", "token"])))
        grant = session.get(AgentGrant, credential.grant_id) if credential else None
        if (credential is None or credential.expires_at <= utc_now()
                or valid_grant(session, grant) is None):
            return None
        return credential, grant
    with factory() as session:
        found = lookup(session)
        if found is None:
            return None
        credential, grant = found
        identity = grant.id
        update_due = grant.last_used_at <= utc_now() - timedelta(minutes=1)
    if update_due:
        # End the read snapshot and recheck everything under the write lock.
        with factory.begin() as session:
            found = lookup(session)
            if found is None:
                return None
            credential, grant = found
            if grant.last_used_at <= utc_now() - timedelta(minutes=1):
                grant.last_used_at = utc_now()
                if grant.kind == "token":
                    credential.expires_at = grant.last_used_at + IDLE
                if grant.client_id:
                    session.get(OAuthClient, grant.client_id).last_used_at = grant.last_used_at
    return identity


def server_info(factory, grant_id):
    with factory() as session:
        grant = session.get(AgentGrant, grant_id)
        staff = valid_grant(session, grant)
        if staff is None:
            raise ValueError("連線已失效，請重新授權")
        brands = session.scalars(BrandAccess(session, staff).statement(Brand).order_by(Brand.id))
        return {"server_version": SERVER_VERSION, "mcp_api_version": MCP_API_VERSION,
                "user": {"display_name": staff.display_name, "role": staff.role},
                "brands": [{"id": brand.id, "name": brand.name} for brand in brands],
                "connection": {"kind": grant.kind, "name": grant.name}}


def maintain(factory):
    from app.models.agent_publish import AgentPublishConfirmation, AgentUpload

    with factory.begin() as session:
        now = utc_now()
        for model in (AgentUpload, AgentPublishConfirmation):
            session.execute(delete(model).where(model.expires_at <= now))
        session.execute(update(AgentGrant).where(AgentGrant.revoked_at.is_(None),
            AgentGrant.last_used_at <= now - IDLE).values(revoked_at=now))
        session.execute(delete(OAuthRequest).where(OAuthRequest.expires_at <= now))
        session.execute(delete(AgentCode).where(AgentCode.expires_at <= now))
        # Approved in the browser but the client never redeemed the code: not a connection.
        session.execute(update(AgentGrant).where(
            AgentGrant.kind == "oauth", AgentGrant.revoked_at.is_(None),
            ~exists().where(AgentCredential.grant_id == AgentGrant.id),
            ~exists().where(AgentCode.grant_id == AgentGrant.id)).values(revoked_at=now))
        live = select(AgentGrant.id).where(AgentGrant.revoked_at.is_(None))
        # Used refresh digests survive expiry while the grant is live to detect reuse.
        session.execute(delete(AgentCredential).where(
            (AgentCredential.grant_id.not_in(live)) |
            ((AgentCredential.expires_at <= now) &
             ((AgentCredential.kind != "refresh") | AgentCredential.used_at.is_(None)))))
        stale = list(session.scalars(select(OAuthClient.id).where(
            OAuthClient.last_used_at <= now - IDLE,
            ~exists().where(AgentGrant.client_id == OAuthClient.id,
                            AgentGrant.revoked_at.is_(None)))))
        if stale:
            session.execute(delete(OAuthRequest).where(OAuthRequest.client_id.in_(stale)))
            session.execute(update(AgentGrant).where(AgentGrant.client_id.in_(stale))
                            .values(client_id=None))
            session.execute(delete(OAuthClient).where(OAuthClient.id.in_(stale)))

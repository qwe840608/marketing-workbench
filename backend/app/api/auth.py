from fastapi import APIRouter, Request, Response

from app.api.dependencies import Access, Database
from app.schemas.auth import (
    CSRFView,
    InitialSetup,
    LanguageUpdate,
    LoginInput,
    LoginView,
    PasswordChange,
    PasswordRecovery,
    RecoveryCodeCreate,
    RecoveryCodeView,
    RecoveryStatus,
    SetupStatus,
    StaffView,
)
from app.services import auth, members

router = APIRouter(prefix="/api/auth")


def set_session_cookie(response: Response, request: Request, credentials: auth.SessionCredentials):
    response.set_cookie(
        auth.COOKIE_NAME,
        credentials.token,
        max_age=credentials.max_age,
        httponly=True,
        secure=auth.secure_cookie(request.app.state.settings, str(request.base_url).rstrip("/")),
        samesite="strict",
        path="/",
    )


def check_origin(request: Request) -> None:
    auth.validate_origin(
        request.headers.get("origin"),
        request.headers.get("sec-fetch-site"),
        request.app.state.settings,
    )


@router.get("/csrf", response_model=CSRFView)
def csrf(request: Request, response: Response, session: Database):
    check_origin(request)
    credentials = auth.bootstrap_csrf(
        session, request.app.state.settings, request.cookies.get(auth.COOKIE_NAME)
    )
    set_session_cookie(response, request, credentials)
    return {"csrf_token": credentials.csrf_token}


@router.post("/login", response_model=LoginView)
def login(body: LoginInput, request: Request, response: Response, session: Database):
    check_origin(request)
    staff, credentials = auth.login(
        session,
        request.app.state.settings,
        request.cookies.get(auth.COOKIE_NAME),
        request.headers.get("x-csrf-token"),
        body.username,
        body.password,
    )
    set_session_cookie(response, request, credentials)
    return {"user": members.staff_view(session, staff), "csrf_token": credentials.csrf_token}


def is_local(request: Request) -> bool:
    return auth.local_request(
        request.client.host if request.client else None, request.headers.get("host")
    )


@router.get("/setup", response_model=SetupStatus)
def setup_status(request: Request, session: Database):
    return {"needed": auth.setup_needed(session), "local": is_local(request)}


@router.post("/setup", response_model=LoginView)
def initial_setup(body: InitialSetup, request: Request, response: Response, session: Database):
    check_origin(request)
    staff, credentials = auth.initial_setup(
        session,
        request.app.state.settings,
        request.cookies.get(auth.COOKIE_NAME),
        request.headers.get("x-csrf-token"),
        is_local(request),
        body.username,
        body.password,
        body.brand_name,
    )
    set_session_cookie(response, request, credentials)
    return {"user": members.staff_view(session, staff), "csrf_token": credentials.csrf_token}


@router.get("/me", response_model=StaffView)
def me(request: Request, session: Database):
    return members.staff_view(
        session, auth.current_staff(session, request.cookies.get(auth.COOKIE_NAME))
    )


@router.post("/change-password", response_model=StaffView)
def change_password(body: PasswordChange, request: Request, session: Database):
    check_origin(request)
    return auth.change_password(
        session, request.cookies.get(auth.COOKIE_NAME), request.headers.get("x-csrf-token"), body
    )


@router.put("/language", response_model=StaffView)
def set_language(body: LanguageUpdate, request: Request, session: Database):
    check_origin(request)
    return auth.set_language(
        session, request.cookies.get(auth.COOKIE_NAME), request.headers.get("x-csrf-token"),
        body.language,
    )


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, session: Database):
    check_origin(request)
    auth.logout(session, request.cookies.get(auth.COOKIE_NAME), request.headers.get("x-csrf-token"))
    response.delete_cookie(
        auth.COOKIE_NAME,
        path="/",
        httponly=True,
        secure=auth.secure_cookie(request.app.state.settings, str(request.base_url).rstrip("/")),
        samesite="strict",
    )


@router.get("/recovery-code", response_model=RecoveryStatus)
def recovery_code_status(access: Access):
    return auth.recovery_status(access.staff)


@router.post("/recovery-code", response_model=RecoveryCodeView)
def create_recovery_code(body: RecoveryCodeCreate, access: Access):
    return auth.create_recovery_code(access.session, access.staff, body.current_password)


@router.post("/recover", status_code=204)
def recover(body: PasswordRecovery, request: Request, session: Database):
    check_origin(request)
    auth.recover_password(
        session,
        request.cookies.get(auth.COOKIE_NAME),
        request.headers.get("x-csrf-token"),
        body.username,
        body.recovery_code,
        body.new_password,
    )

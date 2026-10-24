import logging
import time
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.agent_auth import router as agent_auth_router
from app.api.agent_packages import router as agent_packages_router
from app.api.ai import router as ai_router
from app.api.ai_settings import router as ai_settings_router
from app.api.auth import router as auth_router
from app.api.catalog import router as catalog_router
from app.api.classify import router as classify_router
from app.api.credentials import router as credentials_router
from app.api.csv_import import router as csv_import_router
from app.api.dependencies import enforce_password_change
from app.api.exports import router as exports_router
from app.api.health import router as health_router
from app.api.ideation import router as ideation_router
from app.api.members import roles_router
from app.api.members import router as members_router
from app.api.notify import router as notify_router
from app.api.oauth import router as oauth_router
from app.api.publish import media_router
from app.api.publish import router as publish_router
from app.api.receive_health import router as receive_health_router
from app.api.scheduler import router as scheduler_router
from app.api.webhooks import router as webhooks_router
from app.api.workspace import router as workspace_router
from app.config import Settings
from app.db import DatabaseBusy, build_engine, session_factory
from app.logging_config import configure_logging, error_fields
from app.services.csv_import import ImportStore
from app.services.export_md import ExportWorker
from app.services.notify import bootstrap_groups
from app.services.obsidian import ObsidianWorker
from app.services.public_boundary import PublicBoundary
from app.services.receive_health import ReceiveHealthWorker
from app.services.scheduler import Scheduler

logger = logging.getLogger("mwb.http")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    from app.services.agent_mcp import build_manager

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        configure_logging(settings.log_path)
        engine = build_engine(settings)
        application.state.session_factory = session_factory(engine)
        from app.services import publish

        publish.recover(application.state.session_factory)
        bootstrap_groups(application.state.session_factory, settings)
        worker = ExportWorker(application.state.session_factory, settings)
        application.state.export_worker = worker
        obsidian_worker = ObsidianWorker(application.state.session_factory, settings)
        application.state.obsidian_worker = obsidian_worker
        if settings.export_worker_enabled:
            worker.start()
            obsidian_worker.start()
        scheduler = Scheduler(application.state.session_factory, settings)
        application.state.scheduler = scheduler
        if settings.scheduler_enabled:
            scheduler.start()
        health_worker = ReceiveHealthWorker(application.state.session_factory, settings)
        if settings.receive_health_worker_enabled:
            health_worker.start()
        try:
            # A TestClient or embedded host may enter lifespan again on the same app.
            agent_mcp = build_manager(settings)
            application.state.agent_mcp = agent_mcp
            async with agent_mcp.run():
                yield
        finally:
            health_worker.close()
            scheduler.close()
            worker.close()
            obsidian_worker.close()
            engine.dispose()

    application = FastAPI(
        title="行銷管理工作檯後台",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        dependencies=[Depends(enforce_password_change)],
    )
    application.state.settings = settings
    application.state.csv_import_store = ImportStore()
    public_host = urlsplit(settings.webhook_public_url).hostname
    hosts = settings.allowed_hosts + ([public_host] if public_host else [])
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
    application.add_middleware(PublicBoundary, settings=settings)

    @application.middleware("http")
    async def access_log(request: Request, call_next):
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
            if request.url.path == "/" and "agent_authorize" in request.query_params:
                # no-referrer makes native form POSTs send Origin:null in Chromium.
                # same-origin retains CSRF's strict Origin check and hides external referrals.
                response.headers["Referrer-Policy"] = "same-origin"
            response.headers["X-Frame-Options"] = "DENY"
            status = response.status_code
            return response
        except Exception as error:
            logger.error("request_failed", extra=error_fields(error))
            if (
                isinstance(error, DatabaseBusy)
                or error_fields(error).get("error_code") == "database_locked"
            ):
                busy = DatabaseBusy()
                status = busy.status_code
                return JSONResponse(
                    {"detail": busy.detail}, status_code=status, headers=busy.headers
                )
            return JSONResponse({"detail": "伺服器暫時無法處理請求"}, status_code=500)
        finally:
            route = request.scope.get("route")
            logger.info(
                "request",
                extra={
                    "method": request.method,
                    "route": getattr(route, "path", "unmatched"),
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )

    @application.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _error: RequestValidationError):
        # Pydantic 的預設錯誤會回傳原始 input，登入密碼等欄位不可反射到回應。
        if _request.url.path == "/oauth/register":
            return JSONResponse({"error": "invalid_client_metadata"}, status_code=400)
        return JSONResponse({"detail": "輸入格式錯誤"}, status_code=422)

    application.include_router(scheduler_router)
    application.include_router(webhooks_router)
    application.include_router(health_router)
    application.include_router(receive_health_router)
    application.include_router(auth_router)
    application.include_router(agent_auth_router)
    application.include_router(agent_packages_router)
    application.include_router(members_router)
    application.include_router(roles_router)
    application.include_router(catalog_router)
    application.include_router(notify_router)
    application.include_router(ideation_router)
    application.include_router(classify_router)
    application.include_router(ai_router)
    application.include_router(ai_settings_router)
    application.include_router(credentials_router)
    application.include_router(oauth_router)
    application.include_router(publish_router)
    application.include_router(media_router)
    application.include_router(workspace_router)
    application.include_router(exports_router)
    application.include_router(csv_import_router)
    frontend = settings.frontend_dist_dir
    if (frontend / "index.html").is_file():

        @application.get("/", include_in_schema=False)
        def frontend_index():
            return FileResponse(frontend / "index.html")

        application.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")
    return application


app = create_app()

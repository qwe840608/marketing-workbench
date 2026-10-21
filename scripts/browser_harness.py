"""Batch 4 browser acceptance on an isolated DB and HTTP mocks; blocks external sockets."""

from runtime_tmp import (
    launch_chromium,
    cleanup,
    output_dir,
    runtime_check,
    stop_process,
    temporary_dir,
)

import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from ports import KEEP_ALIVE_SECONDS, browser_port

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))


def serve():
    import uvicorn

    from app.config import Settings
    from app.main import create_app
    from app.services import jev, autostart
    from oauth_http_mock import install_oauth_mock

    install_oauth_mock()
    if os.environ.get("PUBLISH_CHECK") == "1":
        from publish_http_mock import install_publish_mock

        install_publish_mock()
    from app.services.ai import providers

    autostart.execute = lambda *args: autostart.state()
    original_connect = socket.socket.connect

    def local_only(sock, address):
        if address[0] not in ("127.0.0.1", "localhost", "::1"):
            raise RuntimeError("External network disabled in batch 4 acceptance")
        return original_connect(sock, address)

    socket.socket.connect = local_only

    def review(_url, _key, payload, _timeout):
        text = payload["state"].get("draft", "")
        failed = (
            "forbidden_promise"
            if "達成效果" in text
            else "unreferenced_price"
            if "1,500" in text
            else None
        )
        return (
            200,
            {
                "model": "jev-1.13.0",
                "answers": {
                    k: {"type": "noul", "noul": 0.99 if k == failed else 0.01}
                    for k in payload["questions"]
                },
                "usage": {"input_tokens": 100, "output_tokens": 20},
            },
            0,
        )

    jev.post_json = review
    if os.environ.get("AGENT_CONTENT_CHECK") == "1":
        from agent_content_fixture import no_ai, typed
        from app.services import ai

        jev.ask = typed
        ai.run = no_ai
    providers.call_api = lambda *a: providers.Result(
        "[隔離驗收] 請提供需求類型照片，專人將說明服務流程。", "gemini-3.8-flash", 100, 20
    )
    settings = Settings(_env_file=None)
    if os.environ.get("AGENTPACK_CHECK") == "1":
        settings.app_origin += ",https://office.example.test"
    if os.environ.get("METAOAUTH_CHECK") == "1":
        from pydantic import SecretStr

        settings.app_origin += ",https://office.example.test"
        settings.meta_app_id = settings.threads_app_id = "12345"
        settings.meta_app_secret = settings.threads_app_secret = SecretStr("isolated-app-secret")
    uvicorn.run(
        create_app(settings),
        host="127.0.0.1",
        port=int(os.environ["BATCH4_PORT"]),
        log_level="warning",
        timeout_keep_alive=KEEP_ALIVE_SECONDS,
    )


@runtime_check
def main(polish=False, exercise=None):
    from alembic import command
    from alembic.config import Config
    from cryptography.fernet import Fernet
    from playwright.sync_api import expect, sync_playwright
    from sqlalchemy import select

    from app.config import Settings
    from app.db import build_engine, session_factory
    from app.models import (
        Account,
        Brand,
        Classification,
        Contact,
        Message,
        Staff,
        Thread,
    )
    from app.models.base import utc_now

    folder = temporary_dir()
    artifacts = output_dir()
    artifacts.mkdir(parents=True, exist_ok=True)
    port = browser_port()
    origin = f"http://127.0.0.1:{port}"
    password = secrets.token_urlsafe(32)
    os.environ.update(
        {
            "DATABASE_PATH": str(folder / "test.db"),
        "FRONTEND_DIST_DIR": os.environ.get("FRONTEND_DIST_DIR", str(REPO / "frontend/dist")),
            "LOG_PATH": str(folder / "backend.jsonl"),
            "EXPORT_ROOT": str(folder / "export"),
            "PUBLISH_MEDIA_ROOT": str(folder / "publish-media"),
            "WEBHOOK_PUBLIC_URL": "https://media.example.test/webhook/meta-inbound",
            "OBSIDIAN_ROOT": str(folder / "obsidian"),
            "EXPORT_WORKER_ENABLED": "false",
            "RECEIVE_HEALTH_WORKER_ENABLED": "false",
        "SCHEDULER_ENABLED": "false",
            "RECEIVE_HEALTH_ALERTS_ENABLED": "false",
            "APP_ORIGIN": origin,
            "ALLOWED_HOSTS": '["127.0.0.1"]',
            "SESSION_COOKIE_SECURE": "false",
            "ADMIN_INITIAL_PASSWORD": password,
            "ACCOUNT_ENCRYPTION_KEY": Fernet.generate_key().decode(),
            "COMMENTS_WAKE_ENABLED": "false",
            "BATCH4_PORT": str(port),
            "GEMINI_API_KEY": secrets.token_urlsafe(32),
            "GEMINI_MODEL": "gemini-3.8-flash",
            "JEV_API_KEY": secrets.token_urlsafe(32),
            "LINE_CHANNEL_ACCESS_TOKEN": secrets.token_urlsafe(32),
            "META_PAGE_ACCESS_TOKEN": secrets.token_urlsafe(32),
        }
    )
    settings = Settings(_env_file=None)
    command.upgrade(Config(str(REPO / "backend/alembic.ini")), "head")
    engine = build_engine(settings)
    cleanup(engine.dispose)
    factory = session_factory(engine)
    with factory.begin() as s:
        seed_records(s, settings)
        brand = s.scalar(select(Brand).where(Brand.slug == "TEST"))
        brand.name = "[隔離驗收] 行銷工作區"
        brand.marketing_dm_enabled = True
        s.scalar(select(Staff).where(Staff.username == "admin")).display_name = "隔離驗收管理員"
        for index, (platform, enabled) in enumerate(
            [("facebook", True), ("line", True), ("instagram", False)]
            + ([("instagram", True)] if polish else [])
        ):
            account = Account(
                id=101 + index,
                brand_id=brand.id,
                platform=platform,
                external_id=f"mock-account-{index}",
                name=f"[隔離驗收] {platform}",
                send_enabled=enabled,
                token_ref="LINE_CHANNEL_ACCESS_TOKEN"
                if platform == "line"
                else "META_PAGE_ACCESS_TOKEN",
            )
            c = Contact(
                brand_id=brand.id,
                platform=platform,
                external_id=f"mock-contact-{index}",
                display_name=f"[隔離驗收] {platform}{' 已開放測試' if index == 3 else ''} 客人",
            )
            s.add_all([account, c])
            s.flush()
            t = Thread(
                brand_id=brand.id,
                account_id=account.id,
                contact_id=c.id,
                external_id=c.external_id,
                kind="dm",
                last_inbound_at=utc_now(),
            )
            s.add(t)
            s.flush()
            m = Message(
                thread_id=t.id,
                contact_id=c.id,
                external_id=f"mock-in-{index}",
                direction="in",
                author_type="fan",
                text="[隔離驗收] 請問服務流程？",
                sent_at=utc_now(),
            )
            s.add(m)
            s.flush()
            s.add(
                Classification(
                    message_id=m.id,
                    engine="jev",
                    intent="other",
                    sentiment="neutral",
                    sensitive=False,
                    action="human",
                    confidence=0.99,
                )
            )
    log = (folder / "server.log").open("w", encoding="utf-8")
    cleanup(log.close)
    server = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--serve"],
        cwd=REPO / "backend",
        env=dict(os.environ),
        stdout=log,
        stderr=log,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    cleanup(stop_process, server)
    shots = []
    errors = []
    external = []
    checks = []
    try:
        for _ in range(150):
            try:
                urllib.request.urlopen(origin + "/api/health", timeout=1).close()
                break
            except OSError:
                if server.poll() is not None:
                    raise RuntimeError("Isolated server failed") from None
                time.sleep(0.1)
        with sync_playwright() as pw:
            browser = launch_chromium(pw)
            for width, height in [(1440, 900), (390, 844)]:
                context = browser.new_context(viewport={"width": width, "height": height})

                def guard(route):
                    if route.request.url.startswith(origin + "/"):
                        route.continue_()
                    else:
                        external.append(route.request.url.split("?")[0])
                        route.abort()

                context.route("**/*", guard)
                if polish:
                    from check_polish_frontend import TIMER_HARNESS

                    context.add_init_script(TIMER_HARNESS)
                page = context.new_page()
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(origin)
                page.get_by_label("帳號", exact=True).fill("admin")
                page.get_by_label("密碼", exact=True).fill(password)
                page.get_by_role("button", name="登入工作檯").click()

                expect(page.locator(".dashboard-kpis .kpi")).to_have_count(2)
                def shot(name, page=page, width=width, height=height):
                    page.screenshot(path=str(artifacts / f"{name}-{width}x{height}.png"))
                    overflow = page.evaluate("document.documentElement.scrollWidth > innerWidth")
                    assert not overflow, (name, width)
                    dialog = page.locator("dialog[open]")
                    if dialog.count():
                        assert dialog.evaluate("(e) => e.scrollWidth <= e.clientWidth + 1")
                    shots.append(f"{name}-{width}x{height}.png")

                if exercise is not None:
                    exercise(page, None, shot, checks)
                else:
                    from check_polish_frontend import check_polling, run_checks
                    run_checks(page, None, shot, checks)
                    check_polling(page, None, checks)
                context.close()
            browser.close()
        report = {
            "checks": checks,
            "screenshots": shots,
            "page_errors": errors,
            "external_requests": external,
            "http_transport": "MockTransport",
            "database": "isolated",
            "real_platform_sends": 0,
        }
        (artifacts / "verification.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        assert not errors and not external
        print(
            json.dumps(
                {
                    "checks": len(checks),
                    "screenshots": len(shots),
                    "page_errors": len(errors),
                    "external_requests": len(external),
                }
            )
        )
    finally:
        stop_process(server)
        log.close()
        engine.dispose()




def seed_records(session, settings, *, include_content=False):
    import sys
    from pathlib import Path
    location = Path(__file__).resolve()
    sys.path.insert(0, str(location.parents[2] / "scripts")
                    if "tests" in location.parts else str(location.parent))
    from test_prices import seed_prices
    from test_records import seed_records as seed_base_records
    counts = seed_base_records(session, settings, include_content=include_content)
    seed_prices(session)
    return counts


if __name__ == "__main__":
    serve() if "--serve" in sys.argv else main()

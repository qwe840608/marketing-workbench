"""First-run setup page on an empty isolated DB; no external sockets."""

from runtime_tmp import cleanup, launch_chromium, output_dir, runtime_check, temporary_dir

import os
import secrets
import sys

from browser_harness import REPO, launch_server, run_uvicorn
from ports import browser_port


def serve():
    from app.config import Settings
    from app.main import create_app

    run_uvicorn(create_app(Settings(_env_file=None)), os.environ["SETUP_CHECK_PORT"])


@runtime_check
def main():
    from alembic import command
    from alembic.config import Config
    from cryptography.fernet import Fernet
    from playwright.sync_api import expect, sync_playwright
    from sqlalchemy import func, select

    from app.config import Settings
    from app.db import build_engine, session_factory
    from app.models import Brand, Staff

    folder = temporary_dir()
    artifacts = output_dir()
    artifacts.mkdir(parents=True, exist_ok=True)
    port = browser_port()
    origin = f"http://127.0.0.1:{port}"
    os.environ.update({
        "DATABASE_PATH": str(folder / "test.db"),
        "FRONTEND_DIST_DIR": os.environ.get("FRONTEND_DIST_DIR", str(REPO / "frontend/dist")),
        "LOG_PATH": str(folder / "backend.jsonl"),
        "EXPORT_ROOT": str(folder / "export"),
        "PUBLISH_MEDIA_ROOT": str(folder / "publish-media"),
        "EXPORT_WORKER_ENABLED": "false",
        "RECEIVE_HEALTH_WORKER_ENABLED": "false",
        "SCHEDULER_ENABLED": "false",
        "RECEIVE_HEALTH_ALERTS_ENABLED": "false",
        "COMMENTS_WAKE_ENABLED": "false",
        "APP_ORIGIN": origin,
        "ALLOWED_HOSTS": '["127.0.0.1"]',
        "SESSION_COOKIE_SECURE": "false",
        "ACCOUNT_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "SETUP_CHECK_PORT": str(port),
    })
    # 全新安裝：只有資料表結構，沒有任何帳號或品牌。
    command.upgrade(Config(str(REPO / "backend/alembic.ini")), "head")
    launch_server(folder, origin, script=__file__)
    password = secrets.token_urlsafe(18)
    with sync_playwright() as playwright:
        browser = launch_chromium(playwright)
        for width in (1280, 390):
            page = browser.new_page(viewport={"width": width, "height": 844})
            page.goto(origin)
            expect(page.get_by_role("heading", name="建立管理員")).to_be_visible()
            expect(page.get_by_role("button", name="登入工作檯")).to_have_count(0)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
            page.screenshot(path=str(artifacts / f"initial-setup-{width}.png"), full_page=True)
            page.close()
        page = browser.new_page(viewport={"width": 1280, "height": 844})
        page.goto(origin)
        page.get_by_label("管理員帳號").fill("setup-admin")
        page.get_by_label("密碼", exact=True).fill(password)
        page.get_by_label("再次輸入密碼").fill(password + "x")
        page.get_by_label("品牌名稱").fill("[隔離驗收] 測試品牌")
        page.get_by_role("button", name="建立並登入").click()
        expect(page.get_by_role("alert")).to_have_text("兩次輸入的密碼不一致")
        page.get_by_label("再次輸入密碼").fill(password)
        page.get_by_role("button", name="建立並登入").click()
        expect(page.locator(".workspace")).to_be_visible()
        page.reload()
        expect(page.locator(".workspace")).to_be_visible()
        # 建立後再開新的瀏覽器工作階段，只會看到登入表單。
        fresh = browser.new_context().new_page()
        fresh.goto(origin)
        expect(fresh.get_by_role("button", name="登入工作檯")).to_be_visible()
        expect(fresh.get_by_role("heading", name="建立管理員")).to_have_count(0)
        browser.close()
    engine = build_engine(Settings(_env_file=None))
    cleanup(engine.dispose)
    with session_factory(engine)() as session:
        assert session.scalar(select(func.count()).select_from(Staff)) == 1
        assert [b.name for b in session.scalars(select(Brand))] == ["[隔離驗收] 測試品牌"]
    print("check_initial_setup: 4 passed（空資料庫顯示首次設定、390px 不溢出、密碼不一致擋下、建立後自動登入且之後只顯示登入）")


if __name__ == "__main__":
    if "--serve" in sys.argv:
        serve()
    else:
        main()

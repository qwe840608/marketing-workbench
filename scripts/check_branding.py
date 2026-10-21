"""Isolated identity/template browser acceptance; no external requests."""

from runtime_tmp import (
    launch_chromium,
    cleanup,
    output_dir,
    runtime_check,
    stop_process,
    temporary_dir,
)

from ui_navigation import navigate

from ports import KEEP_ALIVE_SECONDS, browser_port
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))


def configured():
    from app.config import Settings

    return Settings(
        _env_file=None,
        scheduler_enabled=False,
        export_worker_enabled=False,
        receive_health_worker_enabled=False,
        receive_health_alerts_enabled=False,
        comments_wake_enabled=False,
    )


def serve():
    import uvicorn

    from app.main import create_app

    uvicorn.run(
        create_app(configured()),
        host="127.0.0.1",
        port=int(os.environ["BRANDING_PORT"]),
        timeout_keep_alive=KEEP_ALIVE_SECONDS,
    )


@runtime_check
def main():
    from alembic import command
    from alembic.config import Config
    from playwright.sync_api import expect, sync_playwright
    from test_records import seed_records

    from app.db import build_engine, session_factory

    folder = temporary_dir()
    output = output_dir()
    output.mkdir(parents=True, exist_ok=True)
    port = browser_port()
    origin = f"http://127.0.0.1:{port}"
    password = secrets.token_urlsafe(32)
    os.environ.update(
        {
            "DATABASE_PATH": str(folder / "test.db"),
            "EXPORT_ROOT": str(folder / "export"),
            "LOG_PATH": str(folder / "backend.jsonl"),
            "ADMIN_INITIAL_PASSWORD": password,
            "APP_ORIGIN": origin,
            "ALLOWED_HOSTS": '["127.0.0.1"]',
            "SESSION_COOKIE_SECURE": "false",
            "BRANDING_PORT": str(port),
            "FRONTEND_DIST_DIR": os.environ.get(
                "FRONTEND_DIST_DIR", str(REPO / "frontend/dist")
            ),
        }
    )
    cfg = Config(str(REPO / "backend/alembic.ini"))
    cfg.set_main_option("script_location", str(REPO / "backend/migrations"))
    command.upgrade(cfg, "head")
    settings = configured()
    engine = build_engine(settings)
    cleanup(engine.dispose)
    with session_factory(engine).begin() as session:
        seed_records(session, settings, include_content=False)
    engine.dispose()
    errors, external = [], []
    with (folder / "server.log").open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [sys.executable, __file__, "--serve"],
            stdout=log,
            stderr=log,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        cleanup(stop_process, proc)
        try:
            for _ in range(100):
                try:
                    with urllib.request.urlopen(origin + "/api/health", timeout=1):
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("隔離伺服器未就緒")
            with sync_playwright() as pw:
                browser = launch_chromium(pw)
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page.on("pageerror", lambda e: errors.append(str(e)))

                def route(r):
                    if r.request.url.endswith('/api/workspace/autostart'):
                        r.fulfill(json={"enabled": False, "supported": True, "task_name": "MWB-AutoStart", "code": None})
                        return
                    if r.request.url.startswith(origin + "/"):
                        r.continue_()
                    else:
                        external.append(r.request.url)
                        r.abort()

                page.route("**/*", route)
                page.goto(origin)
                page.get_by_label("帳號", exact=True).fill("admin")
                page.get_by_label("密碼", exact=True).fill(password)
                page.get_by_role("button", name="登入工作檯").click()
                navigate(page, "工作區設定")
                field = page.get_by_label("產品顯示名稱")
                expect(field).to_be_visible()
                # 等設定初始讀取完成，避免晚到的名稱回應覆蓋正在輸入的驗收值。
                page.wait_for_load_state("networkidle")
                assert page.locator(".branding-settings").evaluate("""e => {
                    const sections = [...e.querySelectorAll(':scope > .workspace-subsection')];
                    return sections.every((section, index) => !index || section.getBoundingClientRect().top - sections[index - 1].getBoundingClientRect().bottom >= 24);
                }""")
                field.fill("創作測試工作室")
                page.get_by_role("button", name="儲存工作區名稱").click()
                expect(page).to_have_title("創作測試工作室")
                expect(page.locator(".mark")).to_have_text("創")
                # uiorder：頁首右上不再重複工作區名稱，名稱只在側邊欄標誌顯示。
                expect(page.locator(".workspace-name")).to_have_count(0)
                expect(page.locator(".sidebar .wordmark")).to_contain_text("創作測試工作室")
                page.get_by_role("button", name="預覽差異", exact=True).click()
                expect(page.get_by_label("範本差異")).to_contain_text("AI 工具")
                page.screenshot(
                    path=str(output / "desktop-preview.png"), full_page=True
                )
                page.get_by_role("button", name="確認套用此差異").click()
                expect(page.get_by_label("品牌禁語（每行一項）")).to_have_value(
                    "保證爆紅\n保證收入\n保證接案\n穩賺"
                )
                expect(
                    page.get_by_text("範本已套用並記錄稽核", exact=True)
                ).to_be_visible()
                page.set_viewport_size({"width": 390, "height": 844})
                page.get_by_label("品牌禁語（每行一項）").scroll_into_view_if_needed()
                assert page.locator(".branding-settings").evaluate("""e => {
                    const sections = [...e.querySelectorAll(':scope > .workspace-subsection')];
                    return sections.every((section, index) => !index || section.getBoundingClientRect().top - sections[index - 1].getBoundingClientRect().bottom >= 24);
                }""")
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= innerWidth"
                )
                page.screenshot(
                    path=str(output / "mobile-settings.png"), full_page=True
                )
                from ui_navigation import open_settings

                open_settings(page)
                page.get_by_role("button", name="登出", exact=True).click()
                expect(page.locator(".wordmark")).to_contain_text("創作測試工作室")
                expect(page).to_have_title("創作測試工作室")
                page.screenshot(path=str(output / "mobile-login.png"), full_page=True)
                browser.close()
        finally:
            stop_process(proc)
    assert not errors and not external
    report = {
        "passed": True,
        "screenshots": 3,
        "page_errors": errors,
        "external_requests": external,
    }
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    serve() if "--serve" in sys.argv else main()

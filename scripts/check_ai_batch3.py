"""Isolated batch 3 browser acceptance. No real provider or platform calls."""

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
from datetime import timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))


def serve():
    import uvicorn
    from fastapi import HTTPException

    from app.config import Settings
    from app.main import create_app
    from app.services import ai_keys, jev
    from app.services.ai import providers

    def probe(provider, key, settings):
        if not key or key.get_secret_value().startswith("invalid"):
            raise HTTPException(422, "隔離驗收：連線測試失敗")

    def no_network(*args, **kwargs):
        raise RuntimeError("隔離驗收禁止外部呼叫")

    ai_keys.probe = probe
    jev.post_json = no_network
    providers.call_api = no_network
    uvicorn.run(
        create_app(Settings(_env_file=None)),
        host="127.0.0.1",
        port=int(os.environ["BATCH3_PORT"]),
        log_level="warning",
        timeout_keep_alive=KEEP_ALIVE_SECONDS,
    )


@runtime_check
def main():
    from alembic import command
    from alembic.config import Config
    from cryptography.fernet import Fernet
    from playwright.sync_api import expect, sync_playwright
    from sqlalchemy import select

    from app.config import Settings
    from app.db import build_engine, session_factory
    from app.models import Brand, Message, Post, Staff
    from app.models.base import utc_now

    folder = temporary_dir()
    artifacts = output_dir()
    artifacts.mkdir(parents=True, exist_ok=True)
    port = browser_port()
    origin = f"http://127.0.0.1:{port}"
    password = secrets.token_urlsafe(32)
    env = {
        "DATABASE_PATH": str(folder / "test.db"),
        "LOG_PATH": str(folder / "backend.jsonl"),
        "EXPORT_ROOT": str(folder / "export"),
        "EXPORT_WORKER_ENABLED": "false",
        "SCHEDULER_ENABLED": "false",
        "RECEIVE_HEALTH_WORKER_ENABLED": "false",
        "APP_ORIGIN": origin,
        "ALLOWED_HOSTS": '["127.0.0.1"]',
        "SESSION_COOKIE_SECURE": "false",
        "ADMIN_INITIAL_PASSWORD": password,
        "ACCOUNT_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "COMMENTS_WAKE_ENABLED": "false",
        "BATCH3_PORT": str(port),
    }
    os.environ.update(env)
    for provider in ("OPENAI", "GEMINI", "ANTHROPIC", "JEV"):
        os.environ.pop(provider + "_API_KEY", None)
    settings = Settings(_env_file=None)
    command.upgrade(Config(str(REPO / "backend/alembic.ini")), "head")
    engine = build_engine(settings)
    cleanup(engine.dispose)
    factory = session_factory(engine)
    with factory.begin() as session:
        seed_records(session, settings, include_content=True)
        session.scalar(select(Brand)).name = "[隔離驗收] AI 設定測試品牌"
        for staff in session.scalars(select(Staff)):
            staff.display_name = (
                "隔離驗收管理員" if staff.role == "admin" else "隔離驗收成員"
            )
        for message in session.scalars(select(Message)):
            message.text = "[隔離驗收] 請問服務流程？電話０９１２３４５６７８，信箱hello@example.com。"
            message.sent_at = utc_now() - timedelta(days=20)
        for post in session.scalars(select(Post)):
            post.caption = "[隔離驗收] 服務注意事項"
            post.published_at = utc_now()
    engine.dispose()
    server_log = (folder / "server.log").open("w", encoding="utf-8")
    cleanup(server_log.close)
    server = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--serve"],
        cwd=REPO / "backend",
        env=dict(os.environ),
        stdout=server_log,
        stderr=server_log,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    cleanup(stop_process, server)
    checks, measures, errors, external = [], [], [], []
    canary = "sk-proj-" + secrets.token_urlsafe(32)
    try:
        for _ in range(150):
            try:
                urllib.request.urlopen(origin + "/api/health", timeout=1).close()
                break
            except OSError:
                if server.poll() is not None:
                    raise RuntimeError("隔離後台啟動失敗") from None
                time.sleep(0.1)
        with sync_playwright() as pw:
            browser = launch_chromium(pw)
            context = browser.new_context(viewport={"width": 1440, "height": 900})

            def guard(route):
                if route.request.url.startswith(origin + "/"):
                    allowed = route.request.method in {"GET", "HEAD"} or any(
                        part in route.request.url for part in ("/api/auth/", "/api/ai/")
                    )
                    route.continue_() if allowed else route.abort()
                else:
                    external.append(route.request.url.split("?")[0])
                    route.abort()

            context.route("**/*", guard)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(origin)
            page.get_by_label("帳號", exact=True).fill("admin")
            page.get_by_label("密碼", exact=True).fill(password)
            page.get_by_role("button", name="登入工作檯").click()
            navigate(page, "AI 設定")
            expect(page.get_by_role("heading", name="設定", exact=True)).to_be_visible()
            page.get_by_role("tab", name="AI 金鑰", exact=True).click()
            key_input = page.get_by_label("新增或替換金鑰")
            save_key = page.get_by_role("button", name="儲存已驗證金鑰")
            expect(save_key).to_be_disabled()
            for name, hint in (
                ("gemini", "AIza…"),
                ("anthropic", "sk-ant-…"),
                ("openai", "sk-proj-…"),
            ):
                page.get_by_label("金鑰供應商").select_option(name)
                expect(key_input).to_have_attribute("placeholder", hint)
            key_input.fill("invalid-isolated-credential")
            page.get_by_role("button", name="測試連線", exact=True).click()
            expect(page.get_by_text("隔離驗收：連線測試失敗")).to_be_visible()
            expect(key_input).to_have_value("")
            expect(save_key).to_be_disabled()
            key_input.fill(canary)
            page.get_by_role("button", name="測試連線", exact=True).click()
            expect(save_key).to_be_enabled()
            expect(key_input).to_have_value("")
            assert canary not in page.content()
            assert page.evaluate(
                "key => !JSON.stringify([localStorage, sessionStorage]).includes(key)",
                canary,
            )
            key_input.fill("changed-isolated-credential")
            expect(save_key).to_be_disabled()
            key_input.fill(canary)
            page.get_by_role("button", name="測試連線", exact=True).click()
            expect(save_key).to_be_enabled()
            save_key.click()
            expect(page.get_by_text("金鑰已加密儲存。", exact=True)).to_be_visible()
            checks.append("key-form-placeholder-test-gate-clear-secret-state-save")
            page.get_by_role("tab", name="品牌說明", exact=True).click()
            editor = page.get_by_role("region", name="品牌說明", exact=True)
            editor.get_by_label("品牌說明內容").fill(
                "[隔離驗收] 先確認需求類型，再提供服務流程。\n使用親切、清楚的繁體中文。"
            )
            editor.get_by_role("button", name="儲存新版本").click()
            expect(
                editor.get_by_text("新版本已儲存。")
            ).to_be_visible()
            editor.locator("summary").click()
            editor.get_by_label("檢視版本").select_option("1")
            editor.get_by_role("button", name="還原此版本").click()
            expect(
                editor.get_by_text("已還原為新的版本，既有歷史保留。")
            ).to_be_visible()
            expect(editor.get_by_label("檢視版本").locator("option")).to_have_count(3)
            checks.append("prompt-save-history-diff-restore-new-revision")
            expect(page.get_by_role('region', name='完整 prompt 預覽')).to_have_count(0)
            checks.append('draft-prompt-preview-removed-content-prompts-preserved')

            def capture(name, target):
                target.evaluate("e => e.scrollIntoView({block: 'start'})")
                page.wait_for_load_state("networkidle")
                measure = page.evaluate("""() => ({width: innerWidth, height: innerHeight,
                    document: document.documentElement.scrollWidth <= innerWidth,
                    overflow: [...document.querySelectorAll('.settings-page *')].filter(e => {
                        const s=getComputedStyle(e), r=e.getBoundingClientRect();
                        return r.width > 0 && r.height > 0 && s.display !== 'none' &&
                          ['auto','scroll'].includes(s.overflowX) && e.scrollWidth > e.clientWidth+1;
                    }).map(e => e.className)})""")
                assert measure["document"] and not measure["overflow"], measure
                assert canary not in page.content()
                page.screenshot(path=str(artifacts / (name + ".png")))
                measures.append({"screenshot": name + ".png", **measure})

            for width, height in ((1440, 900), (390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                capture(
                    f"ai-settings-{width}x{height}",
                    page.get_by_role("heading", name="設定", exact=True),
                )
                capture(
                    f"prompt-versions-{width}x{height}",
                    editor.locator(".prompt-history"),
                )
            page.set_viewport_size({"width": 1440, "height": 900})
            page.get_by_role("tab", name="AI 金鑰", exact=True).click()
            page.get_by_role("button", name="刪除 UI 金鑰").click()
            expect(
                page.get_by_text("UI 金鑰已刪除；未設定時會使用 .env。")
            ).to_be_visible()
            checks.append("delete-ui-key-returns-source")
            page.get_by_role("button", name="貼文數據", exact=True).click()

            page.locator(".post-card").first.click()
            page.get_by_role("group", name="留言日期", exact=True).get_by_role(
                "radio", name="近 7 天", exact=True
            ).click()
            expect(page.get_by_text("這段期間沒有留言", exact=True)).to_be_visible()
            for width, height in ((1440, 900), (390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                capture(
                    f"empty-comments-{width}x{height}", page.locator(".post-comments")
                )
            page.set_viewport_size({"width": 1440, "height": 900})
            page.get_by_label("發文日期起日", exact=True).fill("2099-01-01")
            expect(page.get_by_text("這段期間沒有貼文", exact=True)).to_be_visible()
            checks.append("date-filter-empty-copy-posts-and-comments")
            assert not errors and not external
            browser.close()
        assert canary not in (folder / "backend.jsonl").read_text("utf-8")
        assert canary.encode() not in (folder / "test.db").read_bytes()
        result = {
            "checks": checks,
            "screenshots": measures,
            "page_errors": errors,
            "external_requests": external,
            "data": "隔離資料庫與連線測試替身；未使用真實金鑰或平台 API",
        }
        (artifacts / "verification.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "checks": len(checks),
                    "screenshots": len(measures),
                    "page_errors": len(errors),
                    "external_requests": len(external),
                }
            )
        )
    finally:
        stop_process(server)
        server_log.close()


def seed_records(session, settings, *, include_content=False):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts") if "tests" in Path(__file__).parts else str(Path(__file__).resolve().parent))
    from test_prices import seed_prices
    from test_records import seed_records as seed_base_records
    counts = seed_base_records(session, settings, include_content=include_content)
    seed_prices(session)
    return counts


if __name__ == "__main__":
    serve() if "--serve" in sys.argv else main()

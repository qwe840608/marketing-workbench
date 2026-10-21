"""Batch 2 fixes: isolated browser acceptance; only local reads and login allowed."""

from runtime_tmp import (
    launch_chromium,
    cleanup,
    output_dir,
    runtime_check,
    stop_process,
    temporary_dir,
)

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


@runtime_check
def main():
    from alembic import command
    from alembic.config import Config
    from playwright.sync_api import expect, sync_playwright
    from sqlalchemy import select

    from app.config import Settings
    from app.db import build_engine, session_factory
    from app.models import (
        Account,
        Brand,
        Contact,
        Message,
        MetricSnapshot,
        Post,
        Thread,
    )
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
        "RECEIVE_HEALTH_ALERTS_ENABLED": "false",
        "APP_ORIGIN": origin,
        "ALLOWED_HOSTS": '["127.0.0.1"]',
        "SESSION_COOKIE_SECURE": "false",
        "ADMIN_INITIAL_PASSWORD": password,
        "COMMENTS_WAKE_ENABLED": "false",
    }
    env_path = folder / ".env"
    env_path.write_text("\n".join(f"{k}='{v}'" for k, v in env.items()), encoding="utf-8")
    os.environ.update(env)
    settings = Settings(_env_file=env_path)
    command.upgrade(Config(str(REPO / "backend/alembic.ini")), "head")
    engine = build_engine(settings)
    cleanup(engine.dispose)
    factory = session_factory(engine)
    now = utc_now()
    ids = {}
    with factory.begin() as session:
        seed_records(session, settings, include_content=False)
        brand = session.scalar(select(Brand).where(Brand.slug == "TEST"))
        for platform in ("facebook", "instagram"):
            account = Account(
                brand_id=brand.id,
                platform=platform,
                external_id="batch2-" + platform,
                name="[隔離驗收] " + ("FB" if platform == "facebook" else "IG"),
            )
            session.add(account)
            session.flush()
            post = Post(
                account_id=account.id,
                external_id="post-" + platform,
                caption="[隔離驗收] 使用時遇到問題，諮詢前要先確認什麼？"
                if platform == "facebook"
                else "[隔離驗收] Reels：從使用者的提問，找出內容方向",
                media_type="REELS" if platform == "instagram" else "POST",
                published_at=now - timedelta(hours=1 if platform == "facebook" else 2),
            )
            session.add(post)
            session.flush()
            contact = Contact(
                brand_id=brand.id,
                platform=platform,
                external_id="audience-" + platform,
                display_name="驗收觀眾",
            )
            session.add(contact)
            session.flush()
            thread = Thread(
                brand_id=brand.id,
                account_id=account.id,
                contact_id=contact.id,
                kind="comment_thread",
                external_id="root-" + platform,
                post_id=post.id,
            )
            session.add(thread)
            session.flush()
            ids[platform] = post.id
            texts = [
                "使用半小時還有問題，是操作步驟有誤，還是需要調整設定？",
                "可以先記錄問題出現的時間，並提供畫面截圖，讓品牌客服協助確認。",
                "謝謝，我會先拍照。我剛開始使用，多久需要檢查一次？",
                "這是沒有可靠父留言紀錄的舊留言，保持獨立顯示。",
                "這則回覆的父留言尚未同步，不能猜測它屬於哪一串。",
            ]
            for index in range(205 if platform == "facebook" else 5):
                session.add(
                    Message(
                        thread_id=thread.id,
                        contact_id=contact.id,
                        external_id=f"{platform}-c{index}",
                        text="[隔離驗收] "
                        + (
                            texts[index]
                            if index < 5
                            else f"觀眾問題 {index}：想了解服務與日常保養的差別。"
                        ),
                        sent_at=now
                        - timedelta(days=40 if index >= 100 else 0, minutes=30)
                        + timedelta(seconds=index),
                        direction="out" if index == 1 else "in",
                        author_type="brand" if index == 1 else "fan",
                        comment_parent_known=index != 3,
                        comment_parent_id=f"{platform}-c{index - 1}"
                        if index in (1, 2)
                        else "missing"
                        if index == 4
                        else None,
                        comment_root_id=f"{platform}-c0" if index < 3 else None,
                    )
                )
            for index in range(4):
                session.add(
                    MetricSnapshot(
                        post_id=post.id,
                        captured_at=now - timedelta(hours=4 - index),
                        views=index * 120,
                        reach=index * 90 if index != 1 else None,
                        comments=index * 2,
                        likes=index * 3,
                        shares=0,
                        saves=None,
                    )
                )
        session.flush()
    server_log = (folder / "server.log").open("w", encoding="utf-8")
    cleanup(server_log.close)
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--timeout-keep-alive",
            str(KEEP_ALIVE_SECONDS),
        ],
        cwd=REPO / "backend",
        env={**os.environ, **env},
        stdout=server_log,
        stderr=server_log,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    cleanup(stop_process, server)
    checks, measures, errors, external = [], [], [], []
    try:
        for _ in range(100):
            try:
                with urllib.request.urlopen(origin + "/api/health", timeout=1):
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
                    if route.request.method not in {
                        "GET",
                        "HEAD",
                    } and not route.request.url.endswith("/api/auth/login"):
                        route.abort()
                    else:
                        route.continue_()
                else:
                    external.append(route.request.url.split("?")[0])
                    route.abort()

            context.route("**/*", guard)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            comment_requests = []
            page.on(
                "request",
                lambda request: (
                    comment_requests.append(request.url)
                    if "/comment-threads?" in request.url
                    else None
                ),
            )

            def capture(name):
                page.wait_for_load_state("networkidle")
                value = page.evaluate("""() => ({
                    width: innerWidth, height: innerHeight,
                    document_height: document.documentElement.scrollHeight,
                    document: document.documentElement.scrollWidth <= innerWidth,
                    overflow: [...document.querySelectorAll('*')].filter(e => {
                        const s = getComputedStyle(e), r = e.getBoundingClientRect();
                        return r.width > 0 && r.height > 0
                            && ['auto','scroll'].includes(s.overflowX)
                            && e.scrollWidth > e.clientWidth + 2;
                    }).map(e => e.className),
                    text: document.querySelector('.comment-text')
                        ? getComputedStyle(document.querySelector('.comment-text')).fontSize : null,
                    columns: getComputedStyle(document.querySelector('.post-detail'))
                        .gridTemplateColumns
                })""")
                assert value["document"] and not value["overflow"], value
                assert value["document_height"] == value["height"], value
                page.screenshot(path=str(artifacts / (name + ".png")), full_page=False)
                measures.append({"screenshot": name + ".png", **value})

            page.goto(origin)
            page.get_by_label("帳號", exact=True).fill("admin")
            page.get_by_label("密碼", exact=True).fill(password)
            page.get_by_role("button", name="登入工作檯").click()
            page.get_by_role("button", name="貼文數據", exact=True).click()
            expect(page.locator(".post-card")).to_have_count(1)
            post_dates = page.get_by_role("group", name="發文日期", exact=True)
            comment_dates = page.get_by_role("group", name="留言日期", exact=True)
            capture("fix-list-1440x900")
            page.locator(".post-card").click()
            expect(page.locator(".comment-range-total")).to_have_text("此範圍 100 則")
            assert "period=30" in comment_requests[-1]
            initial = page.request.get(comment_requests[-1]).json()
            assert initial['total'] == 205 and initial['range_total'] == 100
            assert len({row['id'] for row in initial['items']}) == len(initial['items'])
            comment_requests.clear()
            comment_dates.get_by_role("radio", name="近 90 天", exact=True).click()
            expect(page.locator('.post-comment[data-depth="0"]')).to_have_count(50)
            expect(page.locator(".post-comment")).to_have_count(50)
            expect(page.locator(".comment-range-total")).to_have_text("此範圍 205 則")
            assert (
                page.locator(".post-metrics").evaluate("e => e.getBoundingClientRect().width")
                == 380
            )
            capture("fix-comments-1440x900")
            assert len(comment_requests) == 1 and "limit=50" in comment_requests[0]
            page.wait_for_timeout(3200)
            assert len(comment_requests) == 1
            checks.append("50-latest-roots-with-server-pagination")
            more = page.get_by_role("button", name="顯示更多", exact=True)
            more.click()
            expect(page.locator('.post-comment[data-depth="0"]')).to_have_count(100)
            expect(page.locator(".post-comment")).to_have_count(102)
            for root_count in (150, 200, 203):
                more.click()
                expect(page.locator('.post-comment[data-depth="0"]')).to_have_count(root_count)
            expect(more).to_have_count(0)
            expect(page.locator(".post-comment")).to_have_count(205)
            assert page.locator('.post-comment[data-depth="2"]').count() == 1
            ids_on_page = page.locator(".post-comment").evaluate_all(
                "es => es.map(e => e.dataset.messageId)"
            )
            assert len(ids_on_page) == len(set(ids_on_page)) == 205
            checks.append("load-more-preserves-replies-no-duplicates-complete")
            comment_dates.get_by_role("radio", name="近 7 天", exact=True).click()
            expect(page.locator(".comment-range-total")).to_have_text("此範圍 100 則")
            expect(page.locator('.post-comment[data-depth="0"]')).to_have_count(50)
            more.click()
            expect(page.locator(".post-comment")).to_have_count(100)
            expect(more).to_have_count(0)
            assert "comment_range=7" in page.url
            checks.append("filter-resets-page-and-more-stays-in-range")
            post_dates.get_by_role("radio", name="近 30 天", exact=True).click()
            assert "post_range=30" in page.url
            page.reload()
            expect(
                comment_dates.get_by_role("radio", name="近 7 天", exact=True)
            ).to_have_attribute("aria-checked", "true")
            expect(post_dates.get_by_role("radio", name="近 30 天", exact=True)).to_have_attribute(
                "aria-checked", "true"
            )
            expect(page.locator(".comment-range-total")).to_have_text("此範圍 100 則")
            expect(page.locator('.post-comment[data-depth="0"]')).to_have_count(50)
            checks.append("independent-filter-urls-survive-reload")
            from zoneinfo import ZoneInfo

            today = now.astimezone(ZoneInfo("Asia/Taipei")).date()
            tomorrow = (today + timedelta(days=1)).isoformat()
            post_dates.get_by_label("發文日期起日").fill(tomorrow)
            expect(page.locator(".post-card")).to_have_count(0)
            expect(page.locator(".comment-range-total")).to_have_text("此範圍 100 則")
            post_dates.get_by_role("radio", name="全部", exact=True).click()
            expect(page.locator(".post-card")).to_have_count(1)
            expect(comment_dates.get_by_role("radio")).to_have_text(['近 7 天', '近 30 天', '近 90 天', '全部'])
            expect(comment_dates.get_by_label("留言日期起日")).to_have_count(0)
            comment_dates.get_by_role("radio", name="全部", exact=True).click()
            expect(page.locator(".comment-range-total")).to_have_text("此範圍 205 則")
            expect(comment_dates.get_by_role("radio", name="全部", exact=True)).to_have_attribute('aria-checked', 'true')
            assert 'period=all' in comment_requests[-1]
            page.reload()
            expect(comment_dates.get_by_role("radio", name="全部", exact=True)).to_have_attribute('aria-checked', 'true')
            expect(page.locator(".comment-range-total")).to_have_text("此範圍 205 則")
            for days in (30, 90):
                comment_dates.get_by_role("radio", name=f"近 {days} 天", exact=True).click()
                expect(page.locator(".comment-range-total")).to_have_text(
                    "此範圍 100 則" if days == 30 else "此範圍 205 則"
                )
                expect(page.locator('.post-comment[data-depth="0"]')).to_have_count(50)
                assert f"comment_range={days}" in page.url
            page.reload()
            expect(comment_dates.get_by_role("radio", name="近 90 天", exact=True)).to_have_attribute("aria-checked", "true")
            expect(page.locator('.post-comment[data-depth="0"]')).to_have_count(50)
            checks.append("comment-7-30-90-filter-and-pagination")
            for width in (599, 600):
                page.set_viewport_size({"width": width, "height": 844})
                metrics_first = page.locator(".post-metrics").evaluate("""e =>
                    e.getBoundingClientRect().bottom
                    <= document.querySelector('.post-comments').getBoundingClientRect().top""")
                assert metrics_first == (width < 600)
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.locator(".post-metrics").evaluate("""e =>
                    e.getBoundingClientRect().bottom
                <= document.querySelector('.post-comments').getBoundingClientRect().top""")
            capture("fix-mobile-top-390x844")
            page.locator(".post-detail").evaluate("""e => {
                e.scrollTop += e.querySelector('.post-metrics').getBoundingClientRect().top
                    - e.getBoundingClientRect().top;
            }""")
            capture("fix-mobile-metrics-390x844")
            page.locator(".post-detail").evaluate("""e => {
                e.scrollTop += e.querySelector('.post-comments').getBoundingClientRect().top
                    - e.getBoundingClientRect().top;
            }""")
            capture("fix-mobile-comments-390x844")
            page.get_by_role("button", name="← 返回貼文", exact=True).click()
            capture("fix-list-390x844")
            expect(post_dates.get_by_role("radio", name="全部", exact=True)).to_have_attribute(
                "aria-checked", "true"
            )
            checks.append("mobile-metrics-before-comments-desktop-three-columns")
            assert not errors and not external, (errors, external)
            browser.close()
        summary = {
            "checks": checks,
            "check_count": len(checks),
            "screenshots": len(measures),
            "messages": {"facebook": 205, "instagram": 5},
            "page_errors": errors,
            "external_requests": external,
            "measurements": measures,
        }
        (artifacts / "isolated-verification.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
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
        engine.dispose()




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
    main()

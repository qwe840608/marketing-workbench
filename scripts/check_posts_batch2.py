"""批次 2：隔離資料與 Playwright，禁止瀏覽器連接外部服務。"""

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
import subprocess
import sys
import time
import urllib.request
from datetime import timedelta
from pathlib import Path

from ports import KEEP_ALIVE_SECONDS, browser_port

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
        for platform in ("facebook", "instagram", "threads"):
            account = Account(
                brand_id=brand.id,
                platform=platform,
                external_id="batch2-" + platform,
                name="[隔離驗收] " + {"facebook": "FB", "instagram": "IG", "threads": "Threads"}[platform],
            )
            session.add(account)
            session.flush()
            post = Post(
                account_id=account.id,
                external_id="post-" + platform,
                caption={
                    "facebook": "[隔離驗收] 使用時遇到問題，諮詢前要先確認什麼？",
                    "instagram": "[隔離驗收] Reels：從使用者的提問，找出內容方向",
                    "threads": "[隔離驗收] Threads：這週最常被問到的三個問題",
                }[platform],
                media_type={"facebook": "POST", "instagram": "REELS", "threads": "TEXT_POST"}[platform],
                # Threads 最舊，預設平台仍是最新貼文所在的 FB。
                published_at=now - timedelta(hours={"facebook": 1, "instagram": 2, "threads": 3}[platform]),
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
                        sent_at=now - timedelta(minutes=30) + timedelta(seconds=index),
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
                        # Threads 沒有觸及與收藏；轉發與引用放在 extra_json。
                        reach=None if platform == "threads" else index * 90 if index != 1 else None,
                        comments=index * 2,
                        likes=index * 3,
                        shares=0,
                        saves=None,
                        extra_json={"reposts": index, "quotes": index // 2}
                        if platform == "threads"
                        else {},
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
                    route.continue_()
                else:
                    external.append(route.request.url.split("?")[0])
                    route.abort()

            context.route("**/*", guard)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))

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
            panel = page.get_by_role("tablist", name="貼文平台")
            expect(panel.get_by_role("tab", name="FB", exact=True)).to_have_attribute(
                "aria-selected", "true"
            )
            expect(page.locator(".post-card")).to_have_count(1)
            for label in ("YouTube", "TikTok"):
                button = panel.get_by_role("tab", name=label, exact=True)
                expect(button).to_be_enabled()
                button.click()
                expect(button).to_have_attribute("aria-selected", "true")
                expect(page.locator(".follower-unconnected")).to_have_text(
                    "尚未串接，串接後開始記錄" + ("訂閱數" if label == "YouTube" else "粉絲數")
                )
                expect(page.locator(".post-card")).to_have_count(0)
            panel.get_by_role("tab", name="FB", exact=True).click()
            expect(page.locator(".post-card")).to_have_count(1)
            checks.append("latest-platform-and-unconnected-tabs")
            # 卡片高度要依內容撐開，來源、內文、時間不可互相重疊。
            assert page.locator(".post-card").evaluate(
                "e => e.scrollHeight <= e.clientHeight + 1 && [...e.children].every("
                "(c, i, a) => !i || a[i - 1].getBoundingClientRect().bottom"
                " <= c.getBoundingClientRect().top + 1)"
            )
            # 發文日期已移到粉絲數列（e92902b）：四個區間按鈕固定一行，且不超出粉絲數面板。
            assert page.evaluate(
                "() => { const b = [...document.querySelectorAll('.follower-panel .post-date-filter .filter-choice button')]"
                ".map(e => e.getBoundingClientRect()); const c = document.querySelector('.follower-panel')"
                ".getBoundingClientRect(); return b.length === 4 && b.every(r => Math.abs(r.top - b[0].top) < 1)"
                " && b[0].left >= c.left && b[3].right <= c.right + 1; }"
            )
            capture("fb-list-1440x900")
            page.locator(".post-card").click()
            expect(page.locator(".post-comment")).to_have_count(50)
            more = page.get_by_role("button", name="顯示更多", exact=True)
            for count in (100, 150, 200, 205):
                more.click()
                expect(page.locator(".post-comment")).to_have_count(count)
            expect(more).to_have_count(0)
            assert page.locator('.post-comment[data-depth="2"]').count() == 1
            expect(page.locator(".post-comment").filter(has_text="舊留言")).to_have_attribute("data-depth", "0")
            message_ids = page.locator(".post-comment").evaluate_all("es => es.map(e => e.dataset.messageId)")
            assert len(set(message_ids)) == len(message_ids) == 205
            expect(page.locator(".brand-comment").first).to_contain_text("品牌")
            assert page.locator(".batch2-posts textarea").count() == 0
            checks.append("all-205-comments-nesting-brand-readonly")
            data = page.request.get(origin + f"/api/posts/{ids['facebook']}/comments").json()
            assert data["total"] == 205 and len(data["items"]) == 200 and data["next_after"]
            tail = page.request.get(origin + f"/api/posts/{ids['facebook']}/comments?after_id={data['next_after']}").json()
            assert len(tail["items"]) == 5 and tail["next_after"] is None
            for message in data["items"][:5]:
                inbox = page.request.get(
                    origin + f"/api/threads/{message['thread_id']}/messages?limit=200&offset=0"
                ).json()
                assert any(row["id"] == message["id"] and row["text"] == message["text"] for row in inbox)
            assert page.request.get(origin + "/api/inbox").status == 404
            checks.append("stored-comments-api-pagination-message-identity-and-retired-inbox")
            capture("fb-comments-1440x900")
            assert page.locator(".post-conversation").evaluate(
                "e => e.scrollHeight > e.clientHeight"
            )
            page.locator(".post-conversation").evaluate("e => e.scrollTop = 250")
            assert page.locator(".post-metrics").evaluate("e => e.scrollTop") == 0
            checks.append("desktop-independent-scroll")
            panel.get_by_role("tab", name="IG", exact=True).click()
            expect(page.locator(".post-card")).to_have_count(1)
            expect(page.locator(".post-card")).to_contain_text("Reels")
            expect(panel.get_by_role("tab", name="FB", exact=True)).to_have_attribute(
                "aria-selected", "false"
            )
            page.locator(".post-card").click()
            expect(page.locator(".post-comment")).to_have_count(5)
            capture("ig-reels-1440x900")
            panel.get_by_role("tab", name="Threads", exact=True).click()
            expect(panel.get_by_role("tab", name="Threads", exact=True)).to_have_attribute(
                "aria-selected", "true"
            )
            expect(page.locator(".post-card")).to_have_count(1)
            expect(page.locator(".post-card .ideation-platform")).to_have_text("Threads")
            expect(page.locator(".post-card")).to_contain_text("[隔離驗收] Threads")
            capture("threads-list-1440x900")
            page.locator(".post-card").click()
            expect(page.locator(".post-comment")).to_have_count(5)
            check_threads_detail(page, expect)
            page.locator(".post-conversation").evaluate("e => e.scrollTop = 0")
            capture("threads-detail-1440x900")
            page.locator(".post-metrics").evaluate("e => e.scrollTop = 280")
            capture("threads-metrics-1440x900")
            page.set_viewport_size({"width": 768, "height": 1024})
            page.wait_for_load_state("networkidle")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.set_viewport_size({"width": 1440, "height": 900})
            checks.append("threads-tab-posts-metrics-names-and-replies")
            panel.get_by_role("tab", name="IG", exact=True).click()
            page.locator(".post-card").click()
            expect(page.locator(".post-comment")).to_have_count(5)
            page.reload()
            expect(page.locator(".post-comment")).to_have_count(5)
            expect(
                page.get_by_role("tablist", name="貼文平台").get_by_role(
                    "tab", name="IG", exact=True
                )
            ).to_have_attribute("aria-selected", "true")
            assert "post_platform=instagram" in page.url and "view=posts" in page.url
            checks.append("platform-and-post-survive-reload")
            page.set_viewport_size({"width": 390, "height": 844})
            capture("ig-reels-390x844")
            page.get_by_role("button", name="← 返回貼文", exact=True).click()
            capture("ig-list-390x844")
            panel.get_by_role("tab", name="FB", exact=True).click()
            page.locator(".post-card").click()
            expect(page.locator(".post-comment")).to_have_count(50)
            for count in (100, 150, 200, 205):
                more.click()
                expect(page.locator(".post-comment")).to_have_count(count)
            capture("fb-comments-390x844")
            page.locator(".post-detail").evaluate("e => e.scrollTop = e.scrollHeight")
            expect(page.get_by_role("heading", name="貼文成效", exact=True)).to_be_visible()
            capture("fb-metrics-390x844")
            checks.append("mobile-comments-and-metrics-scroll")
            panel.get_by_role("tab", name="Threads", exact=True).click()
            expect(page.locator(".post-card")).to_have_count(1)
            capture("threads-list-390x844")
            page.locator(".post-card").click()
            expect(page.locator(".post-comment")).to_have_count(5)
            capture("threads-detail-390x844")
            page.locator(".metric-grid").scroll_into_view_if_needed()
            expect(page.get_by_role("heading", name="貼文成效", exact=True)).to_be_visible()
            capture("threads-metrics-390x844")
            checks.append("threads-mobile-no-horizontal-overflow")
            assert all(m["text"] in (None, "16px") for m in measures)
            assert not errors and not external, (errors, external)
            browser.close()
        summary = {
            "checks": checks,
            "check_count": len(checks),
            "screenshots": len(measures),
            "messages": {"facebook": 205, "instagram": 5, "threads": 5},
            "page_errors": errors,
            "external_requests": external,
            "measurements": measures,
        }
        (artifacts / "verification.json").write_text(
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


def check_threads_detail(page, expect):
    """Threads 單篇：成效只顯示 Threads 有的指標，回覆唯讀，抓取按鈕與其他平台一致。"""
    names = ["觀看", "按讚", "回覆", "轉發", "引用", "分享"]
    expect(page.locator(".batch2-posts .metric-grid > div")).to_have_count(6)
    assert page.locator(".metric-grid > div span").all_inner_texts() == names
    # 最新一筆快照：觀看 360、按讚 9、回覆 6、轉發 3、引用 1、分享 0；平台沒有的指標不顯示。
    assert page.locator(".metric-grid > div strong").all_inner_texts() == ["360", "9", "6", "3", "1", "0"]
    for missing in ("觸及", "收藏"):
        assert page.locator(".post-metrics").get_by_text(missing, exact=True).count() == 0, missing
    expect(page.locator(".metric-chart select option")).to_have_text(names)
    expect(page.locator(".metric-chart select")).to_have_value("views")
    assert page.locator(".snapshot-table th").all_inner_texts() == ["抓取時間", "觀看", "按讚", "回覆"]
    # 成效面板 380px：抓取時間「日期 時間」與指標欄名都排在同一行，不拆開、不直排。
    lines = page.locator(".snapshot-table").evaluate(
        """table => [...table.querySelectorAll('th,td')].map(cell => {
            const range = document.createRange(); range.selectNodeContents(cell);
            return [cell.textContent, new Set([...range.getClientRects()].map(r => Math.round(r.top))).size,
                cell.offsetWidth, table.clientWidth];
        })"""
    )
    assert lines and all(row[1] == 1 for row in lines), lines
    expect(page.locator(".comment-sync strong")).to_have_text("Threads 回覆")
    expect(page.locator(".post-comments .comment-sync")).to_have_count(1)  # uiorder: 各平台同步區都在留言與回覆卡片內
    expect(page.locator(".post-metrics .comment-sync")).to_have_count(0)
    expect(page.get_by_role("button", name="抓取留言", exact=True)).to_be_enabled()
    expect(page.locator(".comment-heading h3")).to_have_text("留言與回覆")
    expect(page.locator(".comment-heading .readonly-label")).to_have_text("唯讀")
    assert page.locator('.post-comment[data-depth="2"]').count() == 1
    expect(page.locator(".brand-comment").first).to_contain_text("品牌")
    assert page.locator(".batch2-posts textarea").count() == 0


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

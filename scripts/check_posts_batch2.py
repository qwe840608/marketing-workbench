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
import sys
from datetime import timedelta

from browser_harness import REPO, launch_server, run_uvicorn, seed_records
from ports import browser_port


def serve():
    # 與原本 `python -m uvicorn app.main:app` 相同：使用模組層級的 app（讀 backend/.env，再由環境變數覆寫）。
    from app.main import app

    run_uvicorn(app, sys.argv[2])


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
                        # IG Reels 有影片觀看表現：平均觀看時長以毫秒保存，另有總時數、滑走率與留存。
                        avg_watch_time=index * 1500 if platform == "instagram" else None,
                        extra_json={"reposts": index, "quotes": index // 2}
                        if platform == "threads"
                        else {"metric_units": {"avg_watch_time": "milliseconds"},
                              "watch_hours": index * 0.25, "skip_rate": 40 + index,
                              "retention": [100, 80, 61.5, 40]}
                        if platform == "instagram"
                        else {},
                    )
                )
        session.flush()
    server = launch_server(folder, origin, script=__file__, args=[port])
    checks, measures, errors, external = [], [], [], []
    try:
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
            watch = page.get_by_role("region", name="觀看表現")
            expect(watch.locator(".watch-grid span")).to_have_text(
                ["平均觀看時長（秒）", "觀看總時數（小時）", "前 3 秒滑走率（%）"]
            )
            expect(watch.locator(".watch-grid strong")).to_have_text(["4.5", "0.75", "43"])
            expect(page.locator(".retention-chart .metric-note")).to_have_text(
                "影片中段仍在看：61.5% · 看到結尾：40%"
            )
            # 觀看變化與觀眾留存各自一張有外框的卡片，觀看指標用分頁籤切換。
            watch_chart = page.get_by_role("region", name="觀看變化")
            watch_tabs = watch_chart.get_by_role("tab")
            expect(watch_tabs).to_have_text(["平均觀看時長（秒）", "觀看總時數（小時）", "前 3 秒滑走率（%）"])
            expect(watch_tabs.first).to_have_attribute("aria-selected", "true")
            watch_tabs.nth(2).click()
            expect(watch_tabs.nth(2)).to_have_attribute("aria-selected", "true")
            expect(watch_chart.locator("svg")).to_have_attribute("aria-label", "前 3 秒滑走率（%）變化，4筆有效快照，最高43")
            for name in ("數據變化", "觀看變化", "觀眾留存"):
                assert page.get_by_role("region", name=name).evaluate("e => getComputedStyle(e).borderTopStyle") == "solid", name
            expect(page.locator(".post-metrics .metric-chart select")).to_have_count(0)
            page.locator(".post-metrics").evaluate("e => e.scrollTop = e.querySelector('.watch-chart').offsetTop - 120")
            capture("ig-watch-charts-1440x900")
            checks.append("ig-reels-watch-time-skip-rate-retention")
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
            check_comment_date_ranges(page, origin, factory, now, capture, checks)
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
        engine.dispose()


def check_comment_date_ranges(page, origin, factory, now, capture, checks):
    """批次 2 修正（原 check_posts_fix）：留言日期 7／30／90／全部與分頁、網址保留、成效欄位置。

    把 FB 貼文第 100 則以後的留言改成 40 天前，讓「近 30 天」只剩 100 則、「全部」仍是 205 則；
    前面的批次 2 斷言都已在這之前完成，不受此處資料改動影響。
    """
    from zoneinfo import ZoneInfo

    from playwright.sync_api import expect
    from sqlalchemy import select

    from app.models import Message

    with factory.begin() as session:
        aged = [f"facebook-c{index}" for index in range(100, 205)]
        for message in session.scalars(select(Message).where(Message.external_id.in_(aged))):
            message.sent_at -= timedelta(days=40)
    comment_requests = []
    page.on(
        "request",
        lambda request: (
            comment_requests.append(request.url)
            if "/comment-threads?" in request.url
            else None
        ),
    )
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(origin)
    page.get_by_role("button", name="貼文數據", exact=True).click()
    page.get_by_role("tablist", name="貼文平台").get_by_role("tab", name="FB", exact=True).click()
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
    # 成效在中間且是最寬的欄；貼文摘要與留言在右側。
    assert page.locator(".post-metrics").evaluate("""e => {
        const m = e.getBoundingClientRect(),
            c = document.querySelector('.post-conversation').getBoundingClientRect();
        return m.right <= c.left && m.width > c.width;
    }""")
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
        assert metrics_first
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
    checks.append("mobile-tablet-metrics-before-comments-desktop-metrics-center")


def check_threads_detail(page, expect):
    """Threads 單篇：成效只顯示 Threads 有的指標，回覆唯讀，抓取按鈕與其他平台一致。"""
    names = ["觀看", "按讚", "回覆", "轉發", "引用", "分享"]
    expect(page.locator(".batch2-posts .metric-grid > div")).to_have_count(6)
    assert page.locator(".metric-grid > div span").all_inner_texts() == names
    # 最新一筆快照：觀看 360、按讚 9、回覆 6、轉發 3、引用 1、分享 0；平台沒有的指標不顯示。
    assert page.locator(".metric-grid > div strong").all_inner_texts() == ["360", "9", "6", "3", "1", "0"]
    for missing in ("觸及", "收藏"):
        assert page.locator(".post-metrics").get_by_text(missing, exact=True).count() == 0, missing
    tabs = page.get_by_role("region", name="數據變化").get_by_role("tab")
    expect(tabs).to_have_text(names)
    expect(tabs.first).to_have_attribute("aria-selected", "true")
    # 快照數字已在「數據變化」曲線，不再另列數據快照表。
    expect(page.locator(".snapshot-table, .snapshot-heading")).to_have_count(0)
    expect(page.locator(".comment-sync strong")).to_have_text("Threads 回覆")
    expect(page.locator(".post-comments .comment-sync")).to_have_count(1)  # uiorder: 各平台同步區都在留言與回覆卡片內
    expect(page.locator(".post-metrics .comment-sync")).to_have_count(0)
    expect(page.get_by_role("button", name="抓取留言", exact=True)).to_be_enabled()
    expect(page.locator(".comment-heading h3")).to_have_text("留言與回覆")
    expect(page.locator(".comment-heading .readonly-label")).to_have_text("唯讀")
    assert page.locator('.post-comment[data-depth="2"]').count() == 1
    expect(page.locator(".brand-comment").first).to_contain_text("品牌")
    assert page.locator(".batch2-posts textarea").count() == 0


if __name__ == "__main__":
    serve() if "--serve" in sys.argv else main()

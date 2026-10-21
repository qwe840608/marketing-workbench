"""平台設定教學彈出視窗：隔離資料庫與伺服器，不連外、不呼叫任何平台。"""

import re

from browser_harness import REPO, main
from playwright.sync_api import expect
from ui_navigation import navigate

# 權限一個一列、各自一顆複製鈕（Meta 後台要逐一新增）。
FB = ["pages_show_list", "pages_read_engagement", "pages_read_user_content", "pages_manage_metadata", "pages_manage_posts", "read_insights"]
IG = ["instagram_basic", "instagram_manage_comments", "instagram_manage_insights", "instagram_content_publish"]
THREADS = ["threads_basic", "threads_content_publish", "threads_manage_replies", "threads_manage_insights", "threads_read_replies"]
TT_SCOPES = ["user.info.basic", "user.info.stats", "video.list", "video.upload"]
YT_SCOPES = ["https://www.googleapis.com/auth/youtube.readonly", "https://www.googleapis.com/auth/yt-analytics.readonly", "https://www.googleapis.com/auth/youtube.upload"]


def exercise(page, unused, shot, checks):
    from app.config import Settings
    from app.services.credentials import GROUPS

    settings = Settings(_env_file=None)
    for path in (settings.database_path, settings.export_root):
        assert path.resolve().is_relative_to((REPO / ".runtime").resolve()), path
    folder = REPO / ".runtime/guides4-screens"
    folder.mkdir(parents=True, exist_ok=True)
    size = page.viewport_size
    mobile = size["width"] < 600
    popups = []
    page.on("popup", lambda p: popups.append(p.url))
    page.context.on("page", lambda p: popups.append(p.url) if p is not page else None)

    def stable():
        page.wait_for_load_state("networkidle")
        page.evaluate("async () => { await document.fonts.ready; await new Promise(r => "
                      "requestAnimationFrame(() => requestAnimationFrame(r))); }")

    def no_overflow(label):
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (label, page.viewport_size)
        dialog = page.get_by_role("dialog")
        if dialog.count():
            assert dialog.evaluate("e => e.scrollWidth <= e.clientWidth + 1"), (label, "dialog")
            assert dialog.locator(".guide-body").evaluate("e => e.scrollWidth <= e.clientWidth + 1"), (label, "body")

    def open_faq(dialog):
        # 常見問題預設收合，點開後看得到說明。
        details = dialog.locator("details.guide-faq")
        expect(details).to_have_count(1)
        assert details.get_attribute("open") is None, "faq starts collapsed"
        details.locator("summary").click()
        expect(details).to_have_attribute("open", "")
        expect(details.locator("li").first).to_be_visible()

    def check_links(dialog, title):
        # 直達平台後台的連結：新分頁開啟、noopener、https 且網域在允許清單內；檢查屬性，不實際點擊連外。
        links = dialog.locator(".guide-links a")
        assert links.count() >= 1, (title, "links")
        for item in links.all():
            href = item.get_attribute("href")
            assert re.match(r"^https://(developers\.facebook\.com|console\.cloud\.google\.com|manager\.line\.biz|developers\.line\.biz|developers\.tiktok\.com|console\.typesafe\.ai|dashboard\.ngrok\.com)/", href), (title, href)
            assert item.get_attribute("target") == "_blank", (title, href)
            assert "noopener" in item.get_attribute("rel"), (title, href)
            expect(item).to_be_visible()

    def scroll_to_end(dialog, label):
        # 捲到底要看得到最後一步，而且標題列（含關閉）固定在頂部不跟著捲。
        body = dialog.locator(".guide-body")
        top_before = dialog.locator(".guide-heading").bounding_box()["y"]
        body.evaluate("e => { e.scrollTop = e.scrollHeight; }")
        page.wait_for_timeout(100)
        assert body.evaluate("e => e.scrollTop + e.clientHeight >= e.scrollHeight - 1"), (label, "scrolled to end")
        last = dialog.locator("details.guide-faq")
        expect(last).to_be_visible()
        last_box, body_box = last.bounding_box(), body.bounding_box()
        assert last_box["y"] + last_box["height"] <= body_box["y"] + body_box["height"] + 1, (label, "faq visible at end")
        assert dialog.locator(".guide-heading").bounding_box()["y"] == top_before, (label, "heading stays fixed")
        expect(dialog.get_by_role("button", name="關閉", exact=True)).to_be_visible()
        body.evaluate("e => { e.scrollTop = 0; }")

    def capture(name):
        stable()
        page.screenshot(path=str(folder / f"{name}-{size['width']}x{size['height']}.png"))

    navigate(page, "平台連線")
    cards = page.locator(".connection-card")
    expect(cards).to_have_count(len(GROUPS))
    stable()
    # 讀取與畫面相同的 API，作為回呼網址與 Webhook 網址的期望值；複製以替身記錄，不依賴剪貼簿權限。
    status = page.evaluate("fetch('/api/oauth/status').then(r => r.json())")
    webhook = page.evaluate("fetch('/api/credentials').then(r => r.json()).then(d => d.webhook_public_url)")
    assert webhook, "harness must provide a webhook url"
    callbacks = status["callbacks"]
    page.evaluate("""() => {
        window.__copied = [];
        Object.defineProperty(navigator, 'clipboard', { configurable: true,
            value: { writeText: async value => { window.__copied.push(value); } } });
    }""")

    # YouTube 外開連結與後端文字端點都已移除；頁面沒有任何開新分頁的連結。
    expect(page.locator("a[target=_blank]")).to_have_count(0)
    expect(page.locator("a[href*='youtube/guide']")).to_have_count(0)
    assert page.evaluate("fetch('/api/oauth/youtube/guide').then(r => r.status)") == 404
    expect(page.locator(".oauth-setup, .youtube-callback")).to_have_count(0)

    # TikTok 與 YouTube 同樣是自建用戶端：卡片直接設定 Client key／secret，未設定前不能連結；
    # 讀留言需要公司身分，卡片的「留言（選用）」照實說明。
    tiktok = page.locator("section.connection-card[aria-labelledby=connection-tiktok]")
    expect(tiktok).to_have_count(1)
    expect(page.locator("section.guide-card")).to_have_count(0)
    expect(tiktok.locator(".oauth-account .status-badge")).to_have_text("未連結")
    expect(tiktok.locator("form.credential-field")).to_have_count(2)
    assert tiktok.locator("form.credential-field").evaluate_all("rows => rows.map(r => r.getAttribute('aria-label'))") == ["TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET"]
    expect(tiktok.get_by_role("button", name="連結 TikTok 帳號", exact=True)).to_be_disabled()
    expect(tiktok.locator(".tiktok-comments")).to_contain_text("讀取 TikTok 留言需要以公司身分申請 TikTok API for Business")
    expect(tiktok.locator("details.oauth-manual")).to_have_count(0)
    # jev 與 Webhook 也有教學入口。
    expect(page.locator(".connection-card:has(#connection-jev)").get_by_role("button", name="設定教學")).to_have_count(1)
    expect(page.locator("section[aria-labelledby=connection-webhook]").get_by_role("button", name="設定教學")).to_have_count(1)
    # uiorder：Webhook 卡片只留 meta-inbound 與 line-notify 兩條網址（line-inbound 已退役），加 WEBHOOK_PUBLIC_URL 共三個唯讀欄位。
    endpoints = page.locator("section[aria-labelledby=connection-webhook]")
    expect(endpoints.locator("input[readonly]")).to_have_count(3)
    assert [text.strip() for text in endpoints.locator("label").all_inner_texts()] == ["公開網址", "Meta 留言通知網址", "LINE 通知網址"]
    expect(endpoints.locator("input[value$='/webhook/line-inbound']")).to_have_count(0)
    endpoints.scroll_into_view_if_needed()
    endpoints.screenshot(path=str(folder / f"webhook-card-{size['width']}x{size['height']}.png"))
    assert "line-inbound" not in endpoints.inner_text()
    tiktok.scroll_into_view_if_needed()

    cases = [
        ("connection-meta", "Facebook 粉專與 Instagram 設定教學", [callbacks["meta"], *FB, *IG]),
        ("connection-threads", "Threads 設定教學", [callbacks["threads"], *THREADS]),
        ("connection-youtube", "YouTube 設定教學", [*YT_SCOPES, callbacks["youtube"]]),
        ("connection-notify", "LINE 通知設定教學", [webhook.rstrip("/") + "/webhook/line-notify"]),
        ("connection-jev", "jev 設定教學", []),
        ("connection-webhook", "Webhook 設定教學", [webhook.rstrip("/") + "/webhook/meta-inbound"]),
        # TikTok 後端尚無授權路由：回呼網址由前端依工作檯網址組出，路徑與其他平台一致。
        ("connection-tiktok", "TikTok 設定教學", [status["backoffice_origin"] + "/api/oauth/tiktok/callback", *TT_SCOPES]),
    ]
    shots = {"connection-meta": "guide-meta", "connection-notify": "guide-line", "connection-jev": "guide-jev", "connection-webhook": "guide-webhook"}
    closers = ["button", "escape"] if mobile else ["button", "escape", "backdrop"]
    for card_id, title, copies in cases:
        card = page.locator(f"section[aria-labelledby={card_id}]")
        card.scroll_into_view_if_needed()
        button = card.get_by_role("button", name="設定教學", exact=True)
        expect(button).to_have_class("secondary")
        expect(card.locator("details.oauth-setup")).to_have_count(0)
        for index, closer in enumerate(closers):
            button.click()
            dialog = page.get_by_role("dialog")
            expect(dialog).to_have_count(1)
            expect(dialog).to_have_attribute("aria-modal", "true")
            expect(dialog).to_have_accessible_name(title)
            expect(dialog.get_by_role("heading", level=2)).to_have_text(title)
            expect(dialog.get_by_role("button", name="關閉", exact=True)).to_be_focused()
            for step in dialog.locator(".guide-steps li").all():
                assert step.inner_text().strip()
            # 精簡版內容：預估時間、開始前你需要、至少一個確認點、直達連結。
            expect(dialog.locator(".guide-time")).to_have_text(re.compile(r"^大約需要 \d+ 分鐘$"))
            expect(dialog.get_by_role("heading", name="開始前你需要")).to_be_visible()
            assert dialog.locator(".guide-intro li").count() >= 1, (title, "needs")
            assert dialog.locator(".guide-note.notice.success").count() >= 1, (title, "check point")
            check_links(dialog, title)
            if index == 0:
                open_faq(dialog)
                scroll_to_end(dialog, title)
                codes = dialog.locator(".guide-copy code")
                expect(codes).to_have_text(copies) if copies else expect(codes).to_have_count(0)
                no_overflow(title)
                if card_id in shots:
                    capture(shots[card_id])
                page.evaluate("window.__copied = []")
                for position, value in enumerate(copies):
                    copy = dialog.locator(".guide-copy").nth(position).get_by_role("button")
                    expect(copy).to_have_class("secondary")
                    copy.click()
                    expect(copy).to_have_text("已複製")
                    assert page.evaluate("window.__copied")[-1] == value, (title, value)
                # Tab 與 Shift+Tab 都不離開視窗。
                for key in ["Tab"] * 8 + ["Shift+Tab"] * 12:
                    page.keyboard.press(key)
                    assert page.evaluate("!!document.activeElement.closest('[role=dialog]')"), (title, key)
                if mobile:
                    box = dialog.bounding_box()
                    assert box["width"] >= size["width"] - 1 and box["height"] >= size["height"] - 1, box
            if closer == "button":
                dialog.get_by_role("button", name="關閉", exact=True).click()
            elif closer == "escape":
                page.keyboard.press("Escape")
            else:
                page.mouse.click(4, 4)
            expect(page.get_by_role("dialog")).to_have_count(0)
            expect(button).to_be_focused()
        checks.append(f"guide-{card_id}-intro-links-faq-copy-focus-close-{'-'.join(closers)}")

    # 每份教學（含展開的常見問題）在三種寬度都不水平溢出，捲到底看得到最後一步，標題列固定。
    for card_id, title, _ in cases:
        card = page.locator(f"section[aria-labelledby={card_id}]")
        card.scroll_into_view_if_needed()
        card.get_by_role("button", name="設定教學", exact=True).click()
        dialog = page.get_by_role("dialog")
        open_faq(dialog)
        for width, height in ((1440, 900), (768, 1024), (390, 844)):
            page.set_viewport_size({"width": width, "height": height})
            stable()
            no_overflow(f"{card_id}-{width}")
            scroll_to_end(dialog, f"{card_id}-{width}")
            if width == 390 and card_id not in {"connection-tiktok", "connection-jev"}:
                assert dialog.locator(".guide-body").evaluate("e => e.scrollHeight > e.clientHeight"), "body must scroll inside dialog"
        page.set_viewport_size(size)
        stable()
        page.keyboard.press("Escape")
        expect(page.get_by_role("dialog")).to_have_count(0)
    checks.append("guides-scroll-to-last-step-fixed-heading-all-widths")
    for width, height in ((1440, 900), (768, 1024), (390, 844)):
        page.set_viewport_size({"width": width, "height": height})
        stable()
        no_overflow("page-" + str(width))
    page.set_viewport_size(size)
    stable()

    assert not popups, popups
    assert len(page.context.pages) == 1, len(page.context.pages)
    checks.append("guides-no-popup-without-click-all-widths")


if __name__ == "__main__":
    main(exercise=exercise)

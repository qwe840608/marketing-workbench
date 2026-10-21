"""One-off comment controls in React; isolated server and mocked local API."""

from urllib.parse import parse_qs, urlsplit

import check_polish_frontend as polish
from browser_harness import main
from playwright.sync_api import expect


def check_comments(page, open_thread, shot, checks):
    expect(page.locator(".workspace")).to_be_visible()
    origin = urlsplit(page.url)._replace(path="", query="", fragment="").geturl()
    user = page.request.get(origin + "/api/auth/me").json()
    brand_id = page.request.get(origin + "/api/brands").json()[0]["id"]
    post = dict(
        id=901,
        account_id=801,
        external_id="isolated-comment-post",
        # 超過四行的長內文：驗證預設收合與展開／收合按鈕。
        caption="[隔離驗收] 手動留言\n" + "\n".join(f"第 {n} 行內文" for n in range(2, 9)),
        media_type="IMAGE",
        permalink=None,
        published_at="2020-01-01T00:00:00Z",
        schedule_tier="weekly",
    )
    sync = dict(
        state="idle",
        last_completed_at=None,
        last_auto_completed_at=None,
        auto_sync_enabled=False,
        window_days=None,
        manual_requested=False,
        next_poll_at="2099-09-30T04:05:00Z",
        retry_at=None,
        wait_reason=None,
        last_error=None,
        interval_minutes=10080,
        webhook_live=False,
        progress=dict(comments_done=False, pending_replies=0, pages=0, saved_comments=0),
    )
    # TikTok 影片：只同步影片與成效，不讀留言；清單要列出、留言區不能有抓取留言。
    tiktok_post = dict(post, id=902, account_id=802, external_id="isolated-tiktok-video",
                       caption="[隔離驗收] TikTok 影片", media_type="VIDEO")
    queued, stopped, reads = [], [], []
    tiktok_sync = []
    modes = []

    def posts(route):
        path = urlsplit(route.request.url).path
        if "/902/" in path and "/comments/" in path:
            tiktok_sync.append(path)
            route.fulfill(status=422, json={"detail": "TikTok 不讀留言"})
            return
        if path.endswith("/comments/sync"):
            if route.request.method == "POST":
                selected = page.get_by_role("group", name="留言日期", exact=True).locator(
                    '[role=radio][aria-checked="true"]'
                ).inner_text()
                assert parse_qs(urlsplit(route.request.url).query)["period"] == [
                    "all" if selected == "全部" else selected.split()[1]
                ]
                query = parse_qs(urlsplit(route.request.url).query)
                full = query.get('full_rescan') == ['true']
                assert not full or selected == '全部'
                queued.append(path)
                modes.append((role, selected, full))
                sync.update(state="pending", manual_requested=True)
                route.fulfill(status=202, json={"queued": 1})
            else:
                route.fulfill(json=sync)
        elif path.endswith("/comments/stop"):
            assert route.request.method == "POST"
            stopped.append(path)
            sync.update(state="stopped", manual_requested=False, wait_reason=None)
            route.fulfill(json={"stopped": True})
        elif path.endswith("/backfill"):
            route.fulfill(json={"accounts": []})
        elif path.endswith("/comment-threads"):
            reads.append(route.request.url)
            route.fulfill(
                json=dict(
                    items=[], total=0, range_total=0, root_total=0, root_ids=[], next_offset=None
                )
            )
        elif path.endswith("/followers"):
            route.fulfill(
                json={
                    "platform": "instagram",
                    "connected": False,
                    "years": [],
                    "current_count": None,
                    "week_delta": None,
                    "month_delta": None,
                }
            )
        elif path.endswith("/metrics"):
            route.fulfill(json=[])
        elif path.endswith("/platforms"):
            route.fulfill(json={"default_platform": "instagram", "comment_retention_days": 365,
                                "youtube_fresh_days": 30, "retention_enabled": False})
        elif path.endswith("/901"):
            route.fulfill(json=post)
        elif path.endswith("/902"):
            route.fulfill(json=tiktok_post)
        elif parse_qs(urlsplit(route.request.url).query).get("platform") == ["tiktok"]:
            route.fulfill(json=[tiktok_post])
        else:
            route.fulfill(json=[post])

    page.route("**/api/posts**", posts)
    page.route(
        "**/api/accounts**",
        lambda route: route.fulfill(
            json=[dict(id=801, brand_id=brand_id, platform="instagram", name="[隔離驗收] IG"),
                  dict(id=802, brand_id=brand_id, platform="tiktok", name="[隔離驗收] TikTok")]
        ),
    )
    page.route("**/api/auth/me", lambda route: route.fulfill(json=user))
    url = origin + "/?view=posts&platform=instagram&post_id=901"
    for role in ("admin", "marketing", "viewer"):
        user["role"] = role
        sync.update(state="idle", manual_requested=False, last_completed_at=None)
        page.goto(url)
        panel = page.get_by_role("region", name="留言同步")
        expect(panel).to_contain_text("只讀取目前留言日期範圍內的留言與回覆")
        caption = page.locator(".post-intro .post-caption")
        toggle = page.locator(".post-intro").get_by_role("button", name="展開全文 ▾")
        expect(caption).to_have_class("post-caption collapsed")
        collapsed_height = caption.evaluate("e => e.getBoundingClientRect().height")
        assert caption.evaluate("e => e.scrollHeight > e.clientHeight + 1")
        toggle.click()
        expect(caption).to_have_class("post-caption")
        assert caption.evaluate("e => e.getBoundingClientRect().height") > collapsed_height
        page.locator(".post-intro").get_by_role("button", name="收合 ▴").click()
        expect(caption).to_have_class("post-caption collapsed")
        # uiorder：留言同步狀態與「抓取留言」在「留言與回覆」卡片內，右側「貼文成效」只留成效數字。
        comments_card = page.get_by_role("region", name="留言與回覆")
        expect(comments_card.get_by_role("region", name="留言同步")).to_have_count(1)
        expect(page.locator(".post-metrics .comment-sync")).to_have_count(0)
        expect(page.locator(".post-metrics").get_by_role("button", name="抓取留言", exact=True)).to_have_count(0)
        expect(page.locator(".post-metrics .metric-grid")).to_have_count(1)
        assert comments_card.evaluate("e => { const sync = e.querySelector('.comment-sync'), list = e.querySelector('.comment-sync-summary'); return !!sync && list.compareDocumentPosition(sync) & Node.DOCUMENT_POSITION_FOLLOWING; }")
        # 平台條款的保存期限照後端設定顯示；隔離環境未啟用每日刪除，要一併說明。
        notice = comments_card.locator(".comment-retention")
        expect(notice).to_contain_text("自工作檯取得起保留 365 天")
        expect(notice).to_contain_text("每日刪除尚未啟用")
        assert notice.evaluate("e => e.scrollWidth <= e.clientWidth + 1")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        button = panel.get_by_role("button", name="抓取留言", exact=True)
        if role == "viewer":
            expect(button).to_have_count(0)
            expect(panel.get_by_role("button", name="停止", exact=True)).to_have_count(0)
            continue
        expect(button).to_be_enabled()
        button.click()
        expect(button).to_be_disabled()
        expect(panel).to_contain_text("已排入同步")
        sync.update(
            state="waiting",
            wait_reason="system_budget",
            calls_per_hour=180,
            usage_percent=8,
            retry_at="2099-09-30T04:05:00Z",
            progress=dict(comments_done=True, pending_replies=3, pages=17, saved_comments=120),
        )
        page.evaluate("window.__polishTick(3000)")
        expect(panel).to_contain_text("已達本系統每小時 180 次")
        expect(panel).to_contain_text("待續頁回覆 3 組")
        expect(panel).to_contain_text("已處理 17 頁 · 已存 120 則")
        expect(button).to_be_disabled()
        sync.update(
            state="idle",
            manual_requested=False,
            wait_reason=None,
            last_completed_at="2026-09-30T04:00:00Z",
        )
        page.evaluate("window.__polishTick(3000)")
        expect(panel).to_contain_text("最近完成")
        expect(button).to_be_enabled()
        button.click()
        expect(panel.get_by_role("button", name="停止", exact=True)).to_be_visible()
        panel.get_by_role("button", name="停止", exact=True).click()
        expect(panel).to_contain_text("已停止抓取")
        expect(button).to_be_enabled()
        expect(panel.get_by_role("button", name="停止", exact=True)).to_have_count(0)
        dates = page.get_by_role("group", name="留言日期", exact=True)
        expect(dates.get_by_role("radio")).to_have_count(4)
        expect(dates.get_by_role("radio", name="近 30 天", exact=True)).to_have_attribute(
            "aria-checked", "true"
        )
        for days in (7, 90, 30):
            dates.get_by_role("radio", name=f"近 {days} 天", exact=True).click()
            expect(dates.get_by_role("radio", name=f"近 {days} 天", exact=True)).to_have_attribute(
                "aria-checked", "true"
            )
            button.click()
            expect(button).to_be_disabled()
            panel.get_by_role("button", name="停止", exact=True).click()
            expect(button).to_be_enabled()
        dates.get_by_role("radio", name="全部", exact=True).click()
        full = panel.get_by_role("button", name="完整重抓", exact=True)
        expect(full).to_be_enabled()
        button.click()
        expect(panel).to_contain_text('已排入同步')
        assert modes[-1] == (role, '全部', False)
        panel.get_by_role('button', name='停止', exact=True).click()
        expect(button).to_be_enabled()
        before_cancel = len(queued)
        full.click()
        confirm = page.get_by_role("dialog")
        expect(confirm).to_be_visible()
        expect(confirm.get_by_role("button", name="取消", exact=True)).to_be_focused()
        confirm.get_by_role("button", name="取消", exact=True).click()
        expect(confirm).to_have_count(0)
        expect(full).to_be_focused()
        expect(button).to_be_enabled()
        assert len(queued) == before_cancel
        full.click()
        confirm.get_by_role("button", name="完整重抓", exact=True).click()
        expect(confirm).to_have_count(0)
        expect(button).to_be_disabled()
        expect(panel).to_contain_text('已排入同步')
        assert modes[-1] == (role, '全部', True)
        panel.get_by_role("button", name="停止", exact=True).click()
        expect(button).to_be_enabled()
        assert all("limit=50" in read for read in reads)
        shot("manual-comments-" + role)
    assert len(queued) == 14 and len(stopped) == 12
    assert sum(full for _, _, full in modes) == 2
    checks.append("long-caption-collapsed-by-default-and-toggles")
    checks.append("comment-manual-role-queue-progress-wait-completion-stop-filter")
    user["role"] = "admin"
    page.goto(origin + "/?view=posts&platform=tiktok&post_id=902")
    expect(page.get_by_role("tab", name="TikTok", exact=True)).to_have_attribute("aria-selected", "true")
    expect(page.locator(".post-list")).to_contain_text("[隔離驗收] TikTok 影片")
    card = page.get_by_role("region", name="留言與回覆")
    expect(card.locator(".comment-retention")).to_have_text("TikTok 留言不會讀取或保存。")
    expect(card.get_by_role("region", name="留言同步")).to_have_count(0)
    expect(page.get_by_role("button", name="抓取留言", exact=True)).to_have_count(0)
    assert tiktok_sync == [], tiktok_sync
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    shot("tiktok-posts")
    checks.append("tiktok-videos-listed-without-comment-sync")


if __name__ == "__main__":
    polish.run_checks = check_comments
    polish.check_polling = lambda *args: None
    main(polish=True)

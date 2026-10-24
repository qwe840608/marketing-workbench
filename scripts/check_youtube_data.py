"""YouTube UI on browser_harness's .runtime database/exports; API responses are synthetic."""

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

from browser_harness import REPO, main
from playwright.sync_api import expect


def exercise(page, unused, shot, checks):
    from app.config import Settings
    from app.models.base import utc_now

    settings = Settings(_env_file=None)
    for path in (settings.database_path, settings.export_root):
        assert path.resolve().is_relative_to((REPO / ".runtime").resolve())
    origin = page.evaluate("location.origin")
    internal = "https://office.example.test"
    folder = REPO / ".runtime/ytdata-screens"
    folder.mkdir(parents=True, exist_ok=True)
    initial_size = page.viewport_size
    now = utc_now()
    stamp = now.isoformat()
    mode = {"configured": False, "linked": False, "failed": False, "hidden": False,
            "upload_missing": False, "category": "22"}
    upload_scope = "https://www.googleapis.com/auth/youtube.upload"
    read_scopes = ["https://www.googleapis.com/auth/youtube.readonly",
                   "https://www.googleapis.com/auth/yt-analytics.readonly"]
    categories = [dict(id="22", name="人物與網誌"), dict(id="27", name="教育"), dict(id="28", name="科學與技術")]
    saved = []

    for cookie in page.context.cookies(origin):
        page.context.add_cookies([{
            "name": cookie["name"], "value": cookie["value"], "domain": "office.example.test",
            "path": "/", "secure": True, "httpOnly": True,
        }])

    def internal_route(route):
        parts = urlsplit(route.request.url)
        url = origin + parts.path + ("?" + parts.query if parts.query else "")
        response = route.fetch(url=url, headers={
            **route.request.headers, "host": urlsplit(origin).netloc,
        })
        route.fulfill(response=response)

    page.route(internal + "/**", internal_route)

    def credentials(route):
        route.fulfill(json={"webhook_public_url": "", "items": [
            dict(name=name, configured=mode["configured"],
                 source="DB" if mode["configured"] else "未設定",
                 mask="••••" if mode["configured"] else None, version=1, error=None)
            for name in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET")
        ]})

    def status(route):
        neutral = dict(linked=False, name="", ig_username="", expires_at=None,
                       granted=[], missing=[], state="neutral", verified=True)
        yt = {**neutral, "configured": mode["configured"], "linked": mode["linked"],
              "name": "[隔離驗收] YouTube 頻道" if mode["linked"] else "",
              "state": "failed" if mode["failed"] else "ready" if mode["linked"] else "neutral",
              "verified": not mode["failed"]}
        if mode["upload_missing"]:
            # 既有連結只缺上傳範圍：狀態仍為已連結，缺口放在 data_missing。
            yt.update(granted=read_scopes, data_missing=[upload_scope],
                      category_id=mode["category"], categories=categories)
        route.fulfill(json=dict(backoffice_origin=internal,
                                callbacks={"youtube": internal + "/api/oauth/youtube/callback"},
                                platforms={"youtube": yt, "meta": neutral, "threads": neutral},
                                pages=[]))

    def category(route):
        body = route.request.post_data_json
        saved.append(body)
        mode["category"] = body["category_id"]
        route.fulfill(json=body)

    page.route("**/api/credentials", credentials)
    page.route("**/api/oauth/youtube/category", category)
    page.route("**/api/oauth/status*", status)

    def stable():
        page.wait_for_load_state("networkidle")
        page.evaluate("async () => { await document.fonts.ready; await new Promise(r => "
                      "requestAnimationFrame(() => requestAnimationFrame(r))); }")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

    def widths():
        for width, height in ((1440, 900), (768, 1024), (390, 844)):
            page.set_viewport_size({"width": width, "height": height})
            stable()
        page.set_viewport_size(initial_size)
        stable()

    def capture(name, locator):
        locator.scroll_into_view_if_needed()
        stable()
        page.screenshot(path=str(folder / f'{name}-{initial_size["width"]}x{initial_size["height"]}.png'))

    card = page.locator(".connection-card:has(#connection-youtube)")
    for configured, linked, failed, state in (
        (False, False, False, "neutral"), (True, False, False, "neutral"),
        (True, True, False, "ready"), (True, True, True, "failed"),
    ):
        mode.update(configured=configured, linked=linked, failed=failed)
        page.goto(internal + "/?view=settings&settings_tab=connections")
        expect(card.locator(".oauth-account .status-badge")).to_have_class("status-badge " + state)
        # 教學改為站內視窗：卡片上有「設定教學」按鈕，不再有外開連結。
        expect(card.get_by_role("button", name="設定教學", exact=True)).to_have_class("secondary")
        expect(card.get_by_role("link", name="如何建立 Google Cloud OAuth 用戶端")).to_have_count(0)
        expect(card.locator("a[target=_blank]")).to_have_count(0)
        expect(card.locator("form.credential-field")).to_have_count(2)
        button = card.get_by_role("button", name="重新連結" if linked else "連結 YouTube 帳號", exact=True)
        if configured:
            expect(button).to_be_enabled()
        else:
            expect(button).to_be_disabled()
        if failed:
            expect(card.locator(".oauth-account")).to_contain_text("權杖失效")
        if linked:
            disconnect = card.get_by_role("button", name="中斷連結")
            expect(disconnect).to_have_class("secondary")
            # YouTube 政策：刪除方式要說清楚只刪工作檯資料、不影響 YouTube；取消不送出請求。
            disconnect.click()
            dialog = page.get_by_role("dialog")
            expect(dialog).to_contain_text("刪除已同步的 YouTube 影片資料")
            expect(dialog).to_contain_text("YouTube 上的影片不受影響")
            expect(dialog.get_by_role("button", name="中斷並刪除資料")).to_have_class("primary danger")
            dialog.get_by_role("button", name="取消").click()
            expect(page.get_by_role("dialog")).to_have_count(0)
            expect(disconnect).to_be_focused()
        widths()
        card.get_by_role("button", name="設定教學", exact=True).click()
        callback = page.get_by_role("dialog").locator(".guide-copy code").last
        expect(callback).to_have_text(internal + "/api/oauth/youtube/callback")
        assert callback.evaluate("e => e.getBoundingClientRect().height < 100")
        page.keyboard.press("Escape")
        expect(page.get_by_role("dialog")).to_have_count(0)
        checks.append("youtube-connection-" + state + str(configured) + "-all-widths")
    mode["failed"] = False
    page.reload()
    expect(card.locator(".status-badge.ready").first).to_be_visible()
    capture("connections-youtube", card)
    # 既有連結缺少上傳權限：卡片提示重新連結（比照 Threads 的 data_missing），讀取狀態維持已連結。
    mode.update(configured=True, linked=True, failed=False, upload_missing=True)
    page.goto(internal + "/?view=settings&settings_tab=connections")
    expect(card.locator(".oauth-account .status-badge")).to_have_class("status-badge ready")
    expect(card.locator(".oauth-permissions")).to_have_text("需要重新連結以取得上傳權限")
    expect(card.locator(".notice.danger")).to_have_count(0)
    expect(card.get_by_role("button", name="重新連結", exact=True)).to_have_class("secondary")
    # 已連結時重新連結是次要動作；卡片內沒有實心提交按鈕（只剩危險色的移除）。
    expect(card.locator(".primary:not(.danger)")).to_have_count(0)
    select = card.get_by_label("YouTube 上傳類別", exact=True)
    expect(select).to_have_value("22")
    expect(select.locator("option")).to_have_text(["人物與網誌", "教育", "科學與技術"])
    widths()
    assert select.evaluate("e => e.getBoundingClientRect().width <= e.parentElement.getBoundingClientRect().width + 1")
    select.select_option("27")
    expect(card.locator(".success-note")).to_have_text("已儲存上傳類別")
    assert saved == [{"category_id": "27"}], saved
    expect(select).to_have_value("27")
    shots = REPO / ".runtime/ytpublish-screens"
    shots.mkdir(parents=True, exist_ok=True)
    card.scroll_into_view_if_needed()
    stable()
    page.screenshot(path=str(shots / f'connections-youtube-upload-missing-{initial_size["width"]}x{initial_size["height"]}.png'))
    checks.append("youtube-connection-upload-scope-missing-category-all-widths")
    mode.update(upload_missing=False)
    page.reload()
    expect(card.locator(".oauth-permissions")).to_have_count(0)
    expect(card.get_by_label("YouTube 上傳類別", exact=True)).to_have_count(0)
    post = dict(id=501, account_id=501, external_id="isolated_video", caption="[隔離驗收] Shorts：從觀眾提問找內容方向",
                permalink=None, media_type="SHORTS", published_at=(now - timedelta(days=3)).isoformat(),
                schedule_tier="daily")
    sync = dict(state="idle", manual_requested=False, last_completed_at=None,
                last_auto_completed_at=None, auto_sync_enabled=False, next_poll_at=stamp,
                last_error=None, retry_at=None, progress={})
    message = dict(id=601, thread_id=601, external_id="isolated_comment", comment_parent_known=True,
                   comment_parent_id=None, comment_root_id="isolated_comment", direction="in",
                   author_type="fan", contact_name="觀眾A", text="[隔離驗收] [REDACTED_PHONE] [REDACTED_EMAIL]",
                   has_text=True, sent_at=stamp, received_at=stamp, edited_at=None,
                   attachments_json=[], sources_json=["poll"], version=1)
    actions = []

    def posts(route):
        parts = urlsplit(route.request.url)
        path = parts.path
        if path.endswith("/followers"):
            data = dict(platform="youtube", connected=True, years=[now.year], weeks=[],
                        is_current_month=True, is_current_week=True,
                        current_count=None if mode["hidden"] else 1234,
                        week_delta=None if mode["hidden"] else 5,
                        month_delta=None if mode["hidden"] else 12, subscriber_hidden=mode["hidden"])
        elif path.endswith("/platforms"):
            data = {"default_platform": "youtube"}
        elif path.endswith("/metrics"):
            data = [dict(id=1, captured_at=stamp, views=1000, likes=20, comments=3, shares=5,
                         reach=None, saves=None, avg_watch_time="30.0000",
                         extra_json={"watch_hours": 2.5, "subscribers_gained": 3,
                                     "avg_view_percentage": 48.25})]
        elif path.endswith("/comment-threads"):
            data = dict(items=[message], total=1, range_total=1, root_total=1,
                        root_ids=[601], next_offset=None)
        elif path.endswith("/comments/sync"):
            if route.request.method == "POST":
                actions.append(parse_qs(parts.query))
                sync.update(state="pending", manual_requested=True)
            data = sync
        elif path == "/api/posts/501":
            data = post
        else:
            data = [post]
        route.fulfill(json=data)

    page.route("**/api/posts**", posts)
    page.route("**/api/accounts**", lambda route: route.fulfill(json=[
        dict(id=501, brand_id=1, platform="youtube", name="[隔離驗收] YouTube 頻道")
    ]))
    page.goto(internal + "/?view=posts&post_platform=youtube")
    expect(page.locator(".post-items .post-card")).to_have_count(1)
    expect(page.locator(".follower-panel dt")).to_have_text(["訂閱數", "本週", "本月"])
    expect(page.locator(".follower-panel dd")).to_have_text(["1,234", "+5", "+12"])
    widths()
    capture("posts-youtube-list", page.locator(".post-items"))
    page.locator(".post-items .post-card").click()
    # 互動五項在上，觀看表現（平均觀看時長、平均觀看百分比、總時數）另成一區。
    expect(page.locator(".post-metrics > .metric-grid > div")).to_have_count(5)
    expect(page.locator(".post-metrics > .metric-grid strong")).to_have_text(["1,000", "20", "3", "5", "3"])
    expect(page.locator(".watch-grid strong")).to_have_text(["30", "48.3", "2.5"])
    expect(page.locator(".metric-delay")).to_have_count(5)
    expect(page.locator(".post-comment .comment-text")).to_contain_text("[REDACTED_PHONE]")
    expect(page.get_by_role("button", name="抓取留言", exact=True)).to_be_enabled()
    expect(page.locator(".post-intro .eyebrow")).to_contain_text("Shorts")
    widths()
    capture("posts-youtube-metrics", page.locator(".post-metrics"))
    page.get_by_role("button", name="抓取留言", exact=True).click()
    expect(page.get_by_role("button", name="停止", exact=True)).to_be_visible()
    assert actions and actions[0]["period"] == ["30"], actions
    mode["hidden"] = True
    page.reload()
    expect(page.locator(".follower-panel dd").first).to_have_text("—")
    page.get_by_role("button", name="訂閱數說明").click()
    expect(page.locator(".follower-hint [role=tooltip]")).to_have_text("頻道隱藏訂閱數，無法取得統計")
    widths()
    checks.append("youtube-posts-shorts-five-plus-three-watch-metrics-delay-comments-sync-hidden-subscribers-all-widths")


if __name__ == "__main__":
    main(exercise=exercise)

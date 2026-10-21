"""P1-2 screenshot and edge-state checks using the isolated workspace harness."""

from runtime_tmp import output_dir

import os

from check_workspace import main
from ui_navigation import one_brand, two_brands


def check_trends(page):
    from datetime import date, timedelta
    from urllib.parse import parse_qs, urlparse

    from playwright.sync_api import expect

    # uiorder：需要「全部可見品牌」選單，瀏覽器端替身多加第二個品牌，結束時還原。
    added = two_brands(page)
    page.reload()
    original_size = page.viewport_size
    output = output_dir() / "trend"
    output.mkdir(parents=True, exist_ok=True)
    state = {"empty": False, "failed": False}
    requests = []

    def respond(route):
        query = parse_qs(urlparse(route.request.url).query)
        days = int(query["days"][0])
        requests.append(query)
        if state["failed"]:
            route.fulfill(status=500, json={"detail": "每日趨勢隔離讀取錯誤"})
            return
        rows = [{
            "date": (date(2026, 10, 4) - timedelta(days=days - i - 1)).isoformat(),
            "new_messages": 0 if state["empty"] else (i * 7 + 3) % 24,
        } for i in range(days)]
        route.fulfill(json={"days": days, "timezone": "Asia/Taipei", "series": rows})

    page.route("**/api/dashboard/trends?*", respond)
    page.get_by_role("button", name="重新整理 ↻", exact=True).click()
    card = page.get_by_role("region", name="每日趨勢", exact=True)
    expect(card.locator(".trend-day")).to_have_count(30)
    expect(card.get_by_role("radio", name="30 天", exact=True)).to_have_attribute("aria-checked", "true")
    expect(card.locator(".trend-point")).to_have_count(0)
    expect(card.locator(".trend-line")).to_have_count(0)
    expect(card.locator(".trend-bar")).to_have_count(30)
    expect(card.locator("svg text").filter(has_text="小時")).to_have_count(0)
    for width, height in [(1440, 900), (390, 844)]:
        page.set_viewport_size({"width": width, "height": height})
        check_dashboard_layout(page)
        card.scroll_into_view_if_needed()
        page.evaluate("document.fonts.ready")
        assert "NaN" not in card.inner_html() and "Infinity" not in card.inner_html()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert card.evaluate("e => e.scrollWidth <= e.clientWidth")
        sizes = card.locator("svg text").evaluate_all("es => es.map(e => parseFloat(getComputedStyle(e).fontSize) * e.ownerSVGElement.getBoundingClientRect().width / 620)")
        assert min(sizes) >= 11.9
        page.screenshot(path=str(output / f"dashboard-30-{width}x{height}.png"))
    page.set_viewport_size({"width": 1440, "height": 900})
    card.scroll_into_view_if_needed()
    days = card.locator(".trend-day")
    days.nth(0).focus()
    days.nth(0).press("ArrowRight")
    expect(days.nth(1)).to_be_focused()
    expect(card.get_by_role("tooltip")).to_contain_text("2026-09-06")
    assert days.nth(1).evaluate("e => getComputedStyle(e).stroke !== 'none'")
    assert card.locator('.trend-day[tabindex="0"]').count() == 1
    days.nth(1).press("ArrowLeft")
    expect(days.nth(0)).to_be_focused()
    days.nth(0).press("End")
    expect(days.nth(29)).to_be_focused()
    days.nth(29).press("Home")
    expect(days.nth(0)).to_be_focused()
    days.nth(2).hover()
    expect(card.get_by_role("tooltip")).to_contain_text("新留言 17")
    page.screenshot(path=str(output / "dashboard-hover-1440x900.png"))
    card.get_by_role("radio", name="7 天", exact=True).click()
    expect(card.locator(".trend-day")).to_have_count(7)
    assert "trend_days=7" in page.url
    expect(card.locator("svg text").filter(has_text="分鐘")).to_have_count(0)
    page.reload()
    expect(page.locator(".dashboard-kpis .kpi")).to_have_count(2)
    expect(card.locator(".trend-day")).to_have_count(7)
    expect(card.get_by_role("radio", name="7 天", exact=True)).to_have_attribute("aria-checked", "true")
    card.scroll_into_view_if_needed()
    page.screenshot(path=str(output / "dashboard-7-1440x900.png"))
    with page.expect_request("**/api/dashboard/trends?*"):
        page.get_by_role("combobox", name="目前品牌", exact=True).select_option("1")
    expect(card.locator(".trend-day")).to_have_count(7)
    assert requests[-1]["brand_id"] == ["1"]
    state["failed"] = True
    page.get_by_role("button", name="重新整理 ↻", exact=True).click()
    expect(card.get_by_role("alert")).to_have_text("每日趨勢隔離讀取錯誤")
    expect(page.locator(".dashboard-kpis .kpi")).to_have_count(2)
    expect(page.locator(".intent-bars")).to_be_visible()
    state.update(empty=True, failed=False)
    card.get_by_role("radio", name="30 天", exact=True).click()
    expect(card).to_contain_text("累積留言後會顯示每日趨勢")
    expect(card.locator("svg")).to_have_count(0)
    card.scroll_into_view_if_needed()
    page.screenshot(path=str(output / "dashboard-empty-1440x900.png"))
    page.reload()
    expect(card).to_contain_text("累積留言後會顯示每日趨勢")
    expect(card.get_by_role("radio", name="30 天", exact=True)).to_have_attribute("aria-checked", "true")
    assert "trend_days=30" in page.url
    with page.expect_response("**/api/dashboard/trends?*") as final_response:
        page.get_by_role("combobox", name="目前品牌", exact=True).select_option("")
    assert final_response.value.status == 200
    # Finish the last brand refresh before removing its route substitute.
    page.wait_for_load_state("networkidle")
    page.unroute("**/api/dashboard/trends?*")
    if added:
        one_brand(page)
        page.reload()
    page.set_viewport_size(original_size)


# 1×1 透明 PNG：縮圖路由的替身圖片，不連任何平台或 CDN。
PIXEL = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d4944415478da63f8cfc0f01f0005000201a5f6b1b4"
    "0000000049454e44ae426082"
)


def check_growth_funnel(page):
    import re

    from playwright.sync_api import expect

    output = output_dir() / "growth"
    output.mkdir(parents=True, exist_ok=True)
    state = {"empty": False, "failed": False}
    requests = []

    def funnel(route):
        query = re.search(r"days=(\d+)", route.request.url)
        requests.append(route.request.url)
        if state["failed"]:
            route.fulfill(status=500, json={"detail": "轉換漏斗隔離讀取錯誤"})
            return
        days = int(query.group(1)) if query else 30
        values = [0, 0, 0, 0] if state["empty"] else [12400, 1380, 96, 27]
        route.fulfill(json={"days": days, "timezone": "Asia/Taipei", "posts": 0 if state["empty"] else 6,
                            "stages": [{"key": k, "value": v} for k, v in zip(["reach", "engagement", "comments", "inquiries"], values)]})

    summary_url = re.compile(r"/api/dashboard(?:\?.*)?$")
    ranked = {"id": 1, "caption": "[隔離驗收] 縮圖貼文", "platform": "facebook", "reach": 820,
              "captured_at": "2026-10-03T00:00:00Z", "thumbnail_url": "/api/posts/1/thumbnail?v=isolated"}
    page.route(summary_url, lambda route: route.fulfill(json={
        "week_start": "2026-09-28T00:00:00Z", "as_of": "2026-10-03T00:00:00Z",
        "new_messages": 9, "new_comments": 9, "previous": {"start": "2026-09-21T00:00:00Z", "end": "2026-09-26T00:00:00Z", "new_comments": 6},
        "top_intent": {"intent": "price", "count": 4}, "intents": [{"intent": "price", "count": 4}],
        "highest_reach": [ranked], "lowest_reach": [{**ranked, "id": 2, "thumbnail_url": None, "caption": "[隔離驗收] 無縮圖"}],
    }))
    page.route("**/api/dashboard/funnel?*", funnel)
    page.route("**/api/posts/*/thumbnail*", lambda route: route.fulfill(body=PIXEL, content_type="image/png"))
    page.get_by_role("button", name="重新整理 ↻", exact=True).click()
    expect(page.locator(".kpi-compare")).to_have_text("比上週同期增加 50% · 上週同期 6 則")
    card = page.get_by_role("region", name="轉換漏斗", exact=True)
    expect(card.locator(".funnel-stage")).to_have_count(4)
    expect(card.locator(".funnel-row > span")).to_have_text(["觸及人數", "互動次數", "留言", "消費詢問"])
    expect(card.locator(".funnel-row > strong")).to_have_text(["12,400", "1,380", "96", "27"])
    expect(card.locator(".funnel-rate")).to_have_text(["上一階的 11%", "上一階的 7%", "上一階的 28%"])
    widths = card.locator(".funnel-track > span").evaluate_all("es => es.map(e => e.getBoundingClientRect().width / e.parentElement.getBoundingClientRect().width)")
    assert abs(widths[0] - 1) < 0.01 and all(widths[i] >= widths[i + 1] for i in range(3)) and widths[3] >= 0.019
    expect(page.locator(".rank-thumb")).to_have_count(1)
    assert page.locator(".rank-thumb").evaluate("e => e.complete && e.naturalWidth === 1")
    for width, height in [(1440, 900), (390, 844)]:
        page.set_viewport_size({"width": width, "height": height})
        card.scroll_into_view_if_needed()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert page.locator(".dashboard-page").evaluate("e => e.scrollWidth <= e.clientWidth")
        assert card.evaluate("e => e.scrollWidth <= e.clientWidth")
        assert "NaN" not in card.inner_html() and "Infinity" not in card.inner_html()
        page.screenshot(path=str(output / f"funnel-{width}x{height}.png"))
    page.set_viewport_size({"width": 1440, "height": 900})
    card.get_by_role("radio", name="7 天", exact=True).click()
    expect(card.get_by_role("radio", name="7 天", exact=True)).to_have_attribute("aria-checked", "true")
    assert "funnel_days=7" in page.url and "days=7" in requests[-1]
    state["failed"] = True
    page.get_by_role("button", name="重新整理 ↻", exact=True).click()
    expect(card.get_by_role("alert")).to_have_text("轉換漏斗隔離讀取錯誤")
    expect(page.locator(".dashboard-kpis .kpi")).to_have_count(2)
    state.update(failed=False, empty=True)
    card.get_by_role("radio", name="30 天", exact=True).click()
    expect(card).to_contain_text("近 30 天沒有提供觸及數據的貼文")
    expect(card.locator(".funnel-stage")).to_have_count(0)
    page.unroute(summary_url)
    page.unroute("**/api/dashboard/funnel?*")

    def posts(route):
        response = route.fetch()
        rows = response.json()
        if rows:
            rows[0] = {**rows[0], "thumbnail_url": f"/api/posts/{rows[0]['id']}/thumbnail?v=isolated"}
        route.fulfill(response=response, json=rows)

    page.route(re.compile(r"/api/posts\?"), posts)
    page.get_by_role("button", name="貼文數據", exact=True).click()
    first = page.locator(".post-card").first
    expect(first.locator(".post-thumb")).to_have_count(1)
    assert page.locator(".post-card.has-thumb").count() == 1
    first.click()
    expect(page.locator(".post-detail-thumb")).to_be_visible()
    for width, height in [(1440, 900), (390, 844)]:
        page.set_viewport_size({"width": width, "height": height})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(output / f"post-thumb-{width}x{height}.png"))
    page.set_viewport_size({"width": 1440, "height": 900})
    page.unroute(re.compile(r"/api/posts\?"))
    page.unroute("**/api/posts/*/thumbnail*")
    page.get_by_role("button", name="儀表板", exact=True).click()


def check_audience(page):
    from playwright.sync_api import expect

    output = output_dir() / "audience"
    output.mkdir(parents=True, exist_ok=True)
    stamp = "2026-10-04T02:00:00Z"

    def row(metric, breakdown, items, period="this_month", unit="count", status="ready", error=None):
        return {"metric": metric, "breakdown": breakdown, "status": status, "error": error,
                "period": period, "unit": unit, "items": items, "fetched_at": stamp}

    hours = [{"key": str(h), "value": 10 + (h * 7) % 30} for h in range(24)]
    body = {"timezone": "Asia/Taipei", "accounts": [
        {"id": 1, "brand_id": 1, "platform": "instagram", "name": "[測試] IG", "status": "connected", "insights": [
            row("followers", "age", [{"key": "18-24", "value": 120}, {"key": "25-34", "value": 300}, {"key": "65+", "value": 4}]),
            row("followers", "gender", [{"key": "F", "value": 330}, {"key": "M", "value": 90}, {"key": "U", "value": 4}]),
            row("followers", "country", [{"key": "TW", "value": 400}, {"key": "HK", "value": 24}]),
            row("followers", "city", [], status="unavailable", error="not_available"),
            row("online", "hour", hours, period="last_7_days"),
        ]},
        {"id": 2, "brand_id": 1, "platform": "facebook", "name": "[測試] FB", "status": "connected", "insights": [
            row("followers", "country", [{"key": "TW", "value": 90}], period="day"),
        ]},
        {"id": 3, "brand_id": 1, "platform": "youtube", "name": "[測試] YT", "status": "connected", "insights": [
            row("viewers", "age", [{"key": "18-24", "value": 30.0}, {"key": "65-", "value": 2.5}], "last_28_days", "percent"),
            row("viewers", "gender", [], "last_28_days", "percent", "unavailable", "permission_missing"),
        ]},
    ]}
    page.route("**/api/dashboard/audience*", lambda route: route.fulfill(json=body))
    page.get_by_role("button", name="重新整理 ↻", exact=True).click()
    card = page.get_by_role("region", name="受眾分析", exact=True)
    expect(card.get_by_role("radio")).to_have_count(6)
    expect(card.get_by_role("radio", name="Instagram", exact=True)).to_have_attribute("aria-checked", "true")
    expect(card.locator(".audience-section")).to_have_count(5)
    expect(card).to_contain_text("70.8%")
    expect(card).to_contain_text("女性")
    expect(card).to_contain_text("65+")
    expect(card).to_contain_text("帳號未達門檻")
    expect(card.locator(".audience-hours > span")).to_have_count(24)
    expect(card.locator(".audience-peak")).to_contain_text("台北時間")
    for width, height in [(1440, 900), (390, 844)]:
        page.set_viewport_size({"width": width, "height": height})
        card.scroll_into_view_if_needed()
        assert "NaN" not in card.inner_html() and "Infinity" not in card.inner_html()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert card.evaluate("e => e.scrollWidth <= e.clientWidth")
        page.screenshot(path=str(output / f"audience-instagram-{width}x{height}.png"))
    page.set_viewport_size({"width": 1440, "height": 900})
    card.get_by_role("radio", name="Facebook", exact=True).click()
    assert "audience_platform=facebook" in page.url
    expect(card.locator(".audience-section")).to_have_count(2)
    expect(card).to_contain_text("2024 年 3 月")
    expect(card).to_contain_text("尚未取得")
    card.get_by_role("radio", name="YouTube", exact=True).click()
    expect(card).to_contain_text("重新連結這個帳號")
    card.get_by_role("radio", name="Threads", exact=True).click()
    expect(card).to_contain_text("還沒有連結 Threads 帳號")
    for name, text in (("TikTok", "Business API"), ("LINE", "只用來發送通知")):
        card.get_by_role("radio", name=name, exact=True).click()
        expect(card.locator(".audience-section")).to_have_count(0)
        expect(card.locator(".audience-hint")).to_contain_text(text)
        card.scroll_into_view_if_needed()
        page.screenshot(path=str(output / f"audience-{name.lower()}-1440x900.png"))
    page.route("**/api/dashboard/audience*", lambda route: route.fulfill(status=500, json={"detail": "受眾分析隔離讀取錯誤"}))
    page.get_by_role("button", name="重新整理 ↻", exact=True).click()
    expect(card.get_by_role("alert")).to_have_text("受眾分析隔離讀取錯誤")
    page.unroute("**/api/dashboard/audience*")
    page.route("**/api/dashboard/audience*", lambda route: route.fulfill(json=body))
    card.get_by_role("radio", name="Instagram", exact=True).click()
    page.get_by_role("button", name="重新整理 ↻", exact=True).click()
    expect(card.locator(".audience-section")).to_have_count(5)
    page.unroute("**/api/dashboard/audience*")


def check_dashboard_layout(page):
    cards = page.locator(".dashboard-kpis .kpi")
    # 儀表板資料是非同步載入，先等兩張 KPI 出現再量測，避免偶發失敗。
    from playwright.sync_api import expect

    expect(cards).to_have_count(2)
    result = cards.evaluate_all("""es => es.map(e => {
        const s = getComputedStyle(e), r = e.getBoundingClientRect();
        return { background: s.backgroundColor, width: r.width, x: r.x, y: r.y,
                 surface: s.getPropertyValue('--bg-surface').trim(),
                 overflow: e.scrollWidth > e.clientWidth };
    })""")
    assert len(result) == 2 and not any(row["overflow"] for row in result)
    assert len({row["background"] for row in result}) == 1
    assert max(row["width"] for row in result) - min(row["width"] for row in result) <= 1
    if page.viewport_size["width"] < 600:
        assert len({row["x"] for row in result}) == 1
        assert result[0]["y"] < result[1]["y"]
    else:
        assert len({row["y"] for row in result}) == 1
    assert page.locator(".dashboard-page").evaluate("e => e.scrollWidth <= e.clientWidth")
    trend = page.locator(".dashboard-trend")
    expect(trend).to_be_visible()
    expect(trend).not_to_contain_text("正在讀取每日趨勢")
    assert trend.locator(".trend-days button").evaluate_all("es => es.every(e => parseFloat(getComputedStyle(e).borderRadius) === parseFloat(getComputedStyle(e).getPropertyValue('--ui-radius-control')) - 3 && getComputedStyle(e.closest('.segmented-control')).borderRadius === getComputedStyle(e).getPropertyValue('--ui-radius-control').trim())")
    assert trend.evaluate("e => e.scrollWidth <= e.clientWidth")
    assert "NaN" not in trend.inner_html() and "Infinity" not in trend.inner_html()
    if trend.locator("svg").count():
        assert trend.locator("svg").evaluate("e => { const r = e.getBoundingClientRect(), p = e.closest('.dashboard-trend').getBoundingClientRect(); return r.left >= p.left && r.right <= p.right; }")


def exercise(page, settings, folder, checks):
    from playwright.sync_api import expect

    baseline = os.environ.get("UI_P1_2_BASELINE") == "1"
    output = output_dir()
    output.mkdir(parents=True, exist_ok=True)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.set_viewport_size({"width": 1440, "height": 900})
    two_brands(page)
    page.reload()
    page.get_by_role("button", name="儀表板", exact=True).click()
    expect(page.locator(".dashboard-kpis")).to_be_visible()
    if not baseline:
        check_trends(page)
        check_growth_funnel(page)
        check_audience(page)
    for width, height in [(1440, 900), (390, 844)]:
        page.set_viewport_size({"width": width, "height": height})
        if not baseline:
            check_dashboard_layout(page)
        page.screenshot(path=str(output / f"dashboard-data-{width}x{height}.png"))
        assert page.locator(".dashboard-page").evaluate("e => e.scrollWidth <= e.clientWidth")
    page.set_viewport_size({"width": 1440, "height": 900})
    if not baseline:
        trigger = page.get_by_role("button", name="匯出報表", exact=True)
        trigger.focus()
        page.keyboard.press("Enter")
        dialog = page.get_by_role("dialog", name="匯出報表", exact=True)
        expect(dialog).to_be_visible()
        expect(dialog.get_by_role("button", name="下載 Word 報表 ↓", exact=True)).to_be_disabled()
        start, end = dialog.get_by_label("開始日期"), dialog.get_by_label("結束日期")
        today = page.evaluate("new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())")
        expect(start).to_have_value(today[:7] + "-01")
        expect(end).to_have_value(today)
        assert start.get_attribute("max") == end.input_value()
        assert end.get_attribute("min") == start.input_value()
        assert start.get_attribute("required") is not None and end.get_attribute("required") is not None
        dialog.get_by_role("button", name="關閉", exact=True).focus()
        page.keyboard.press("Shift+Tab")
        expect(end).to_be_focused()
        page.keyboard.press("Tab")
        expect(dialog.get_by_role("button", name="關閉", exact=True)).to_be_focused()
    page.screenshot(path=str(output / "export-dialog-1440x900.png"))
    if not baseline:
        page.keyboard.press("Escape")
        expect(trigger).to_be_focused()
        trigger.press("Space")
        page.mouse.click(5, 5)
        expect(dialog).not_to_be_visible()
        expect(trigger).to_be_focused()
        colors = page.locator(".kpi").evaluate_all("es => es.map(e => getComputedStyle(e).backgroundColor)")
        surface = page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--bg-surface').trim()")
        assert len(colors) == 2 and len(set(colors)) == 1
        assert colors[0] == page.evaluate("color => { const e = document.createElement('div'); e.style.backgroundColor = color; document.body.append(e); const result = getComputedStyle(e).backgroundColor; e.remove(); return result; }", surface)
        sizes = page.locator(".kpi > strong").evaluate_all("es => es.map(e => parseFloat(getComputedStyle(e).fontSize))")
        assert sizes[1] <= sizes[0]
        page.get_by_role("combobox", name="目前品牌", exact=True).select_option("1")
        trigger.click()
        pending = []
        page.route("**/api/exports/report/docx", lambda route: pending.append(route))
        with page.expect_request("**/api/exports/report/docx"):
            dialog.get_by_role("button", name="下載 Word 報表 ↓", exact=True).click()
        expect(dialog.get_by_role("button", name="正在匯出…", exact=True)).to_be_disabled()
        assert len(pending) == 1
        pending[0].fulfill(status=500, json={"detail": "隔離匯出錯誤"})
        expect(dialog.get_by_role("alert")).to_have_text("隔離匯出錯誤")
        expect(dialog.get_by_role("button", name="下載 Word 報表 ↓", exact=True)).to_be_enabled()
        page.unroute("**/api/exports/report/docx")
        page.set_viewport_size({"width": 390, "height": 844})
        assert dialog.evaluate("e => e.scrollWidth <= e.clientWidth && e.getBoundingClientRect().right <= innerWidth")
        dialog.get_by_role("button", name="關閉", exact=True).click()
        expect(trigger).to_be_focused()
        page.set_viewport_size({"width": 1440, "height": 900})
        expect(page.locator('.mobile-logout')).to_have_count(0)
        page.get_by_role("combobox", name="目前品牌", exact=True).select_option("")
    # 精確攔截摘要，避免把摘要形狀誤送到新的每日序列 API。
    import re
    summary_url = re.compile(r"/api/dashboard(?:\?.*)?$")
    page.route(summary_url, lambda route: route.fulfill(json={
        "week_start": "2026-09-28T00:00:00Z", "as_of": "2026-10-03T00:00:00Z",
        "new_messages": 0, "new_comments": 0, "top_intent": None, "intents": [], "highest_reach": [], "lowest_reach": [],
    }))
    page.get_by_role("button", name="重新整理 ↻", exact=True).click()
    expect(page.locator(".intent-bars")).to_contain_text("本週尚無新留言")
    expect(page.locator('.kpi > span')).to_have_text(['本週新留言', '最多人問的類別'])
    expect(page.locator('.kpi > strong')).to_have_text(['0', '尚無資料'])
    assert not any(word in page.locator('.dashboard-page').inner_text() for word in ('待回覆', '首次回覆'))
    page.screenshot(path=str(output / "dashboard-empty-1440x900.png"))
    page.unroute(summary_url)
    page.route(summary_url, lambda route: route.fulfill(json={
        "week_start": "2026-09-28T00:00:00Z", "as_of": "2026-10-03T00:00:00Z",
        "new_messages": 12, "new_comments": 8, "top_intent": {"intent": "price", "count": 5},
        "intents": [{"intent": "price", "count": 5}], "highest_reach": [], "lowest_reach": [],
    }))
    page.get_by_role("button", name="重新整理 ↻", exact=True).click()
    expect(page.locator('.kpi > strong')).to_have_text(['8', '價格詢問 · 5 則'])
    page.unroute(summary_url)
    page.get_by_role("button", name="貼文數據", exact=True).click()
    page.locator(".post-card").first.click()
    expect(page.locator(".chart-point")).to_have_count(3)
    page.locator(".metric-chart").scroll_into_view_if_needed()
    page.screenshot(path=str(output / "metrics-data-1440x900.png"))
    row = {"id": 100, "captured_at": "2026-10-03T00:00:00Z", "views": None, "reach": 12, "likes": None, "comments": None, "shares": None, "saves": None, "extra_json": {}}
    for name, metrics in [("empty", []), ("null", [{**row, "reach": None}]), ("single", [row]), ("same-time", [row, {**row, "id": 101, "reach": 24}])]:
        def fulfill_metrics(route):
            route.fulfill(json=metrics)

        page.route("**/api/posts/*/metrics", fulfill_metrics)
        page.get_by_role("button", name="儀表板", exact=True).click()
        page.get_by_role("button", name="貼文數據", exact=True).click()
        page.locator(".post-card").first.click()
        expect(page.locator(".chart-point")).to_have_count(0 if name in ("empty", "null") else len(metrics))
        chart = page.locator(".metric-chart")
        assert "NaN" not in chart.inner_html()
        assert "Infinity" not in chart.inner_html()
        if name in ("empty", "null"):
            expect(chart.locator("svg")).to_have_count(0)
        if name == "empty":
            chart.scroll_into_view_if_needed()
            page.screenshot(path=str(output / "metrics-empty-1440x900.png"))
        page.unroute("**/api/posts/*/metrics")
    assert not errors, errors
    checks.append("dashboard-kpi-dialog-chart-edge-states")


if __name__ == "__main__":
    main(exercise)

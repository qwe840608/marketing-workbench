"""Ideation navigation/download acceptance on isolated SQLite; no cloud/platform calls."""

from runtime_tmp import (
    launch_chromium,
    cleanup,
    output_dir,
    runtime_check,
    stop_process,
    temporary_dir,
)

from browser_harness import REPO, launch_server, seed_records
from ports import browser_port
import json
from playwright.sync_api import expect
import os
import secrets
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


# 長內文：驗證清單截斷與「[全文]」展開。
LONG_CAPTION = "[隔離驗收] 長內文開頭說明服務流程與合作細節，" + "這段內文刻意寫得很長，用來確認全文在視窗內捲動。\n" * 40


def check_exports(page, container, kind, identifier, export_root):
    from playwright.sync_api import expect

    cards = container.locator(".export-card")
    expect(cards).to_have_count(2)
    container.scroll_into_view_if_needed()
    for index, (label, extension) in enumerate((("Markdown", "md"), ("Word", "docx"))):
        expect(cards.nth(index)).to_be_visible()
        expect(cards.nth(index)).to_be_in_viewport()
        link = cards.nth(index).get_by_role("link", name="下載 " + label, exact=True)
        expect(link).to_have_attribute(
            "href", f"/api/ideation/{kind}/{identifier}/download/{extension}"
        )
        expect(link).to_have_attribute("download", "")
    text = page.locator("body").inner_text()
    attributes = page.locator("[title], [aria-label]").evaluate_all(
        "els => els.map(e => [e.title, e.getAttribute('aria-label')].join(' ')).join(' ')"
    )
    for content in (text, attributes):
        assert str(export_root) not in content
        assert ':\\' not in content and '/Users/' not in content


def check_report_delete(page, origin, brand_id, report_id, width, checks):
    from playwright.sync_api import expect

    listing = page.request.get(origin + f"/api/ideation/reports?brand_id={brand_id}").json()
    template = page.request.get(origin + f"/api/ideation/reports/{report_id}").json()
    records = {501 + i: {**template, "id": 501 + i, "status": status}
               for i, status in enumerate(["ready", "failed", "pending", "processing", "syncing_comments"])}
    deleted, requests, dialogs = [], [], []
    reject = [False]

    def reports(route):
        path = urlsplit(route.request.url).path
        if path.endswith("/reports"):
            route.fulfill(json={**listing, "reports": list(records.values())})
            return
        identity = int(path.split("/")[4])
        if route.request.method == "DELETE":
            requests.append(identity)
            if reject[0]:
                route.fulfill(status=409, json={"detail": "報告產生中，完成後才能刪除"})
            else:
                del records[identity]
                deleted.append(identity)
                route.fulfill(status=204)
        elif path.endswith("/scripts"):
            route.fulfill(json=[])
        elif identity in records:
            route.fulfill(json=records[identity])
        else:
            route.fulfill(status=404, json={"detail": "找不到報告"})

    page.route("**/api/ideation/reports**", reports)
    page.goto(origin + "/?view=ideation&report_id=501")
    button = page.locator(".report-row").filter(has=page.locator('[aria-current="true"]')).get_by_role("button", name=__import__("re").compile("刪除主題列表"))
    expect(button).to_be_enabled()
    expect(button).to_have_class("primary danger")
    # 與實心主要按鈕同樣式，只換成危險色底、白字。
    assert button.evaluate(
        "e => { const s = getComputedStyle(e), r = getComputedStyle(document.documentElement);"
        " const probe = document.createElement('i'); probe.style.color = r.getPropertyValue('--state-danger');"
        " document.body.append(probe); const red = getComputedStyle(probe).color; probe.remove();"
        " return s.backgroundColor === red && s.fontWeight === '700' && parseFloat(s.paddingLeft) >= 12 && parseFloat(s.height) === 32; }"
    )
    button.scroll_into_view_if_needed()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    heading = page.locator(".report-row").first
    assert heading.locator(".report-select").bounding_box()["x"] < button.bounding_box()["x"]
    assert button.bounding_box()["x"] + button.bounding_box()["width"] <= width

    # 不得使用原生對話框：內嵌瀏覽器會直接略過 confirm()，刪除就永遠不會送出。
    page.on("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
    confirm_box = page.get_by_role("dialog")
    button.click()
    expect(confirm_box).to_have_attribute("aria-modal", "true")
    expect(confirm_box.get_by_role("button", name="取消", exact=True)).to_be_focused()
    page.keyboard.press("Escape")
    expect(confirm_box).to_have_count(0)
    expect(button).to_be_focused()
    button.click()
    page.keyboard.press("Tab")
    expect(confirm_box.get_by_role("button", name="刪除", exact=True)).to_be_focused()
    page.keyboard.press("Shift+Tab")
    expect(confirm_box.get_by_role("button", name="取消", exact=True)).to_be_focused()
    folder = REPO / ".runtime/ideaui-screens/after"
    folder.mkdir(parents=True, exist_ok=True)
    height = page.viewport_size["height"]
    page.screenshot(path=str(folder / f"ideation-modal-{width}x{height}.png"))
    expect(confirm_box).to_contain_text(
        "刪除主題列表 #501？由此產生的腳本也會一併隱藏，已匯出的檔案不受影響。"
    )
    # 刪除維持實心危險色；取消依共用按鈕規則採白底細框。
    expect(confirm_box.get_by_role("button", name="刪除", exact=True)).to_have_class("primary danger")
    expect(confirm_box.get_by_role("button", name="取消", exact=True)).to_have_class("secondary")
    confirm_box.get_by_role("button", name="取消", exact=True).click()
    expect(confirm_box).to_have_count(0)
    expect(button).to_be_focused()
    expect(page.locator(".report-history .report-select")).to_have_count(5)
    assert requests == [] and deleted == []
    for identity in (503, 504, 505):
        page.locator(".report-history .report-select").filter(has_text=f"#{identity} ·").click()
        expect(page.locator(".report-heading h2")).to_contain_text(f"#{identity} ·")
        expect(button).to_be_disabled()
        expect(button).to_have_attribute("title", "報告產生中，完成後才能刪除")
    page.locator(".report-history .report-select").filter(has_text="#501 ·").click()
    expect(button).to_be_enabled()
    reject[0] = True
    button.click()
    confirm_box.get_by_role("button", name="刪除", exact=True).click()
    expect(page.get_by_role("alert")).to_have_text("報告產生中，完成後才能刪除")
    expect(page.locator(".report-history .report-select")).to_have_count(5)
    assert parse_qs(urlsplit(page.url).query)["report_id"] == ["501"]
    reject[0] = False
    button.click()
    confirm_box.get_by_role("button", name="刪除", exact=True).click()
    expect(page.locator(".report-heading h2")).to_contain_text("#502 ·")
    expect(page.locator(".report-history .report-select")).to_have_count(4)
    assert parse_qs(urlsplit(page.url).query)["report_id"] == ["502"]
    assert "script_id" not in parse_qs(urlsplit(page.url).query)
    expect(button).to_be_enabled()  # failed reports can be removed.
    for identity in (503, 504, 505):
        records[identity]["status"] = "ready"
    # The full sweep may freeze the browser clock; reload the changed fixture before measuring.
    page.reload()
    expect(page.locator(".report-select").filter(has_text="已完成並匯出")).to_have_count(3)
    for identity in (502, 503, 504, 505):
        expect(page.locator(".report-heading h2")).to_contain_text(f"#{identity} ·")
        expect(button).to_be_enabled()
        button.click()
        confirm_box.get_by_role("button", name="刪除", exact=True).click()
    expect(page.locator(".report-history .report-select")).to_have_count(0)
    expect(page.get_by_text("尚無報告。設定例會後自動產生，也可立即發想。", exact=True)).to_be_visible()
    expect(button).to_have_count(0)
    assert "report_id" not in parse_qs(urlsplit(page.url).query)
    assert deleted == [501, 502, 503, 504, 505]
    assert dialogs == []
    # Viewer role is supplied only in the browser response; the backend permission is tested separately.
    records[501] = {**template, "id": 501}

    def viewer(route):
        payload = route.fetch().json()
        payload["role"] = "viewer"
        route.fulfill(json=payload)

    page.route("**/api/auth/me", viewer)
    page.goto(origin + "/?view=ideation&report_id=501")
    expect(page.locator(".report-heading h2")).to_contain_text("#501 ·")
    expect(button).to_have_count(0)
    expect(page.locator('.idea-card-tools').get_by_role('button', name='編輯', exact=True)).to_have_count(0)
    page.unroute("**/api/auth/me")
    page.unroute("**/api/ideation/reports**")
    checks.append(f"{width}: delete-confirm-cancel-status-error-selection-url-empty-viewer")


def check_ideaui(page, origin, report_id, width, height):
    from playwright.sync_api import expect

    template = page.request.get(origin + f"/api/ideation/reports/{report_id}").json()
    source = template["data"]["ideas"][0]
    template["data"]["ideas"] = [
        {**source, "goal": goal, "title": f"{goal}：服務前的第 {i + 1} 個問題", "quote_ids": [] if i == 0 else source["quote_ids"]}
        for goal in ("變現型", "流量型", "引流型") for i in range(5)
    ]
    calls, created = [], []
    def posts(route):
        query = parse_qs(urlsplit(route.request.url).query)
        calls.append(query)
        rows = [] if query["start_at"][0] < "2021" else [
            {"id": i, "caption": LONG_CAPTION if i == 12 else "[隔離驗收] 服務流程與觀眾提問", "platform": "facebook",
             "published_at": "2025-02-01T02:00:00Z", "total_comment_count": 99,
             "comment_count": int(query.get("comment_range", ["30"])[0])
             if query.get("comment_range") != ["custom"] else 2}
            for i in (11, 12)
        ]
        route.fulfill(json=rows)
    page.route("**/api/ideation/posts?*", posts)
    page.route(f"**/api/ideation/reports/{report_id}", lambda route: route.fulfill(json=template))
    page.route("**/api/ai/execution-options?*", lambda route: route.fulfill(json={
        "options": [{"provider": "gemini_api", "available": True, "model": "isolated"}],
        "draft_provider": "gemini_api",
    }))
    page.goto(origin + f"/?view=ideation&report_id={report_id}")
    boxes = page.locator('.ideation-post input[type="checkbox"]')
    expect(boxes).to_have_count(2)
    for box in boxes.all():
        expect(box).to_be_checked()
    page.get_by_role("checkbox", name="選取全部貼文", exact=True).uncheck()
    for box in boxes.all():
        expect(box).not_to_be_checked()
    expect(page.get_by_role("button", name="立即發想", exact=True)).to_be_disabled()
    assert page.get_by_role("checkbox", name="選取全部貼文", exact=True).evaluate("e => !e.indeterminate && !e.checked")
    expect(page.locator(".ideation-selection-summary")).to_have_text("將使用 FB 0 篇、IG 0 篇貼文、近 30 天的留言")
    page.get_by_role("checkbox", name="選取全部貼文", exact=True).check()
    expect(boxes.first).to_be_checked()
    boxes.first.uncheck()
    all_box = page.get_by_role("checkbox", name="選取全部貼文", exact=True)
    assert all_box.evaluate("e => e.indeterminate && !e.checked")
    expect(page.locator(".ideation-selection-summary")).to_have_text("將使用 FB 1 篇、IG 0 篇貼文、近 30 天的留言")
    page.locator(".ideation-post-caption").first.click()
    expect(boxes.first).to_be_checked()
    assert all_box.evaluate("e => e.checked && !e.indeterminate")
    page.locator(".ideation-post-caption").first.click()
    expect(boxes.first).not_to_be_checked()
    assert all_box.evaluate("e => e.indeterminate")
    # 超過 30 字的內文只露出前 30 字加「...[全文]」；「[全文]」開視窗，長文在視窗內捲動，不勾選貼文。
    long_row = page.locator(".ideation-post").nth(1)
    expect(long_row.locator(".ideation-caption-text")).to_have_text("".join(list(LONG_CAPTION)[:30]) + "...")
    more = long_row.get_by_role("button", name="[全文]", exact=True)
    expect(boxes.nth(1)).to_be_checked()
    row_height = long_row.evaluate("e => e.getBoundingClientRect().height")
    more.click()
    dialog = page.get_by_role("dialog", name="貼文全文")
    expect(dialog.locator(".ideation-caption-body")).to_have_text(LONG_CAPTION)
    expect(dialog.get_by_role("button", name="關閉", exact=True)).to_be_focused()
    box = dialog.bounding_box()
    viewport = page.viewport_size
    assert box["y"] >= 0 and box["y"] + box["height"] <= viewport["height"], box
    assert box["x"] >= 0 and box["x"] + box["width"] <= viewport["width"], box
    assert long_row.evaluate("e => e.getBoundingClientRect().height") == row_height
    expect(boxes.nth(1)).to_be_checked()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    caption_shots = REPO / ".runtime/ideaui-screens/after"
    caption_shots.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(caption_shots / f"ideation-caption-full-{width}x{height}.png"))
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    expect(more).to_be_focused()
    more.click()
    dialog.get_by_role("button", name="關閉", exact=True).click()
    expect(dialog).to_have_count(0)
    expect(boxes.nth(1)).to_be_checked()
    page.get_by_label("開始時間", exact=True).fill("2025-01-01T00:00")
    expect(page.locator(".ideation-posts")).to_have_attribute("aria-busy", "false")
    expect(page.locator(".ideation-post-meta").first).to_contain_text("2025")
    for box in boxes.all():
        expect(box).to_be_checked()
    expect(page.locator(".ideation-card")).to_have_count(15)
    expect(page.locator(".ideation-goal")).to_have_count(3)
    expect(page.locator(".ideation-step h3")).to_have_text(["1 選擇貼文", "2 留言範圍", "3 產生"])
    expect(page.locator(".ideation-post-actions")).to_contain_text("範圍內留言 60 則")
    for group in page.locator(".ideation-goal").all():
        expect(group.locator(".ideation-card")).to_have_count(5)
    expect(page.locator(".ideation-tags").get_by_text("延伸主題", exact=True)).to_have_count(3)
    assert "私訊" not in page.locator(".ideation-page").inner_text()
    folder = REPO / ".runtime/ideaui-screens/after"
    folder.mkdir(parents=True, exist_ok=True)
    for size, columns in [({"width": width, "height": height}, 3 if width == 1440 else 1),
                          ({"width": 768, "height": 1024}, 2)]:
        page.set_viewport_size(size)
        expect(page.locator(".ideation-grid").first).to_be_visible()
        assert page.locator(".ideation-grid").first.evaluate("e => getComputedStyle(e).gridTemplateColumns.split(' ').length") == columns
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        expect(page.locator(".ideation-posts")).to_have_attribute("aria-busy", "false")
        segmented = page.locator(".segmented-control")
        assert segmented.bounding_box()["width"] <= 560
        assert segmented.evaluate("""e => {
            const s=getComputedStyle(e);
            // uiorder：窄螢幕允許換行；高度 = 上下內距與框線 8px + 每列 40px + 列距 2px。
            const rows = new Set([...e.querySelectorAll('[role=radio]')].map(b => Math.round(b.getBoundingClientRect().top))).size;
            return e.getBoundingClientRect().height === 8 + 40 * rows + 2 * (rows - 1) && (innerWidth > 600 ? rows === 1 : true) && s.padding === '3px' &&
                s.borderRadius === '8px' && [...e.querySelectorAll('[role=radio]')].every(b =>
                b.getBoundingClientRect().height === 40 && getComputedStyle(b).fontSize === '13px');
        }""")
        assert page.locator('.ideation-post-actions').evaluate("""e => {
            const s=getComputedStyle(e);
            return e.getBoundingClientRect().height === 44 && s.fontSize === '13px' &&
                s.padding === (innerWidth < 600 ? '8px 12px' : '0px 16px');
        }""")
        assert page.locator('.ideation-form .primary').evaluate_all("""es => es.every(e =>
            e.getBoundingClientRect().height === 40 && getComputedStyle(e).padding === '0px 16px')""")
        if size["width"] > 600:
            assert segmented.bounding_box()["width"] < page.locator(".ideation-form").bounding_box()["width"] - 48
        for group in page.locator(".ideation-goal").all():
            card_heights = group.locator(".ideation-card").evaluate_all("es => es.map(e => e.getBoundingClientRect().height)")
            assert max(card_heights) - min(card_heights) < 1
            for action in group.get_by_role("button", name="建立發佈草稿", exact=True).all():
                expect(action).to_have_class("secondary")
                assert action.bounding_box()["width"] < group.locator(".ideation-card").first.bounding_box()["width"] - 40
        selected_row = page.locator('.report-row[data-selected=true]')
        assert selected_row.evaluate("e => getComputedStyle(e).backgroundColor === 'rgb(241, 245, 249)' && getComputedStyle(e, '::before').width === '3px'")
        assert selected_row.locator(".report-select").evaluate("e => getComputedStyle(e).backgroundColor === 'rgba(0, 0, 0, 0)' && getComputedStyle(e).fontWeight === '600'")
    page.set_viewport_size({"width": width, "height": height})
    page.evaluate("window.scrollTo(0,0)")
    page.screenshot(path=str(folder / f"ideation-{width}x{height}.png"))
    no90 = REPO / ".runtime/no90-screens/after"
    no90.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(no90 / f"ideation-{width}x{height}.png"))
    window = page.get_by_role("group", name="留言範圍", exact=True)
    expect(window.get_by_role("radio")).to_have_count(5)
    expect(window.get_by_role("radio", name="近 30 天", exact=True)).to_have_attribute("aria-checked", "true")
    control = window.get_by_role("radiogroup", name="留言範圍", exact=True)
    expect(control.get_by_role("radio")).to_have_count(5)
    expect(control.locator('[tabindex="0"]')).to_have_count(1)
    control.get_by_role("radio", name="近 30 天", exact=True).focus()
    # uiorder：留言範圍由短到長排列（7、30、60、90、自訂），ArrowRight 從預設 30 天移到 60 天。
    assert control.get_by_role("radio").all_inner_texts() == ["近 7 天", "近 30 天", "近 60 天", "近 90 天", "自訂日期"]
    page.keyboard.press("ArrowRight")
    expect(control.get_by_role("radio", name="近 60 天", exact=True)).to_be_focused()
    expect(control.get_by_role("radio", name="近 60 天", exact=True)).to_have_attribute("aria-checked", "true")
    expect(page.locator(".ideation-selection-summary")).to_have_text("將使用 FB 2 篇、IG 0 篇貼文、近 60 天的留言")
    # 主要與次要按鈕同一列垂直置中對齊（不得被 .settings-section .primary 的上邊距推低）。
    centers = page.locator(".ideation-step .ideation-actions > button").evaluate_all(
        "els => els.map(e => { const r = e.getBoundingClientRect(); return r.top + r.height / 2; })"
    )
    assert len(centers) == 2 and abs(centers[0] - centers[1]) < 1, centers
    # uiorder：次要「重新標註所選留言」在左，主要「立即發想」在最右。
    action_buttons = page.locator(".ideation-step .ideation-actions > button")
    assert action_buttons.all_inner_texts() == ["重新標註所選留言", "立即發想"], action_buttons.all_inner_texts()
    rights = action_buttons.evaluate_all("els => els.map(e => e.getBoundingClientRect().right)")
    assert rights[0] < rights[1]
    expect(action_buttons.last).to_have_class("primary")
    # uiorder：留言範圍分段按鈕不橫向溢出、不被裁切（含窄螢幕）。
    segmented = page.locator(".ideation-comment-window .segmented-control")
    assert segmented.evaluate("e => e.scrollWidth <= e.clientWidth + 1"), "留言範圍分段按鈕橫向溢出"
    assert segmented.evaluate("e => { const c = e.getBoundingClientRect(); return [...e.querySelectorAll('button')].every(b => { const r = b.getBoundingClientRect(); return r.left >= c.left - 1 && r.right <= c.right + 1; }); }"), "留言範圍分段按鈕被裁切"
    # uiorder：頁首不再放無標籤數字，主題列表標題顯示數量。
    expect(page.locator(".page-header .page-count")).to_have_count(0)
    assert page.locator("h2").filter(has_text="主題列表").first.inner_text().startswith("主題列表（")
    if width > 600:
        page.locator(".ideation-form").screenshot(path=str(folder / f"ideation-steps-{width}x{height}.png"))
    else:
        page.locator(".ideation-comment-window").evaluate("e => e.scrollIntoView({block: 'start'})")
        page.screenshot(path=str(folder / f"ideation-steps-range-{width}x{height}.png"))
        page.locator(".ideation-execution-row").evaluate("e => e.scrollIntoView({block: 'center'})")
        page.screenshot(path=str(folder / f"ideation-steps-actions-{width}x{height}.png"))
    page.keyboard.press("ArrowLeft")
    expect(control.get_by_role("radio", name="近 30 天", exact=True)).to_be_focused()
    page.keyboard.press("Home")
    expect(control.get_by_role("radio", name="近 7 天", exact=True)).to_be_focused()
    page.keyboard.press("ArrowLeft")
    expect(control.get_by_role("radio", name="自訂日期", exact=True)).to_be_focused()
    page.keyboard.press("ArrowRight")
    expect(control.get_by_role("radio", name="近 7 天", exact=True)).to_be_focused()
    control.get_by_role("radio", name="近 30 天", exact=True).click()
    expect(page.locator(".ideation-posts")).to_have_attribute("aria-busy", "false")
    expect(page.locator(".ideation-post-meta").first).to_contain_text("範圍內 30 則留言")
    boxes.first.uncheck()
    for period in ("90", "60", "7", "30"):
        window.get_by_role("radio", name=f"近 {period} 天", exact=True).click()
        expect(page.locator(".ideation-posts")).to_have_attribute("aria-busy", "false")
        expect(page.locator(".ideation-post-meta").first).to_contain_text(f"範圍內 {period} 則留言")
        expect(page.locator(".ideation-post-meta").first).to_have_attribute("title", "已存留言總數：99 則")
        expect(boxes.first).not_to_be_checked()
        assert parse_qs(urlsplit(page.url).query)["comment_range"] == [period]
    screens = REPO / ".runtime/cwindow-screens/after"
    screens.mkdir(parents=True, exist_ok=True)
    boxes.first.check()
    page.evaluate("window.scrollTo(0,0)")
    if width == 390:
        window.scroll_into_view_if_needed()
    page.mouse.move(0, 0)
    page.wait_for_function("""() => getComputedStyle(document.querySelector(
        '.ideation-comment-window [aria-checked=true]')).backgroundColor === 'rgb(15, 58, 46)'""")
    assert abs(window.locator(".segmented-control").bounding_box()["x"]
               - page.locator(".policy-grid").first.bounding_box()["x"]) < 1
    page.screenshot(path=str(screens / f"ideation-30-{width}x{height}.png"))
    window.get_by_role("radio", name="自訂日期", exact=True).click()
    expect(page.get_by_role("button", name="立即發想", exact=True)).to_be_disabled()
    page.get_by_label("留言起日", exact=True).fill("2025-01-01")
    page.get_by_label("留言迄日", exact=True).fill("2025-01-31")
    expect(page.locator(".ideation-posts")).to_have_attribute("aria-busy", "false")
    expect(page.locator(".ideation-post-meta").first).to_contain_text("範圍內 2 則留言")
    assert calls[-1]["comment_from"] == ["2025-01-01"]
    assert calls[-1]["comment_to"] == ["2025-01-31"]
    expect(page.locator(".ideation-selection-summary")).to_have_text("將使用 FB 2 篇、IG 0 篇貼文、2025-01-01 至 2025-01-31的留言")
    page.reload()
    expect(page.get_by_label("留言起日", exact=True)).to_have_value("2025-01-01")
    expect(page.get_by_label("留言迄日", exact=True)).to_have_value("2025-01-31")
    expect(page.locator(".ideation-posts")).to_have_attribute("aria-busy", "false")
    expect(page.locator(".ideation-post-meta").first).to_contain_text("範圍內 2 則留言")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if width == 390:
        window.scroll_into_view_if_needed()
    page.screenshot(path=str(screens / f"ideation-custom-{width}x{height}.png"))
    # Restore the post period after reload before continuing the existing scoped action checks.
    page.get_by_label("開始時間", exact=True).fill("2025-01-01T00:00")
    window.get_by_role("radio", name="近 30 天", exact=True).click()
    expect(page.locator(".ideation-post-meta").first).to_contain_text("範圍內 30 則留言")
    expect(page.locator(".ideation-posts")).to_have_attribute("aria-busy", "false")
    reclassified = []
    def reclassify(route):
        reclassified.append(route.request.post_data_json)
        route.fulfill(json={"status": "queued"})
    page.route("**/api/ideation/reclassify?*", reclassify)
    boxes.first.uncheck()
    button = page.get_by_role("button", name="重新標註所選留言", exact=True)
    expect(button).to_have_class("secondary")
    button.click()
    expect(page.get_by_role("status")).to_contain_text("已排入所選留言範圍與貼文")
    assert reclassified == [{"comment_range": "30", "post_ids": [12], "excluded_message_ids": [], "start_at": "2024-12-31T16:00:00.000Z",
                            "end_at": calls[-1]["end_at"][0]}]
    assert page.get_by_label("開始時間", exact=True).input_value() == "2025-01-01T00:00"
    page.unroute("**/api/ideation/reclassify?*")
    boxes.first.check()
    page.locator(".ideation-goal").first.scroll_into_view_if_needed()
    page.screenshot(path=str(folder / f"ideation-cards-{width}x{height}.png"))
    def create(route):
        if route.request.method == "POST":
            created.append(route.request.post_data_json)
            route.fulfill(status=202, json={**template, "status": "syncing_comments"})
        else:
            route.continue_()
    page.route("**/api/ideation/reports?*", create)
    boxes.first.uncheck()
    page.get_by_role("button", name="立即發想", exact=True).click()
    expect(page.locator(".report-select").first).to_contain_text("抓取留言中")
    assert created[0]["post_ids"] == [12]
    assert created[0]["comment_range"] == "30"
    page.get_by_label("開始時間", exact=True).fill("2020-01-01T00:00")
    expect(page.get_by_text("此期間沒有貼文", exact=True)).to_be_visible()
    expect(button).to_be_disabled()
    expect(page.get_by_role("button", name="立即發想", exact=True)).to_be_disabled()
    assert len(calls) >= 3
    page.unroute("**/api/ideation/posts?*")
    page.unroute(f"**/api/ideation/reports/{report_id}")
    page.unroute("**/api/ideation/reports?*")
    page.unroute("**/api/ai/execution-options?*")
    page.goto(origin + f"/?view=ideation&report_id={report_id}")
    expect(page.locator(".ideation-card")).to_have_count(1)


def check_ideapolish(page, origin, report_id, width, height):
    from datetime import UTC, datetime
    from playwright.sync_api import expect

    template = page.request.get(origin + f"/api/ideation/reports/{report_id}").json()
    template["data"].update(notice="品牌資料待品牌覆核", quote_note="原話不足三則時不補造",
                            excluded_message_ids=[1, 2, 3],
                            agent_exclusions=[{"id": 2, "reason": "spam", "note": "[隔離驗收] 重複推銷"}])
    rows = [{"id": i, "platform": "facebook" if i == 11 else "instagram",
             "caption": "[隔離驗收] 合作流程", "published_at": "2025-02-01T02:00:00Z",
             "comment_count": 25, "total_comment_count": 25} for i in (11, 12, 13, 14)]
    previews, pending = [], []
    def comments(route):
        query = parse_qs(urlsplit(route.request.url).query)
        previews.append(query)
        offset = int(query["offset"][0])
        route.fulfill(json={"items": [{"id": i, "author": "觀***", "text": f"隔離原話 {i}",
                                     "sent_at": "2025-02-01T02:00:00Z"}
                                    for i in range(offset, min(offset + 20, 25))],
                            "next_offset": 20 if offset == 0 else None})
    page.route("**/api/ideation/posts?*", lambda r: r.fulfill(json=rows))
    page.route("**/api/ideation/posts/*/comments?*", comments)
    page.route("**/api/ai/execution-options?*", lambda r: r.fulfill(json={"options": [{"provider": "gemini_api", "available": True, "model": "isolated"}], "draft_provider": "gemini_api"}))
    def reports(route):
        path = urlsplit(route.request.url).path
        if route.request.method == "POST":
            pending.append(route)
        elif path.endswith("/scripts"):
            route.fulfill(json=[])
        elif path.endswith(f"/{report_id}"):
            route.fulfill(json=template)
        else:
            route.fulfill(json={"reports": [template], "defaults": {"start_at": template["start_at"], "end_at": template["end_at"]}})
    page.route("**/api/ideation/reports**", reports)
    page.goto(origin + f"/?view=ideation&report_id={report_id}")
    expect(page.locator(".ideation-posts")).to_have_attribute("aria-busy", "false")
    # 報告分開顯示使用者與 Agent 的排除；Agent 的理由收在可展開區。
    exclusions = page.locator(".ideation-exclusions")
    expect(exclusions.locator("p")).to_have_text("已排除 3 則留言（其中 Agent 判斷排除 1 則）")
    expect(exclusions.locator("li")).to_be_hidden()
    exclusions.get_by_text("查看 Agent 排除理由").click()
    expect(exclusions.locator("li")).to_have_text("留言 #2 · 廣告／垃圾 · [隔離驗收] 重複推銷")
    tabs = page.get_by_role("tablist", name="貼文平台")
    expect(tabs.get_by_role("tab", name="Instagram (3)")).to_have_attribute("aria-selected", "true")
    assert tabs.locator('[aria-selected=true]').evaluate(
        "e => { const s=getComputedStyle(e); return s.borderBottomWidth === '3px' && s.borderBottomColor === 'rgb(15, 58, 46)' && s.color === 'rgb(15, 58, 46)'; }"
    )
    expect(page.locator(".ideation-selection-summary")).to_have_text("將使用 FB 1 篇、IG 3 篇貼文、近 30 天的留言")
    page.get_by_role("checkbox", name="選取全部貼文", exact=True).uncheck()
    expect(page.locator(".ideation-selection-summary")).to_contain_text("FB 1 篇、IG 0 篇")
    tabs.get_by_role("tab", name="Facebook (1)").click()
    expect(page.locator(".ideation-post input")).to_be_checked()
    page.keyboard.press("ArrowRight")
    expect(tabs.get_by_role("tab", name="Instagram (3)")).to_be_focused()
    expect(page.locator(".ideation-post input").first).not_to_be_checked()
    page.locator(".ideation-post input").first.check()
    assert page.get_by_role("checkbox", name="選取全部貼文", exact=True).evaluate("e => e.indeterminate && !e.checked")
    # 留言以彈出視窗顯示，清單不被撐高；視窗內容區自行捲動，載入更多也在視窗內。
    expand = page.locator(".ideation-post-expand").first
    list_height = page.locator(".ideation-post-list").evaluate("e => e.getBoundingClientRect().height")
    expand.click()
    comments = page.get_by_role("dialog", name="貼文留言")
    expect(comments.locator(".ideation-preview-item")).to_have_count(20)
    expect(comments.get_by_role("button", name="關閉", exact=True)).to_be_focused()
    assert page.locator(".ideation-post-list").evaluate("e => e.getBoundingClientRect().height") == list_height
    box, viewport = comments.bounding_box(), page.viewport_size
    assert box["y"] >= 0 and box["y"] + box["height"] <= viewport["height"], box
    assert comments.locator(".ideation-dialog-body").evaluate("e => e.scrollHeight > e.clientHeight")
    comments.get_by_role("button", name="載入更多", exact=True).click()
    expect(comments.locator(".ideation-preview-item")).to_have_count(25)
    expect(comments.get_by_role("button", name="載入更多", exact=True)).to_have_count(0)
    assert [query["offset"] for query in previews] == [["0"], ["20"]]
    comments_shots = REPO / ".runtime/ideaui-screens/after"
    comments_shots.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(comments_shots / f"ideation-comments-dialog-{width}x{height}.png"))
    page.keyboard.press("Escape")
    expect(comments).to_have_count(0)
    expect(expand).to_be_focused()
    page.get_by_role("radio", name="近 7 天", exact=True).click()
    expect(page.locator(".ideation-posts")).to_have_attribute("aria-busy", "false")
    expand.click()
    expect(comments.locator(".ideation-preview-item")).to_have_count(20)
    assert previews[-1]["comment_range"] == ["7"]
    # 留言預設全勾；取消勾選即排除，摘要顯示排除數，送出時帶 excluded_message_ids。
    first_comment = comments.get_by_role("checkbox", name="使用留言 0", exact=True)
    expect(first_comment).to_be_checked()
    comments.locator(".ideation-preview-item").first.locator(".ideation-preview-text").click()
    expect(first_comment).not_to_be_checked()
    comments.get_by_role("button", name="關閉", exact=True).click()
    expect(comments).to_have_count(0)
    expect(page.locator(".ideation-selection-summary")).to_contain_text("（已排除 1 則）")
    expand.click()
    expect(first_comment).not_to_be_checked()
    comments.get_by_role("button", name="關閉", exact=True).click()
    excluded_bodies = []
    def capture_reclassify(route):
        excluded_bodies.append(route.request.post_data_json)
        route.fulfill(json={"status": "queued"})
    page.route("**/api/ideation/reclassify?*", capture_reclassify)
    page.get_by_role("button", name="重新標註所選留言", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("已排入所選留言範圍與貼文")
    assert [b["excluded_message_ids"] for b in excluded_bodies] == [[0]], excluded_bodies
    page.unroute("**/api/ideation/reclassify?*")
    tabs.get_by_role("tab", name="Facebook (1)").click()
    tabs.get_by_role("tab", name="Instagram (3)").click()
    expect(page.locator(".ideation-post input").first).to_be_checked()
    # Threads 貼文可選用：期間內有 Threads 貼文才多一個頁籤，沒有時畫面與先前相同。
    rows.append({"id": 15, "platform": "threads", "caption": "[隔離驗收] Threads 回覆整理",
                 "published_at": "2025-02-01T02:00:00Z", "comment_count": 25, "total_comment_count": 25})
    page.reload()
    expect(page.locator(".ideation-posts")).to_have_attribute("aria-busy", "false")
    expect(tabs.get_by_role("tab")).to_have_text(["Facebook (1)", "Instagram (3)", "Threads (1)"])
    expect(page.locator(".ideation-selection-summary")).to_contain_text("將使用 FB 1 篇、IG 3 篇、Threads 1 篇貼文")
    tabs.get_by_role("tab", name="Threads (1)").click()
    expect(page.locator(".ideation-post .ideation-platform")).to_have_text("Threads")
    expect(page.locator(".ideation-post input")).to_be_checked()
    rows.pop()
    page.reload()
    expect(page.locator(".ideation-posts")).to_have_attribute("aria-busy", "false")
    expect(tabs.get_by_role("tab")).to_have_text(["Facebook (1)", "Instagram (3)"])
    # 所選貼文在範圍內全為 0 則留言時只提醒、不禁止送出（送出後才會抓最新留言）。
    no_comments = page.locator(".ideation-no-comments")
    expect(no_comments).to_have_count(0)
    for row in rows:
        row["comment_count"] = 0
    page.reload()
    expect(page.locator(".ideation-posts")).to_have_attribute("aria-busy", "false")
    expect(no_comments).to_have_text("所選貼文在此留言範圍內目前沒有留言。送出後會先抓取最新留言，仍沒有留言就不會產生主題。")
    expect(page.get_by_role("button", name="立即發想", exact=True)).to_be_enabled()
    for row in rows:
        row["comment_count"] = 25
    page.reload()
    expect(page.locator(".ideation-posts")).to_have_attribute("aria-busy", "false")
    expect(no_comments).to_have_count(0)
    tabs.get_by_role("tab", name="Instagram (3)").click()
    # Match CSS geometry at all requested widths after data and DOM settle.
    for size, columns in [({"width": 1440, "height": 900}, 2), ({"width": 768, "height": 1024}, 2), ({"width": 390, "height": 844}, 1)]:
        page.set_viewport_size(size)
        assert page.locator(".ideation-source-fields").evaluate("e => getComputedStyle(e).gridTemplateColumns.split(' ').length") == columns
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        for title in page.locator(".ideation-step h3").all():
            assert title.evaluate("e => getComputedStyle(e).fontSize === '18px' && getComputedStyle(e).fontWeight === '600'")
        if size["width"] == 1440:
            bottoms = page.locator(".ideation-execution-row select,.ideation-execution-row button").evaluate_all("es => es.map(e => e.getBoundingClientRect().bottom)")
            assert max(bottoms) - min(bottoms) < 1
            row = page.locator(".ideation-execution-row").bounding_box()
            actions = page.locator(".ideation-execution-row .ideation-actions").bounding_box()
            assert abs(row["x"] + row["width"] - actions["x"] - actions["width"]) < 1
        for notice in page.locator(".ideation-notice").all():
            assert notice.evaluate("e => { const s=getComputedStyle(e); return s.backgroundColor === 'rgb(241, 245, 249)' && s.paddingLeft === '16px' && s.paddingRight === '16px' && s.borderLeftWidth === '3px'; }")
        for group in page.locator(".ideation-goal").all():
            assert group.evaluate("e => getComputedStyle(e).marginTop === '40px' && getComputedStyle(e.firstElementChild).marginBottom === '16px'")
    page.set_viewport_size({"width": width, "height": height})
    expect(page.locator(".ideation-evidence")).to_have_count(0)
    for action in page.get_by_role("button", name="建立發佈草稿", exact=True).all():
        expect(action).to_have_class("secondary")
    # Hold a mocked creation request to prove the immediate one-second clock.
    page.clock.install()
    # 暫停時鐘，只有 run_for 會前進；否則慢機器（例如 CI）上 reload 的實際耗時會灌進計時。
    began = page.evaluate("Date.now()") + 1000
    page.clock.pause_at(datetime.fromtimestamp(began / 1000, UTC))
    page.get_by_role("button", name="立即發想", exact=True).click()
    expect(page.locator('[role=timer]').first).to_contain_text("已執行 0:00")
    # Optimistic timing renders before the CSRF fetch and mocked POST arrive.
    deadline = time.monotonic() + 5
    while not pending and time.monotonic() < deadline:
        page.wait_for_timeout(10)
    assert len(pending) == 1, f"Expected one mocked POST, got {len(pending)}"
    page.clock.run_for(1100)
    expect(page.locator('[role=timer]').first).to_contain_text("已執行 0:01")
    assert len(pending) == 1
    template["status"] = "syncing_comments"
    template["data"].update(started_at=datetime.fromtimestamp(began / 1000, UTC).isoformat(), comments_synced_at=None, finished_at=None)
    pending[0].fulfill(status=202, json=template)
    # 狀態由列上的膠囊表示；列內計時只顯示時間，不重複狀態文字。
    expect(page.locator(".report-row").first).to_contain_text("抓取留言中")
    expect(page.locator(".report-row [role=timer]").first).not_to_contain_text("抓取留言中")
    page.clock.run_for(2100)
    expect(page.locator(".report-row [role=timer]").first).to_contain_text("已執行 0:03")
    page.reload()
    expect(page.locator(".report-row [role=timer]").first).to_contain_text("已執行 0:03")
    template["status"] = "processing"
    template["data"]["comments_synced_at"] = datetime.fromtimestamp(page.evaluate("Date.now()") / 1000, UTC).isoformat()
    page.reload()
    # 狀態由列上的膠囊表示；列內計時只顯示時間，不重複狀態文字。
    expect(page.locator(".report-row").first).to_contain_text("正在分類與發想")
    expect(page.locator(".report-row [role=timer]").first).not_to_contain_text("產生主題中")
    page.clock.run_for(1100)
    expect(page.locator(".report-row [role=timer]").first).to_contain_text("已執行 0:04")
    # 報告尚未完成時，卡片上的動作一律停用。
    action = page.get_by_role("button", name="建立發佈草稿", exact=True).first
    expect(action).to_be_disabled()
    expect(page.get_by_role("button", name="編輯", exact=True).first).to_be_disabled()
    template["status"] = "ready"
    template["data"]["finished_at"] = datetime.fromtimestamp((began + 68000) / 1000, UTC).isoformat()
    page.reload()
    expect(page.locator(".report-heading .ideation-timer")).to_have_text("耗時 1:08")
    page.clock.run_for(1100)
    expect(page.locator(".report-heading .ideation-timer")).to_have_text("耗時 1:08")
    expect(page.locator('[role=timer]')).to_have_count(0)
    template["status"] = "failed"
    page.reload()
    expect(page.locator(".report-heading .ideation-timer")).to_have_text("耗時 1:08")
    rows[:] = [rows[0]]
    page.reload()
    expect(tabs.get_by_role("tab", name="Instagram (0)")).to_be_disabled()
    expect(tabs.get_by_role("tab", name="Facebook (1)")).to_have_attribute("aria-selected", "true")
    for pattern in ("**/api/ideation/posts?*", "**/api/ideation/posts/*/comments?*", "**/api/ideation/reports**", "**/api/ai/execution-options?*"):
        page.unroute(pattern)
    page.goto(origin + f"/?view=ideation&report_id={report_id}")
    expect(page.locator(".ideation-card")).to_have_count(1)


def check_idea_actions(page, origin, report_id, width, height):
    """主題卡片只剩編輯、還原上一版、查看腳本與建立／開啟發佈草稿；重新生成、延伸、產生腳本已移除。"""
    import copy

    template = page.request.get(origin + f"/api/ideation/reports/{report_id}").json()
    scripts = page.request.get(origin + f"/api/ideation/reports/{report_id}/scripts").json()
    assert scripts and scripts[0]["topic_index"] == 0
    original = copy.deepcopy(template["data"]["ideas"][0])
    template["status"] = "ready"
    # 舊資料：曾被重新生成、延伸過的主題與留下失敗工作的欄位，仍要正常顯示、不再出現進度或錯誤。
    template["data"]["ideas"][0] = {**original, "title": "隔離舊重新生成主題", "regenerated": True,
                                    "extended_from": 1}
    template["data"]["ideas_history"] = {"0": [{"idea": original}]}
    template["data"]["ideas_job"] = dict(action="regenerate", indices=[0], status="failed",
                                         error="舊失敗訊息不得顯示", started_at="2026-01-01T00:00:00Z")
    calls, shown_scripts = [], [[]]
    prefix = f"**/api/ideation/reports/{report_id}"
    page.route(prefix, lambda route: route.fulfill(json=template))
    page.route(prefix + "/scripts", lambda route: route.fulfill(json=shown_scripts[0]))
    page.route("**/api/publish/posts?*", lambda route: route.fulfill(json=[]))

    def restore(route):
        calls.append((route.request.method, route.request.url.rsplit("/", 1)[-1]))
        template["data"]["ideas"][0] = copy.deepcopy(original)
        template["data"]["ideas_history"] = {}
        route.fulfill(json=template)

    page.route(prefix + "/ideas/**", restore)
    page.reload()
    card = page.locator(".ideation-card").first
    expect(card).to_contain_text("隔離舊重新生成主題")
    expect(card).to_contain_text("已重新生成")
    expect(card).to_contain_text("延伸自 #1")
    expect(card).not_to_have_attribute("aria-busy", "true")
    expect(card.get_by_role("alert")).to_have_count(0)
    expect(card.locator(".idea-skeleton,.idea-generating")).to_have_count(0)
    expect(page.get_by_text("舊失敗訊息不得顯示", exact=False)).to_have_count(0)
    # 已移除的按鈕與選取介面在整頁都不存在。
    for name in ("產生腳本", "重新生成", "延伸主題", "重新生成所選"):
        expect(page.get_by_role("button", name=name)).to_have_count(0)
    expect(page.get_by_role("checkbox", name="選取主題 #1")).to_have_count(0)
    expect(page.locator(".idea-select,.idea-selection-actions")).to_have_count(0)
    actions = card.locator(".idea-card-actions")
    # 動作分兩組：底部是產出（沒有腳本時只有「建立發佈草稿」），右上角只剩「編輯」。
    expect(actions.get_by_role("button")).to_have_text(["建立發佈草稿"])
    assert actions.get_by_role("button").evaluate_all("es => es.map(e => e.className)") == ["secondary"]
    tools = card.locator(".idea-card-heading .idea-card-tools")
    expect(tools.get_by_role("button")).to_have_text(["編輯"])
    assert tools.get_by_role("button").evaluate_all(
        "es => es.every(e => e.classList.contains('secondary') && e.classList.contains('small'))"
    )
    for size in (1440, 390, 280):
        page.set_viewport_size({"width": size, "height": height})
        page.wait_for_load_state("networkidle")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert actions.evaluate("e => e.scrollWidth <= e.clientWidth + 1")
        assert tools.evaluate("e => e.scrollWidth <= e.clientWidth + 1")
    page.set_viewport_size({"width": width, "height": height})

    screens = output_dir()
    screens.mkdir(parents=True, exist_ok=True)

    def capture(label):
        page.wait_for_load_state("networkidle")
        card.scroll_into_view_if_needed()
        page.screenshot(path=str(screens / f"cards-{label}-{width}x{height}.png"))

    capture("actions")
    restore_button = card.get_by_role("button", name="還原上一版", exact=True)
    expect(restore_button).to_have_class("secondary idea-restore")
    restore_button.click()
    expect(card.locator("h3")).to_have_text(original["title"])
    expect(card.get_by_text("已重新生成", exact=True)).to_have_count(0)
    expect(restore_button).to_have_count(0)
    assert calls == [("POST", "restore")], calls
    # 已有腳本：卡片底部多一顆 secondary「查看腳本」，開啟既有腳本檢視與編輯。
    shown_scripts[0] = scripts
    page.reload()
    expect(actions.get_by_role("button")).to_have_text(["查看腳本", "建立發佈草稿"])
    assert actions.get_by_role("button").evaluate_all("es => es.map(e => e.className)") == ["secondary", "secondary"]
    for size in (1440, 390, 280):
        page.set_viewport_size({"width": size, "height": height})
        page.wait_for_load_state("networkidle")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert actions.evaluate("e => e.scrollWidth <= e.clientWidth + 1")
        if size >= 390:
            # 底部兩顆按鈕排成一列，不擠成兩行。
            assert actions.get_by_role("button").evaluate_all(
                "es => Math.abs(es[0].getBoundingClientRect().top - es[1].getBoundingClientRect().top) < 2"
            ), size
    page.set_viewport_size({"width": width, "height": height})
    capture("script-view")
    expect(page.locator(".script-editor")).to_have_count(0)
    actions.get_by_role("button", name="查看腳本", exact=True).click()
    expect(page.locator(".script-editor")).to_be_visible()
    assert parse_qs(urlsplit(page.url).query)["script_id"] == [str(scripts[0]["id"])]
    page.unroute(prefix + "/ideas/**")
    page.unroute(prefix + "/scripts")
    page.unroute("**/api/publish/posts?*")
    page.unroute(prefix)
    page.goto(origin + f"/?view=ideation&report_id={report_id}")
    expect(page.locator(".ideation-card")).to_have_count(1)


def check_execution_choice(page, origin, report_id, width, height, checks):
    """執行方式：已設定的 API 供應者加「交給 Agent 撰寫」；舊 CLI 記憶與預設一律略過。"""
    available = [["gemini_api", "openai_api"]]
    default = {"value": ""}
    created = []
    template = page.request.get(origin + f"/api/ideation/reports/{report_id}").json()
    page.evaluate("localStorage.clear()")
    page.route("**/api/ai/execution-options?*", lambda route: route.fulfill(json={
        "options": [{"provider": p, "model": "isolated", "available": p in available[0]}
                    for p in ("gemini_api", "openai_api", "anthropic_api")],
        "draft_provider": default["value"],
    }))
    page.route("**/api/ideation/posts?*", lambda route: route.fulfill(json=[{
        "id": 11, "platform": "facebook", "published_at": "2025-02-01T02:00:00Z",
        "caption": "[隔離驗收] 服務流程", "comment_count": 3, "total_comment_count": 3,
    }]))

    def create(route):
        if route.request.method == "POST":
            created.append(route.request.post_data_json)
            route.fulfill(status=202, json={**template, "status": "syncing_comments"})
        else:
            route.continue_()

    page.route("**/api/ideation/reports?*", create)
    choice = page.get_by_role("combobox", name="執行方式", exact=True)
    brand = [""]

    def reopen(expected):
        page.goto(origin + "/?view=ideation")
        expect(choice).to_have_value(expected)
        page.wait_for_load_state("networkidle")
        # uiorder：主題發想沒有自己的品牌選單，品牌取自網址（單一品牌自動帶入）。
        expect(page.get_by_label("品牌", exact=True)).to_have_count(0)
        brand[0] = parse_qs(urlsplit(page.url).query)["brand_id"][0]
        assert choice.locator("optgroup").count() == 0
        labels = choice.locator("option").all_text_contents()
        assert labels[-1] == "交給 Agent 撰寫" and not any("CLI" in label for label in labels), labels
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

    # 沒有記憶也沒有品牌預設：第一個可用 API；未配置的 API 停用並標示。
    reopen("gemini_api")
    assert choice.locator("option").all_text_contents() == [
        "Gemini API", "OpenAI API", "Anthropic API（未配置）", "交給 Agent 撰寫"]
    assert choice.locator('option[value="anthropic_api"]').evaluate("e => e.disabled")
    assert not choice.locator('option[value="agent"]').evaluate("e => e.disabled")
    default["value"] = "openai_api"
    reopen("openai_api")
    # 人工選擇才寫入記憶，之後優先於品牌預設。
    choice.select_option("gemini_api")
    assert page.evaluate("key => JSON.parse(localStorage.getItem(key))", "ideation-choice:" + brand[0]) == "gemini_api"
    reopen("gemini_api")
    choice.select_option("agent")
    assert page.evaluate("key => JSON.parse(localStorage.getItem(key))", "ideation-choice:" + brand[0]) == "agent"
    reopen("agent")
    # 舊的本機 CLI 記憶、品牌預設值都視為未設定。
    page.evaluate("key => localStorage.setItem(key, JSON.stringify('codex_cli'))", "ideation-choice:" + brand[0])
    default["value"] = "claude_cli"
    reopen("gemini_api")
    default["value"] = "openai_api"
    reopen("openai_api")
    page.evaluate("key => localStorage.setItem(key, '{broken')", "ideation-choice:" + brand[0])
    reopen("openai_api")
    # 立即發想：選 API 送出該 API；選交給 Agent 送出 agent（後端不呼叫任何 AI）。
    page.evaluate("localStorage.clear()")
    default["value"] = ""
    reopen("gemini_api")
    page.get_by_label("開始時間", exact=True).fill("2025-01-01T00:00")
    expect(page.locator(".ideation-posts")).to_have_attribute("aria-busy", "false")
    start = page.get_by_role("button", name="立即發想", exact=True)
    expect(start).to_be_enabled()
    start.click()
    expect(page.locator(".report-select").first).to_contain_text("抓取留言中")
    assert created[-1]["provider"] == "gemini_api" and created[-1]["post_ids"] == [11], created
    choice.select_option("agent")
    page.get_by_label("開始時間", exact=True).fill("2025-01-01T00:00")
    expect(page.locator(".ideation-posts")).to_have_attribute("aria-busy", "false")
    expect(start).to_be_enabled()
    start.click()
    expect(page.get_by_role("button", name="立即發想", exact=True)).to_be_enabled()
    assert created[-1]["provider"] == "agent" and len(created) == 2, created
    # 沒有任何可用 API：預設就是交給 Agent 撰寫，並提示尚無可用 API，仍可開始發想。
    page.evaluate("localStorage.clear()")
    available[0] = []
    reopen("agent")
    expect(page.get_by_text("尚無可用的 AI API", exact=False)).to_be_visible()
    for provider in ("gemini_api", "openai_api", "anthropic_api"):
        assert choice.locator(f'option[value="{provider}"]').evaluate("e => e.disabled"), provider
    assert not choice.locator('option[value="agent"]').evaluate("e => e.disabled")
    page.get_by_label("開始時間", exact=True).fill("2025-01-01T00:00")
    expect(page.locator(".ideation-posts")).to_have_attribute("aria-busy", "false")
    expect(start).to_be_enabled()
    page.screenshot(path=str(output_dir() / f"execution-agent-{width}x{height}.png"))
    available[0] = ["gemini_api", "openai_api"]
    page.unroute("**/api/ideation/reports?*")
    page.unroute("**/api/ideation/posts?*")
    page.unroute("**/api/ai/execution-options?*")
    # 交給 Agent 的報告停在 awaiting_ideas：說明如何接手，沒有匯出檔案或重新生成入口。
    waiting = {**template, "status": "awaiting_ideas", "provider": "agent", "error": None}
    waiting["data"] = {k: v for k, v in template["data"].items() if k not in ("ideas", "ideas_history")}
    page.route(f"**/api/ideation/reports/{report_id}", lambda route: route.fulfill(json=waiting))
    page.goto(origin + f"/?view=ideation&report_id={report_id}")
    expect(page.locator(".report-heading h2")).to_contain_text("等待 Agent 撰寫主題")
    note = page.locator(".agent-awaiting")
    expect(note).to_contain_text("/mwb:ideas")
    expect(note).to_contain_text('get_guide("ideas")')
    # 開啟桌面 App 的按鈕帶報告編號預填指令（不自動送出），另有複製指令給其他 Agent。
    handoff = page.locator(".agent-handoff")
    expect(handoff.locator("a")).to_have_count(3)
    hrefs = handoff.locator("a").evaluate_all("els => els.map(e => e.getAttribute('href'))")
    assert [h.split("?")[0] for h in hrefs] == ["claude://code/new", "claude://claude.ai/new", "codex://new"], hrefs
    assert all(f"%23{report_id}" in h for h in hrefs), hrefs
    assert hrefs[2].endswith("&mode=codex"), hrefs
    expect(handoff.get_by_role("button", name="複製給其他 Agent")).to_be_visible()
    sizes = handoff.locator(".secondary").evaluate_all(
        "els => els.map(e => { const r = e.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; })")
    assert len(sizes) == 4 and len(set(map(tuple, sizes))) == 1, sizes
    handoff.locator("xpath=..").screenshot(path=str(output_dir() / f"agent-handoff-{width}x{height}.png"))
    expect(page.locator(".report-heading").locator("xpath=..").locator(".ideation-exports")).to_have_count(0)
    expect(page.locator(".ideation-card")).to_have_count(0)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path=str(output_dir() / f"awaiting-ideas-{width}x{height}.png"))
    # 舊報告（執行方式是已移除的 CLI）：仍可顯示，錯誤訊息改為已不再支援，且不提供重試。
    legacy = {**template, "status": "failed", "provider": "codex_cli", "can_retry": False,
              "error": "文字模型未完成（cli_not_logged_in）"}
    page.route(f"**/api/ideation/reports/{report_id}", lambda route: route.fulfill(json=legacy))
    page.reload()
    expect(page.locator(".report-heading h2")).to_contain_text("產生失敗")
    expect(page.locator(".report-heading").locator("xpath=..").get_by_text(
        "本機 CLI 已不再支援（舊紀錄），請改用 API 或交給 Agent 撰寫")).to_be_visible()
    expect(page.get_by_role("button", name="重試此報告")).to_have_count(0)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.unroute(f"**/api/ideation/reports/{report_id}")
    page.evaluate("localStorage.clear()")
    page.goto(origin + f"/?view=ideation&report_id={report_id}")
    expect(page.locator(".ideation-card")).to_have_count(1)
    checks.append(f"{width}: execution-api-agent-memory-default-legacy-cli-awaiting-ideas")


def check_idea_edit(page, origin, report_id, checks):
    import copy

    template = page.request.get(origin + f"/api/ideation/reports/{report_id}").json()
    original = copy.deepcopy(template["data"])
    prefix = f"**/api/ideation/reports/{report_id}"
    page.route(prefix, lambda route: route.fulfill(json=template))
    calls = []

    def save(route):
        body = route.request.post_data_json
        calls.append(body)
        assert set(body) == {"version", "title", "hook", "angle", "visual", "keyword"}
        template["data"]["ideas"][0] = {**original["ideas"][0],
                                        **{k: v for k, v in body.items() if k != "version"},
                                        "edited": True}
        template["data"]["ideas_revision"] = body["version"] + 1
        route.fulfill(json=template)

    page.route(prefix + "/ideas/0", save)
    page.reload()
    card = page.locator('.ideation-card').first
    card.get_by_role('button', name='編輯', exact=True).click()
    editor = card.locator('.idea-editor')
    expect(editor).to_be_visible()
    expect(editor.locator('textarea')).to_have_count(5)
    expect(editor.locator('.primary')).to_have_count(1)
    editor.get_by_label('標題', exact=True).fill('隔離編輯後標題')
    editor.get_by_role('button', name='取消', exact=True).click()
    expect(card.locator('h3')).to_have_text(original['ideas'][0]['title'])
    assert not calls
    card.get_by_role('button', name='編輯', exact=True).click()
    editor.get_by_label('關鍵字', exact=True).fill(' ')
    expect(editor.get_by_role('button', name='儲存', exact=True)).to_be_disabled()
    editor.get_by_label('關鍵字', exact=True).fill('隔離關鍵字')
    editor.get_by_label('標題', exact=True).fill('隔離編輯後標題')
    editor.get_by_role('button', name='儲存', exact=True).click()
    expect(card.locator('h3')).to_have_text('隔離編輯後標題')
    expect(card.locator('.idea-edited')).to_have_text('已編輯')
    assert len(calls) == 1
    assert template['data']['groups'] == original['groups']
    page.unroute(prefix + '/ideas/0')
    page.unroute(prefix)
    page.goto(origin + f'/?view=ideation&report_id={report_id}')
    expect(card.locator('h3')).to_have_text(original['ideas'][0]['title'])
    checks.append('pubfix-edit-cancel-required-save-badge-and-evidence')


# 超出視窗的元素必須被某個「可捲動或裁切」且本身在視窗內的祖先容器包住；
# 頁面與主要捲動容器本身也不得比可視寬度寬。
FOUR_TABS_MEASURE = """() => {
  const page = document.querySelector('.ideation-page');
  const loose = [...page.querySelectorAll('*')].filter(e => {
    const r = e.getBoundingClientRect();
    if (r.width === 0 || r.right <= innerWidth + 1) return false;
    for (let a = e.parentElement; a && a !== document.body; a = a.parentElement) {
      const o = getComputedStyle(a).overflowX;
      if (o !== 'visible' && a.getBoundingClientRect().right <= innerWidth + 1) return false;
      if (a === page) break;
    }
    return true;
  }).map(e => e.tagName + '.' + (e.className || '').toString().slice(0, 40));
  return {
    loose,
    page: [page.scrollWidth, page.clientWidth],
    root: [document.documentElement.scrollWidth, innerWidth],
    tabs: [...document.querySelectorAll('.ideation-platform-tabs button')].map(b => b.textContent),
  };
}"""


def check_four_platform_tabs(page, origin, factory, width, capture, checks):
    """主題發想在四個平台分頁（FB／IG／Threads／YouTube）時，手機與桌面都不得撐寬頁面。

    2026-10-14 使用者回報（原 check_ideation_mobile）：手機上平台分頁一排放不下，最後一個分頁把
    .ideation-page 撐到 469px（螢幕 390px），iPhone Safari 整頁可左右滑、左側文字被切掉。
    隔離資料原本沒有 Threads／YouTube 貼文所以沒抓到；這裡補帳號與貼文重現該情境。
    """
    from sqlalchemy import select

    from app.models import Account, Brand, Post
    from app.models.base import utc_now

    with factory.begin() as s:
        if not s.scalar(select(Account).where(Account.platform == "threads")):
            brand = s.scalar(select(Brand).where(Brand.slug == "TEST"))
            for platform in ("instagram", "threads", "youtube"):
                account = Account(
                    brand_id=brand.id,
                    platform=platform,
                    external_id=f"mobile-{platform}",
                    name=f"[隔離驗收] {platform}",
                    send_enabled=False,
                    token_ref="META_PAGE_ACCESS_TOKEN",
                )
                s.add(account)
                s.flush()
                for n in range(3):
                    s.add(Post(
                        account_id=account.id,
                        external_id=f"mobile-{platform}-{n}",
                        caption="[隔離驗收] 很長的貼文標題用來測試手機版面不被撐寬 " * 3,
                        media_type="POST",
                        published_at=utc_now() - timedelta(hours=n + 1),
                    ))
    page.goto(origin + "/?view=ideation")
    tabs = page.locator(".ideation-platform-tabs button")
    expect(tabs).to_have_count(4)
    page.wait_for_load_state("networkidle")
    result = page.evaluate(FOUR_TABS_MEASURE)
    assert result["loose"] == [], (width, result)
    assert result["page"][0] <= result["page"][1] + 1, (width, result)
    assert result["root"][0] <= result["root"][1] + 1, (width, result)
    # 最後一個分頁仍可捲到並點選。
    tabs.last.scroll_into_view_if_needed()
    tabs.last.click()
    expect(tabs.last).to_have_attribute("aria-selected", "true")
    assert page.evaluate(FOUR_TABS_MEASURE)["page"][0] <= result["page"][1] + 1
    capture("ideation-four-tabs")
    checks.append(f"ideation-four-tabs-no-overflow-{width}")


@runtime_check
def main():
    from alembic import command
    from alembic.config import Config
    from playwright.sync_api import expect, sync_playwright
    from sqlalchemy import select
    from stage3_fixture import seed_stage3

    from app.config import Settings
    from app.db import build_engine, session_factory
    from app.models import Account, Brand, Message, Post, Staff, Thread
    from app.models.base import utc_now
    from app.models.ideation import IdeationReport
    from app.services import auth, ideation_exports

    folder = temporary_dir()
    baseline = os.environ.get("UI_P0_3_BASELINE") == "1"
    artifacts = output_dir()
    artifacts.mkdir(parents=True, exist_ok=True)
    port = browser_port()
    origin = f"http://127.0.0.1:{port}"
    env = {
        "DATABASE_PATH": str(folder / "test.db"),
        "LOG_PATH": str(folder / "backend.jsonl"),
        "EXPORT_ROOT": str(folder / "export"),
        "OBSIDIAN_ROOT": str(folder / "obsidian"),
        "EXPORT_WORKER_ENABLED": "false",
        "RECEIVE_HEALTH_WORKER_ENABLED": "false",
        "SCHEDULER_ENABLED": "false",
        "RECEIVE_HEALTH_ALERTS_ENABLED": "false",
        "APP_ORIGIN": origin,
        "ALLOWED_HOSTS": '["127.0.0.1"]',
        "SESSION_COOKIE_SECURE": "false",
        "ADMIN_INITIAL_PASSWORD": secrets.token_urlsafe(32),
        "COMMENTS_WAKE_ENABLED": "false",
        "OPENAI_API_KEY": "",
        "GEMINI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "JEV_API_KEY": "",
        "NOTIFY_LINE_CHANNEL_ACCESS_TOKEN": "",
    }
    env_path = folder / ".env"
    env_path.write_text(
        "\n".join(f"{k}='{v}'" for k, v in env.items()), encoding="utf-8"
    )
    os.environ.update(env)
    settings = Settings(_env_file=env_path)
    command.upgrade(Config(str(REPO / "backend/alembic.ini")), "head")
    engine = build_engine(settings)
    cleanup(engine.dispose)
    factory = session_factory(engine)
    with factory.begin() as session:
        seed_records(session, settings, include_content=False)
        brand = session.scalar(select(Brand).where(Brand.slug == "TEST"))
        bid = brand.id
        account = Account(
            brand_id=bid,
            platform="facebook",
            external_id="fix-isolated",
            name="隔離驗收帳號",
        )
        session.add(account)
        session.flush()
        post = Post(
            account_id=account.id,
            external_id="fix-post",
            caption="[隔離驗收] 原話留言定位貼文",
            media_type="POST",
            published_at=utc_now() - timedelta(days=20),
        )
        session.add(post)
        session.flush()
        post_id = post.id
        dm = Thread(
            brand_id=bid, account_id=account.id, external_id="fix-dm", kind="dm"
        )
        comments = Thread(
            brand_id=bid,
            account_id=account.id,
            post_id=post.id,
            external_id="fix-comments",
            kind="comment_thread",
        )
        session.add_all([dm, comments])
        session.flush()
        dm_id = dm.id
        ids = []
        for thread, count, label in [(dm, 240, "歷史來源"), (comments, 65, "留言")]:
            for i in range(count):
                message = Message(
                    thread_id=thread.id,
                    external_id=f"fix-{label}-{i}",
                    direction="in",
                    author_type="fan",
                    text=f"[隔離驗收] {label}第 {i} 則：服務前確認現場條件？",
                    sent_at=utc_now() - timedelta(days=20) + timedelta(minutes=i),
                    comment_parent_known=True,
                )
                session.add(message)
                session.flush()
                if i == 0:
                    ids.append(message.id)
        credentials = auth.issue_session(
            session,
            settings,
            session.scalar(select(Staff.id).where(Staff.username == "admin")),
        )
    first, script_id = seed_stage3(factory, origin)
    latest, _ = seed_stage3(factory, origin)
    with factory.begin() as session:
        row = session.get(IdeationReport, first)
        data = json.loads(json.dumps(row.data_json))
        data["groups"][0]["quotes"] = [
            {
                "id": mid,
                "text": f"[隔離驗收] {label}：服務前確認現場條件？",
                "platform": "facebook",
                "url": f"https://wrong-origin.invalid/?view=ideation&message_id={mid}",
            }
            for mid, label in zip(ids, ["歷史來源", "留言"], strict=True)
        ]
        data["ideas"][0]["quote_ids"] = ids
        row.data_json = data
    ideation_exports.export_report(factory, settings, first)
    ideation_exports.export_script(factory, settings, script_id)
    with factory.begin() as session:
        # Exercise discovery of historical --ID exports that predate export_json.
        session.get(IdeationReport, first).export_json = {}
    # 伺服器沿用 check_ui_scale 的 serve()（讀 env 檔、不繼承工作機的供應商金鑰）。
    server = launch_server(
        folder, origin, script=REPO / "scripts/check_ui_scale.py", args=[env_path, port]
    )
    errors, external, checks = [], [], []
    try:
        with sync_playwright() as pw:
            browser = launch_chromium(pw)
            for width, height in [(1440, 900), (390, 844)]:
                context = browser.new_context(
                    viewport={"width": width, "height": height}, accept_downloads=True
                )
                context.add_cookies(
                    [
                        {
                            "name": auth.COOKIE_NAME,
                            "value": credentials.token,
                            "url": origin,
                        }
                    ]
                )

                def guard(route):
                    if route.request.url.startswith(origin + "/"):
                        route.continue_()
                    else:
                        external.append(route.request.url.split("?")[0])
                        route.abort()

                context.route("**/*", guard)
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))

                def capture(label, page=page, width=width, height=height):
                    page.wait_for_load_state("networkidle")
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= innerWidth"
                    )
                    page.screenshot(
                        path=str(artifacts / f"{label}-{width}x{height}.png")
                    )
                    checks.append(f"{width}x{height}: {label}")

                page.goto(origin + "/?view=ideation")
                expect(
                    page.get_by_role(
                        "heading", name=f"報告 #{latest} · 已完成・匯出未完成", exact=True
                    )
                ).to_be_visible()  # uiorder：這份報告沒有匯出檔，標題依實際檔案狀態顯示
                assert parse_qs(urlsplit(page.url).query)["report_id"] == [str(latest)]
                expect(page.locator(".ideation-card")).to_have_count(1)
                if not baseline:
                    # Fixture deliberately retains the old fields: UI must ignore them.
                    expect(page.locator(".ideation-evidence")).to_have_count(0)
                    expect(page.get_by_text("全部主題與代表原話", exact=True)).to_have_count(0)
                    assert page.request.get(origin + f"/api/ideation/reports/{latest}").json()["data"]["groups"]
                    expect(page.get_by_text("預約關聯", exact=False)).to_have_count(0)
                    expect(page.get_by_text("權重", exact=False)).to_have_count(0)
                capture("latest-report")
                if not baseline:
                    check_ideaui(page, origin, latest, width, height)
                    check_ideapolish(page, origin, latest, width, height)
                    check_idea_edit(page, origin, latest, checks)
                    check_idea_actions(page, origin, latest, width, height)
                    check_execution_choice(page, origin, latest, width, height, checks)
                page.locator(".ideation-card").scroll_into_view_if_needed()
                capture("ideation-report")
                page.locator(".ideation-actions button").filter(
                    has_text=f"#{first} ·"
                ).click()
                expect(
                    page.get_by_role(
                        "heading", name=f"報告 #{first} · 已完成並匯出", exact=True
                    )
                ).to_be_visible()
                page.reload()
                expect(
                    page.get_by_role(
                        "heading", name=f"報告 #{first} · 已完成並匯出", exact=True
                    )
                ).to_be_visible()
                if not baseline:
                    rows = page.locator(".report-history .report-select")
                    expect(rows).to_have_count(2)
                    boxes = [row.bounding_box() for row in rows.all()]
                    assert abs(boxes[0]["x"] - boxes[1]["x"]) < 1
                    assert boxes[1]["y"] > boxes[0]["y"] + boxes[0]["height"]
                    expect(rows.filter(has_text=f"#{first} ·")).to_have_attribute("aria-current", "true")
                    expect(page.locator('.report-history [aria-current="true"]')).to_have_count(1)
                    check_exports(page, page.locator(".ideation-exports").first, "reports", first, folder / "export")
                else:
                    page.locator(".ideation-exports").first.scroll_into_view_if_needed()
                capture("report-downloads")
                for label in ["Markdown", "Word"]:
                    with page.expect_download() as result:
                        page.get_by_role(
                            "link", name="下載 " + label, exact=True
                        ).first.click()
                    downloaded = result.value
                    assert f"--{first}." in downloaded.suggested_filename
                    assert Path(downloaded.path()).stat().st_size > 0
                    checks.append(f"{width}: report download {label}")
                expect(page.locator(".ideation-card").get_by_role("link", name=f"Facebook · 原話 #{ids[0]} →", exact=True)).to_have_count(0)
                expect(page.locator(".ideation-card")).to_contain_text("歷史來源")
                page.locator(".ideation-card summary").click()
                expect(page.locator(".ideation-card .ideation-quotes").get_by_text(f"原話 #{ids[0]}（來源已無法存取）", exact=True)).to_be_visible()
                expect(page.locator(".ideation-card").get_by_text("私訊", exact=False)).to_have_count(0)
                for mid, kind in [(ids[1], "comment")]:
                    link = page.locator(".ideation-card").get_by_role(
                        "link", name=f"Facebook · 原話 #{mid} →", exact=True
                    )
                    assert link.get_attribute("href").startswith(
                        "/?"
                    ) and not link.get_attribute("target")
                    if not link.is_visible():
                        page.locator(".ideation-card summary").click()
                    link.click()
                    selector = f'[data-message-id="{mid}"]'
                    focused = page.locator(selector)
                    expect(focused).to_be_in_viewport()
                    expect(focused).to_have_class(
                        __import__("re").compile(
                            "focused-message" if kind == "dm" else "focused-comment"
                        )
                    )
                    if kind == "dm":
                        assert parse_qs(urlsplit(page.url).query)["thread_id"] == [
                            str(dm_id)
                        ]
                    else:
                        assert parse_qs(urlsplit(page.url).query)["post_id"] == [
                            str(post_id)
                        ]
                        expect(page.locator(".post-intro .post-caption")).to_have_text(
                            "[隔離驗收] 原話留言定位貼文"
                        )
                    capture(kind + "-focused")
                    page.get_by_role(
                        "link", name=f"← 回到報告 #{first}", exact=True
                    ).click()
                    expect(
                        page.get_by_role(
                            "heading", name=f"報告 #{first} · 已完成並匯出", exact=True
                        )
                    ).to_be_visible()
                    capture(kind + "-returned")
                page.locator(".ideation-actions button").filter(
                    has_text=f"#{script_id} [隔離驗收]"
                ).click()
                expect(page.locator(".script-editor")).to_be_visible()
                page.reload()
                expect(page.locator(".script-editor")).to_be_visible()
                assert parse_qs(urlsplit(page.url).query)["script_id"] == [
                    str(script_id)
                ]
                editor = page.locator(".script-editor")
                editor.scroll_into_view_if_needed()
                if not baseline:
                    check_exports(page, editor.locator(".ideation-exports"), "scripts", script_id, folder / "export")
                else:
                    editor.locator(".ideation-exports").scroll_into_view_if_needed()
                capture("script-downloads")
                for label in ["Markdown", "Word"]:
                    with page.expect_download() as result:
                        editor.get_by_role(
                            "link", name="下載 " + label, exact=True
                        ).click()
                    assert f"--{script_id}-v1." in result.value.suggested_filename
                    assert Path(result.value.path()).stat().st_size > 0
                    checks.append(f"{width}: script download {label}")
                expect(editor.get_by_role("link", name=f"Facebook · 原話 #{ids[0]} →", exact=True)).to_have_count(0)
                expect(editor.get_by_text(f"原話 #{ids[0]}（來源已無法存取）", exact=True)).to_be_visible()
                editor.get_by_role(
                    "link", name=f"Facebook · 原話 #{ids[1]} →", exact=True
                ).click()
                expect(
                    page.locator(f'[data-message-id="{ids[1]}"]')
                ).to_be_in_viewport()
                page.get_by_role(
                    "link", name=f"← 回到報告 #{first}", exact=True
                ).click()
                expect(page.locator(".script-editor")).to_be_visible()
                capture("script-returned")
                # Existing date filters must not prevent a linked older comment from loading.
                page.goto(
                    origin
                    + f"/?view=posts&post_id={post_id}&comment_id={ids[1]}&comment_range=7&return_report_id={first}&brand_id={bid}"
                )
                expect(
                    page.locator(f'[data-message-id="{ids[1]}"]')
                ).to_be_in_viewport()
                capture("comment-outside-date-range")
                page.reload()
                expect(page.locator(f'[data-message-id="{ids[1]}"]')).to_be_in_viewport()
                page.get_by_role("group", name="留言日期", exact=True).get_by_role(
                    "radio", name="近 7 天", exact=True
                ).click()
                expect(page.locator(f'[data-message-id="{ids[1]}"]')).to_have_count(0)
                expect(page.get_by_text("這段期間沒有留言", exact=True)).to_be_visible()
                checks.append(f"{width}: linked-comment-refresh-reload-and-explicit-filter")
                if not baseline:
                    def many_reports(route):
                        payload = route.fetch().json()
                        template = payload["reports"][0]
                        payload["reports"] += [{**template, "id": 100 + i} for i in range(8)]
                        route.fulfill(json=payload)

                    def unavailable_exports(route):
                        payload = route.fetch().json()
                        payload["exports"]["files"] = [
                            {**entry, "available": False} for entry in payload["exports"]["files"]
                        ]
                        payload["exports"]["error"] = "[隔離驗收] 匯出暫時不可用"
                        route.fulfill(json=payload)

                    page.route("**/api/ideation/reports?*", many_reports)
                    page.route(f"**/api/ideation/reports/{first}", unavailable_exports)
                    page.goto(origin + f"/?view=ideation&report_id={first}")
                    history_list = page.locator(".report-history")
                    expect(history_list.locator(".report-select")).to_have_count(10)
                    boxes = [row.bounding_box() for row in history_list.locator(".report-select").all()]
                    assert all(abs(box["x"] - boxes[0]["x"]) < 1 for box in boxes)
                    assert all(b["y"] >= a["y"] + a["height"] for a, b in zip(boxes, boxes[1:]))
                    assert history_list.evaluate("e => e.scrollHeight > e.clientHeight && getComputedStyle(e).overflowY === 'auto'")
                    assert history_list.bounding_box()["height"] <= 288
                    cards = page.locator(".ideation-exports").first
                    expect(cards.locator(".export-card")).to_have_count(2)
                    expect(cards.locator(".ideation-chip")).to_have_text([
                        "Markdown 尚未產生", "Word 尚未產生"
                    ])
                    expect(cards.get_by_role("link")).to_have_count(0)
                    expect(cards.get_by_role("alert")).to_have_text("[隔離驗收] 匯出暫時不可用")
                    # uiorder：匯出檔都不可用時，標題不再寫「已完成並匯出」。
                    expect(page.locator(".report-heading h2")).to_have_text(f"報告 #{first} · 已完成・匯出未完成")
                    checks.append(f"{width}: history-scroll-and-unavailable-exports")
                page.goto(origin + "/?view=prices")
                expect(page.locator('.dashboard-kpis .kpi')).to_have_count(2)
                expect(page.locator('.price-match')).to_have_count(0)
                checks.append(f"{width}: retired-price-url-falls-back-to-dashboard")
                if not baseline:
                    page.unroute("**/api/ideation/reports?*")
                    page.unroute(f"**/api/ideation/reports/{first}")
                    check_report_delete(page, origin, bid, first, width, checks)
                    check_four_platform_tabs(page, origin, factory, width, capture, checks)
                context.close()
            browser.close()
        assert not errors and not external, (errors, external)
        report = {
            "checks": checks,
            "count": len(checks),
            "page_errors": errors,
            "external_requests": external,
            "status": "passed",
        }
        (artifacts / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "checks": len(checks),
                    "page_errors": len(errors),
                    "external_requests": len(external),
                    "status": "passed",
                }
            )
        )
    finally:
        stop_process(server)
        engine.dispose()


if __name__ == "__main__":
    main()

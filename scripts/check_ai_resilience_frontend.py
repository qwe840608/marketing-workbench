"""AI settings, usage table and ideation choice defaults with synthetic HTTP responses only."""

import re
from urllib.parse import urlsplit

import check_polish_frontend as polish
from browser_harness import main
from playwright.sync_api import expect
from runtime_tmp import output_dir
from ui_navigation import navigate

# 用量表的舊紀錄：本機 CLI 已移除，但歷史資料仍要完整顯示（欄位、格式與手機寬度）。
RUNS = [
    dict(id=1, task="video_script", provider="gemini_api", model="primary", tokens_in=None,
         tokens_out=None, cost_usd=None, ok=False, error="provider_http_503", duration_ms=123),
    dict(id=2, task="script", provider="codex_cli", model="legacy", tokens_in=1200, tokens_out=20,
         cost_usd=None, ok=True, error=None, duration_ms=1200),
    dict(id=3, task="script", provider="claude_cli", model="legacy", tokens_in=None, tokens_out=None,
         cost_usd=None, ok=True, error=None, duration_ms=1200),
    dict(id=4, task="script", provider="agy_cli", model="legacy", tokens_in=0, tokens_out=0,
         cost_usd=None, ok=True, error=None, duration_ms=1200),
    dict(id=5, task="script", provider="claude_cli", model="legacy", tokens_in=10, tokens_out=None,
         cost_usd="2.5", ok=True, error=None, duration_ms=1200),
    dict(id=6, task="script", provider="gemini_api", model="primary", tokens_in=100, tokens_out=20,
         cost_usd="0.001", ok=True, error=None, duration_ms=1200),
    dict(id=7, task="ideation", provider="codex_cli", model="legacy", tokens_in=None, tokens_out=None,
         cost_usd=None, ok=False, error="cli_not_logged_in", duration_ms=300),
]
LEGACY_NOTE = "本機 CLI 已不再支援（舊紀錄），請改用 API 或交給 Agent 撰寫"


def check_usage(page, checks):
    original = page.viewport_size
    page.get_by_role("tab", name="基本", exact=True).click()
    rows = page.locator(".usage-table tbody tr")
    expect(rows).to_have_count(len(RUNS))
    expected = [("— / —", "—"), ("1200 / 20", "訂閱"), ("未回報", "訂閱"), ("0 / 0", "訂閱"),
                ("10 / 未回報", "訂閱"), ("100 / 20", "0.001"), ("未回報", "訂閱")]
    names = ["Gemini API", "Codex CLI（已停用）", "Claude Code（已停用）", "Antigravity（已停用）",
             "Claude Code（已停用）", "Gemini API", "Codex CLI（已停用）"]
    for width, height in ((1440, 900), (390, 844)):
        page.set_viewport_size({"width": width, "height": height})
        page.wait_for_load_state("networkidle")
        for index, ((tokens, cost), name) in enumerate(zip(expected, names, strict=True)):
            expect(rows.nth(index).locator('[data-label="輸入／輸出"]')).to_have_text(tokens)
            expect(rows.nth(index).locator('[data-label="美元估算"]')).to_have_text(cost)
            expect(rows.nth(index).locator('[data-label="任務／供應商"]')).to_contain_text(name)
        expect(rows.nth(0).locator("small")).to_have_text("Gemini 目前流量過高（Google 端問題），請稍後再試")
        expect(rows.nth(6).locator("small")).to_have_text(LEGACY_NOTE)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert page.locator(".usage-table").evaluate("e => e.scrollWidth <= e.clientWidth + 1")
        # 本機 CLI 已移除：不再有訂閱說明。
        expect(page.get_by_text("本機 CLI 使用個人訂閱", exact=False)).to_have_count(0)
        page.locator(".usage-table").scroll_into_view_if_needed()
        page.screenshot(path=str(output_dir() / f"usage-{width}x{height}.png"))
    page.set_viewport_size(original)
    checks.append("legacy-cli-usage-rows-numeric-zero-partial-unreported-subscription-api-mobile")


def member_response(member):
    # Playwright 會把 request 當第二個參數傳入，所以用外層函式帶入固定內容。
    return lambda route: route.fulfill(json=member)


def check_tabs(page, origin, settings_gets, saved, checks):
    original_size = page.viewport_size
    page.set_viewport_size({"width": 1440, "height": 900})
    output = output_dir()
    output.mkdir(parents=True, exist_ok=True)
    tabs = [("basic", "基本"), ("brand", "品牌說明"), ("keys", "AI 金鑰")]

    def select(name):
        page.get_by_role("tab", name=name, exact=True).click()
        page.wait_for_load_state("networkidle")

    def capture(name):
        page.get_by_role("heading", name="設定", exact=True).scroll_into_view_if_needed()
        page.wait_for_load_state("networkidle")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        if not name.startswith("marketing-"):
            assert page.get_by_role("tablist", name="AI 設定", exact=True).evaluate("""e => {
                const panel = document.querySelector('.ai-settings-page [role=tabpanel]:not([hidden])');
                const a = e.getBoundingClientRect(), b = panel.getBoundingClientRect();
                return Math.abs(a.left-b.left) <= 1 && a.width < b.width && a.right <= b.right + 1 &&
                    e.scrollWidth <= e.clientWidth + 1 &&
                    e.querySelectorAll('[tabindex="0"]').length === 1;
            }""")
        else:
            assert page.get_by_role("tablist", name="設定", exact=True).evaluate("""e => {
                const panel = document.querySelector('#settings-panel-account');
                const a = e.getBoundingClientRect(), b = panel.getBoundingClientRect();
                const button = e.querySelector('[role=tab]').getBoundingClientRect();
                return Math.abs(a.left-b.left) <= 1 && button.width < b.width && a.right <= b.right + 1 &&
                    e.scrollWidth <= e.clientWidth + 1 &&
                    e.querySelectorAll('[tabindex="0"]').length === 1;
            }""")
        page.screenshot(path=str(output / (name + ".png")))

    expect(page.get_by_label("每月 API 預算（美元）")).to_be_visible()
    page.wait_for_load_state("networkidle")
    tablist = page.get_by_role("tablist", name="AI 設定", exact=True)
    # 本機 CLI 已移除：只剩三個分頁，也沒有任何 CLI 區塊或按鈕。
    expect(tablist.get_by_role("tab")).to_have_text([name for _, name in tabs])
    expect(page.get_by_role("tab", name="本機 CLI", exact=True)).to_have_count(0)
    expect(page.locator(".cli-entry,.local-cli-settings")).to_have_count(0)
    for label in ("儲存 CLI 設定", "全部更新", "重新偵測"):
        expect(page.get_by_role("button", name=label, exact=True)).to_have_count(0)
    loads = len(settings_gets)
    budget = page.get_by_label("每月 API 預算（美元）")
    budget.fill("123.45")
    # uiorder：AI 設定不再有自己的「套用品牌」，改用側邊欄品牌。
    expect(page.get_by_label("套用品牌")).to_have_count(0)
    usage = page.get_by_role("tab", name="基本", exact=True)
    usage.focus()
    usage.press("ArrowRight")
    prompt_tab = page.get_by_role("tab", name="品牌說明", exact=True)
    expect(prompt_tab).to_be_focused()
    expect(prompt_tab).to_have_attribute("aria-selected", "true")
    expect(page.get_by_label("套用品牌")).to_have_count(0)
    prompt = page.get_by_role("textbox", name="品牌說明內容", exact=True)
    expect(prompt).to_be_enabled()
    page.wait_for_load_state("networkidle")
    prompt.fill("隔離驗收未儲存內容")
    select("AI 金鑰")
    expect(page.get_by_label("套用品牌")).to_have_count(0)
    key = page.get_by_label("新增或替換金鑰")
    key.fill("isolated-unsaved-key")
    select("基本")
    expect(budget).to_have_value("123.45")
    select("品牌說明")
    expect(prompt).to_have_value("隔離驗收未儲存內容")
    select("AI 金鑰")
    expect(key).to_have_value("isolated-unsaved-key")
    assert page.evaluate("!JSON.stringify([localStorage, sessionStorage]).includes('isolated-unsaved-key')")
    key.fill("")
    # 切換分頁不重新讀取設定，未儲存的內容也不會被覆蓋。
    assert len(settings_gets) == loads, (loads, settings_gets)
    keys_tab = page.get_by_role("tab", name="AI 金鑰", exact=True)
    keys_tab.press("End")
    expect(keys_tab).to_be_focused()
    keys_tab.press("ArrowRight")
    expect(usage).to_be_focused()
    usage.press("ArrowLeft")
    expect(keys_tab).to_be_focused()
    keys_tab.press("Home")
    expect(usage).to_be_focused()
    for key_name, name in tabs:
        select(name)
        panel_id = page.get_by_role("tab", name=name, exact=True).get_attribute("aria-controls")
        expect(page.locator(".ai-settings-page").get_by_role("tabpanel")).to_have_count(1)
        expect(page.locator("#" + panel_id)).to_be_visible()
        expect(page.locator("#" + panel_id)).to_have_attribute("aria-labelledby", "ai-tab-" + key_name)
        page.reload()
        expect(page.get_by_role("tab", name=name, exact=True)).to_have_attribute("aria-selected", "true")
    page.goto(origin + "/?view=ai&ai_tab=prompt&campaign=isolated#settings")
    expect(prompt_tab).to_have_attribute("aria-selected", "true")
    page.get_by_role("button", name="儀表板", exact=True).click()
    navigate(page, "AI 設定")
    expect(prompt_tab).to_have_attribute("aria-selected", "true")
    assert "campaign=isolated" in page.url and page.url.endswith("#settings")
    select("基本")
    assert "view=settings" in page.url and "settings_tab=ai" in page.url and "campaign=isolated" in page.url
    page.evaluate("history.pushState(null, '', '?view=ai&ai_tab=prompt'); dispatchEvent(new PopStateEvent('popstate'))")
    expect(prompt_tab).to_have_attribute("aria-selected", "true")
    page.goto(origin + "/?view=ai&ai_tab=invalid")
    expect(usage).to_have_attribute("aria-selected", "true")
    expect(page).to_have_url(re.compile(r"[?&]ai_tab=basic(?:&|$)"))
    # 舊網址：usage／prompt／advanced 沿用對應分頁；已移除的 cli 分頁回到基本。
    for old, target in [("usage", "basic"), ("prompt", "brand"), ("advanced", "keys"), ("keys", "keys"),
                        ("cli", "basic")]:
        page.goto(origin + "/?view=ai&ai_tab=" + old + "&campaign=isolated#settings")
        expect(page.locator("#ai-tab-" + target)).to_have_attribute("aria-selected", "true")
        expect(page).to_have_url(re.compile(r"[?&]ai_tab=" + target + r"(?:&|$)"))
        assert "campaign=isolated" in page.url and page.url.endswith("#settings")
    for width, height in ((1440, 900), (390, 844)):
        page.set_viewport_size({"width": width, "height": height})
        for key_name, name in tabs:
            select(name)
            if key_name == "brand":
                expect(page.locator(".prompt-editor textarea").first).to_be_visible()
            capture(f"admin-{key_name}-{width}x{height}")
    # 預設 AI：只列 API 供應者；未設定時顯示「請選擇 API 供應者」，欄位寬度對齊所在區塊。
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(origin + "/?view=ai&ai_tab=basic")
    choice = page.get_by_label("預設 AI（主題發想）", exact=True)
    expect(choice).to_have_value("")
    assert choice.locator("option").all_text_contents() == [
        "請選擇 API 供應者", "Gemini API", "OpenAI API", "Anthropic API"]
    assert not any("CLI" in label for label in choice.locator("option").all_text_contents())
    expect(page.get_by_label("預設 AI（主題發想、腳本）", exact=True)).to_have_count(0)
    choice.select_option("openai_api")
    default_box, label_box = choice.bounding_box(), choice.locator("..").bounding_box()
    assert default_box and label_box and abs(default_box["width"] - label_box["width"]) < 2
    page.get_by_role("button", name="儲存 AI 設定", exact=True).click()
    expect(page.locator("#ai-panel-basic").get_by_role("status")).to_have_text("AI 設定已儲存")
    assert saved[-1]["default_provider"] == "openai_api"
    expect(page.get_by_label("背景任務供應商", exact=True)).to_have_count(0)
    expect(page.get_by_label("自動產生草稿", exact=False)).to_have_count(0)
    expect(page.get_by_role("button", name="AI回覆草稿", exact=True)).to_have_count(0)
    # 非管理員只看得到「我的帳號」，看不到任何 AI 設定。
    for role in ("marketing", "viewer"):
        member = {
            "id": 1, "username": "isolated", "display_name": "隔離驗收成員", "role": role,
            "must_change_password": False, "brand_ids": [1],
        }
        page.route("**/api/auth/me", member_response(member))
        page.goto(origin + "/?view=ai&ai_tab=keys")
        expect(page.get_by_role("heading", name="設定", exact=True)).to_be_visible()
        page.wait_for_load_state("networkidle")
        expect(page.get_by_role("tablist", name="設定", exact=True).get_by_role("tab")).to_have_text(["我的帳號"])
        expect(page.get_by_role("tablist", name="AI 設定", exact=True)).to_have_count(0)
        expect(page.get_by_role("tab", name="AI 金鑰", exact=True)).to_have_count(0)
        expect(page.locator(".ai-keys")).to_have_count(0)
        expect(page.get_by_label("每月 API 預算（美元）")).to_have_count(0)
        expect(page.get_by_label("工作區共用說明內容")).to_have_count(0)
        expect(page.get_by_role("textbox", name="品牌說明內容", exact=True)).to_have_count(0)
        expect(page.get_by_label("預設 AI（主題發想）", exact=True)).to_have_count(0)
        expect(page.locator(".my-account input")).to_have_count(3)
        assert all(field.is_enabled() for field in page.locator(".my-account input").all())
        if role == "marketing":
            capture("marketing-tabs-1440x900")
        page.unroute("**/api/auth/me")
    page.goto(origin + "/?view=ai")
    page.wait_for_load_state("networkidle")
    page.set_viewport_size(original_size)
    checks.append("ai-three-tabs-keyboard-url-roles-unsaved-forms-default-api-only-no-cli")


def check_ai(page, open_thread, shot, checks):
    expect(page.locator(".workspace")).to_be_visible()
    origin = urlsplit(page.url)._replace(path="", query="", fragment="").geturl()
    config = {
        "default_provider": None,
        "manual_provider": "gemini_api",
        "background_provider": "gemini_api",
        "gemini_fallback_model": "gemini-3.7-flash",
        "openai_fallback_model": "",
        "anthropic_fallback_model": "",
        "monthly_budget_usd": None,
        "version": 1,
    }
    saved, settings_gets = [], []

    def configuration(route):
        if route.request.method == "PUT":
            body = route.request.post_data_json
            saved.append(body)
            config.update(body)
            config["version"] += 1
        else:
            settings_gets.append(route.request.url)
        route.fulfill(
            json={
                "config": config,
                "options": [
                    {"provider": name, "model": "primary", "available": True, "reason": None}
                    for name in ("gemini_api", "openai_api", "anthropic_api")
                ],
                "budget": {
                    "estimated_usd": 0,
                    "warning": False,
                    "unknown_cost_runs": 0,
                },
                "runs": RUNS,
            }
        )

    page.route("**/api/ai/settings?*", configuration)
    page.goto(origin + "/?view=ai")
    page.get_by_role("tab", name="AI 金鑰", exact=True).click()
    gemini = page.get_by_label("Gemini API 備援模型", exact=True)
    expect(gemini).to_have_value("gemini-3.7-flash")
    gemini.fill("")
    page.get_by_label("OpenAI API 備援模型", exact=True).fill("backup-openai")
    page.get_by_label("Anthropic API 備援模型", exact=True).fill("backup-anthropic")
    page.get_by_role("button", name="儲存 AI 設定", exact=True).click()
    expect(page.locator("#ai-panel-keys").get_by_text("AI 設定已儲存", exact=True)).to_be_visible()
    assert saved[-1]["gemini_fallback_model"] == ""
    assert saved[-1]["openai_fallback_model"] == "backup-openai"
    assert saved[-1]["anthropic_fallback_model"] == "backup-anthropic"
    assert saved[-1]["version"] == 1
    page.get_by_role("tab", name="基本", exact=True).click()
    expect(page.locator('small[title="provider_http_503"]')).to_have_text(
        "Gemini 目前流量過高（Google 端問題），請稍後再試"
    )
    shot("ai-backup-settings")
    checks.append("ai-fallback-fields-empty-save-version-error-title")
    check_usage(page, checks)
    check_tabs(page, origin, settings_gets, saved, checks)


if __name__ == "__main__":
    polish.run_checks = check_ai
    polish.check_polling = lambda *args: None
    main(polish=True)

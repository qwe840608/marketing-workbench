"""Every workspace page survives a browser reload; isolated database and HTTP mocks."""

from runtime_tmp import output_dir

from urllib.parse import parse_qs, urlsplit

import check_polish_frontend as polish
from browser_harness import main
from playwright.sync_api import expect
from ui_navigation import navigate, navigation_button, open_settings, brand_picker

PAGES = [
    ("儀表板", "dashboard"),
    ("貼文數據", "posts"),
    ("訊息分類", "policy"),
    ("AI 設定", "ai"),
    ("主題發想", "ideation"),
    ("發佈", "publish"),
    ("工作區設定", "settings"),
]


def check_refresh(page, open_thread, shot, checks):
    expect(page.locator(".workspace")).to_be_visible()

    mobile = page.viewport_size['width'] < 600
    output = output_dir()
    output.mkdir(parents=True, exist_ok=True)

    def settle():
        page.wait_for_load_state('networkidle')
        page.evaluate('async () => { await document.fonts.ready; await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); await Promise.all(document.getAnimations().filter(a => a.effect?.getTiming().iterations !== Infinity).map(a => a.finished.catch(() => {}))); }')

    def content_ready():
        # SPA navigation can retain the previous document's networkidle state.
        # Wait for the API-backed panel, before resolving a changing .last locator.
        if page.locator('#ai-panel-basic:not([hidden])').count():
            expect(page.locator('#ai-panel-basic .policy-grid input')).to_have_count(1)
            expect(page.locator('#ai-panel-basic .usage-table')).to_be_attached()
        if page.locator('.publish-editor').count():
            expect(page.locator('.publish-editor')).to_have_attribute('aria-busy', 'false')
            expect(page.get_by_role('tablist', name='文案平台').get_by_role('tab')).to_have_count(6)
            expect(page.locator('.publish-platform-toggle input')).to_have_count(5)
            expect(page.get_by_role('tab', name='共用', exact=True)).to_have_attribute('aria-selected', 'true')
            if parse_qs(urlsplit(page.url).query).get('publish_post_id'):
                # 已存草稿等 debounced check 回應，量測使用新分頁與錯誤原因。
                expect(page.locator('.publish-editor')).to_have_attribute('data-check-state', 'checked')
            else:
                # 空白表單不建草稿，改驗已載入平台開關與空文案。
                expect(page.locator('.publish-editor')).to_have_attribute('data-check-state', 'pending')
                expect(page.get_by_label('主文案', exact=True)).to_have_value('')
                expect(page.get_by_role('switch', name='發佈到 YouTube', exact=True)).to_be_disabled()
                expect(page.get_by_role('switch', name='發佈到 TikTok', exact=True)).to_be_disabled()
        settle()

    def capture(name):
        settle()
        width, height = page.viewport_size['width'], page.viewport_size['height']
        page.screenshot(path=str(output / f'{name}-{width}x{height}.png'), animations='disabled')

    def current(label):
        if mobile:
            expected = label if label in ('主題發想', '儀表板', '貼文數據', '發佈') else '設定'
            selected = page.locator('.mobile-bottom-nav [aria-current="page"]')
            expect(selected).to_have_count(1)
            expect(selected).to_contain_text(expected)
            expect(selected).to_be_enabled()
            assert selected.evaluate('''e => {
                const probe = document.createElement('span'); probe.style.background = 'var(--brand-primary)';
                probe.style.color = 'var(--bg-surface)'; document.body.append(probe);
                const a = getComputedStyle(e), b = getComputedStyle(probe);
                const ok = a.backgroundColor === b.backgroundColor && a.color === b.color && a.opacity === '1';
                probe.remove(); return ok;
            }'''), 'Current mobile navigation uses solid brand fill'
            assert page.locator('h1').evaluate("e => document.querySelector('.mobile-settings-controls').getBoundingClientRect().bottom <= e.getBoundingClientRect().top + e.closest('.workspace > section').scrollTop")
        else:
            expect(navigation_button(page, label)).to_have_class('current')

    def bottom_content():
        content_ready()
        leaf = page.locator('.workspace > :is(.settings-page,.dashboard-page,.posts-panel,.inbox-page) :is(button,p,small,label,summary,a,tbody td,tbody th):visible').last
        if leaf.count():
            leaf.scroll_into_view_if_needed()
            leaf.evaluate('''async element => {
                let previous = '', stable = 0;
                const deadline = performance.now() + 3000;
                while (performance.now() < deadline) {
                    await new Promise(requestAnimationFrame);
                    const box = element.getBoundingClientRect();
                    const scroller = element.closest('.settings-page,.dashboard-page,.posts-panel,.inbox-page');
                    const sample = JSON.stringify([box.x, box.y, box.width, box.height,
                        scroller.scrollTop, scroller.scrollHeight, scroller.clientHeight]);
                    stable = sample === previous ? stable + 1 : 0;
                    if (stable >= 3) return;
                    previous = sample;
                }
                throw new Error('Content geometry did not settle');
            }''')
            bounds = leaf.bounding_box()
            top = page.locator('.mobile-bottom-nav').bounding_box()['y']
            assert bounds['y'] + bounds['height'] <= top + 1, (page.url, bounds, top)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')

    expect(page.locator('.dashboard-kpis .kpi strong').first).to_be_visible()
    settle()
    capture('dashboard')
    if mobile:
        bar = page.locator('.mobile-bottom-nav')
        expect(bar).to_be_visible()
        expect(bar.locator('button')).to_have_count(5)
        expect(page.locator('.inbox-nav-toggle')).to_have_count(0)
        current('儀表板')
        expect(bar.locator('button')).to_have_text(['儀表板', '貼文數據', '主題發想', '發佈', '設定'])
        expect(page.locator('.mobile-more')).to_have_count(0)
        open_settings(page)
        # uiorder：只有一個品牌時手機沒有品牌選單（多品牌行為見 check_brand_scope），仍有登出。
        expect(page.locator('.mobile-brand-picker')).to_have_count(0)
        expect(page.locator('.mobile-logout')).to_be_visible()
        capture('settings')
        checks.append('mobile-five-navigation-settings-brand-logout')
    else:
        expect(page.locator('.mobile-bottom-nav,.mobile-more')).to_have_count(0)
        expect(page.locator('.workspace-nav button')).to_have_count(5)
        assert page.locator('.sidebar').bounding_box()['width'] == 220
        checks.append('desktop-sidebar-unchanged-no-mobile-dom')

    def view():
        return parse_qs(urlsplit(page.url).query).get("view", [None])[0]

    for label, name in PAGES:
        navigate(page, label)
        settle()
        current(label)
        expected_view = 'settings' if name in ('policy', 'ai', 'settings') else name
        expected_tab = 'workspace' if name == 'settings' else name
        if expected_view == 'settings':
            expect(page.locator('.settings-tabs [aria-selected="true"]')).to_have_attribute('id', 'settings-tab-' + expected_tab)
            expect(page.locator('.workspace h1')).to_have_text('設定')
        if mobile and name in ('dashboard', 'ideation'):
            capture(name)
        if mobile:
            bottom_content()
        if name == 'ai':
            content_ready()
            capture('usage')
        assert view() == expected_view, (label, page.url)
        if expected_view == 'settings':
            assert parse_qs(urlsplit(page.url).query)['settings_tab'] == [expected_tab]
            expect(page.locator('.settings-tabs [aria-selected="true"]')).to_have_attribute('id', 'settings-tab-' + expected_tab)
        page.reload()
        expect(page.locator(".workspace")).to_be_visible()
        settle()
        current(label)
        assert view() == expected_view, (label, page.url)
        if expected_view == 'settings':
            assert parse_qs(urlsplit(page.url).query)['settings_tab'] == [expected_tab]
            expect(page.locator('.settings-tabs [aria-selected="true"]')).to_have_attribute('id', 'settings-tab-' + expected_tab)
        if mobile:
            bottom_content()
        checks.append(f"reload-keeps-{name or 'inbox'}")
    if mobile:
        # Delay the resolved response beyond network idle, as with a slow render.
        # The old check scrolls to the brand label while usage is still absent.
        page.evaluate('''() => {
            const original = window.fetch;
            window.fetch = async (...args) => {
                const response = await original(...args);
                if (String(args[0]).includes('/ai/settings?')) {
                    await new Promise(resolve => { window.__releaseUsage = resolve; });
                }
                return response;
            };
            window.__restoreRefreshFetch = () => { window.fetch = original; };
        }''')
        try:
            navigate(page, 'AI 設定')
            expect(page.locator('#ai-panel-basic')).to_be_attached()
            page.wait_for_function('typeof window.__releaseUsage === "function"')
            expect(page.locator('#ai-panel-basic .policy-grid')).to_have_count(0)
            page.evaluate('() => setTimeout(() => window.__releaseUsage(), 100)')
            bottom_content()
            capture('usage-delayed')
            checks.append('delayed-usage-content-ready-and-scrolls-above-navigation')
        finally:
            page.evaluate('() => { window.__releaseUsage?.(); window.__restoreRefreshFetch(); delete window.__restoreRefreshFetch; delete window.__releaseUsage; }')
    if mobile:
        expect(page.locator('.mobile-brand-picker')).to_have_count(0)
        page.set_viewport_size({'width': 600, 'height': 844})
        expect(page.locator('.mobile-more,.mobile-bottom-nav,.mobile-settings-controls')).to_have_count(0)
        expect(page.locator('.workspace-nav')).to_be_visible()
        page.set_viewport_size({'width': 390, 'height': 844})
        expect(page.locator('.mobile-bottom-nav')).to_be_visible()
        expect(page.locator('.mobile-brand-picker,.brand-picker')).to_have_count(0)
        checks.append('single-brand-no-picker-across-breakpoint')
    origin = urlsplit(page.url).scheme + '://' + urlsplit(page.url).netloc
    for legacy, target in [('ai', 'ai'), ('policy', 'policy'), ('settings', 'workspace')]:
        page.goto(origin + '/?view=' + legacy + '&campaign=isolated#settings')
        expect(page.locator('#settings-tab-' + target)).to_have_attribute('aria-selected', 'true')
        page.wait_for_function("location.search.includes('settings_tab=')")
        assert view() == 'settings' and 'campaign=isolated' in page.url and page.url.endswith('#settings')
        checks.append('legacy-' + legacy + '-to-' + target)
    page.goto(origin + '/?view=dashboard')
    navigate(page, '設定')
    # uiorder：進入設定預設為平台連線。
    expect(page.locator('#settings-tab-connections')).to_have_attribute('aria-selected', 'true')
    tabs = page.get_by_role('tablist', name='設定', exact=True)
    expect(tabs.get_by_role('tab')).to_have_text(['平台連線', 'AI', '訊息分類', '工作區', '成員', '我的帳號'])
    tabs.get_by_role('tab', name='平台連線', exact=True).focus()
    for key, target in [('ArrowRight', 'ai'), ('ArrowRight', 'policy'), ('ArrowRight', 'workspace'), ('ArrowRight', 'members'), ('ArrowRight', 'account'), ('ArrowRight', 'connections'), ('ArrowLeft', 'account'), ('Home', 'connections'), ('End', 'account')]:
        page.keyboard.press(key)
        selected = page.locator('#settings-tab-' + target)
        expect(selected).to_be_focused()
        expect(selected).to_have_attribute('aria-selected', 'true')
        expect(tabs.locator('[tabindex="0"]')).to_have_count(1)
        expect(page.locator('#settings-panel-' + target)).to_be_visible()
        assert selected.evaluate("e => getComputedStyle(e).borderBottomWidth === '3px' && getComputedStyle(e).borderBottomColor === getComputedStyle(e).color")
        expect(selected).to_have_attribute('aria-selected', 'true')
        settle()
        assert selected.evaluate("e => getComputedStyle(e).color === 'rgb(15, 58, 46)' && getComputedStyle(e).backgroundColor === 'rgba(0, 0, 0, 0)'")
    navigate(page, '儀表板')
    navigate(page, '設定')
    expect(page.locator('#settings-tab-account')).to_have_attribute('aria-selected', 'true')
    content_ready()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    checks.append('default-connections-keyboard-cycle-home-end-remember-last-tab')
    shot("view-refresh")


if __name__ == "__main__":
    polish.run_checks = check_refresh
    polish.check_polling = lambda *args: None
    main(polish=True)

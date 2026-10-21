"""uiorder 第二輪：品牌選單整合（單一品牌隱藏、多品牌「全部」提示）與文字、分頁順序驗證。

隔離資料庫只有一個品牌；多品牌情境只在瀏覽器端替身 /api/brands 多加第二個品牌，不寫入資料庫、
不呼叫任何平台。
"""

import re

from browser_harness import REPO, main
from playwright.sync_api import expect
from ui_navigation import navigate, one_brand, two_brands

SHOTS = REPO / '.runtime' / 'uiorder-screens'
TAB_ORDER = ['平台連線', 'AI', '訊息分類', '工作區', '成員', '我的帳號']


def exercise(page, unused, shot, checks):
    SHOTS.mkdir(parents=True, exist_ok=True)
    size = page.viewport_size
    mobile = size['width'] < 600
    suffix = f"{size['width']}x{size['height']}"

    def capture(name):
        page.wait_for_load_state('networkidle')
        page.evaluate('async () => { await document.fonts.ready; }')
        page.screenshot(path=str(SHOTS / f'{name}-{suffix}.png'))
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (name, size)

    brands = page.request.get(page.evaluate('location.origin') + '/api/brands?limit=200').json()
    assert len(brands) == 1, brands
    real = brands[0]
    picker = '.mobile-brand-picker' if mobile else '.brand-picker'

    # ---- 單一品牌：沒有任何品牌選單，各頁直接使用該品牌 ----
    expect(page.locator('.brand-picker,.mobile-brand-picker')).to_have_count(0)
    expect(page.locator('.workspace-label')).to_have_count(0)
    if not mobile:
        expect(page.locator('.sidebar-note')).to_have_text('品牌營運工作檯')
        capture('sidebar-single-brand')
    assert '工作台' not in page.inner_text('body') and '同步掌握' not in page.inner_text('body')
    # 儀表板標題與貼文數據標題；頁首不再重複工作區名稱。
    expect(page.locator('.page-header h1')).to_have_text('儀表板')
    expect(page.locator('.page-header .workspace-name')).to_have_count(0)
    capture('dashboard-title')
    navigate(page, '貼文數據')
    expect(page.locator('.page-header h1')).to_have_text('貼文數據')
    expect(page.get_by_role('region', name='貼文數據')).to_be_visible()
    expect(page.locator('.follower-period-label')).to_have_text('粉絲數期間')
    capture('posts-followers')
    navigate(page, '主題發想')
    expect(page.locator('.ideation-form')).to_be_visible()
    expect(page.get_by_label('品牌', exact=True)).to_have_count(0)
    expect(page.locator('.need-brand')).to_have_count(0)
    navigate(page, '發佈')
    expect(page.locator('.publish-editor')).to_be_visible()
    expect(page.get_by_label('發佈品牌', exact=True)).to_have_count(0)
    expect(page.locator('.publish-accounts')).to_be_visible()
    # 「發佈功能尚未開啟」只在頂部提醒與按鈕下方各一次，標題列沒有狀態膠囊。
    expect(page.locator('.publish-switch .status-badge')).to_have_count(0)
    capture('publish-top')
    checks.append(f'single-brand-no-picker-pages-use-it:{size["width"]}')

    # ---- 設定：分頁順序、預設分頁、沒有各頁自己的品牌選單 ----
    navigate(page, '設定')
    tabs = page.get_by_role('tablist', name='設定', exact=True).get_by_role('tab')
    expect(tabs).to_have_text(TAB_ORDER)
    expect(page.locator('#settings-tab-connections')).to_have_attribute('aria-selected', 'true')
    expect(page.locator('.connection-card').first).to_be_visible()
    capture('settings-connections-default')
    for label in ('套用品牌', '目前品牌'):
        expect(page.get_by_label(label, exact=True)).to_have_count(0)
    # Webhook 白話標籤；環境變數名稱改成小號灰色等寬字。
    endpoints = page.locator('section[aria-labelledby=connection-webhook]')
    assert [text.strip() for text in endpoints.locator('label').all_inner_texts()] == ['公開網址', 'Meta 留言通知網址', 'LINE 通知網址']
    endpoints.scroll_into_view_if_needed()
    capture('webhook-card')
    env = page.locator('.credential-env').first
    expect(env).to_be_attached()
    assert env.evaluate("e => { const s = getComputedStyle(e), r = getComputedStyle(document.documentElement); return /mono|consolas|menlo/i.test(s.fontFamily) && parseFloat(s.fontSize) <= 12 && s.color === (() => { const p = document.createElement('i'); p.style.color = r.getPropertyValue('--text-subtle'); document.body.append(p); const c = getComputedStyle(p).color; p.remove(); return c; })(); }")
    for tab, body in (('AI', '#settings-panel-ai'), ('訊息分類', '#settings-panel-policy')):
        page.get_by_role('tab', name=tab, exact=True).click()
        expect(page.locator(body + ' .need-brand')).to_have_count(0)
        expect(page.locator(body + ' .brand-toolbar')).to_have_count(0)
    navigate(page, '工作區設定')
    expect(page.locator('.general-settings .brand-toolbar')).to_have_count(0)
    expect(page.locator('.general-settings .need-brand')).to_have_count(0)
    expect(page.locator('details.workspace-group')).to_have_count(5)
    page.get_by_role('tab', name='成員', exact=True).click()
    expect(page.locator('.member-connections').first).to_contain_text('Agent 連線')
    expect(page.get_by_role('button', name='撤銷全部 Agent 連線').first).to_be_visible()
    expect(page.get_by_role('button', name='全部撤銷')).to_have_count(0)
    capture('members')
    checks.append(f'settings-tab-order-default-connections-labels:{size["width"]}')

    # ---- 多品牌（瀏覽器端替身）：選單、「全部」提示、選擇品牌後內容出現 ----
    two_brands(page)
    page.goto(page.evaluate('location.origin') + '/?view=dashboard')
    expect(page.locator(picker + ' select')).to_be_visible()
    expect(page.locator(picker + ' option')).to_have_text(['全部可見品牌', real['name'], '隔離第二品牌'])
    if not mobile:
        expect(page.locator('.workspace-label')).to_have_count(0)
        capture('sidebar-multi-brand')
    select = page.locator(picker + ' select')
    expect(select).to_have_value('')
    # 多品牌選單字級：手機 16px（避免 iOS 放大）、桌機沿用輸入字級。
    if mobile:
        assert select.evaluate('e => parseFloat(getComputedStyle(e).fontSize)') == 16
    capture('brand-picker-open')
    # 儀表板、貼文數據可用「全部」，不顯示提示。
    expect(page.locator('.dashboard-kpis .kpi')).to_have_count(2)
    navigate(page, '貼文數據')
    expect(page.locator('.need-brand')).to_have_count(0)
    expect(page.locator('.post-toolbar')).to_be_visible()
    wanted = '請先在上方選擇品牌' if mobile else '請先在左側選擇品牌'
    other = '請先在左側選擇品牌' if mobile else '請先在上方選擇品牌'

    def need_brand(scope):
        notice = page.locator(scope + ' .need-brand')
        expect(notice).to_have_count(1)
        expect(notice).to_be_visible()
        assert notice.inner_text().strip() == wanted and other not in notice.inner_text()

    navigate(page, '主題發想')
    need_brand('.settings-page')
    expect(page.locator('.ideation-form,.report-history')).to_have_count(0)
    capture('need-brand-ideation')
    navigate(page, '發佈')
    need_brand('.settings-page')
    expect(page.locator('.publish-editor')).to_have_count(0)
    navigate(page, '設定')
    for tab, panel in (('AI', '#settings-panel-ai'), ('訊息分類', '#settings-panel-policy')):
        page.get_by_role('tab', name=tab, exact=True).click()
        need_brand(panel)
        expect(page.locator(panel + ' input,' + panel + ' textarea')).to_have_count(0)
    navigate(page, '工作區設定', advanced=False)
    need_brand('#settings-panel-workspace')
    # 依品牌的群組（品牌範本、主題發想、通知）不顯示；與品牌無關的資料、系統群組保留。
    expect(page.locator('details.workspace-group')).to_have_count(2)
    expect(page.locator('details.workspace-group > summary')).to_have_text(['資料', '系統'])
    # 選擇品牌後內容出現，網址帶 brand_id（送給後端的參數與以前相同，只是來源改成側邊欄）。
    select.select_option(str(real['id']))
    expect(page.locator('#settings-panel-workspace .need-brand')).to_have_count(0)
    expect(page.locator('details.workspace-group')).to_have_count(5)
    assert f"brand_id={real['id']}" in page.url
    navigate(page, '主題發想')
    expect(page.locator('.ideation-form')).to_be_visible()
    navigate(page, '發佈')
    expect(page.locator('.publish-editor')).to_be_visible()
    # 品牌選擇跨斷點保留，不因視窗寬度切換而重置。
    page.set_viewport_size({'width': 390 if not mobile else 1440, 'height': 844 if not mobile else 900})
    other_picker = '.mobile-brand-picker' if not mobile else '.brand-picker'
    expect(page.locator(other_picker + ' select')).to_have_value(str(real['id']))
    page.set_viewport_size(size)
    # 網址的 brand_id 參數照舊有效：直接開啟需要單一品牌的頁面，不必先選。
    select.select_option('')
    page.goto(page.evaluate('location.origin') + f"/?view=ideation&brand_id={real['id']}")
    expect(page.locator('.ideation-form')).to_be_visible()
    expect(page.locator(picker + ' select')).to_have_value(str(real['id']))
    # 切回「全部」後，需要單一品牌的頁面再次顯示提示。
    page.locator(picker + ' select').select_option('')
    need_brand('.settings-page')
    one_brand(page)
    checks.append(f'multi-brand-picker-all-prompt-select-url:{size["width"]}')


if __name__ == '__main__':
    main(exercise=exercise)

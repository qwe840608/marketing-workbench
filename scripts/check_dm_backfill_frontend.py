"""Retired DM UI stays absent; comment tools and LINE notifications remain usable."""
from browser_harness import main
from playwright.sync_api import expect
from ui_navigation import navigate


def check_backfill(page, open_thread, shot, checks):
    calls=[]
    page.route('**/api/dm/**', lambda route: (calls.append(route.request.url), route.abort()))
    navigate(page, '工作區設定')
    expect(page.get_by_role('heading', name='匯出資料夾', exact=True)).to_be_visible()
    expect(page.get_by_role('region', name='歷史私訊補抓')).to_have_count(0)
    expect(page.locator('.dm-backfill-status')).to_have_count(0)
    assert '私訊' not in page.locator('[data-group="data"]').inner_text()
    navigate(page, '平台連線')
    from app.services.credentials import GROUPS
    expect(page.locator('.connection-card')).to_have_count(len(GROUPS))
    expect(page.get_by_role('heading', name='LINE 官方帳號', exact=True)).to_have_count(0)
    expect(page.get_by_role('heading', name='LINE 通知', exact=True)).to_be_visible()
    expect(page.get_by_role('form', name='NOTIFY_LINE_CHANNEL_SECRET', exact=True)).to_be_visible()
    assert not calls
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    checks.append('DM controls absent; comment exports and notification credentials retained')
    page.unroute('**/api/dm/**')


if __name__ == '__main__':
    main(exercise=check_backfill)

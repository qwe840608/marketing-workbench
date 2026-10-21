"""Visible-only health polling and removed-feature UI regression."""
from playwright.sync_api import expect
from ui_navigation import navigate
TIMER_HARNESS = """(() => {
  const intervals = new Map(); let next = 1;
  window.setInterval = (fn, ms) => { const id = next++; intervals.set(id, {fn, ms}); return id; };
  window.clearInterval = id => intervals.delete(id);
  window.__polishTick = ms => {
    for (const value of [...intervals.values()]) if (value.ms <= ms) value.fn();
  };
  let visibility = 'visible';
  Object.defineProperty(document, 'visibilityState', {get: () => visibility});
  window.__polishVisibility = value => {
    visibility=value; document.dispatchEvent(new Event('visibilitychange'));
  };
})()"""


def check_retired_ui(page):
    """已移除的收件匣：導覽只剩行銷功能，窄版不溢出。"""
    expect(page.locator('.workspace')).to_be_visible()
    expect(page.locator('.inbox-page,.conversation-list,.reply-composer,.workflow-panel')).to_have_count(0)
    expect(page.get_by_role('button', name='收件匣', exact=True)).to_have_count(0)
    expect(page.get_by_role('button', name='價目表', exact=True)).to_have_count(0)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    if page.viewport_size['width'] < 600:
        expect(page.locator('.mobile-bottom-nav button')).to_have_text(['儀表板', '貼文數據', '主題發想', '發佈', '設定'])
    else:
        expect(page.locator('.workspace-nav button')).to_have_text(['儀表板', '貼文數據', '主題發想', '發佈', '設定'])
    expect(page.locator('.mobile-more')).to_have_count(0)


def run_checks(page, unused, shot, checks):
    check_retired_ui(page)
    shot('marketing-navigation')
    checks.append('retired-ui-absent')
    # 原 ui_composer：每個保留頁面都不得出現退休的回覆／送出控制項。
    for label in ('儀表板', '貼文數據', '主題發想', '訊息分類', 'AI 設定', '工作區設定'):
        navigate(page, label)
        page.wait_for_load_state('networkidle')
        check_retired_ui(page)
        expect(page.locator('.draft-panel,.direct-send,.send-settings,.routing-settings')).to_have_count(0)
        expect(page.get_by_role('button', name='AI回覆草稿', exact=True)).to_have_count(0)
        expect(page.get_by_role('button', name='檢查並送出', exact=True)).to_have_count(0)
    shot('no-reply-controls')
    checks.append('no-reply-controls-on-four-pages-and-three-settings-tabs')

def check_polling(page, unused, checks):
    requests = []
    page.on('request', lambda r: requests.append(r.url))
    for label in ('貼文數據', '儀表板', '工作區設定'):
        navigate(page, label)
        page.wait_for_load_state('networkidle')
        page.evaluate("window.__polishVisibility('hidden')")
        requests.clear()
        page.evaluate('window.__polishTick(60000)')
        page.wait_for_timeout(100)
        assert not any('/receive-health' in url for url in requests)
        page.evaluate("window.__polishVisibility('visible')")
        page.wait_for_timeout(200)
        assert any('/receive-health' in url for url in requests)
        assert not any('/api/inbox' in url or '/api/drafts' in url or '/api/send/' in url for url in requests)
    checks.append('health-visible-refresh-hidden-stop-no-retired-polling')

if __name__ == '__main__':
    from browser_harness import main
    main(polish=True)

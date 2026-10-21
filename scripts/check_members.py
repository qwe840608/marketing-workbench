"""Member lifecycle with a synthetic DB; no external sockets."""

import secrets
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

from browser_harness import REPO, main
from playwright.sync_api import expect
from ui_navigation import navigate


def check_members(page, unused, shot, checks):
    from pydantic import SecretStr
    from sqlalchemy import select

    from app.config import Settings
    from app.db import build_engine, session_factory
    from app.models import Brand, Staff, StaffBrand
    from app.models.base import utc_now
    from app.models.ideation import IdeationReport
    from app.services.passwords import hash_password

    settings = Settings(_env_file=None)
    for path in (settings.database_path, settings.export_root):
        assert path.resolve().is_relative_to((REPO / '.runtime').resolve())
    engine = build_engine(settings)
    factory = session_factory(engine)
    viewer_password = SecretStr(secrets.token_urlsafe(24))
    try:
        with factory.begin() as session:
            brand = session.scalar(select(Brand).where(Brand.slug == 'TEST'))
            bid = brand.id
            if not session.scalar(select(Brand).where(Brand.slug == 'members-other')):
                session.add(Brand(slug='members-other', name='隔離其他品牌'))
            viewer = session.scalar(select(Staff).where(Staff.username == 'viewer_test'))
            viewer.password_hash = hash_password(viewer_password)
            if not session.scalar(select(StaffBrand).where(StaffBrand.staff_id == viewer.id,
                                                           StaffBrand.brand_id == bid)):
                session.add(StaffBrand(staff_id=viewer.id, brand_id=bid))
            if not session.scalar(select(IdeationReport).where(IdeationReport.brand_id == bid)):
                now = utc_now()
                session.add(IdeationReport(brand_id=bid, meeting_at=now, start_at=now - timedelta(days=7),
                    end_at=now, trigger='manual', provider='gemini_api', status='ready',
                    notification_status='skipped', data_json={'ideas': [{
                        'title': '隔離驗收主題', 'hook': '如何整理製作需求？', 'goal': '流量型',
                        'element': '人群', 'topic': '服務', 'angle': '整理需求',
                        'visual': '需求清單', 'keyword': '製作，需求', 'quote_ids': [],
                    }]}))
    finally:
        engine.dispose()
    page.reload()
    expect(page.locator('.workspace')).to_be_visible()
    origin = page.evaluate('location.origin')
    width, height = page.viewport_size['width'], page.viewport_size['height']
    artifacts = REPO / '.runtime/members-screens/after'
    artifacts.mkdir(parents=True, exist_ok=True)

    def capture(name):
        page.wait_for_load_state('networkidle')
        page.evaluate('async () => { await document.fonts.ready; await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); }')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (name, width)
        # 分頁列維持單行；側邊欄「登出」不換行；底部導覽未選項目不是有框按鈕。
        assert page.evaluate("""() => {
            const tabs = [...document.querySelectorAll('.settings-tabs [role=tab]')]
                .filter(e => e.offsetParent);
            const top = e => e.getBoundingClientRect().top;
            const oneRow = tabs.every(e => Math.abs(top(e) - top(tabs[0])) < 2);
            const logout = [...document.querySelectorAll('.sidebar button')]
                .find(e => e.textContent.trim() === '登出' && e.offsetParent);
            const logoutOk = !logout || (logout.classList.contains('quiet') && logout.getClientRects().length === 1
                && logout.getBoundingClientRect().height < 2 * parseFloat(getComputedStyle(logout).fontSize) + 24);
            const nav = [...document.querySelectorAll('.mobile-bottom-nav button:not(.current)')];
            return oneRow && logoutOk && nav.every(e => e.classList.contains('quiet') && !e.classList.contains('secondary'));
        }"""), (name, width, 'tabs/logout/nav')
        for modal in page.get_by_role('dialog').all():
            assert modal.evaluate('e => e.scrollWidth <= e.clientWidth + 1'), (name, width, 'dialog')
        # The generated password is memory-only; screenshots contain a neutral mask.
        code = page.locator('.temporary-password')
        if code.count():
            original = code.text_content()
            code.evaluate("e => e.textContent = '••••••••••••••••••••'")
            try:
                page.screenshot(path=str(artifacts / f'{name}-{width}x{height}.png'))
            finally:
                code.evaluate('(e, value) => e.textContent = value', original)
        else:
            page.screenshot(path=str(artifacts / f'{name}-{width}x{height}.png'))
        page.set_viewport_size({'width': 768, 'height': 1024})
        page.wait_for_load_state('networkidle')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (name, 768)
        page.set_viewport_size({'width': width, 'height': height})
        checks.append(f'{name}:{width}')

    navigate(page, '設定')
    page.get_by_role('tab', name='成員', exact=True).click()
    expect(page.locator('.member-row')).to_have_count(3 if width == 1440 else 4)
    capture('members-list')
    page.get_by_role('button', name='新增成員', exact=True).click()
    dialog = page.get_by_role('dialog', name='新增成員', exact=True)
    expect(dialog).to_be_visible()
    username = f'member-{width}'
    dialog.get_by_label('帳號', exact=True).fill(username)
    dialog.get_by_label('顯示名稱', exact=True).fill('隔離行銷成員')
    dialog.get_by_role('radio', name='管理員', exact=True).click()
    expect(dialog.get_by_text('管理員可存取全部品牌', exact=True)).to_be_visible()
    expect(dialog.locator('fieldset')).to_have_count(0)
    dialog.get_by_role('radio', name='行銷', exact=True).click()
    dialog.get_by_label('[隔離驗收] 行銷工作區', exact=True).check()
    capture('members-create')
    dialog.get_by_role('button', name='新增', exact=True).click()
    expect(page.get_by_role('dialog', name='臨時密碼', exact=True)).to_be_visible()
    temporary = SecretStr(page.locator('.temporary-password').text_content())
    assert len(temporary.get_secret_value()) >= 16
    capture('members-password')
    page.get_by_role('button', name='關閉', exact=True).click()
    expect(page.locator('.temporary-password')).to_have_count(0)
    row = page.locator('.member-row').filter(has_text=username)
    row.get_by_role('button', name='編輯').click()
    expect(page.get_by_role('dialog', name='編輯成員', exact=True)).to_be_visible()
    capture('members-edit')
    editor = page.get_by_role('dialog', name='編輯成員', exact=True)
    editor.get_by_role('button', name='停用帳號', exact=True).click()
    confirm = page.get_by_role('dialog').filter(has_text='此成員將立即登出。').last
    expect(confirm).to_be_visible()
    expect(confirm.get_by_role('button', name='取消', exact=True)).to_be_focused()
    confirm.press('Escape')
    expect(editor).to_be_visible()
    expect(page.get_by_role('dialog')).to_have_count(1)
    editor.get_by_role('button', name='重設密碼', exact=True).click()
    expect(page.get_by_role('dialog', name='臨時密碼', exact=True)).to_be_visible()
    temporary = SecretStr(page.locator('.temporary-password').text_content())
    page.get_by_role('button', name='關閉', exact=True).click()
    expect(page.locator('.temporary-password')).to_have_count(0)
    checks.append(f'reset-password-once-and-confirm-escape:{width}')
    # Self-disable must retain the editor and display the backend's Chinese conflict.
    page.locator('.member-row').filter(has_text='admin').get_by_role('button', name='編輯').click()
    page.get_by_role('dialog', name='編輯成員').get_by_role('button', name='停用帳號').click()
    page.get_by_role('dialog').last.get_by_role('button', name='停用帳號').click()
    expect(page.get_by_role('dialog', name='編輯成員').get_by_role('alert')).to_have_text('管理員不可停用自己')
    checks.append(f'self-disable-conflict:{width}')
    page.get_by_role('button', name='取消', exact=True).click()

    admin_cookies = page.context.cookies()
    # Retain an independent admin cookie for the disable request later.
    page.context.clear_cookies()
    page.reload()
    expect(page.get_by_role('button', name='登入工作檯')).to_be_visible()
    page.get_by_label('帳號', exact=True).fill(username)
    page.get_by_label('密碼', exact=True).fill(temporary.get_secret_value())
    page.get_by_role('button', name='登入工作檯').click()
    expect(page.get_by_role('heading', name='請設定新密碼')).to_be_visible()
    expect(page.locator('.sidebar,.mobile-bottom-nav')).to_have_count(0)
    capture('password-required')
    new_password = SecretStr(secrets.token_urlsafe(24))
    page.get_by_label('目前密碼', exact=True).fill(temporary.get_secret_value())
    page.get_by_label('新密碼', exact=True).fill(new_password.get_secret_value())
    page.get_by_label('再次輸入新密碼', exact=True).fill(new_password.get_secret_value())
    page.get_by_role('button', name='變更密碼').click()
    expect(page.locator('.workspace')).to_be_visible()
    # uiorder：只看得到一個品牌的成員，側邊欄與手機都沒有品牌選單，也沒有「品牌工作區」標籤與底部標語。
    expect(page.locator('.brand-picker,.mobile-brand-picker')).to_have_count(0)
    expect(page.locator('.workspace-label')).to_have_count(0)
    expect(page.locator('.sidebar-note')).not_to_contain_text('讓團隊同步掌握')
    navigate(page, '設定')
    expect(page.get_by_role('tablist', name='設定', exact=True).get_by_role('tab')).to_have_text(['我的帳號'])
    expect(page.locator('.my-account')).to_be_visible()
    capture('marketing-settings')
    # Use a separate request context so the member's next UI request detects revocation.
    request = page.context.browser.new_context()
    try:
        request.add_cookies(admin_cookies)
        csrf = request.request.get(origin + '/api/auth/csrf').json()['csrf_token']
        members = request.request.get(origin + '/api/members').json()
        identity = next(member['id'] for member in members if member['username'] == username)
        response = request.request.put(origin + f'/api/members/{identity}/state',
            headers={'Origin': origin, 'X-CSRF-Token': csrf}, data={'active': False})
        assert response.status == 200
    finally:
        request.close()
    page.reload()
    expect(page.get_by_role('button', name='登入工作檯')).to_be_visible()
    assert page.request.get(origin + '/api/auth/me').status == 401
    checks.append(f'disable-revokes-next-request:{width}')
    page.get_by_label('帳號', exact=True).fill('viewer_test')
    page.get_by_label('密碼', exact=True).fill(viewer_password.get_secret_value())
    page.get_by_role('button', name='登入工作檯').click()
    expect(page.locator('.workspace')).to_be_visible()
    navigate(page, '主題發想')
    expect(page.locator('.report-select').first).to_be_visible()
    expect(page.locator('.report-select').first).to_have_attribute('aria-current', 'true')
    expect(page.locator('.ideation-card').first).to_be_visible()
    expect(page.locator('.ideation-form,.idea-card-actions,.idea-select,.report-row .danger')).to_have_count(0)
    for name in ('立即發想', '重新生成', '延伸主題', '產生腳本', '查看腳本', '建立發佈草稿', '開啟發佈草稿', '還原上一版', '刪除'):
        expect(page.get_by_role('button', name=name, exact=True)).to_have_count(0)
    capture('viewer-ideation')
    for size in ({'width': 768, 'height': 1024}, {'width': 390, 'height': 844}):
        page.set_viewport_size(size)
        expect(page.locator('.ideation-card').first).to_be_visible()
        page.wait_for_load_state('networkidle')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.set_viewport_size({'width': width, 'height': height})
    checks.append(f'viewer-readonly-and-widths:{width}')
    # Restore admin for the harness's next viewport and keep passwords out of artifacts.
    page.context.add_cookies(admin_cookies)
    if width == 390:
        admin = page.request.get(origin + '/api/auth/me').json()
        brands = page.request.get(origin + '/api/brands?limit=200').json()
        expanded = brands + [{'id': 10000 + i, 'name': f'隔離品牌 {i}', 'slug': f'isolated-{i}'} for i in range(201 - len(brands))]
        offsets = []
        def brand_page(route):
            offset = int(parse_qs(urlsplit(route.request.url).query).get('offset', ['0'])[0])
            offsets.append(offset)
            route.fulfill(json=expanded[offset:offset + 200])
        page.route('**/api/auth/me', lambda route: route.fulfill(json={**admin, 'brand_ids': [b['id'] for b in expanded]}))
        page.route('**/api/brands?*', brand_page)
        page.reload()
        expect(page.locator('.mobile-brand-picker select option')).to_have_count(202)
        assert offsets == [0, 200]
        expect(page.locator('.mobile-brand-picker select option').last).to_have_text(expanded[-1]['name'])
        page.unroute('**/api/auth/me')
        page.unroute('**/api/brands?*')
        checks.append('complete-brand-menu-across-two-pages')
        page.reload()
        navigate(page, '設定')
        page.get_by_role('tab', name='成員', exact=True).click()
        page.locator('.member-row').filter(has_text='admin').get_by_role('button', name='編輯').click()
        page.get_by_role('dialog', name='編輯成員').get_by_role('button', name='重設密碼').click()
        expect(page.get_by_role('dialog', name='臨時密碼')).to_be_visible()
        assert page.request.get(origin + '/api/auth/me').status == 401
        expect(page.locator('.temporary-password')).to_be_visible()
        page.get_by_role('button', name='關閉', exact=True).click()
        expect(page.locator('.temporary-password')).to_have_count(0)
        expect(page.get_by_role('button', name='登入工作檯')).to_be_visible()
        checks.append('self-reset-retains-once-dialog-after-logout')


if __name__ == '__main__':
    main(exercise=check_members)

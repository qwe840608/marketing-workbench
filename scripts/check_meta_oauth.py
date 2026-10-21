"""OAuth browser flow through an isolated backend and MockTransport; no external requests."""

import os
import json
from urllib.parse import parse_qs, urlsplit

from browser_harness import REPO, main
from playwright.sync_api import expect
from ui_navigation import navigate


def exercise(page, unused, shot, checks):
    from sqlalchemy import delete
    from app.config import Settings
    from app.db import build_engine, session_factory
    from app.models import OAuthConnection, OAuthState, PlatformCredential

    settings = Settings(_env_file=None)
    for path in (settings.database_path, settings.export_root):
        assert path.resolve().is_relative_to((REPO / '.runtime').resolve())
    engine = build_engine(settings)
    try:
        with session_factory(engine).begin() as session:
            session.execute(delete(OAuthState))
            session.execute(delete(OAuthConnection))
            session.execute(delete(PlatformCredential).where(PlatformCredential.provider.in_([
                'META_PAGE_ID', 'META_PAGE_ACCESS_TOKEN', 'META_USER_ACCESS_TOKEN', 'META_IG_ACCOUNT_ID',
                'THREADS_USER_ID', 'THREADS_ACCESS_TOKEN'])))
    finally:
        engine.dispose()
    local = page.evaluate("location.origin")
    internal = "https://office.example.test"
    folder = REPO / ".runtime/metaoauth-screens/after"
    folder.mkdir(parents=True, exist_ok=True)
    size = page.viewport_size
    names = []

    def capture(name, card=None):
        if card is not None:
            card.scroll_into_view_if_needed()
        page.wait_for_load_state("networkidle")
        page.evaluate("async () => { await document.fonts.ready; await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); }")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (name, size)
        page.screenshot(path=str(folder / f'{name}-{size["width"]}x{size["height"]}.png'))
        for width, height in [(768, 1024), (390, 844), (1440, 900)]:
            page.set_viewport_size({"width": width, "height": height})
            page.wait_for_load_state("networkidle")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (name, width)
        page.set_viewport_size(size)
        names.append(name)

    navigate(page, "平台連線")
    meta = page.locator('.connection-card:has(#connection-meta)')
    threads = page.locator('.connection-card:has(#connection-threads)')
    expect(meta.locator('.oauth-origin')).to_contain_text('請用內部 https 網址')
    expect(meta.get_by_role('button', name='連結 Meta 帳號')).to_be_disabled()
    expect(meta.locator('.oauth-origin a')).to_have_attribute('href', internal)
    capture('unlinked', meta)
    # An internal HTTPS test origin is fulfilled locally; no HTTPS socket is opened.
    cookies = page.context.cookies(local)
    for cookie in cookies:
        page.context.add_cookies([{"name": cookie["name"], "value": cookie["value"],
            "domain": "office.example.test", "path": "/", "secure": True, "httpOnly": True}])

    def internal_route(route):
        parts = urlsplit(route.request.url)
        target_url = local + parts.path + ("?" + parts.query if parts.query else "")
        if parts.path.endswith('/callback'):
            # 真實平台跨站導回時，SameSite=Strict 的登入 cookie 不會送出：
            # 以不帶任何 cookie 的獨立請求呼叫回呼，避免瀏覽器內容自動附上登入狀態。
            import urllib.error
            import urllib.request

            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *args, **kwargs):
                    return None

            try:
                urllib.request.build_opener(NoRedirect).open(target_url, timeout=15)
                raise AssertionError('callback must redirect')
            except urllib.error.HTTPError as redirect:
                assert redirect.code == 303, redirect.code
                landing = redirect.headers['location']
            assert 'oauth_pending=' in landing or 'oauth_result=' in landing, landing
            route.fulfill(content_type='text/html',
                          body='<script>location.replace(' + json.dumps(internal + landing) + ')</script>')
            return
        response = route.fetch(url=target_url,
            headers={**route.request.headers, "host": urlsplit(local).netloc}, max_redirects=0)
        if response.status in {302, 303}:
            target = response.headers['location']
            if target.startswith('/'):
                target = internal + target
            route.fulfill(content_type='text/html', body='<script>location.replace(' + json.dumps(target) + ')</script>')
        else:
            route.fulfill(response=response)

    page.route(internal + '/**', internal_route)

    def authorization(route):
        args = parse_qs(urlsplit(route.request.url).query)
        assert args['response_type'] == ['code']
        callback = args['redirect_uri'][0]
        assert callback.startswith(internal + '/api/oauth/')
        target = callback + '?state=' + args['state'][0] + '&code=isolated-oauth-code'
        route.fulfill(content_type='text/html', body='<script>location.replace(' + json.dumps(target) + ')</script>')

    page.route('https://www.facebook.com/**', authorization)
    page.route('https://threads.net/**', authorization)
    page.goto(internal + '/?view=settings&settings_tab=connections')
    expect(meta.get_by_role('button', name='連結 Meta 帳號')).to_be_enabled()
    meta.get_by_role('button', name='連結 Meta 帳號').click()
    expect(meta.get_by_role('button', name='使用這個粉專')).to_be_visible()
    expect(meta.get_by_label('粉絲專頁')).to_have_value('100')
    capture('page-selection', meta)
    meta.get_by_label('粉絲專頁').select_option('101')
    meta.get_by_role('button', name='使用這個粉專').click()
    expect(meta.locator('.oauth-account')).to_contain_text('隔離粉專 2')
    expect(meta.locator('.oauth-account .status-badge.ready')).to_contain_text('已連結')
    capture('linked', meta)
    # Force-check response deliberately models a declined publication permission.
    def missing(route):
        response = route.fetch(url=local + '/api/oauth/status?force=true',
            headers={**route.request.headers, 'host': urlsplit(local).netloc})
        body = response.json()
        status = body['platforms']['meta']
        status.update(state='failed', missing=['pages_manage_posts'])
        status['granted'] = [s for s in status['granted'] if s != 'pages_manage_posts']
        route.fulfill(json=body)

    page.route('**/api/oauth/status?force=true', missing)
    meta.get_by_role('button', name='測試連線').click()
    expect(meta.locator('.oauth-permissions')).to_contain_text('pages_manage_posts')
    expect(meta.get_by_role('button', name='重新連結')).to_be_visible()
    capture('missing-permissions', meta)
    page.unroute('**/api/oauth/status?force=true', missing)
    threads.get_by_role('button', name='連結 Threads 帳號').click()
    expect(threads.locator('.oauth-account')).to_contain_text('isolated_threads')
    expect(threads.locator('.oauth-account .status-badge.ready')).to_contain_text('已連結')
    expect(threads.locator('.oauth-permissions')).to_have_count(0)
    expect(threads.get_by_role('button', name='重新連結')).to_have_class('primary')
    capture('threads-linked', threads)
    # 數據權限之前連結的既有 Threads：連結狀態與發佈就緒不變，只提示重新連結以取得成效與回覆。
    from sqlalchemy import select
    from app.services import oauth

    engine = build_engine(settings)
    try:
        with session_factory(engine).begin() as session:
            row = session.scalar(select(OAuthConnection).where(OAuthConnection.platform == 'threads'))
            row.granted_scopes = list(oauth.THREADS_PUBLISH_SCOPES)
            row.cache_json, row.checked_at = {}, None
    finally:
        engine.dispose()
    threads.get_by_role('button', name='測試連線').click()
    hint = threads.locator('.oauth-permissions')
    expect(hint).to_have_text('需要重新連結以取得數據與回覆權限')
    expect(hint).to_have_class('notice warning oauth-permissions')
    expect(threads.locator('.oauth-account .status-badge.ready')).to_contain_text('已連結')
    expect(threads.get_by_role('button', name='重新連結')).to_have_class('secondary')
    expect(meta.locator('.oauth-permissions')).to_have_count(0)
    capture('threads-data-relink', threads)
    threads.get_by_role('button', name='重新連結').click()
    expect(threads.locator('.oauth-account')).to_contain_text('isolated_threads')
    expect(threads.locator('.oauth-permissions')).to_have_count(0)
    expect(threads.get_by_role('button', name='重新連結')).to_have_class('primary')
    capture('threads-data-relinked', threads)
    for card, platform in [(meta, 'meta'), (threads, 'threads')]:
        # 回呼網址改在站內「設定教學」視窗內顯示與複製（原收合的首次設定步驟已移除）。
        expect(card.locator('details.oauth-setup')).to_have_count(0)
        card.get_by_role('button', name='設定教學', exact=True).click()
        dialog = page.get_by_role('dialog')
        expect(dialog.locator('.guide-copy code').first).to_have_text(internal + f'/api/oauth/{platform}/callback')
        expect(dialog.locator('.guide-copy button').first).to_have_class('secondary')
        if platform == 'meta':
            capture('setup-steps', meta)
        page.keyboard.press('Escape')
        expect(dialog).to_have_count(0)
    assert page.evaluate("() => !JSON.stringify([localStorage,sessionStorage]).includes('isolated-oauth-token')")
    checks.extend(names)


if __name__ == '__main__':
    os.environ['METAOAUTH_CHECK'] = '1'
    main(exercise=exercise)

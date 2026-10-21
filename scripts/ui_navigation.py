"""Use the same visible navigation controls as a desktop or mobile user."""

import re

from playwright.sync_api import expect


def navigation_button(page, label):
    mobile = page.viewport_size["width"] < 600
    label = "設定" if label in ("AI 設定", "平台連線", "訊息分類", "工作區設定") else label
    selector = ".mobile-bottom-nav" if mobile else ".workspace-nav"
    return page.locator(selector).get_by_role("button", name=re.compile("^" + label))


def open_settings(page):
    navigation_button(page, "設定").click()
    expect(page.get_by_role("tablist", name="設定", exact=True)).to_be_visible()


def navigate(page, label, *, advanced=True):
    navigation_button(page, label).click()
    tab = {"AI 設定": "AI", "平台連線": "平台連線", "訊息分類": "訊息分類", "工作區設定": "工作區"}.get(label)
    if tab:
        page.get_by_role("tablist", name="設定", exact=True).get_by_role("tab", name=tab, exact=True).click()
    if label == "工作區設定" and advanced:
        groups = page.locator("details.workspace-group")
        expect(groups).to_have_count(5)
        for details in groups.all():
            if details.get_attribute("open") is None:
                details.locator(":scope > summary").click()
            expect(details).to_have_attribute("open", "")
        # Opening later groups scrolls the shared settings container. Restore the
        # common page origin before the caller measures headers and control sizes.
        page.locator('.settings-hub').evaluate('e => e.scrollTop = 0')


BRANDS_ROUTE = '**/api/brands?*'


def two_brands(page):
    """隔離資料庫只有一個品牌；需要「全部可見品牌」情境時，只在瀏覽器端替身多加第二個品牌（不寫入資料庫）。"""
    def handler(route):
        rows = route.fetch().json()
        route.fulfill(json=[*rows, {**rows[0], 'id': 99999, 'name': '隔離第二品牌', 'slug': 'second-isolated'}] if rows else rows)
    if getattr(page, '_two_brands', False):
        return False
    page.route(BRANDS_ROUTE, handler)
    page._two_brands = True
    return True


def one_brand(page):
    page.unroute(BRANDS_ROUTE)
    page._two_brands = False


def brand_picker(page):
    if page.viewport_size["width"] < 600:
        open_settings(page)
        return page.locator(".mobile-brand-picker select")
    return page.locator(".brand-picker select")

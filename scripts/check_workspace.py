"""E 組：隔離資料庫、明確的 SDK 替身；不連接平台或雲端模型。"""

from runtime_tmp import (
    launch_chromium,
    cleanup,
    output_dir,
    runtime_check,
    stop_process,
    temporary_dir,
)

from ui_navigation import navigate, one_brand, two_brands

import json
import os
import secrets
import sys
from datetime import timedelta

from browser_harness import REPO, launch_server, run_uvicorn, seed_records
from ports import browser_port


def serve():
    from app.config import Settings
    from app.main import create_app
    from app.services import autostart, jev
    from app.services.ai import providers

    def response(_url, _key, payload, _timeout):
        answers = {}
        for key, q in payload["questions"].items():
            if q["type"] == "noul":
                answers[key] = {"type": "noul", "noul": 0.01}
            elif q["type"] == "choice":
                choice = "model_question" if key == "intent" else "none"
                answers[key] = {
                    "type": "choice",
                    "choice": choice,
                    "confidence": 0.96,
                    "probabilities": {c: float(c == choice) for c in q["criteria"]},
                }
            else:
                score = 0 if key == "urgency" else 2
                answers[key] = {
                    "type": "score",
                    "score": score,
                    "confidence": 0.95,
                    "probabilities": {str(i): float(i == score) for i in range(5)},
                    "legend": {str(i): c for i, c in enumerate(q["criteria"])},
                }
        return (
            200,
            {
                "model": "browser-substitute",
                "answers": answers,
                "usage": {"input_tokens": 100, "output_tokens": 20},
            },
            0,
        )

    autostart.execute = lambda *args: autostart.state()
    jev.post_json = response
    providers.call_api = lambda *a: providers.Result(
        "[瀏覽器驗收] 請提供服務照片，專人將協助確認需求類型與服務方式。",
        "browser-substitute",
        100,
        30,
    )
    run_uvicorn(create_app(Settings(_env_file=sys.argv[2])), sys.argv[3])


def open_info(page):
    for selector in (".mobile-info", ".info-summary"):
        button = page.locator(selector)
        if button.is_visible() and button.get_attribute("aria-expanded") != "true":
            button.click()


def close_info(page):
    for selector in (".mobile-info", ".info-summary"):
        button = page.locator(selector)
        if button.is_visible() and button.get_attribute("aria-expanded") == "true":
            button.click()


def check_settings_tabs(page):
    """設定分頁大小一致（使用者 2026-10-14：手機上「AI」分頁太小）：寬度差 ≤1px、文字不被裁切。"""
    from playwright.sync_api import expect
    tabs = page.get_by_role("tablist", name="設定", exact=True).get_by_role("tab")
    expect(tabs).to_have_count(6)
    for width, height in [(1440, 900), (390, 844)]:
        page.set_viewport_size({"width": width, "height": height})
        sizes = tabs.evaluate_all(
            "els => els.map(e => [e.getBoundingClientRect().width, e.scrollWidth, e.clientWidth])"
        )
        widths = [w for w, _, _ in sizes]
        assert max(widths) - min(widths) <= 1, (width, sizes)
        assert all(scroll <= client + 1 for _, scroll, client in sizes), (width, sizes)
        list_box = page.get_by_role("tablist", name="設定", exact=True)
        assert list_box.evaluate("e => e.scrollWidth <= e.clientWidth + 1"), (width, sizes)
    page.set_viewport_size({"width": 1440, "height": 900})


def check_classification_settings(page):
    from playwright.sync_api import expect
    page.set_viewport_size({"width": 1440, "height": 900})
    navigate(page, "訊息分類")
    check_settings_tabs(page)
    expect(page.locator(".intent-notes input")).to_have_count(9)
    expect(page.locator(".settings-page .settings-section h2")).to_have_text(["類別說明"])
    expect(page.get_by_label("主管帳號")).to_have_count(0)
    expect(page.get_by_role("button", name="儲存並重算分流")).to_have_count(0)
    notes = page.locator(".intent-notes")
    notes.get_by_label("價格詢問", exact=True).fill("  剪輯費用、拍攝報價  ")
    with page.expect_response(lambda r: "/api/classifications/intents?" in r.url and r.request.method == "PUT") as saved_notes:
        notes.get_by_role("button", name="儲存", exact=True).click()
    assert saved_notes.value.ok and saved_notes.value.json()["price"] == "剪輯費用、拍攝報價"
    expect(notes.get_by_role("status")).to_have_text("類別說明已儲存")
    expect(notes.get_by_label("價格詢問", exact=True)).to_have_value("剪輯費用、拍攝報價")
    # 真正更新隔離 API 版本，驗證舊畫面的 409 與未儲存文字保留。
    latest = saved_notes.value.json()
    headers = saved_notes.value.request.all_headers()
    assert page.request.put(
        saved_notes.value.url, data={**latest, "other": "致謝"},
        headers={key: headers[key] for key in ("origin", "x-csrf-token")},
    ).ok
    notes.get_by_label("價格詢問", exact=True).fill("未儲存的補充")
    notes.get_by_role("button", name="儲存", exact=True).click()
    expect(notes.get_by_role("alert")).to_have_text("設定已更新，請重新整理")
    expect(notes.get_by_label("價格詢問", exact=True)).to_have_value("未儲存的補充")
    for width, height in [(1440, 900), (390, 844)]:
        page.set_viewport_size({"width": width, "height": height})
        notes.evaluate("e => e.scrollIntoView({block: 'start'})")
        expect(notes.get_by_label("其他", exact=True)).to_be_in_viewport()
        for label in notes.locator(".intent-notes-fields label").all():
            assert label.evaluate("e => getComputedStyle(e).display") == "grid"
            assert len(label.evaluate("e => getComputedStyle(e).gridTemplateColumns.split(' ')")) == 2
        assert notes.evaluate("e => e.scrollWidth <= e.clientWidth")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        details = output_dir() / "details"
        details.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(details / f"classification-notes-{width}x{height}.png"))
    page.set_viewport_size({"width": 1440, "height": 900})
    user = page.request.get(page.evaluate("location.origin") + "/api/auth/me").json()
    page.route("**/api/auth/me", lambda route: route.fulfill(json={**user, "role": "viewer"}))
    page.reload()
    expect(page.get_by_role('tablist', name='設定', exact=True).get_by_role('tab')).to_have_text(['我的帳號'])
    expect(page.locator('.my-account')).to_be_visible()
    expect(page.locator('.intent-notes input')).to_have_count(0)
    expect(page.locator('.my-account input')).to_have_count(3)
    assert all(control.is_enabled() for control in page.locator('.my-account input').all())
    expect(page.locator('.intent-notes button')).to_have_count(0)
    page.unroute("**/api/auth/me")
    page.reload()


def open_system(page):
    # uiorder：開機自動啟動已移進「系統」群組，群組預設收合，操作前先展開。
    details = page.locator('details.workspace-group[data-group=system]')
    if details.get_attribute('open') is None:
        details.locator(':scope > summary').click()
    return details


def check_autostart(page):
    from playwright.sync_api import expect

    output = output_dir()
    output.mkdir(parents=True, exist_ok=True)
    state = {"enabled": False, "supported": True, "task_name": "MWB-AutoStart", "code": None}
    mode = {"value": "ok"}
    pending = []
    requests = []

    def route(r):
        if r.request.method == 'PUT':
            requests.append(r.request.post_data_json)
            assert set(requests[-1]) == {'enabled'}
            if mode['value'] == 'busy':
                pending.append(r)
                return
            if mode['value'] == 'failed':
                r.fulfill(json={**state, 'code': 'autostart_conflict'})
                return
            if mode['value'] == 'network':
                r.abort()
                return
            state['enabled'] = requests[-1]['enabled']
        r.fulfill(json=state)

    page.route('**/api/workspace/autostart', route)
    page.route('**/api/workspace/status', lambda r: r.fulfill(json={'autostart': state}))
    navigate(page, '工作區設定')
    system = open_system(page)
    box = page.get_by_label('登入 Windows 後自動啟動工作檯', exact=True)
    card = page.locator('.autostart-settings')
    # uiorder：卡片在「系統」群組內、收訊健康監測之前；不再是工作區最上方獨立卡片。
    expect(page.locator('.general-settings > .autostart-settings')).to_have_count(0)
    expect(system.locator('.workspace-group-content > .autostart-settings')).to_have_count(1)
    assert system.locator('.workspace-group-content > section').evaluate_all(
        "els => els.map(e => e.classList.contains('autostart-settings') ? 'autostart' : e.classList.contains('receive-health') ? 'receive' : 'other')"
    ) == ['autostart', 'receive']
    expect(box).to_be_enabled()
    expect(box).not_to_be_checked()

    def capture(name):
        expect(page.locator('.general-settings .brand-toolbar')).to_have_count(0)
        expect(page.get_by_label('上班時間', exact=True)).to_have_count(0)
        for width, height in [(1440, 900), (390, 844)]:
            page.set_viewport_size({'width': width, 'height': height})
            page.locator('.general-settings').evaluate('e => e.scrollTop = 0')
            page.evaluate('document.fonts.ready')
            assert page.locator('.general-settings').evaluate('e => e.scrollWidth <= e.clientWidth')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            # uiorder：已在群組卡內，改成小節（無自己的卡片外框），標題為 h3。
            assert card.evaluate("e => !e.classList.contains('section-card') && e.matches('.workspace-group-content > .workspace-subsection')")
            expect(card.locator('h3')).to_have_text('開機自動啟動')
            expect(card.locator('input')).to_have_count(1)
            expect(card.locator('.autostart-row label > input[type=checkbox]')).to_have_count(1)
            expect(card.locator('button')).to_have_count(0)
            # 小節貼齊群組內容區（扣除左右內距）。
            a = card.bounding_box()
            b = system.locator('.workspace-group-content').evaluate(
                "e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e), l = parseFloat(s.paddingLeft), rr = parseFloat(s.paddingRight); return { x: r.x + l, width: r.width - l - rr }; }")
            assert abs(a['x'] - b['x']) <= 1 and abs(a['width'] - b['width']) <= 1, (a, b)
            assert card.evaluate("e => getComputedStyle(e).fontFamily === getComputedStyle(document.body).fontFamily")
            page.screenshot(path=str(output / f'workspace-{name}-{width}x{height}.png'))
        page.set_viewport_size({'width': 1440, 'height': 900})

    capture('off')
    box.click()
    expect(box).to_be_checked()
    expect(box).to_be_enabled()
    capture('on')
    box.click()
    expect(box).not_to_be_checked()
    mode['value'] = 'busy'
    box.click()
    expect(box).to_be_disabled()
    expect(card.get_by_role('status')).to_have_text('處理中…')
    capture('busy')
    assert len(pending) == 1
    pending.pop().fulfill(json=state)
    expect(box).to_be_enabled()
    mode['value'] = 'failed'
    box.click()
    expect(card.get_by_role('alert')).to_contain_text('同名排程的設定不同')
    expect(box).not_to_be_checked()
    capture('failed')
    page.reload()
    open_system(page)
    expect(box).to_be_enabled()
    mode['value'] = 'network'
    # A lost PUT response must restore the subsequently queried real state.
    state['enabled'] = True
    box.click()
    expect(card.get_by_role('alert')).to_contain_text('無法更新或取得')
    expect(box).to_be_checked()
    state.update(supported=False, enabled=False, code='autostart_unsupported')
    page.reload()
    open_system(page)
    expect(card.get_by_role('status')).to_have_text('僅支援 Windows')
    expect(box).to_be_disabled()
    state.update(supported=True, enabled=True, code=None)
    user = page.request.get(page.evaluate('location.origin') + '/api/auth/me').json()
    for role in ('marketing', 'viewer'):
        page.route('**/api/auth/me', lambda r: r.fulfill(json={**user, 'role': role}))
        page.reload()
        expect(page.get_by_role('tablist', name='設定', exact=True).get_by_role('tab')).to_have_text(['我的帳號'])
        expect(page.locator('.autostart-settings')).to_have_count(0)
        expect(page.locator('.my-account')).to_be_visible()
        page.unroute('**/api/auth/me')
    assert requests[:3] == [{'enabled': True}, {'enabled': False}, {'enabled': True}]
    page.unroute('**/api/workspace/autostart')
    page.unroute('**/api/workspace/status')
    page.reload()
    navigate(page, '工作區設定')
    open_system(page)
    expect(box).to_be_enabled()


def check_obsidian(page, settings, checks):
    from playwright.sync_api import expect

    navigate(page, "工作區設定")
    section = page.get_by_role("region", name="Obsidian 留言資料夾", exact=True)
    field = section.get_by_label("Obsidian 留言資料夾", exact=True)
    expect(field).to_have_value(str(settings.obsidian_root))
    root = settings.database_path.parent / "obsidian-saved"
    field.fill(str(root))
    section.get_by_role("button", name="儲存 Obsidian 資料夾", exact=True).click()
    expect(section.get_by_role("status")).to_have_text("已儲存，寫入檢查通過")
    page.reload()
    navigate(page, "工作區設定")
    expect(field).to_have_value(str(root))
    section.get_by_role("button", name="立即同步到 Obsidian").click()
    expect(section.get_by_role("status")).to_contain_text("已同步")
    assert list(root.rglob("貼文.md"))
    assert root.resolve().is_relative_to((REPO / ".runtime").resolve())
    for width, height in ((1440, 900), (390, 844)):
        page.set_viewport_size({"width": width, "height": height})
        page.wait_for_load_state("networkidle")
        section.scroll_into_view_if_needed()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        screens = output_dir()
        screens.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(screens / f"settings-data-{width}x{height}.png"))
    page.set_viewport_size({"width": 1440, "height": 900})
    # 手機版控制列依 matchMedia 重繪；等它消失再繼續，避免後續「登出」同時命中兩顆。
    expect(page.locator(".mobile-logout")).to_have_count(0)
    checks.append("obsidian-path-persist-permission-sync-responsive")


@runtime_check
def main(extra_checks=None):
    from alembic import command
    from alembic.config import Config
    from playwright.sync_api import expect, sync_playwright
    from sqlalchemy import select

    from app.config import Settings
    from app.db import build_engine, session_factory
    from app.models import (
        Account,
        Brand,
        Contact,
        Message,
        MetricSnapshot,
        Post,
        Setting,
        Thread,
    )
    from app.models.base import utc_now

    folder = temporary_dir()
    port = browser_port()
    origin = f"http://127.0.0.1:{port}"
    password, key = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    temporary = {
        "DATABASE_PATH": str(folder / "mwb.db"),
        "LOG_PATH": str(folder / "backend.jsonl"),
        "EXPORT_ROOT": str(folder / "export"),
        "OBSIDIAN_ROOT": str(folder / "obsidian"),
        "APP_ORIGIN": origin,
        "ALLOWED_HOSTS": '["127.0.0.1"]',
        "SESSION_COOKIE_SECURE": "false",
        "ADMIN_INITIAL_PASSWORD": password,
        "MARKETING_TEST_INITIAL_PASSWORD": password,
        "VIEWER_TEST_INITIAL_PASSWORD": password,
        "INGEST_API_KEY": key,
        "COMMENTS_WAKE_ENABLED": "false",
        "SCHEDULER_ENABLED": "false",
        "EXPORT_WORKER_ENABLED": "false",
        "RECEIVE_HEALTH_WORKER_ENABLED": "false",
        "RECEIVE_HEALTH_ALERTS_ENABLED": "false",
        "GEMINI_API_KEY": key,
        "GEMINI_MODEL": "browser-substitute",
        "JEV_API_KEY": key,
        "NOTIFY_LINE_CHANNEL_ACCESS_TOKEN": key,
        "NOTIFY_LINE_GROUP_ID": "C" + "a" * 32,
    }
    env_path = folder / ".env"
    env_path.write_text("\n".join(f"{k}='{v}'" for k, v in temporary.items()), encoding="utf-8")
    os.environ.update(temporary)
    settings = Settings(_env_file=None)
    command.upgrade(Config(str(REPO / "backend" / "alembic.ini")), "head")
    engine = build_engine(settings)
    cleanup(engine.dispose)
    now = utc_now()
    with session_factory(engine).begin() as session:
        seed_records(session, settings, include_content=False)
        brand = session.scalar(select(Brand).where(Brand.slug == "TEST"))
        session.add(Setting(
            key="notification.discovered_groups",
            value_json={"C" + "a" * 32: {}},
        ))
        for platform, name, age in [("line", "E組驗收用戶", 1), ("facebook", "即將逾時用戶", 21)]:
            account = Account(
                brand_id=brand.id,
                platform=platform,
                external_id="e-" + platform,
                name="[瀏覽器驗收] " + platform,
            )
            session.add(account)
            session.flush()
            contact = Contact(
                brand_id=brand.id, platform=platform, external_id=name, display_name=name
            )
            session.add(contact)
            session.flush()
            thread = Thread(
                brand_id=brand.id,
                account_id=account.id,
                contact_id=contact.id,
                kind="dm",
                external_id=name,
                last_inbound_at=now - timedelta(hours=age),
            )
            session.add(thread)
            session.flush()
            session.add(
                Message(
                    thread_id=thread.id,
                    external_id=name,
                    direction="in",
                    author_type="fan",
                    text="[瀏覽器驗收] 不確定服務需求類型，可以提供照片嗎？",
                    sent_at=thread.last_inbound_at,
                )
            )
            if platform == "facebook":
                post = Post(
                    account_id=account.id,
                    external_id="e-post",
                    caption="[瀏覽器驗收] 服務內容的數據變化",
                    media_type="image",
                    # Keep the ranked fixture in this week at the Monday boundary.
                    published_at=now,
                )
                session.add(post)
                session.flush()
                for i, reach in enumerate([10, None, 35, 50]):
                    session.add(
                        MetricSnapshot(
                            post_id=post.id,
                            captured_at=now - timedelta(minutes=40 - 10 * i),
                            reach=reach,
                            views=20 * i,
                            comments=i,
                        )
                    )
    engine.dispose()
    server = launch_server(folder, origin, script=__file__, args=[env_path, port])
    try:
        with sync_playwright() as pw:
            browser = launch_chromium(pw)
            page = browser.new_page(viewport={"width": 1440, "height": 980})
            errors, checks = [], []
            page.on("pageerror", lambda e: errors.append(type(e).__name__))

            def capture(name):
                page.wait_for_load_state("networkidle")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), name
                overflow = page.evaluate("""() => [...document.querySelectorAll('*')].filter(e => {
                    const s = getComputedStyle(e), r = e.getBoundingClientRect();
                    return r.width > 0 && r.height > 0 && ['auto','scroll'].includes(s.overflowX)
                        && e.scrollWidth > e.clientWidth + 2;
                }).map(e => e.className)""")
                assert not overflow, (name, overflow)
                page.screenshot(path=str(output_dir() / (name + ".png")), full_page=True)
                checks.append(name)

            def both(name):
                capture(name + "-desktop")
                page.set_viewport_size({"width": 390, "height": 844})
                capture(name + "-mobile")
                page.set_viewport_size({"width": 1440, "height": 980})
                expect(page.locator('.mobile-logout')).to_have_count(0)

            # uiorder：儀表板／貼文數據的「全部可見品牌」情境需要多品牌；用瀏覽器端替身，設定頁前再還原成單一品牌。
            two_brands(page)
            page.goto(origin)
            expect(page.get_by_role("heading", name="歡迎回來")).to_be_visible()
            both("login")
            page.get_by_label("帳號", exact=True).fill("admin")
            page.get_by_label("密碼", exact=True).fill(password)
            page.get_by_role("button", name="登入工作檯").click()
            page.get_by_role("button", name="儀表板", exact=True).click()
            expect(page.locator(".dashboard-kpis")).to_contain_text("尚無資料")
            expect(page.locator(".ranked-post")).to_have_count(2)
            both("dashboard")
            page.get_by_role("combobox", name="目前品牌", exact=True).select_option("1")
            baseline = os.environ.get("UI_P1_2_BASELINE") == "1"
            if not baseline:
                page.get_by_role("button", name="匯出報表", exact=True).click()
            report = page.locator(".report-export") if baseline else page.get_by_role("dialog", name="匯出報表", exact=True)
            start = report.get_by_label("開始日期").input_value()
            end = report.get_by_label("結束日期").input_value()
            with page.expect_request("**/api/exports/report/docx") as request:
                with page.expect_download() as download:
                    report.get_by_role("button", name="下載 Word 報表 ↓", exact=True).click()
            assert request.value.post_data_json == {"brand_id": 1, "start": start, "end": end}
            assert download.value.suggested_filename == f"營運報表_{start}_{end}.docx"
            download.value.save_as(folder / "report.docx")
            if not baseline:
                report.get_by_role("button", name="關閉", exact=True).click()
            page.get_by_role("combobox", name="目前品牌", exact=True).select_option("")
            expect(page.locator('.stage-bars')).to_have_count(0)
            expect(page.locator('.intent-bars')).to_be_visible()
            page.get_by_role("button", name="貼文數據", exact=True).click()
            page.locator(".post-card").first.click()
            expect(page.locator(".chart-point")).to_have_count(3)
            expect(page.locator(".chart-line")).to_have_count(2)
            both("posts-chart")
            page.locator(".metric-chart").screenshot(path=str(output_dir() / "curve-desktop.png"))
            page.set_viewport_size({"width": 390, "height": 844})
            page.locator(".metric-chart").screenshot(path=str(output_dir() / "curve-mobile.png"))
            page.set_viewport_size({"width": 1440, "height": 980})
            page.get_by_role("tablist", name="曲線指標", exact=True).get_by_role("tab", name="收藏", exact=True).click()
            expect(page.locator(".metric-chart")).to_contain_text("尚無「收藏」的有效快照")
            one_brand(page)
            page.reload()
            expect(page.locator(".brand-picker,.mobile-brand-picker")).to_have_count(0)
            for label, heading, name in [
                ("訊息分類", "設定", "classification"),
                ("AI 設定", "設定", "ai-settings"),
            ]:
                navigate(page, label)
                expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()
                both(name)
            navigate(page, "工作區設定")
            expect(page.get_by_role("heading", name="設定", exact=True)).to_be_visible()
            # 品牌選擇可見；自動啟動在收合的系統群組內；進階預設收合，重整後亦相同。
            page.reload()
            groups = page.locator('details.workspace-group')
            expect(groups).to_have_count(5)
            assert groups.evaluate_all('''groups => groups.every(g =>
                g.matches('.section-card') && g.querySelector(':scope > summary').closest('.section-card') === g
                && !g.querySelector('.section-card') && [...g.querySelectorAll('.workspace-group-content > section')].every(s => s.querySelector(':scope > h3')))
            '''), 'Workspace group headings and subsections share one card'
            expect(groups.locator(':scope > summary')).to_have_text(['品牌範本', '主題發想', '資料', '通知', '系統'])
            expect(page.locator('details.workspace-group[open]')).to_have_count(0)
            details = page.locator('details.workspace-group[data-group=data]')
            # uiorder：工作區不再有自己的「目前品牌」選單。
            expect(page.locator('.general-settings .brand-toolbar')).to_have_count(0)
            # uiorder：開機自動啟動在收合的「系統」群組內，展開前不可見；群組順序以 summary 為準。
            expect(page.locator('.autostart-settings')).not_to_be_visible()
            assert page.locator('details.workspace-group[data-group=system] .autostart-settings').count() == 1
            expect(page.get_by_label('上班時間', exact=True)).to_have_count(0)
            details.locator(':scope > summary').click()
            expect(details).to_have_attribute('open', '')
            expect(page.locator('details.workspace-group[open]')).to_have_count(1)
            navigate(page, '工作區設定')
            page.get_by_label("匯出目錄", exact=True).fill(str(folder / "export-check"))
            export_section = page.locator('.settings-section').filter(has=page.get_by_role('heading', name='匯出資料夾', exact=True))
            export_section.get_by_role("button", name="儲存並檢查寫入權限", exact=True).click()
            expect(page.get_by_role('status').filter(has_text='匯出目錄已儲存，寫入檢查通過')).to_be_visible()
            page.get_by_role("button", name="立即同步 Markdown", exact=True).click()
            expect(page.locator(".export-status")).not_to_contain_text("等待首次匯出")
            page.locator(".general-settings").evaluate("el => el.scrollTop = 0")
            both("workspace-settings")
            notification_panel = page.locator(".settings-section").filter(
                has=page.get_by_role("heading", name="LINE 群組通知", exact=True)
            )
            expect(page.get_by_label("品牌通知", exact=True)).to_be_disabled()
            page.get_by_label("此品牌通知群組").select_option("C" + "a" * 32)
            expect(page.get_by_label("品牌通知", exact=True)).to_be_enabled()
            page.get_by_label("品牌通知", exact=True).select_option("on")
            page.get_by_label("公開聲譽風險門檻（0–1）", exact=True).fill("0.55")
            page.get_by_role("button", name="儲存通知政策", exact=True).click()
            expect(notification_panel.get_by_role("status")).to_contain_text("通知政策已儲存")
            page.reload()
            navigate(page, "工作區設定")
            expect(page.get_by_label("此品牌通知群組")).to_have_value("C" + "a" * 32)
            expect(page.get_by_label("品牌通知", exact=True)).to_have_value("on")
            expect(page.get_by_label("公開聲譽風險門檻（0–1）", exact=True)).to_have_value("0.55")
            page.get_by_label("公開聲譽風險門檻（0–1）", exact=True).scroll_into_view_if_needed()
            both("notification-settings")
            check_classification_settings(page)
            if not os.environ.get('AUTOSTART_BASELINE'):
                check_autostart(page)
            check_obsidian(page, settings, checks)
            if extra_checks:
                extra_checks(page, settings, folder, checks)
            page.get_by_role("button", name="登出", exact=True).click()
            page.get_by_label("帳號", exact=True).fill("viewer_test")
            page.get_by_label("密碼", exact=True).fill(password)
            page.get_by_role("button", name="登入工作檯").click()
            # uiorder：只看得到一個品牌，沒有品牌選單。
            expect(page.locator(".brand-picker,.mobile-brand-picker")).to_have_count(0)
            # 重新登入後停留的頁面取決於前面的額外檢查，明確切到工作區分頁再驗證。
            navigate(page, "設定")
            expect(page.get_by_role('tablist', name='設定', exact=True).get_by_role('tab')).to_have_text(['我的帳號'])
            expect(page.locator('.my-account')).to_be_visible()
            expect(page.locator('.general-settings')).to_have_count(0)
            expect(page.locator(".obsidian-settings input")).to_have_count(0)
            expect(page.get_by_role("button", name="立即同步到 Obsidian")).to_have_count(0)
            assert page.request.get(origin + "/api/brands").json() == []
            expect(page.get_by_role('button', name='收件匣', exact=True)).to_have_count(0)
            page.get_by_role("button", name="儀表板", exact=True).click()
            expect(page.locator('.no-brands')).to_have_text('尚未指派品牌，請聯絡管理員')
            expect(page.get_by_role("button", name="匯出報表", exact=True)).to_have_count(0)
            page.set_viewport_size({"width": 390, "height": 844})
            expect(page.locator('.no-brands')).to_be_visible()
            expect(page.locator('.mobile-logout')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('.mobile-logout').click()
            expect(page.get_by_role('button', name='登入工作檯')).to_be_visible()
            checks.append('viewer-mobile-logout')
            assert not errors
            browser.close()
            (output_dir() / "result.json").write_text(
                json.dumps(
                    {"checks": checks, "sdk": "substitutes", "errors": errors},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(
                json.dumps(
                    {
                        "workspace_checks": "passed",
                        "screens": len(checks),
                        "output": str(output_dir()),
                    },
                    ensure_ascii=True,
                )
            )
    finally:
        stop_process(server)


if __name__ == "__main__":
    serve() if len(sys.argv) > 1 and sys.argv[1] == "--serve" else main()

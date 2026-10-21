"""Full UI operation sweep: synthetic SQLite, browser_harness and local API substitutes.

Run from backend with FRONTEND_DIST_DIR pointing into .runtime. --baseline only
captures the same synthetic pages before UI changes. No live credentials are read.
"""

from runtime_tmp import cleanup, output_dir, output_path

import json
import os
import re
import secrets
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from browser_harness import REPO, main
from playwright.sync_api import expect
from ui_navigation import navigate

BASELINE = "--baseline" in sys.argv
OUTPUT = output_path(__file__)
RESULTS = []

UNIFORM = """() => {
    const failures = [], seen = [], visible = e => e.checkVisibility() && e.getBoundingClientRect().width > 0;
    const check = (ok, label) => { seen.push(label); if (!ok) failures.push(label); };
    for (const tabs of document.querySelectorAll('.tabs')) {
        if (!visible(tabs)) continue;
        const buttons = [...tabs.querySelectorAll('[role=tab]')], r = tabs.getBoundingClientRect();
        check(buttons.every(e => getComputedStyle(e).backgroundColor === 'rgba(0, 0, 0, 0)'), 'underline tabs transparent');
        check(buttons.filter(e => e.getAttribute('aria-selected') === 'true').every(e => {
            const s = getComputedStyle(e); return s.borderBottomWidth === '3px' && s.borderBottomColor === s.color;
        }), 'selected underline and text');
        const spread = Math.max(...buttons.map(e => e.offsetWidth)) - Math.min(...buttons.map(e => e.offsetWidth));
        if (tabs.matches('.settings-tabs') && buttons.length > 1) {
            // 使用者 2026-10-14 指定：設定分頁大小一致（其他底線分頁仍依內容寬度）。
            check(spread <= 1, 'settings tabs equal widths');
        } else {
            check(buttons.length > 1 ? spread > 8 : buttons[0].offsetWidth < tabs.clientWidth,
                  'tabs use content widths');
        }
        check(r.left >= 0 && r.right <= innerWidth + 1 && tabs.scrollWidth >= tabs.clientWidth, 'tabs own scroll container');
    }
    for (const control of document.querySelectorAll('.segmented-control.compact')) {
        if (!visible(control)) continue;
        const s = getComputedStyle(control), r = control.getBoundingClientRect();
        check(parseFloat(s.paddingLeft) === 3 && parseFloat(s.borderLeftWidth) === 1, 'segmented border and inset');
        const naturalWidth = [...control.children].reduce((sum, e) => sum + e.getBoundingClientRect().width, 8);
        check(r.width <= control.parentElement.clientWidth + 1 &&
              (naturalWidth >= control.parentElement.clientWidth || r.width < control.parentElement.clientWidth), 'segmented content width');
        check([...control.querySelectorAll('[aria-checked=true],[aria-selected=true]')].every(e =>
              getComputedStyle(e).backgroundColor !== 'rgba(0, 0, 0, 0)'), 'segmented selected fill');
    }
    // Groups contain several independent forms; count submissions per form.
    for (const form of document.querySelectorAll('.section-card form')) {
        if (visible(form)) check(form.querySelectorAll('button.primary:not([type=button],.danger)').length <= 1, 'one submit per form');
    }
    // 非提交動作一律為次要按鈕（白底細框），不得是實心 primary。
    for (const button of document.querySelectorAll('main button:not(.ideation-page *, .sidebar *, nav *)')) {
        if (visible(button) && /^(匯出報表|更換|設定|測試連線|全部更新|更新|重新偵測|重新整理 ↻|立即同步|立即同步到 Obsidian|立即同步 Markdown|顯示更多|完整重抓|停止|← 上一頁|下一頁 →|還原此版本|預覽差異)$/.test(button.textContent.trim()))
            check(button.classList.contains('secondary') && !button.classList.contains('primary'), 'secondary action ' + button.textContent.trim());
    }
    for (const button of document.querySelectorAll('.credential-controls button,.mobile-back,.confirm-dialog [data-cancel]')) {
        if (visible(button) && /取消|返回|移除/.test(button.textContent))
            check(button.classList.contains('secondary'), 'secondary cancel action');
    }
    for (const toolbar of document.querySelectorAll('.brand-toolbar')) {
        if (visible(toolbar)) check(toolbar.getBoundingClientRect().width <= 360, 'brand toolbar <=360');
    }
    for (const group of document.querySelectorAll('details.workspace-group')) {
        check(group.matches('.section-card') && group.querySelector(':scope > summary')?.closest('.section-card') === group, 'workspace summary inside its card');
        check(!group.querySelector('.section-card'), 'workspace contains no nested cards');
        check([...group.querySelectorAll('.workspace-group-content > section')].every(e => e.querySelector(':scope > h3')), 'workspace subsections use h3');
        const summary = getComputedStyle(group.querySelector(':scope > summary'));
        check(summary.fontWeight === '600' && getComputedStyle(group.querySelector('summary'), '::after').content !== 'none', 'workspace heading weight and expansion icon');
        if (group.open) {
            const sections = [...group.querySelectorAll('.workspace-group-content > section')];
            check(sections.every((e, i) => !i || Math.abs(e.getBoundingClientRect().top - sections[i - 1].getBoundingClientRect().bottom - 24) <= 1), 'workspace subsection gap 24');
        }
    }
    const workspaceCards = [...document.querySelectorAll('.general-settings > .workspace-group')];
    check(workspaceCards.every((e, i) => !i || Math.abs(e.getBoundingClientRect().top - workspaceCards[i - 1].getBoundingClientRect().bottom - 24) <= 1), 'workspace card gap 24');
    for (const row of document.querySelectorAll('.settings-hub label:has(> input[type=checkbox])')) {
        if (!visible(row)) continue;
        const next = row.nextElementSibling;
        const field = next?.matches('label') ? next : next?.querySelector('label');
        if (field && visible(field)) check(field.getBoundingClientRect().top - row.getBoundingClientRect().bottom >= 16, 'checkbox to next field >=16');
    }
    for (const item of document.querySelectorAll('.post-card')) {
        if (!visible(item)) continue;
        const box = item.closest('.list-box'), badge = item.querySelector('.ideation-platform'), meta = item.querySelector('.post-card-meta');
        check(!!box && !!badge && meta?.contains(badge) && meta.contains(item.querySelector('small')), 'post list container and inline platform capsule');
        check(getComputedStyle(box).borderLeftWidth === '1px' && getComputedStyle(item.querySelector('strong')).webkitLineClamp === '2', 'post list border and two caption lines');
        if (item.matches('.chosen')) {
            const stripe = getComputedStyle(item, '::before'), s = getComputedStyle(item);
            const token = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
            const probe = document.createElement('span'); probe.style.color = token('--brand-primary'); document.body.append(probe);
            check(stripe.width === '3px' && stripe.backgroundColor === getComputedStyle(probe).color, 'selected post brand stripe'); probe.remove();
            check(s.backgroundColor === getComputedStyle(document.querySelector('.status-badge.neutral') || badge).backgroundColor, 'selected post subtle background');
        }
    }
    for (const select of document.querySelectorAll('.follower-filter select')) {
        if (!visible(select)) continue;
        check(select.scrollWidth <= select.clientWidth, 'calendar select fits');
        const s = getComputedStyle(select), canvas = document.createElement('canvas'), context = canvas.getContext('2d');
        context.font = `${s.fontWeight} ${s.fontSize} ${s.fontFamily}`;
        check([...select.options].every(option => context.measureText(option.text).width + parseFloat(s.paddingLeft) + parseFloat(s.paddingRight) + 24 <= select.clientWidth), 'calendar option text fits including native arrow');
    }
    if (innerWidth < 600 && document.querySelector('.workspace')) {
        const controls = document.querySelector('.mobile-settings-controls'), heading = document.querySelector('.workspace h1');
        check(!!controls && !!heading && controls.getBoundingClientRect().bottom <= heading.getBoundingClientRect().top + heading.closest('.workspace > section').scrollTop, 'global mobile brand and logout above h1');
        const selected = document.querySelector('.mobile-bottom-nav [aria-current=page]');
        check(!!selected && !selected.disabled && getComputedStyle(selected).opacity === '1', 'mobile current page enabled with full opacity');
        const probe = document.createElement('span'); probe.style.background = 'var(--brand-primary)'; probe.style.color = 'var(--bg-surface)'; document.body.append(probe);
        check(getComputedStyle(selected).backgroundColor === getComputedStyle(probe).backgroundColor && getComputedStyle(selected).color === getComputedStyle(probe).color, 'mobile current brand fill and white text'); probe.remove();
        for (const row of document.querySelectorAll('.credential-heading')) {
            if (!visible(row)) continue;
            const label = row.querySelector('label'), status = row.querySelector('.credential-status'), name = row.querySelector('.credential-name');
            check(label.getBoundingClientRect().bottom <= status.getBoundingClientRect().top, 'mobile credential identity and status on separate rows');
            check(getComputedStyle(name).whiteSpace === 'nowrap' && name.scrollWidth <= label.clientWidth, 'mobile credential name unbroken');
        }
        const intro = document.querySelector('.post-intro'), metrics = document.querySelector('.post-metrics');
        if (intro && metrics && visible(metrics)) check(Math.abs(metrics.getBoundingClientRect().top - intro.getBoundingClientRect().bottom - 16) <= 1, 'mobile detail card gap 16');
    }
    check(document.documentElement.scrollWidth <= innerWidth, 'uniform document fits');
    return {failures, assertions:seen.length};
}"""


class Audit:
    def __init__(self, page):
        self.page = page
        self.errors = []
        self.responses = []
        self.expected = []
        self.console = []
        self.controls = []
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("console", self.on_console)
        page.on("response", self.on_response)

    def on_console(self, message):
        if message.type == "error":
            self.console.append({"text": message.text, "url": message.location.get("url", "")})

    def on_response(self, response):
        if response.status >= 400:
            self.responses.append(
                (response.request.method, urlsplit(response.url).path, response.status)
            )

    def allow(self, method, path, status, reason):
        self.expected.append({"method": method, "path": path, "status": status, "reason": reason})

    def finish(self):
        allowed = [(e["method"], e["path"], e["status"]) for e in self.expected]
        unexpected = [r for r in self.responses if r not in allowed]
        # Chromium logs a failed HTTP resource for injected HTTP errors. Match the
        # exact resource AND status; arbitrary React/JS errors are never exempted.
        console = [
            c
            for c in self.console
            if not any(
                urlsplit(c["url"]).path == path
                and re.fullmatch(
                    r"Failed to load resource: the server responded with a status of "
                    + str(status)
                    + r" \(.*\)",
                    c["text"],
                )
                for _, path, status in self.responses
                if (_, path, status) in allowed
            )
        ]
        result = {
            "viewport": self.page.viewport_size,
            "expected_errors": self.expected,
            "responses_400": self.responses,
            "unexpected_http": unexpected,
            "console_errors": console,
            "page_errors": self.errors,
            "controls": self.controls,
        }
        RESULTS.append(result)
        (output_dir() / "features.json").write_text(
            json.dumps(RESULTS, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        assert not unexpected and not console and not self.errors, result

    def measure(self, label, screenshot=False):
        page = self.page
        page.wait_for_load_state("networkidle")
        page.evaluate(
            "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), label
        failures = page.locator(
            "button, .kpi, .dashboard-card, .settings-section, "
            ".export-card, .ideation-card, .post-card"
        ).evaluate_all("""els => els.filter(e => {
            const r=e.getBoundingClientRect();
            return r.width && r.height && e.checkVisibility()
                && e.scrollHeight > e.clientHeight+1;
        }).map(e => ({tag:e.tagName, class:e.className, text:e.textContent.slice(0,80),
                     scroll:e.scrollHeight, client:e.clientHeight}))""")
        if not BASELINE:
            assert not failures, (label, failures)
            uniform = page.evaluate(UNIFORM)
            assert not uniform["failures"], (label, uniform)
        controls = page.locator("button, input, select, textarea, summary, a").evaluate_all(
            """els => els.filter(e => e.checkVisibility()).map(e => ({
            tag:e.tagName, type:e.type || '', label:e.getAttribute('aria-label')
                || (e.labels && e.labels[0]?.textContent) || e.textContent.trim(),
            href:e.getAttribute('href'), disabled:!!e.disabled}))"""
        )
        self.controls.append({"page": label, "controls": controls, "layout_failures": failures})
        if screenshot:
            size = page.viewport_size
            page.screenshot(path=str(OUTPUT / f"{label}-{size['width']}x{size['height']}.png"))


def section(page, title):
    return page.locator(".settings-section").filter(
        has=page.get_by_role("heading", name=title, exact=True)
    )


def workspace(page):
    navigate(page, "工作區設定")
    expect(page.get_by_label("產品顯示名稱")).to_be_visible()


def save_form(audit, scope, button_name, endpoint, edit, verify, reopen):
    """Real backend persistence plus per-form error/disabled feedback checks."""
    page = audit.page
    page.wait_for_load_state("networkidle")
    edit()
    button = scope.get_by_role("button", name=button_name, exact=True)
    with page.expect_response(
        lambda r: urlsplit(r.url).path == endpoint and r.request.method == "PUT"
    ) as response:
        button.click()
    assert response.value.status == 200, (button_name, response.value.status)
    page.reload()
    reopen()
    verify()
    for status in (409, 422):
        edit()
        scope.get_by_role("button", name=button_name, exact=True).evaluate(
            "e => e.setAttribute('data-sweep-submit', '')"
        )
        button = scope.locator("[data-sweep-submit]")
        message = "設定已更新，請重新整理" if status == 409 else "欄位格式不正確，請檢查輸入"
        audit.allow(
            "PUT",
            endpoint,
            status,
            button_name + "：版本衝突" if status == 409 else button_name + "：驗證失敗",
        )
        pending = []
        pattern = "**" + endpoint + "*"

        def reject(route, _request, pending=pending):
            if route.request.method == "PUT":
                pending.append(route)
            else:
                route.fallback()

        page.route(pattern, reject)
        button.click()
        expect(button).to_be_disabled()
        for _ in range(100):
            if pending:
                break
            page.wait_for_timeout(10)
        assert pending, button_name
        pending.pop().fulfill(status=status, json={"detail": message})
        expect(
            page.get_by_text(message, exact=True).and_(page.locator(":visible")).first
        ).to_be_visible()
        expect(button).to_be_enabled()
        verify()
        page.unroute(pattern, reject)
    audit.measure(button_name)


def seed():
    global VIEWER_TOKEN
    from pydantic import SecretStr
    from sqlalchemy import select
    from stage3_fixture import seed_stage3

    from app.config import Settings
    from app.db import build_engine, session_factory
    from app.models import Account, Brand, Message, MetricSnapshot, Post, Staff, StaffBrand, Thread
    from app.models.base import utc_now
    from app.services import auth, ideation_exports
    from app.services.passwords import hash_password

    settings = Settings(_env_file=None)
    for path in (settings.database_path, settings.export_root):
        assert Path(path).resolve().is_relative_to(REPO / ".runtime")
    engine = build_engine(settings)
    cleanup(engine.dispose)
    factory = session_factory(engine)
    with factory.begin() as s:
        bid = s.scalar(select(Brand.id).where(Brand.slug == "TEST"))
        viewer = s.scalar(select(Staff).where(Staff.username == "viewer_test"))
        viewer.password_hash = hash_password(SecretStr(secrets.token_urlsafe(32)))
        s.add(StaffBrand(staff_id=viewer.id, brand_id=bid))
        VIEWER_TOKEN = auth.issue_session(s, settings, viewer.id).token
        account = s.get(Account, 101)
        account.name = "[隔離驗收] FB"
        post = Post(
            account_id=account.id,
            external_id="sweep-post",
            caption="[隔離驗收] 完整功能操作貼文",
            media_type="POST",
            published_at=utc_now(),
        )
        s.add(post)
        s.flush()
        pid = post.id
        s.add(MetricSnapshot(post_id=pid, captured_at=utc_now(), reach=100, views=120, comments=60))
        thread = Thread(
            brand_id=bid,
            account_id=account.id,
            post_id=pid,
            external_id="sweep-comments",
            kind="comment_thread",
        )
        s.add(thread)
        s.flush()
        for i in range(60):
            s.add(
                Message(
                    thread_id=thread.id,
                    external_id=f"sweep-comment-{i}",
                    direction="in",
                    author_type="fan",
                    text=f"[隔離驗收] 詢問 {i}",
                    sent_at=utc_now(),
                    comment_parent_known=True,
                )
            )
    rid, sid = seed_stage3(factory, "http://127.0.0.1")
    ideation_exports.export_report(factory, settings, rid)
    ideation_exports.export_script(factory, settings, sid)
    engine.dispose()
    return bid, pid, rid, sid


def settings_forms(audit):
    page = audit.page
    navigate(page, "AI 設定")
    page.get_by_role("tab", name="基本", exact=True).click()
    basic = page.locator("#ai-panel-basic")
    budget = page.get_by_label("每月 API 預算（美元）")
    save_form(
        audit,
        basic,
        "儲存 AI 設定",
        "/api/ai/settings",
        lambda: budget.fill("234.56"),
        lambda: expect(budget).to_have_value("234.56"),
        lambda: expect(budget).to_be_visible(),
    )
    page.get_by_role("tab", name="AI 金鑰", exact=True).click()
    advanced = page.locator("#ai-panel-keys")
    models = advanced.locator(".provider-fallback input")

    def edit_models():
        expect(models).to_have_count(3)
        for i, model in enumerate(models.all()):
            model.fill(f"isolated-model-{i}")

    def verify_models():
        for i, model in enumerate(models.all()):
            expect(model).to_have_value(f"isolated-model-{i}")

    save_form(
        audit,
        advanced,
        "儲存 AI 設定",
        "/api/ai/settings",
        edit_models,
        verify_models,
        lambda: expect(models).to_have_count(3),
    )
    page.get_by_role("tab", name="品牌說明", exact=True).click()
    for title in ("工作區共用說明", "品牌說明"):
        editor = page.get_by_role("region", name=title, exact=True)
        field = editor.get_by_label(title + "內容")
        counter = [0]

        def edit(counter=counter, field=field, title=title):
            counter[0] += 1
            field.fill(f"[隔離驗收] {title}版本 {counter[0]}")

        save_form(
            audit,
            editor,
            "儲存新版本",
            "/api/ai/prompts",
            edit,
            lambda field=field, title=title, counter=counter: expect(field).to_have_value(
                f"[隔離驗收] {title}版本 {counter[0]}"
            ),
            lambda field=field: expect(field).to_be_visible(),
        )
        editor.get_by_role("button", name="儲存新版本", exact=True).click()
        expect(editor.get_by_text("新版本已儲存。", exact=True)).to_be_visible()
        editor.locator("summary").click()
        choices = editor.get_by_label("檢視版本")
        options = choices.locator("option").all()
        choices.select_option(options[-1].get_attribute("value"))
        expect(editor.locator(".prompt-diff")).to_be_visible()
        editor.get_by_role("button", name="還原此版本").click()
        expect(editor.get_by_text("已還原為新的版本，既有歷史保留。", exact=True)).to_be_visible()
    navigate(page, "訊息分類")
    notes = page.locator(".intent-notes")

    def edit_notes():
        expect(notes.locator("input")).to_have_count(9)
        for index, field in enumerate(notes.locator("input").all()):
            field.fill(f"[隔離驗收] 分類 {index}")

    def verify_notes():
        for index, field in enumerate(notes.locator("input").all()):
            expect(field).to_have_value(f"[隔離驗收] 分類 {index}")

    save_form(
        audit,
        notes,
        "儲存",
        "/api/classifications/intents",
        edit_notes,
        verify_notes,
        lambda: expect(notes.locator("input")).to_have_count(9),
    )
    workspace(page)
    specs = [
        (
            "工作區名稱與品牌範本",
            "產品顯示名稱",
            "[隔離驗收] 功能工作檯",
            "儲存工作區名稱",
            "/api/workspace/identity",
        ),
        (
            "工作區名稱與品牌範本",
            "品牌禁語（每行一項）",
            "[隔離驗收] 禁止承諾",
            "儲存品牌禁語",
            "/api/settings/brand-rules",
        ),
        (
            "收訊健康監測",
            "系統警示對象（LINE 群組、聊天室或用戶 ID）",
            "C" + "0" * 32,
            "儲存系統警示對象",
            "/api/settings/receive-health",
        ),
        (
            "LINE 群組通知",
            "群組備註名稱",
            "[隔離驗收] 通知群組",
            "儲存通知政策",
            "/api/notify/policy",
        ),
        (
            "匯出資料夾",
            "匯出目錄",
            str(Path(os.environ["EXPORT_ROOT"]).resolve()),
            "儲存並檢查寫入權限",
            "/api/settings/export",
        ),
        (
            "Obsidian 留言資料夾",
            "Obsidian 留言資料夾",
            str(Path(os.environ["OBSIDIAN_ROOT"]).resolve()),
            "儲存 Obsidian 資料夾",
            "/api/settings/obsidian",
        ),
    ]
    for title, label, value, button, endpoint in specs:
        scope = section(page, title)
        field = scope.get_by_label(label)
        save_form(
            audit,
            scope,
            button,
            endpoint,
            lambda field=field, value=value: field.fill(value),
            lambda field=field, value=value: expect(field).to_have_value(value),
            lambda: workspace(page),
        )
    meeting = section(page, "例會與觀眾主題")

    def edit_meeting():
        meeting.get_by_label("啟用例會前自動發想").check()
        meeting.get_by_label("例會星期").select_option("2")
        meeting.get_by_label("例會時間").fill("14:30")
        meeting.get_by_role("combobox", name="頻率", exact=True).select_option("2")
        meeting.get_by_label("隔週起算日").fill("2026-10-01")
        meeting.locator("textarea").fill("其他\n[隔離驗收] 服務問題")

    def verify_meeting():
        expect(meeting.get_by_label("啟用例會前自動發想")).to_be_checked()
        expect(meeting.get_by_label("例會星期")).to_have_value("2")
        expect(meeting.get_by_label("例會時間")).to_have_value("14:30")
        expect(meeting.get_by_role("combobox", name="頻率", exact=True)).to_have_value("2")
        expect(meeting.get_by_label("隔週起算日")).to_have_value("2026-10-01")

    save_form(
        audit,
        meeting,
        "儲存例會與主題",
        "/api/ideation/settings",
        edit_meeting,
        verify_meeting,
        lambda: workspace(page),
    )
    meeting.locator("summary").click()
    expect(meeting.locator("details")).to_have_attribute("open", "")
    section(page, "收訊健康監測").locator("summary").click()
    expect(section(page, "收訊健康監測").locator("details")).to_have_attribute("open", "")


def validation_error(audit):
    page = audit.page
    navigate(page, "AI 設定")
    page.get_by_role("tab", name="基本", exact=True).click()
    budget = page.get_by_label("每月 API 預算（美元）")
    expect(budget).to_be_visible()
    page.wait_for_load_state("networkidle")
    budget.fill("-1")
    audit.allow("PUT", "/api/ai/settings", 422, "真實隔離 API：負數預算驗證失敗")
    with page.expect_response(
        lambda r: urlsplit(r.url).path == "/api/ai/settings" and r.request.method == "PUT"
    ) as result:
        page.get_by_role("button", name="儲存 AI 設定", exact=True).click()
    assert result.value.status == 422
    assert result.value.json()["detail"] == "輸入格式錯誤"
    expect(page.locator("#ai-panel-basic [role=alert]")).to_have_text("輸入格式錯誤")
    size = page.viewport_size
    page.screenshot(path=str(OUTPUT / f"validation-error-{size['width']}x{size['height']}.png"))
    page.reload()


def screenshots(audit):
    page = audit.page
    for name, target in (
        ("dashboard", "儀表板"),
        ("posts", "貼文數據"),
        ("ideation", "主題發想"),
        ("ai-basic", "AI 設定"),
        ("classification", "訊息分類"),
        ("workspace", "工作區設定"),
        ("connections", "平台連線"),
    ):
        navigate(page, target)
        if target == "AI 設定":
            page.get_by_role("tab", name="基本", exact=True).click()
            expect(page.get_by_label("每月 API 預算（美元）")).to_be_visible()
        if target == "主題發想":
            expect(page.locator(".report-heading")).to_be_visible()
        audit.measure(name, True)

    original = page.viewport_size
    if original["width"] == 1440 and not BASELINE:
        page.set_viewport_size({"width": 768, "height": 1024})
        screenshots(audit)
        page.set_viewport_size(original)
    navigate(page, "AI 設定")
    for tab, name in (("品牌說明", "ai-brand"), ("AI 金鑰", "ai-keys")):
        page.get_by_role("tab", name=tab, exact=True).click()
        expect(
            page.locator(".prompt-editor textarea" if tab == "品牌說明" else ".ai-keys").first
        ).to_be_visible()
        audit.measure(name, True)
    # 本機 CLI 已移除：沒有對應分頁與區塊。
    expect(page.get_by_role("tab", name="本機 CLI", exact=True)).to_have_count(0)
    expect(page.locator(".cli-entry,.local-cli-settings")).to_have_count(0)


def readonly(audit, origin, script_id):
    from app.services.auth import COOKIE_NAME

    page = audit.page
    cookies = page.context.cookies()
    page.context.add_cookies([{"name": COOKIE_NAME, "value": VIEWER_TOKEN, "url": origin}])
    page.reload()
    for tab in ('ai', 'connections', 'policy', 'workspace', 'members'):
        page.goto(origin + '/?view=settings&settings_tab=' + tab)
        expect(page.get_by_role('tablist', name='設定', exact=True).get_by_role('tab')).to_have_text(['我的帳號'])
        expect(page.locator('.my-account')).to_be_visible()
        expect(page.locator('.my-account input')).to_have_count(3)
        assert all(field.is_enabled() for field in page.locator('.my-account input').all())
        expect(page.get_by_role('button', name=re.compile('儲存|更新|偵測|套用|匯入|抓取|重新標註|同步 Markdown|新增成員'))).to_have_count(0)
        audit.measure('viewer-restricted-bookmark-' + tab)
    page.goto(origin + f"/?view=ideation&script_id={script_id}")
    expect(page.locator(".script-editor")).to_be_visible()
    for field in page.locator(
        ".script-editor input, .script-editor textarea, .script-editor form select"
    ).all():
        expect(field).to_be_disabled()
    expect(page.locator(".report-row .danger")).to_have_count(0)
    csrf = page.request.get(origin + "/api/auth/csrf").json()["csrf_token"]
    denied_read = page.request.get(origin + "/api/ai/settings?brand_id=1")
    assert denied_read.status == 403
    audit.allow('GET', '/api/ai/settings', 403, 'viewer 不可讀取設定')
    audit.responses.append(('GET', '/api/ai/settings', denied_read.status))
    denied = page.request.put(
        origin + "/api/ai/settings?brand_id=1",
        data={},
        headers={"Origin": origin, "X-CSRF-Token": csrf},
    )
    assert denied.status == 403
    audit.allow("PUT", "/api/ai/settings", 403, "真實 viewer session 的後端拒寫")
    audit.responses.append(("PUT", "/api/ai/settings", denied.status))
    page.context.add_cookies(cookies)
    page.reload()
    expect(page.locator('.ideation-form')).to_be_visible()


def action(audit, scope, button_name, endpoint, result, message=None, method="POST"):
    """Hold a substitute response so progress and the failure UI are observable."""
    page = audit.page
    pattern = "**" + endpoint + "*"
    for status in (503, 200):
        pending = []

        def respond(route, _request, pending=pending):
            if route.request.method == method:
                pending.append(route)
            else:
                route.fallback()

        page.route(pattern, respond)
        button = scope.get_by_role("button", name=button_name, exact=True)
        button.evaluate("e => e.setAttribute('data-sweep-action', '')")
        stable = scope.locator("[data-sweep-action]")
        with page.expect_request(lambda r: urlsplit(r.url).path == endpoint and r.method == method):
            button.click()
        expect(stable).to_be_disabled()
        assert len(pending) == 1
        if status == 503:
            audit.allow(method, endpoint, 503, button_name + "：服務暫時失敗替身")
            pending.pop().fulfill(status=503, json={"detail": "隔離驗收：暫時無法處理，請稍後再試"})
            expect(
                scope.get_by_text("隔離驗收：暫時無法處理，請稍後再試", exact=True)
            ).to_be_visible()
        else:
            pending.pop().fulfill(json=result)
            if message:
                expect(scope.get_by_text(message, exact=False)).to_be_visible()
        expect(stable).to_be_enabled()
        stable.evaluate("e => e.removeAttribute('data-sweep-action')")
        page.unroute(pattern, respond)
    audit.measure(button_name)


def workspace_actions(audit):
    from check_csv_ui import exercise_csv

    page = audit.page
    workspace(page)
    page.wait_for_load_state("networkidle")
    branding = section(page, "工作區名稱與品牌範本")
    branding.get_by_role("combobox", name="品牌範本", exact=True).select_option("blank")
    branding.get_by_role("button", name="預覽差異").click()
    expect(branding.get_by_label("範本差異")).to_be_visible()
    branding.get_by_role("button", name="取消", exact=True).click()
    expect(branding.get_by_label("範本差異")).to_have_count(0)
    branding.get_by_role("button", name="預覽差異").click()
    with page.expect_response(lambda r: "/templates/apply?" in r.url) as applied:
        branding.get_by_role("button", name="確認套用此差異").click()
    assert applied.value.status == 200
    expect(branding.get_by_text("範本已套用並記錄稽核")).to_be_visible()
    page.reload()
    workspace(page)
    expect(branding.get_by_label("品牌禁語（每行一項）")).to_have_value("")
    expect(section(page, "例會與觀眾主題").locator("textarea")).to_have_value("其他")
    expect(section(page, "例會與觀眾主題").get_by_role(
        "button", name="重新標註", exact=False
    )).to_have_count(0)  # 範圍操作移至發想頁，工作區不再無範圍重算。
    action(
        audit,
        page.locator(".general-settings"),
        "立即同步 Markdown",
        "/api/exports/sync",
        {
            "files": 3,
            "pending": 0,
            "enabled": False,
            "last_success_at": "2026-10-05T00:00:00Z",
            "error": None,
        },
        "已匯出 3 份 Markdown",
    )
    action(
        audit,
        page.get_by_role('region', name='Obsidian 留言資料夾', exact=True),
        '立即同步到 Obsidian',
        '/api/exports/obsidian/sync',
        {'ok': True, 'written': 3, 'error': None},
        '已同步 3 份檔案',
    )
    exercise_csv(
        page,
        page.viewport_size["width"],
        page.viewport_size["height"],
        lambda name, *_: audit.measure(name),
    )
    # Toggle only the route substitute; Windows Task Scheduler is never touched.
    state = {"enabled": False, "supported": True, "task_name": "MWB-AutoStart", "code": None}
    changes = []

    def autostart(route):
        if route.request.method == "PUT":
            changes.append(route.request.post_data_json)
            state.update(changes[-1])
        route.fulfill(json=state)

    page.route("**/api/workspace/autostart", autostart)
    page.reload()
    workspace(page)
    box = page.get_by_label("登入 Windows 後自動啟動工作檯", exact=True)
    box.click()
    expect(box).to_be_checked()
    expect(box).to_be_enabled()
    page.reload()
    workspace(page)
    expect(box).to_be_checked()
    box.click()
    expect(box).not_to_be_checked()
    expect(box).to_be_enabled()
    assert changes == [{"enabled": True}, {"enabled": False}]
    audit.measure("autostart")
    page.unroute("**/api/workspace/autostart")
    # A configured notification group is synthetic; no send transport is invoked.
    policy_url = page.url.split("/?")[0].rstrip("/") + f"/api/notify/policy?brand_id={SEED[0]}"
    policy = page.request.get(policy_url).json()
    policy.update(
        configured=True,
        bot_configured=True,
        groups=[{"id": "C" + "1" * 32, "label": "[隔離驗收] 通知群組"}],
    )

    def notification(route):
        if route.request.method == "PUT":
            policy.update(route.request.post_data_json)
            policy["version"] += 1
        route.fulfill(json=policy)

    page.route("**/api/notify/policy?*", notification)
    page.reload()
    workspace(page)
    notify = section(page, "LINE 群組通知")
    notify.get_by_label("此品牌通知群組").select_option("C" + "1" * 32)
    notify.get_by_label("品牌通知", exact=True).select_option("on")
    notify.get_by_label("急迫度通知門檻（0–1）").fill("0.65")
    notify.get_by_label("公開聲譽風險門檻（0–1）").fill("0.7")
    notify.get_by_role("button", name="儲存通知政策").click()
    expect(notify.get_by_role("status")).to_contain_text("通知政策已儲存")
    page.reload()
    workspace(page)
    expect(notify.get_by_label("品牌通知", exact=True)).to_have_value("on")
    expect(notify.get_by_label("急迫度通知門檻（0–1）")).to_have_value("0.65")
    expect(notify.get_by_label("公開聲譽風險門檻（0–1）")).to_have_value("0.7")
    notify.get_by_label("品牌通知", exact=True).select_option("off")
    notify.get_by_role("button", name="儲存通知政策").click()
    expect(notify.get_by_role("status")).to_contain_text("通知政策已儲存")
    audit.measure("notification-controls")
    page.unroute("**/api/notify/policy?*")


def keys(audit):
    page = audit.page
    rows = [
        {"provider": p, "source": "未設定", "version": 0, "mask": None, "error": None}
        for p in ("openai", "gemini", "anthropic")
    ]
    calls = []

    def endpoint(route):
        path = urlsplit(route.request.url).path
        if route.request.method == "GET":
            route.fulfill(json=rows)
            return
        calls.append((path, route.request.method))
        provider = path.split("/")[4]
        row = next(r for r in rows if r["provider"] == provider)
        if path.endswith("/test"):
            assert route.request.post_data_json == {"key": "isolated-test-value"}
            route.fulfill(json={"receipt": "isolated-receipt", "mask": "••••test"})
        else:
            row.update(
                source="UI" if route.request.method == "PUT" else "未設定",
                mask="••••test" if route.request.method == "PUT" else None,
                version=row["version"] + 1,
            )
            route.fulfill(json=rows)

    page.route("**/api/ai/keys**", endpoint)
    navigate(page, "AI 設定")
    page.get_by_role("tab", name="AI 金鑰", exact=True).click()
    area = page.get_by_role("region", name="API 金鑰")
    for provider in ("openai", "gemini", "anthropic"):
        area.get_by_label("金鑰供應商").select_option(provider)
        expect(area.get_by_role("button", name="儲存已驗證金鑰")).to_be_disabled()
        failure_path = f"/api/ai/keys/{provider}/test"
        audit.allow("POST", failure_path, 503, "金鑰連線失敗替身")
        page.route(
            "**" + failure_path,
            lambda r: r.fulfill(status=503, json={"detail": "隔離驗收連線失敗"}),
        )
        area.get_by_role("button", name="測試連線", exact=True).click()
        expect(area.get_by_role("alert")).to_have_text("隔離驗收連線失敗")
        page.unroute("**" + failure_path)

        def verify_key():
            area.get_by_label("新增或替換金鑰").fill("isolated-test-value")
            area.get_by_role("button", name="測試連線", exact=True).click()
            expect(area.get_by_label("新增或替換金鑰")).to_have_value("")
            expect(area.get_by_role("button", name="儲存已驗證金鑰")).to_be_enabled()

        save_form(
            audit,
            area,
            "儲存已驗證金鑰",
            f"/api/ai/keys/{provider}",
            verify_key,
            lambda: expect(area.get_by_label("新增或替換金鑰")).to_have_value(""),
            lambda provider=provider: area.get_by_label("金鑰供應商").select_option(provider),
        )
        expect(area.get_by_role("button", name="刪除 UI 金鑰")).to_be_visible()
        area.get_by_role("button", name="刪除 UI 金鑰").click()
        expect(area.get_by_text("UI 金鑰已刪除；未設定時會使用 .env。", exact=True)).to_be_visible()
        assert "isolated-test-value" not in page.content()
        assert page.evaluate(
            "!JSON.stringify([localStorage,sessionStorage]).includes('isolated-test-value')"
        )
    for provider in ("openai", "gemini", "anthropic"):
        assert calls.count((f"/api/ai/keys/{provider}/test", "POST")) == 3
        assert calls.count((f"/api/ai/keys/{provider}", "PUT")) == 1
        assert calls.count((f"/api/ai/keys/{provider}", "DELETE")) == 1
    audit.measure("api-keys")
    page.unroute("**/api/ai/keys**")


def content_operations(audit, origin, bid, pid, rid, sid):
    page = audit.page
    from check_ideation_fixes import check_report_delete
    from ui_navigation import brand_picker

    # 只有一個品牌時品牌選單隱藏、各頁自動用該品牌；多品牌時才需要選擇。
    picker = brand_picker(page)
    if picker.count():
        picker.select_option(str(bid))
    else:
        expect(page.locator(".brand-picker, .mobile-brand-picker")).to_have_count(0)
    navigate(page, "儀表板")
    expect(page.locator(".ranked-post").first).to_be_visible()
    page.locator(".ranked-post").first.click()
    expect(page.locator(".post-intro h2")).to_have_text("[隔離驗收] 完整功能操作貼文")
    # 標題可先於網址 effect 呈現；等選取狀態寫入網址再驗證重整保留。
    page.wait_for_function("id => new URLSearchParams(location.search).get('post_id') === String(id)", arg=pid)
    page.reload()
    expect(page.locator(".post-intro h2")).to_be_visible()
    dates = page.get_by_role("group", name="留言日期", exact=True)
    for days in (7, 90, 30):
        dates.get_by_role("radio", name=f"近 {days} 天", exact=True).click()
        expect(page.locator(".post-comment")).to_have_count(50)
    page.get_by_role("button", name="顯示更多", exact=True).click()
    expect(page.locator(".post-comment")).to_have_count(60)
    comment_id = int(page.locator(".post-comment").first.get_attribute("data-message-id"))
    audit.measure("post-detail")
    if page.viewport_size["width"] < 600:
        page.get_by_role("button", name="← 返回貼文", exact=True).click()
    filters = page.get_by_role("group", name="發文日期", exact=True)
    for button in filters.get_by_role("radio").all():
        button.click()
        expect(button).to_have_attribute("aria-checked", "true")
    filters.get_by_label("發文日期起日", exact=True).fill("2026-01-01")
    filters.get_by_label("發文日期迄日", exact=True).fill("2026-12-31")
    page.reload()
    expect(filters.get_by_label("發文日期起日", exact=True)).to_have_value("2026-01-01")
    expect(filters.get_by_label("發文日期迄日", exact=True)).to_have_value("2026-12-31")
    post = page.request.get(origin + f"/api/posts/{pid}").json()
    offsets = []

    def pagination(route):
        offset = int(parse_qs(urlsplit(route.request.url).query)["offset"][0])
        offsets.append(offset)
        count = 50 if offset == 0 else 1
        route.fulfill(
            json=[
                {**post, "id": 10000 + offset + i, "caption": f"[隔離驗收] 分頁貼文 {offset + i}"}
                for i in range(count)
            ]
        )

    page.route("**/api/posts?*", pagination)
    # 管理員的貼文數據頁首是「立即同步」（會呼叫排程），這裡只需重讀清單，所以重新載入頁面。
    page.reload()
    expect(page.locator(".post-card")).to_have_count(50)
    page.get_by_role("button", name="下一頁 →", exact=True).click()
    expect(page.locator(".post-card")).to_have_count(1)
    expect(page.locator(".pagination")).to_contain_text("第 2 頁")
    expect(page.get_by_role("button", name="下一頁 →", exact=True)).to_be_disabled()
    page.get_by_role("button", name="← 上一頁", exact=True).click()
    expect(page.locator(".post-card")).to_have_count(50)
    expect(page.get_by_role("button", name="← 上一頁", exact=True)).to_be_disabled()
    assert offsets[-3:] == [0, 50, 0]
    audit.measure("post-pagination")
    page.unroute("**/api/posts?*", pagination)
    navigate(page, "儀表板")
    page.get_by_role("button", name="匯出報表", exact=True).click()
    dialog = page.get_by_role("dialog", name="匯出報表")
    dialog.get_by_label("開始日期").fill("2026-10-01")
    dialog.get_by_label("結束日期").fill("2026-10-05")
    with (
        page.expect_download() as download,
        page.expect_response("**/api/exports/report/docx") as response,
    ):
        dialog.get_by_role("button", name="下載 Word 報表 ↓").click()
    assert response.value.status == 200
    assert Path(download.value.path()).stat().st_size > 0
    dialog.get_by_role("button", name="關閉", exact=True).click()
    page.goto(origin + f"/?view=ideation&report_id={rid}&script_id={sid}")
    editor = page.locator(".script-editor")
    expect(editor).to_be_visible()
    report = page.request.get(origin + f"/api/ideation/reports/{rid}").json()
    source_report = json.loads(json.dumps(report))
    source_report["data"]["groups"][0]["quotes"].append(
        {
            "id": comment_id,
            "text": "[隔離驗收] 留言來源",
            "platform": "facebook",
            "kind": "comment_thread",
            "post_id": pid,
        }
    )
    source_report["data"]["ideas"][0]["quote_ids"].append(comment_id)
    page.route(f"**/api/ideation/reports/{rid}", lambda r: r.fulfill(json=source_report))
    page.route(
        f"**/api/posts/{pid}",
        lambda r: r.fulfill(json={**post, "permalink": "https://example.invalid/sweep-post"}),
    )
    page.reload()
    page.locator(".ideation-card summary").first.click()
    page.locator(".ideation-card .ideation-quotes a").first.click()
    expect(page.locator(f'[data-message-id="{comment_id}"]')).to_be_in_viewport()
    page.reload()
    expect(page.locator(f'[data-message-id="{comment_id}"]')).to_be_in_viewport()
    external_links(page)
    page.get_by_role("link", name=f"← 回到報告 #{rid}", exact=True).click()
    expect(page.locator(".report-heading")).to_contain_text(f"#{rid}")
    for summary in section(page, "全部主題與代表原話").locator("summary").all():
        summary.click()
        expect(summary.locator("..")).to_have_attribute("open", "")
        summary.click()
    page.unroute(f"**/api/ideation/reports/{rid}")
    page.unroute(f"**/api/posts/{pid}")
    page.goto(origin + f"/?view=ideation&report_id={rid}&script_id={sid}")
    expect(editor).to_be_visible()
    for container in (page.locator(".ideation-exports").first, editor.locator(".ideation-exports")):
        for link in container.get_by_role("link").all():
            href = link.get_attribute("href")
            assert page.request.get(origin + href).status == 200
            with page.expect_download() as result:
                link.click()
            assert Path(result.value.path()).stat().st_size > 0
    title = editor.get_by_label("主題", exact=True)

    def edit_script():
        title.fill("[隔離驗收] 已修改脚本")

    save_form(
        audit,
        editor,
        "儲存版本並重新檢查",
        f"/api/ideation/scripts/{sid}",
        edit_script,
        lambda: expect(title).to_have_value("[隔離驗收] 已修改脚本"),
        lambda: expect(editor).to_be_visible(),
    )
    editor.get_by_role("button", name="新增分鏡", exact=True).click()
    expect(editor.locator(".script-shot")).to_have_count(3)
    editor.get_by_role("button", name="移除此鏡", exact=True).last.click()
    expect(editor.locator(".script-shot")).to_have_count(2)
    for field in editor.locator("textarea").all():
        field.fill("[隔離驗收] 拍攝內容")
    editor.get_by_label("目標類型").select_option("流量型")
    editor.get_by_label("片長（秒）").fill("20")
    for field in editor.get_by_role("combobox", name="機位", exact=True).all():
        field.select_option("側拍")
    for field in editor.get_by_label("鏡頭秒數", exact=True).all():
        field.fill("10")
    with page.expect_response(
        lambda r: (
            urlsplit(r.url).path == f"/api/ideation/scripts/{sid}" and r.request.method == "PUT"
        )
    ) as saved:
        editor.get_by_role("button", name="儲存版本並重新檢查").click()
    assert saved.value.status == 200
    page.reload()
    expect(editor).to_be_visible()
    for field in editor.locator("textarea").all():
        expect(field).to_have_value("[隔離驗收] 拍攝內容")
    expect(editor.get_by_label("目標類型")).to_have_value("流量型")
    for field in editor.get_by_role("combobox", name="機位", exact=True).all():
        expect(field).to_have_value("側拍")
    editor.get_by_label("歷史版本").select_option("1")
    expect(editor.locator(".script-history")).to_be_visible()
    editor.get_by_role("button", name="套用此版本供編輯").click()
    expect(title).not_to_have_value("[隔離驗收] 已修改脚本")
    editor.get_by_role("button", name="儲存版本並重新檢查").click()
    expect(editor.get_by_role("heading", name=re.compile("腳本編輯 · 第"))).to_be_visible()
    page.wait_for_load_state("networkidle")
    audit.measure("script-editor")
    # Only report creation is substituted; editing/review above uses the real isolated API.
    report = page.request.get(origin + f"/api/ideation/reports/{rid}").json()
    page.route("**/api/ideation/posts?*", lambda route: route.fulfill(json=[{
        "id": 991, "platform": "facebook", "published_at": "2025-02-02T00:00:00Z",
        "caption": "[隔離驗收] 發想來源", "comment_count": 3,
    }]))
    page.get_by_label("開始時間", exact=True).fill("2025-01-01T00:00")
    page.get_by_label("結束時間", exact=True).fill("2026-10-05T00:00")
    expect(page.locator(".ideation-post input")).to_be_checked()
    expect(page.locator(".ideation-posts")).to_have_attribute("aria-busy", "false")
    action(audit, page.locator(".ideation-page"), "重新標註所選留言",
           "/api/ideation/reclassify", {"status": "queued"},
           "已排入所選留言範圍與貼文的主題重算。")
    action(audit, page.locator(".ideation-page"), "立即發想", "/api/ideation/reports", report)
    expect(page.locator(".report-heading")).to_contain_text(f"#{rid}")
    # 產生腳本、重新生成、延伸主題已移除；已有腳本的主題卡片改提供「查看腳本」。
    for name in ("產生腳本", "重新生成", "延伸主題"):
        expect(page.get_by_role("button", name=name)).to_have_count(0)
    card = page.locator(".ideation-card").first
    expect(card.locator(".idea-card-tools").get_by_role("button")).to_have_text(["編輯"])
    expect(card.locator(".idea-card-actions").get_by_role("button")).to_have_text(
        ["查看腳本", "建立發佈草稿"]
    )
    card.get_by_role("button", name="查看腳本", exact=True).click()
    expect(page.locator(".script-editor")).to_be_visible()
    page.route(
        f"**/api/ideation/reports/{rid}",
        lambda r: r.fulfill(json={**report, "status": "failed", "can_retry": True}),
    )
    page.goto(origin + f"/?view=ideation&report_id={rid}")
    expect(page.get_by_role("button", name="重試此報告")).to_be_visible()
    retry_calls = []

    def retry(route):
        retry_calls.append(route.request.method)
        route.fulfill(json={**report, "status": "processing", "can_retry": False})

    page.route(f"**/api/ideation/reports/{rid}/retry", retry)
    page.get_by_role("button", name="重試此報告").click()
    expect(page.locator(".report-heading h2")).to_contain_text("正在分類與發想")
    assert retry_calls == ["POST"]
    page.unroute(f"**/api/ideation/reports/{rid}/retry")
    page.unroute(f"**/api/ideation/reports/{rid}")
    audit.allow("DELETE", "/api/ideation/reports/501", 409, "產生中報告刪除失敗")
    check_report_delete(page, origin, bid, rid, page.viewport_size["width"], [])
    page.goto(origin + f"/?view=ideation&report_id={rid}&script_id={sid}")
    expect(page.locator(".script-editor")).to_be_visible()


def helper_operations(page, origin, checks):
    from check_comment_sync_frontend import check_comments
    from check_dm_backfill_frontend import check_backfill
    from check_followers_frontend import check_followers
    from check_view_refresh import check_refresh
    from ui_dashboard import check_trends
    from check_ideation_fixes import check_idea_actions

    extra = page.context.new_page()
    audit = Audit(extra)
    extra.goto(origin + f'/?view=ideation&report_id={SEED[2]}')
    expect(extra.locator('.ideation-card')).to_have_count(1)
    extra.clock.install()
    check_idea_actions(extra, origin, SEED[2], extra.viewport_size['width'], extra.viewport_size['height'])
    audit.measure('idea-actions')
    audit.finish()
    extra.close()

    # The follower fixture fixes the context clock; keep it last.
    for helper in (
        check_comments,
        check_backfill,
        check_refresh,
        check_trends,
        check_followers,
    ):
        extra = page.context.new_page()
        audit = Audit(extra)
        audit.allow("GET", "/api/dashboard/trends", 500, "每日趨勢讀取失敗替身")
        extra.goto(origin)
        expect(extra.locator(".dashboard-kpis .kpi")).to_have_count(2)
        if helper is check_trends:
            helper(extra)
        else:
            helper(extra, None, lambda label, audit=audit: audit.measure(label), checks)
        audit.measure(helper.__name__)
        audit.finish()
        extra.close()


def external_links(page):
    """Exercise real anchors with an in-memory response, before the deny-all guard."""
    for link in page.locator('a[href^="https://"]:visible').all():
        href = link.get_attribute("href")
        expect(link).to_have_attribute("target", "_blank")
        hits = []

        def substitute(route, _request, hits=hits):
            hits.append(route.request.url)
            route.fulfill(status=200, content_type="text/html", body="<p>Isolated link target</p>")

        page.context.route(href, substitute)
        with page.expect_popup() as popup:
            link.click()
        popup.value.wait_for_load_state()
        assert hits == [href]
        popup.value.close()
        page.context.unroute(href, substitute)


def platform_connections(audit):
    """Real encrypted storage; connection buttons use an explicit HTTP substitute."""
    from app.services.credentials import GROUPS

    page = audit.page
    navigate(page, "平台連線")
    expect(page.locator('.connection-card')).to_have_count(len(GROUPS))
    expect(page.get_by_label('公開網址', exact=True)).to_have_attribute('readonly', '')
    expect(page.locator('.env-only')).to_contain_text('ACCOUNT_ENCRYPTION_KEY')
    for group, names in GROUPS.items():
        card = page.locator('.connection-card').filter(has=page.locator('#connection-' + group))
        if group == 'youtube':
            # 頻道與權杖只由 Google 授權流程寫入，設定頁只開放用戶端 ID／密鑰。
            for hidden in ('YOUTUBE_CHANNEL_ID', 'YOUTUBE_ACCESS_TOKEN', 'YOUTUBE_REFRESH_TOKEN'):
                expect(page.get_by_role('form', name=hidden, exact=True)).to_have_count(0)
            names = ('YOUTUBE_CLIENT_ID', 'YOUTUBE_CLIENT_SECRET')
        if group == 'tiktok':
            # 同 YouTube：open_id 與權杖只由 TikTok 授權流程寫入，設定頁只開放 Client key／secret。
            for hidden in ('TIKTOK_OPEN_ID', 'TIKTOK_ACCESS_TOKEN', 'TIKTOK_REFRESH_TOKEN'):
                expect(page.get_by_role('form', name=hidden, exact=True)).to_have_count(0)
            names = ('TIKTOK_CLIENT_KEY', 'TIKTOK_CLIENT_SECRET')
        for name in names:
            if group in {'meta', 'threads'}:
                card.locator('.oauth-manual').evaluate('e => e.open = true')
            form = page.get_by_role('form', name=name, exact=True)
            source = form.locator('.key-source').inner_text()
            if form.get_by_role('button', name='更換', exact=True).count():
                form.get_by_role('button', name='更換', exact=True).click()
            elif form.get_by_role('button', name='設定', exact=True).count():
                form.get_by_role('button', name='設定', exact=True).click()
            field = form.get_by_label(name, exact=True)
            expect(field).to_have_attribute('type', 'password')
            value = ('https://api.typesafe.ai/v1' if name == 'JEV_API_BASE_URL'
                     else '1234567890123456' if name in ('META_APP_ID', 'META_PAGE_ID', 'META_IG_ACCOUNT_ID', 'THREADS_APP_ID', 'THREADS_USER_ID')
                     else 'U' + 'a' * 32 if name.endswith('BOT_USER_ID')
                     else 'C' + 'a' * 32 if name.endswith('GROUP_ID')
                     else 'isolated-platform-private-' + name)
            field.fill(value)
            with page.expect_response('**/api/credentials/' + name) as response:
                form.get_by_role('button', name='儲存', exact=True).click()
            assert response.value.status == 200
            expect(form.locator('.key-source')).to_have_text('DB')
            expect(form.locator('input')).to_have_count(0)
            assert value not in form.inner_text()
            assert page.evaluate('value => !JSON.stringify([localStorage,sessionStorage]).includes(value)', value)
            page.reload()
            if group in {'meta', 'threads'}:
                card.locator('.oauth-manual').evaluate('e => e.open = true')
            expect(form.locator('.key-source')).to_have_text('DB')
            expect(form.locator('code')).to_contain_text('••••')
            # A stale editor receives a safe conflict and cannot expose its submitted secret.
            form.get_by_role('button', name='更換', exact=True).click()
            field.fill(value)
            pattern = '**/api/credentials/' + name
            audit.allow('PUT', '/api/credentials/' + name, 409, '憑證版本衝突替身')
            page.route(pattern, lambda r: r.fulfill(status=409, json={'detail': '憑證設定已變更，請重新整理後再試'}))
            form.get_by_role('button', name='儲存', exact=True).click()
            expect(form.get_by_role('alert')).to_contain_text('憑證設定已變更')
            expect(field).to_have_value('')
            page.unroute(pattern)
            form.get_by_role('button', name='取消', exact=True).click()
            form.get_by_role('button', name='移除', exact=True).click()
            expect(form.locator('.key-source')).to_have_text(source)
            page.reload()
            if group in {'meta', 'threads'}:
                card.locator('.oauth-manual').evaluate('e => e.open = true')
            expect(form.locator('.key-source')).to_have_text(source)
        # YouTube、TikTok 與 Meta／Threads 同為 OAuth 平台：測試連線走授權狀態檢查。
        requests = []
        endpoint = '/api/oauth/status?force=true' if group in {'meta', 'threads', 'youtube', 'tiktok'} else '/api/credentials/' + group + '/test'

        def probe(route):
            requests.append((route.request.method, route.request.post_data_json
                if route.request.method == 'POST' else route.request.post_data))
            if group in {'meta', 'threads', 'youtube', 'tiktok'}:
                route.fulfill(json={'backoffice_origin': 'https://office.example.test', 'callbacks': {}, 'platforms': {}, 'pages': []})
            else:
                route.fulfill(json={'ok': True})

        page.route('**' + endpoint, probe)
        card.get_by_role('button', name='測試連線', exact=True).click()
        expect(card.get_by_role('status')).to_have_text('權限檢查完成' if group in {'meta', 'threads', 'youtube', 'tiktok'} else '連線成功')
        assert requests == [('GET', None)] if group in {'meta', 'threads', 'youtube', 'tiktok'} else requests == [('POST', {})]
        page.unroute('**' + endpoint)
        audit.allow('GET' if group in {'meta', 'threads', 'youtube', 'tiktok'} else 'POST', endpoint.split('?')[0], 422, '平台連線失敗替身')
        page.route('**' + endpoint, lambda r: r.fulfill(status=422, json={'detail': '連線測試失敗'}))
        card.get_by_role('button', name='測試連線', exact=True).click()
        expect(card.get_by_role('alert')).to_have_text('連線測試失敗')
        page.unroute('**' + endpoint)
    audit.measure('platform-connections', True)


def run(page, _, shot, checks):
    global SEED
    if SEED is None:
        SEED = seed()
    bid, pid, rid, sid = SEED
    origin = page.url.split("/?")[0].rstrip("/")
    origin = f"{urlsplit(origin).scheme}://{urlsplit(origin).netloc}"
    audit = Audit(page)
    screenshots(audit)
    if not BASELINE:
        validation_error(audit)
        settings_forms(audit)
        workspace_actions(audit)
        keys(audit)
        platform_connections(audit)
        content_operations(audit, origin, bid, pid, rid, sid)
        readonly(audit, origin, sid)
    audit.finish()
    if not BASELINE:
        helper_operations(page, origin, checks)
        logout_audit = Audit(page)
        navigate(page, "工作區設定")
        with page.expect_response("**/api/auth/logout") as result:
            page.get_by_role("button", name="登出", exact=True).and_(
                page.locator(":visible")
            ).click()
        assert result.value.status == 204
        expect(page.get_by_role("button", name="登入工作檯")).to_be_visible()
        logout_audit.measure("logout")
        logout_audit.finish()
    checks.append(f"{page.viewport_size['width']}: full-feature-sweep")


if __name__ == "__main__":
    dist = Path(os.environ["FRONTEND_DIST_DIR"]).resolve()
    assert dist.is_relative_to(REPO / ".runtime"), "Build into .runtime first"
    OUTPUT.mkdir(parents=True, exist_ok=True)
    SEED = None
    main(polish=True, exercise=run)

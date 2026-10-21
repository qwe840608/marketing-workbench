"""Internal agent consent with synthetic runtime DB/export and local-only HTTP."""

import base64
import hashlib
import os
import re
import secrets
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from browser_harness import REPO, main
from ports import browser_port
from playwright.sync_api import expect
from ui_navigation import navigate


def check_install(page, checks, *, screenshots=False):
    origin = page.evaluate("location.origin")
    section = page.locator(".agent-install")
    expect(section).to_be_visible()
    expect(section.get_by_role("heading", name="安裝 Agent")).to_be_visible()
    expect(section.locator(".agent-install-origin")).to_contain_text(
        "其他成員請用內部 https 網址開啟工作檯後再複製指令")
    identity = page.request.get(origin + "/api/workspace/identity").json()
    expect(section.locator(".agent-install-origin a")).to_have_attribute(
        "href", identity["backoffice_origin"])
    page.evaluate("""() => { window.installCopied = []; Object.defineProperty(navigator,
        'clipboard', {configurable: true, value: {writeText: async value => {
            window.installCopied.push(value); }}}); }""")
    original_size = page.viewport_size
    folder = REPO / ".runtime/agentdesk-screens"
    folder.mkdir(parents=True, exist_ok=True)
    expect(section.get_by_role("radio")).to_have_count(3)
    for agent in ("Claude Code", "Codex", "Claude 桌面版"):
        section.get_by_role("radio", name=agent, exact=True).click()
        expect(section.get_by_role("radio", name=agent, exact=True)).to_have_attribute(
            "aria-checked", "true")
        page.wait_for_load_state("networkidle")
        commands = section.locator(".agent-install-command")
        expect(commands).to_have_count(1 if agent == "Claude 桌面版" else 2)
        for row in commands.all():
            value = row.locator("code").text_content()
            expect(row.get_by_role("button")).to_have_class("secondary")
            row.get_by_role("button").click()
            expect(row.get_by_role("button")).to_have_text("已複製")
            assert page.evaluate("window.installCopied.at(-1)") == value
        if agent == "Claude Code":
            expect(commands.first).to_contain_text(
                f"/plugin marketplace add {origin}/plugin/marketplace.json")
            expect(commands.last).to_contain_text("/plugin install mwb@marketing-workbench")
            expect(section).to_contain_text("Enable auto-update")
        elif agent == "Codex":
            download = section.get_by_role("link", name="下載 Codex 套件")
            expect(download).to_have_class("secondary agent-install-download")
            expect(download).to_have_attribute("href", origin +
                f"/plugin/codex/mwb-codex-{identity['plugin_version']}.zip")
            assert page.request.get(download.get_attribute("href")).status == 200
            expect(commands.first).to_contain_text("Expand-Archive")
            expect(commands.last).to_contain_text("codex mcp login mwb")
            expect(section).to_contain_text("config.toml 合併")
        else:
            download = section.get_by_role("link", name="下載桌面擴充")
            expect(download).to_have_class("secondary agent-install-download")
            expect(download).to_have_attribute("href", origin +
                f"/plugin/desktop/mwb-{identity['plugin_version']}.mcpb")
            assert page.request.get(download.get_attribute("href")).status == 200
            expect(section.locator(".agent-install-steps > li")).to_have_count(3)
            expect(section).to_contain_text("擴充功能 → 安裝擴充功能")
            expect(section).to_contain_text("本機可填 http://127.0.0.1:8000")
            expect(section).to_contain_text("在下方「Agent 連線」建立連線權杖")
            expect(commands.first.locator("code")).to_have_text(origin)
        for size in ({"width": 1440, "height": 900}, {"width": 768, "height": 1024},
                     {"width": 390, "height": 844}):
            page.set_viewport_size(size)
            page.wait_for_load_state("networkidle")
            page.evaluate("async () => { await document.fonts.ready; await new Promise(r => "
                          "requestAnimationFrame(() => requestAnimationFrame(r))); }")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert section.evaluate("e => e.scrollWidth <= e.clientWidth + 1")
        page.set_viewport_size(original_size)
        checks.append(f"install-{agent}-copy-origin-widths:{original_size['width']}")
    if screenshots:
        internal = "https://office.example.test"
        # Fulfil every HTTPS request through this isolated loopback backend.
        for cookie in page.context.cookies(origin):
            page.context.add_cookies([{"name": cookie["name"], "value": cookie["value"],
                "domain": "office.example.test", "path": "/", "secure": True,
                "httpOnly": True}])

        def internal_route(route):
            parts = urlsplit(route.request.url)
            response = route.fetch(url=origin + parts.path +
                ("?" + parts.query if parts.query else ""),
                headers={**route.request.headers, "host": urlsplit(origin).netloc})
            route.fulfill(response=response)

        page.route(internal + "/**", internal_route)
        try:
            page.goto(internal + "/?view=settings&settings_tab=account")
            section = page.locator(".agent-install")
            expect(section.get_by_role("link", name="下載 Codex 套件")).to_have_count(0)
            section.get_by_role("radio", name="Claude 桌面版", exact=True).click()
            expect(section.locator(".agent-install-origin")).to_have_count(0)
            expect(section.locator(".agent-install-command code")).to_have_text(internal)
            page.evaluate("""() => { window.desktopCopied = ''; Object.defineProperty(navigator,
                'clipboard', {configurable: true, value: {writeText: async value => {
                    window.desktopCopied = value; }}}); }""")
            section.get_by_role("button", name="複製", exact=True).click()
            expect(section.get_by_role("button", name="已複製")).to_be_visible()
            assert page.evaluate("window.desktopCopied") == internal
            expect(section.get_by_role("link", name="下載桌面擴充")).to_have_attribute(
                "href", internal + f"/plugin/desktop/mwb-{identity['plugin_version']}.mcpb")
            page.wait_for_load_state("networkidle")
            page.evaluate("async () => { await document.fonts.ready; await new Promise(r => "
                          "requestAnimationFrame(() => requestAnimationFrame(r))); }")
            section.scroll_into_view_if_needed()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert section.evaluate("e => e.scrollWidth <= e.clientWidth + 1")
            page.screenshot(path=str(folder /
                f"install-desktop-{original_size['width']}x{original_size['height']}.png"))
            checks.append(f"desktop-https-copy:{original_size['width']}")
        finally:
            page.goto(origin + "/?view=settings&settings_tab=account")
            page.unroute(internal + "/**", internal_route)
            section = page.locator(".agent-install")
            expect(section).to_be_visible()
    section.get_by_role("radio", name="Claude Code", exact=True).click()


def check_agent_auth(page, unused, shot, checks):
    # browser_harness supplies both paths before Settings or the application is created.
    for name in ("DATABASE_PATH", "EXPORT_ROOT"):
        assert Path(os.environ[name]).resolve().is_relative_to((REPO / ".runtime").resolve())
    origin = page.evaluate("location.origin")
    width, height = page.viewport_size["width"], page.viewport_size["height"]
    artifacts = REPO / ".runtime/agentauth-screens/after"
    artifacts.mkdir(parents=True, exist_ok=True)
    csrf = page.request.get(origin + "/api/auth/csrf").json()["csrf_token"]
    # Restore the initial isolated account between the harness's two viewport runs.
    connections = page.request.get(origin + "/api/agent/connections").json()
    for row in connections:
        assert page.request.delete(origin + f"/api/agent/connections/{row['id']}",
            headers={"Origin": origin, "X-CSRF-Token": csrf}).status == 204

    def capture(name):
        page.wait_for_load_state("networkidle")
        page.evaluate("async () => { await document.fonts.ready; await new Promise(r => "
                      "requestAnimationFrame(() => requestAnimationFrame(r))); }")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (name, width)
        for dialog in page.get_by_role("dialog").all():
            assert dialog.evaluate("e => e.scrollWidth <= e.clientWidth + 1")
        token = page.locator(".agent-token")
        original = token.text_content() if token.count() else None
        if original:
            token.evaluate("e => e.textContent = '••••••••••••••••••••••••••••••••'")
        try:
            page.screenshot(path=str(artifacts / f"{name}-{width}x{height}.png"))
        finally:
            if original:
                token.evaluate("(e, value) => e.textContent = value", original)
        page.set_viewport_size({"width": 768, "height": 1024})
        page.wait_for_load_state("networkidle")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (name, 768)
        page.set_viewport_size({"width": width, "height": height})
        checks.append(f"{name}:{width}")

    callback = f"http://127.0.0.1:{browser_port()}/callback"
    callback_query = {}

    def intercept_callback(route):
        callback_query.clear()
        callback_query.update(parse_qs(urlsplit(route.request.url).query))
        route.fulfill(content_type="text/html", body="<p>OAuth callback received</p>")

    page.route(callback + "?*", intercept_callback)

    def start(name):
        response = page.request.post(origin + "/oauth/register", data={
            "client_name": name, "redirect_uris": [callback]})
        assert response.status == 201
        client_id = response.json()["client_id"]
        verifier = secrets.token_urlsafe(32)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode()
        state = secrets.token_urlsafe(24)
        params = {"client_id": client_id, "redirect_uri": callback, "response_type": "code",
                  "state": state, "code_challenge": challenge.rstrip("="),
                  "code_challenge_method": "S256", "resource": origin + "/mcp"}
        page.goto(origin + "/oauth/authorize?" + urlencode(params))
        return client_id, verifier, state

    def finish(client_id, verifier, state):
        with page.expect_response("**/api/agent/authorization/decision") as decision:
            page.get_by_role("button", name="核准", exact=True).click()
        result = decision.value
        assert result.status == 200, {
            "status": result.status, "body": result.text(),
            "origin": result.request.headers.get("origin"),
            "fetch_site": result.request.headers.get("sec-fetch-site"),
        }
        # 授權在背景送到本機接收網址，瀏覽器停在工作檯自己的中文完成頁。
        expect(page.get_by_role("heading", name="核准完成")).to_be_visible()
        expect(page.get_by_text("OAuth callback received", exact=True)).to_have_count(0)
        assert callback_query["state"] == [state]
        response = page.request.post(origin + "/oauth/token", form={
            "client_id": client_id, "grant_type": "authorization_code", "redirect_uri": callback,
            "code": callback_query["code"][0], "code_verifier": verifier, "resource": origin +
            "/mcp"})
        assert response.status == 200
        return response.json()["access_token"]

    def info(token):
        response = page.request.post(origin + "/mcp", headers={"Authorization": "Bearer " + token,
            "Accept": "application/json, text/event-stream"}, data={"jsonrpc": "2.0", "id": 1,
            "method": "tools/call", "params": {"name": "get_server_info", "arguments": {}}})
        return response

    page.context.clear_cookies()
    client_id, verifier, state = start("隔離 OAuth")
    expect(page.get_by_role("button", name="登入工作檯")).to_be_visible()
    page.get_by_label("帳號", exact=True).fill("admin")
    page.get_by_label("密碼", exact=True).fill(os.environ["ADMIN_INITIAL_PASSWORD"])
    page.get_by_role("button", name="登入工作檯").click()
    expect(page.get_by_role("heading", name="核准 Agent 連線")).to_be_visible()
    expect(page.get_by_text("應用程式自稱", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="核准", exact=True)).to_be_enabled()
    capture("approve")
    access = finish(client_id, verifier, state)
    capture("approve-done")
    assert info(access).json()["result"]["structuredContent"]["connection"]["kind"] == "oauth"
    page.goto(origin)
    expect(page.locator(".workspace")).to_be_visible()
    # 新版本提醒：伺服器上的 index.html 換了主程式檔名時，畫面提醒重新整理。
    expect(page.locator(".update-notice")).to_have_count(0)

    def newer_build(route):
        response = route.fetch()
        route.fulfill(response=response, body=re.sub(
            r"/assets/index-[A-Za-z0-9_-]+\.js", "/assets/index-NEWBUILD.js", response.text()))

    page.route(origin + "/", newer_build)
    page.evaluate("window.dispatchEvent(new Event('focus'))")
    expect(page.locator(".update-notice")).to_contain_text("工作檯已更新")
    expect(page.locator(".update-notice button.secondary")).to_have_text("重新整理")
    capture("update-notice")
    page.unroute(origin + "/", newer_build)
    page.reload()
    expect(page.locator(".workspace")).to_be_visible()
    expect(page.locator(".update-notice")).to_have_count(0)
    navigate(page, "設定")
    page.get_by_role("tab", name="我的帳號", exact=True).click()
    expect(page.locator(".agent-connection-row")).to_have_count(1)
    check_install(page, checks, screenshots=True)
    page.get_by_role("button", name="建立連線權杖", exact=True).click()
    page.get_by_label("連線名稱", exact=True).fill("隔離桌面")
    page.get_by_role("button", name="建立", exact=True).click()
    expect(page.locator(".agent-token")).to_be_visible()
    manual = page.locator(".agent-token").text_content()
    assert manual.startswith("mwb_")
    assert info(manual).status == 200
    capture("account-token")
    page.get_by_role("button", name="關閉", exact=True).click()
    expect(page.locator(".agent-token")).to_have_count(0)
    expect(page.locator(".agent-connection-row")).to_have_count(2)
    page.locator(".agent-connections").scroll_into_view_if_needed()
    assert manual not in page.content()
    assert manual not in page.request.get(origin + "/api/agent/connections").text()
    capture("account-list")
    row = page.locator(".agent-connection-row").filter(has_text="隔離桌面")
    row.get_by_role("button", name="撤銷", exact=True).click()
    expect(page.get_by_role("dialog")).to_be_visible()
    expect(page.get_by_role("button", name="取消", exact=True)).to_be_focused()
    capture("account-revoke")
    page.get_by_role("dialog").get_by_role("button", name="撤銷", exact=True).click()
    expect(page.locator(".agent-connection-row")).to_have_count(1)
    assert info(manual).status == 401
    page.reload()
    expect(page.locator(".agent-connection-row")).to_have_count(1)
    expect(page.locator(".agent-token")).to_have_count(0)
    page.get_by_role("tab", name="成員", exact=True).click()
    expect(page.locator(".member-row").filter(has_text="admin").get_by_text(
        "Agent 連線 1 個", exact=True)).to_be_visible()
    capture("members-connections")
    member_row = page.locator(".member-row").filter(has_text="admin")
    member_row.get_by_role("button", name="撤銷全部 Agent 連線").click()
    page.get_by_role("dialog").get_by_role("button", name="撤銷全部 Agent 連線").click()
    expect(page.locator(".member-row").filter(has_text="admin").get_by_text(
        "Agent 連線 0 個", exact=True)).to_be_visible()
    assert info(access).status == 401
    checks.append(f"oauth-login-pkce-mcp-once-revoke-admin:{width}")

    from pydantic import SecretStr
    from sqlalchemy import select

    from app.config import Settings
    from app.db import build_engine, session_factory
    from app.models import Staff
    from app.services.passwords import hash_password

    engine = build_engine(Settings(_env_file=None))
    viewer_password = secrets.token_urlsafe(24)
    try:
        with session_factory(engine).begin() as session:
            viewer = session.scalar(select(Staff).where(Staff.username == "viewer_test"))
            viewer.password_hash = hash_password(SecretStr(viewer_password))
    finally:
        engine.dispose()
    page.context.clear_cookies()
    client_id, verifier, state = start("隔離檢視者 OAuth")
    expect(page.get_by_role("button", name="登入工作檯")).to_be_visible()
    page.get_by_label("帳號", exact=True).fill("viewer_test")
    page.get_by_label("密碼", exact=True).fill(viewer_password)
    page.get_by_role("button", name="登入工作檯").click()
    expect(page.locator(".agent-approval-details")).to_be_visible()
    expect(page.get_by_text("查詢資料", exact=True)).to_be_visible()
    viewer_token = finish(client_id, verifier, state)
    assert info(viewer_token).json()["result"]["structuredContent"]["user"]["role"] == "viewer"
    page.goto(origin + "/?view=settings&settings_tab=account")
    expect(page.locator(".agent-connections")).to_be_visible()
    check_install(page, checks)
    expect(page.get_by_role("tablist", name="設定", exact=True).get_by_role("tab")).to_have_text(
        ["我的帳號"])
    viewer_csrf = page.request.get(origin + "/api/auth/csrf").json()["csrf_token"]
    response = page.request.post(origin + "/api/members/1/revoke-connections", headers={
        "X-CSRF-Token": viewer_csrf})
    assert response.status == 403
    for size in ({"width": 1440, "height": 900}, {"width": 768, "height": 1024},
                 {"width": 390, "height": 844}):
        page.set_viewport_size(size)
        page.wait_for_load_state("networkidle")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.set_viewport_size({"width": width, "height": height})
    checks.append(f"viewer-consent-and-account-widths:{width}")
    # A separate synthetic marketing account verifies the same member-only install surface.
    engine = build_engine(Settings(_env_file=None))
    marketing_password = secrets.token_urlsafe(24)
    try:
        with session_factory(engine).begin() as session:
            marketer = session.scalar(select(Staff).where(Staff.username == "agentpack_marketing"))
            if marketer is None:
                marketer = Staff(username="agentpack_marketing", display_name="隔離行銷",
                                 role="marketing", password_hash=hash_password(
                                     SecretStr(marketing_password)))
                session.add(marketer)
            else:
                marketer.password_hash = hash_password(SecretStr(marketing_password))
    finally:
        engine.dispose()
    page.context.clear_cookies()
    page.goto(origin + "/?view=settings&settings_tab=account")
    page.get_by_label("帳號", exact=True).fill("agentpack_marketing")
    page.get_by_label("密碼", exact=True).fill(marketing_password)
    page.get_by_role("button", name="登入工作檯").click()
    expect(page.locator(".agent-install")).to_be_visible()
    check_install(page, checks)
    expect(page.get_by_role("tablist", name="設定", exact=True).get_by_role("tab")).to_have_text(
        ["我的帳號"])
    checks.append(f"marketing-install-visible:{width}")
    page.context.clear_cookies()
    # The first session was replaced by login; use the current admin session for restoration.
    page.goto(origin)
    page.get_by_label("帳號", exact=True).fill("admin")
    page.get_by_label("密碼", exact=True).fill(os.environ["ADMIN_INITIAL_PASSWORD"])
    page.get_by_role("button", name="登入工作檯").click()
    expect(page.locator(".workspace")).to_be_visible()


if __name__ == "__main__":
    os.environ["AGENTPACK_CHECK"] = "1"
    main(exercise=check_agent_auth)

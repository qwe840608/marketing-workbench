"""MCP authored content, web sources and responsive screens on a synthetic DB."""

import json
import os
import sys
import time
from pathlib import Path

from browser_harness import main, serve
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]


def check_agent_content(page, _, shot, checks):
    from agent_content_fixture import fetch_comments, ideas_for, no_ai, script_content, seed_content, typed
    from app.config import Settings
    from app.db import build_engine, session_factory
    from app.models.agent_auth import AgentGrant
    from app.services import ideation, jev
    from runtime_tmp import cleanup
    from sqlalchemy import select

    origin = os.environ["APP_ORIGIN"]
    settings = Settings(_env_file=None)
    assert settings.database_path.resolve().is_relative_to(ROOT / ".runtime")
    assert settings.export_root.resolve().is_relative_to(ROOT / ".runtime")
    engine = build_engine(settings)
    cleanup(engine.dispose)
    factory = session_factory(engine)
    jev.ask = typed
    ideation.ai.run = no_ai
    brand_id = page.request.get(origin + "/api/brands").json()[0]["id"]
    width, height = page.viewport_size["width"], page.viewport_size["height"]
    with factory() as session:
        # One scenario per browser size; the shared DB has unique platform keys.
        grant = session.scalar(select(AgentGrant).where(AgentGrant.name == "隔離 Agent 內容"))
    if grant is None:
        ids = seed_content(factory, brand_id)
        csrf = page.request.get(origin + "/api/auth/csrf").json()["csrf_token"]
        token = page.request.post(origin + "/api/agent/connections", headers={"X-CSRF-Token": csrf},
                                  data={"name": "隔離 Agent 內容"}).json()["token"]
        os.environ["AGENT_CONTENT_MOCK_TOKEN"] = token
        os.environ["AGENT_CONTENT_POST_ID"] = str(ids["post_id"])
    else:
        token = os.environ["AGENT_CONTENT_MOCK_TOKEN"]
        ids = {"post_id": int(os.environ["AGENT_CONTENT_POST_ID"])}

    headers = {"Authorization": "Bearer " + token, "Accept": "application/json, text/event-stream"}

    def rpc(method, params=None):
        response = page.request.post(origin + "/mcp", headers=headers,
            data={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
        assert response.status == 200
        result = response.json()["result"]
        assert not result.get("isError"), result
        return result

    def call(name, arguments):
        return rpc("tools/call", {"name": name, "arguments": arguments})["structuredContent"]

    tools = rpc("tools/list")["tools"]
    (ROOT / ".runtime/agentquery-tools.json").write_text(
        json.dumps(tools, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / ".runtime/agentpost-tools.json").write_text(
        json.dumps(tools, ensure_ascii=False, indent=2), encoding="utf-8")
    call("get_brand_guide", {"brand_id": brand_id})
    call("list_posts", {"brand_id": brand_id})
    report = call("start_ideation", {"brand_id": brand_id, "post_ids": [ids["post_id"]]})
    report_id = report["report_id"]
    # Complete the actual existing comment worker via MockTransport; no network platform access.
    if report["status"] == "syncing_comments":
        fetch_comments(factory, settings, ids["post_id"])
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        ideation.process(factory, settings, report_id)
        status = call("get_ideation_report", {"report_id": report_id})["status"]
        if status == "awaiting_ideas":
            break
        time.sleep(0.1)
    assert status == "awaiting_ideas"
    screens = ROOT / ".runtime/agentquery-screens/after"
    screens.mkdir(parents=True, exist_ok=True)

    def capture(label):
        page.wait_for_load_state("networkidle")
        page.evaluate("document.fonts.ready")
        for size in ({"width": 1440, "height": 900}, {"width": 768, "height": 1024},
                     {"width": 390, "height": 844}):
            page.set_viewport_size(size)
            page.wait_for_load_state("networkidle")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.set_viewport_size({"width": width, "height": height})
        target = ".script-heading" if label == "script" else ".report-heading"
        page.locator(target).evaluate("e => e.scrollIntoView({block: 'start'})")
        page.wait_for_load_state("networkidle")
        expect(page.locator(target + " .agent-source-chip")).to_be_in_viewport()
        shot(label)
        page.screenshot(path=str(screens / f"{label}-{width}x{height}.png"))

    page.goto(origin + f"/?view=ideation&report_id={report_id}&brand_id={brand_id}")
    expect(page.locator(".report-heading h2")).to_contain_text("等待 Agent 撰寫主題")
    expect(page.locator(".agent-awaiting")).to_be_visible()
    expect(page.locator(".report-heading .agent-source-chip")).to_have_text("來自 隔離 Agent 內容")
    expect(page.locator(".report-row").filter(has_text=f"#{report_id} ·").get_by_role(
        "button", name="刪除", exact=False)).to_be_enabled()
    expect(page.get_by_role("button", name="重試此報告")).to_have_count(0)
    capture("waiting")
    evidence = call("get_ideation_evidence", {"report_id": report_id})
    call("save_ideation_ideas", {"report_id": report_id, "ideas": ideas_for(evidence)})
    page.reload()
    expect(page.locator(".ideation-card")).to_have_count(15)
    expect(page.locator(".report-heading h2")).to_contain_text("已完成並匯出")
    expect(page.locator(".agent-awaiting")).to_have_count(0)
    expect(page.locator(".report-heading .agent-source-chip")).to_have_text("來自 隔離 Agent 內容")
    capture("report")
    saved = call("save_script", {"report_id": report_id, "topic_index": 0,
                                  "content": script_content()})
    assert saved["review"]["passed"]
    script_id = saved["script_id"]
    page.goto(origin + f"/?view=ideation&report_id={report_id}&script_id={script_id}&brand_id={brand_id}")
    expect(page.locator(".script-editor")).to_be_visible()
    page.locator(".script-editor").scroll_into_view_if_needed()
    expect(page.locator(".script-heading .agent-source-chip")).to_have_text("來自 隔離 Agent 內容")
    expect(page.locator(".script-editor .success-note")).to_contain_text("檢查通過")
    capture("script")
    # Viewer keeps sources/content and sees no content write controls.
    def viewer(route):
        payload = route.fetch().json()
        payload["role"] = "viewer"
        route.fulfill(json=payload)

    page.route("**/api/auth/me", viewer)
    page.reload()
    expect(page.locator(".script-editor")).to_be_visible()
    expect(page.get_by_role("button", name="儲存版本並重新檢查")).to_have_count(0)
    expect(page.locator(".idea-card-tools")).to_have_count(0)
    page.unroute("**/api/auth/me", viewer)
    checks.append(f"mcp-waiting-ready-script-source-viewer-widths:{width}")
    check_agent_publish(page, factory, settings, brand_id, call, shot, checks)
    engine.dispose()


def check_agent_publish(page, factory, settings, brand_id, call, shot, checks):
    import base64
    from datetime import timedelta

    from app.models import OAuthConnection, Setting
    from app.models.base import utc_now
    from publish_http_mock import seed_connections
    from sqlalchemy import select

    origin = os.environ["APP_ORIGIN"]
    for path in (settings.database_path, settings.export_root, settings.publish_media_root):
        assert path.resolve().is_relative_to(ROOT / ".runtime")
    with factory.begin() as session:
        if not session.scalar(select(OAuthConnection.id)):
            seed_connections(session, settings, brand_id)
        switch = session.scalar(select(Setting).where(Setting.key == "publishing.enabled"))
        if switch:
            switch.value_json = {"enabled": True}
        else:
            session.add(Setting(key="publishing.enabled", value_json={"enabled": True}))
    post = call("save_publish_draft", {"brand_id": brand_id, "format": "image",
        "caption": "[隔離驗收] Agent 草稿，確認需求後安排內容。", "platforms": ["facebook"]})
    link = call("create_upload_link", {"post_id": post["id"], "filename": "isolated.png"})
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
                          "+A8AAQUBAScY42YAAAAASUVORK5CYII=")
    response = page.request.put(link["upload_url"], data=png,
                                headers={"Content-Type": "application/octet-stream"})
    assert response.status == 200, response.text()
    post = call("get_publish_post", {"post_id": post["id"]})
    assert len(post["media"]) == 1 and post["checks"]["facebook"]["ok"]
    assert "relative_path" not in post["media"][0]
    size = page.viewport_size
    screens = ROOT / ".runtime/agentpost-screens/after"
    screens.mkdir(parents=True, exist_ok=True)

    def capture(label):
        page.wait_for_load_state("networkidle")
        page.evaluate("document.fonts.ready")
        for width, height in [(1440, 900), (768, 1024), (390, 844)]:
            page.set_viewport_size({"width": width, "height": height})
            page.evaluate("async () => { await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); }")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (label, width)
        page.set_viewport_size(size)
        target = page.locator(".publish-editor" if label == "editor" else ".publish-record").first
        source = target.locator(".publish-agent-source")
        source.scroll_into_view_if_needed()
        expect(source).to_have_text("來自 隔離 Agent 內容")
        expect(source).to_be_in_viewport()
        page.screenshot(path=str(screens / f"{label}-{size['width']}x{size['height']}.png"))
        shot("agentpost-" + label)

    page.goto(origin + f"/?view=publish&brand_id={brand_id}")
    page.get_by_role("tab", name="草稿", exact=True).click()
    row = page.locator(".publish-record").filter(has_text=post["caption"]).first
    expect(row).to_be_visible()
    capture("drafts")
    row.get_by_role("button", name="編輯", exact=True).click()
    expect(page.get_by_label("主文案", exact=True)).to_contain_text(post["caption"])
    capture("editor")
    # 開啟後的延遲檢查跑完時，未修改的草稿不可被自動存檔遞增版本，否則 prepare 會版本衝突。
    expect(page.locator(".publish-editor")).to_have_attribute("data-check-state", "checked")
    assert call("get_publish_post", {"post_id": post["id"]})["version"] == post["version"]
    prep =call("prepare_publish", {"post_id": post["id"], "version": post["version"],
        "scheduled_at": (utc_now() + timedelta(hours=2)).isoformat()})
    assert prep["details"]["caption"] == post["caption"]
    call("confirm_publish", {"post_id": post["id"], "confirmation_code": prep["confirmation_code"]})
    page.goto(origin + f"/?view=publish&brand_id={brand_id}")
    page.get_by_role("tab", name="排程中", exact=True).click()
    expect(page.locator(".publish-record").filter(has_text=post["caption"]).first).to_contain_text("排程中")
    capture("scheduled")
    call("cancel_schedule", {"post_id": post["id"]})
    post = call("get_publish_post", {"post_id": post["id"]})
    prep = call("prepare_publish", {"post_id": post["id"], "version": post["version"]})
    call("confirm_publish", {"post_id": post["id"], "confirmation_code": prep["confirmation_code"]})
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        result = call("get_publish_post", {"post_id": post["id"]})
        if result["status"] == "done":
            break
        time.sleep(0.1)
    assert result["status"] == "done"
    page.goto(origin + f"/?view=publish&brand_id={brand_id}")
    page.get_by_role("tab", name="發佈紀錄", exact=True).click()
    expect(page.locator(".publish-record").first).to_contain_text("成功")
    capture("history")
    checks.append("agentpost-draft-upload-schedule-confirm-source-widths")


if __name__ == "__main__":
    os.environ["AGENT_CONTENT_CHECK"] = "1"
    os.environ["PUBLISH_CHECK"] = "1"
    if "--serve" in sys.argv:
        serve()
    else:
        main(exercise=check_agent_content)

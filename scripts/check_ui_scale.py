"""全站尺寸：隔離資料、禁止外連、三種視窗與共用框架逐頁量測。"""

from runtime_tmp import (
    launch_chromium,
    cleanup,
    output_dir,
    runtime_check,
    stop_process,
    temporary_dir,
)

from ports import KEEP_ALIVE_SECONDS, browser_port
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.request
from datetime import timedelta
from pathlib import Path

from ui_navigation import navigate, open_settings

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))


@runtime_check
def main():
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
        FollowerSnapshot,
        Message,
        MetricSnapshot,
        Post,
        Staff,
        Thread,
    )
    from app.models.base import utc_now

    folder = temporary_dir()
    artifacts = output_dir()
    artifacts.mkdir(parents=True, exist_ok=True)
    port = browser_port()
    origin = f"http://127.0.0.1:{port}"
    password = secrets.token_urlsafe(32)
    env = {
        "DATABASE_PATH": str(folder / "test.db"),
        "FRONTEND_DIST_DIR": os.environ.get("FRONTEND_DIST_DIR", str(REPO / "frontend/dist")),
        "LOG_PATH": str(folder / "backend.jsonl"),
        "EXPORT_ROOT": str(folder / "export"),
        "EXPORT_WORKER_ENABLED": "false",
        "RECEIVE_HEALTH_WORKER_ENABLED": "false",
        "SCHEDULER_ENABLED": "false",
        "RECEIVE_HEALTH_ALERTS_ENABLED": "false",
        "APP_ORIGIN": origin,
        "ALLOWED_HOSTS": '["127.0.0.1"]',
        "SESSION_COOKIE_SECURE": "false",
        "ADMIN_INITIAL_PASSWORD": password,
        "COMMENTS_WAKE_ENABLED": "false",
        "OPENAI_API_KEY": "",
        "GEMINI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "JEV_API_KEY": "",
        "NOTIFY_LINE_CHANNEL_ACCESS_TOKEN": "",
    }
    env_path = folder / ".env"
    env_path.write_text(
        "\n".join(f"{k}='{v}'" for k, v in env.items()), encoding="utf-8"
    )
    os.environ.update(env)
    settings = Settings(_env_file=env_path)
    command.upgrade(Config(str(REPO / "backend/alembic.ini")), "head")
    engine = build_engine(settings)
    cleanup(engine.dispose)
    factory = session_factory(engine)
    now = utc_now()
    ids = {}
    with factory.begin() as session:
        seed_records(session, settings, include_content=False)
        brand = session.scalar(select(Brand).where(Brand.slug == "TEST"))
        for platform in ("facebook", "instagram"):
            account = Account(
                brand_id=brand.id,
                platform=platform,
                external_id="batch2-" + platform,
                name="[隔離驗收] " + ("FB" if platform == "facebook" else "IG"),
            )
            session.add(account)
            session.flush()
            for age, count in ((2, 1234570), (1, 1234571), (0, 1234567)):
                session.add(FollowerSnapshot(
                    account_id=account.id,
                    captured_at=now - timedelta(days=age, minutes=1),
                    followers_count=count,
                ))
            post = Post(
                account_id=account.id,
                external_id="post-" + platform,
                caption="[隔離驗收] 使用時遇到問題，諮詢前要先確認什麼？"
                if platform == "facebook"
                else "[隔離驗收] Reels：從使用者的提問，找出內容方向",
                media_type="REELS" if platform == "instagram" else "POST",
                published_at=now - timedelta(hours=1 if platform == "facebook" else 2),
            )
            session.add(post)
            session.flush()
            contact = Contact(
                brand_id=brand.id,
                platform=platform,
                external_id="audience-" + platform,
                display_name="驗收觀眾",
            )
            session.add(contact)
            session.flush()
            thread = Thread(
                brand_id=brand.id,
                account_id=account.id,
                contact_id=contact.id,
                kind="comment_thread",
                external_id="root-" + platform,
                post_id=post.id,
            )
            session.add(thread)
            session.flush()
            ids[platform] = post.id
            texts = [
                "使用半小時還有問題，是操作步驟有誤，還是需要調整設定？",
                "可以先記錄問題出現的時間，並提供畫面截圖，讓品牌客服協助確認。",
                "謝謝，我會先拍照。我剛開始使用，多久需要檢查一次？",
                "這是沒有可靠父留言紀錄的舊留言，保持獨立顯示。",
                "這則回覆的父留言尚未同步，不能猜測它屬於哪一串。",
            ]
            for index in range(205 if platform == "facebook" else 5):
                session.add(
                    Message(
                        thread_id=thread.id,
                        contact_id=contact.id,
                        external_id=f"{platform}-c{index}",
                        text="[隔離驗收] "
                        + (
                            texts[index]
                            if index < 5
                            else f"觀眾問題 {index}：想了解服務與日常保養的差別。"
                        ),
                        sent_at=now
                        - timedelta(days=40 if index >= 100 else 0, minutes=30)
                        + timedelta(seconds=index),
                        direction="out" if index == 1 else "in",
                        author_type="brand" if index == 1 else "fan",
                        comment_parent_known=index != 3,
                        comment_parent_id=f"{platform}-c{index - 1}"
                        if index in (1, 2)
                        else "missing"
                        if index == 4
                        else None,
                        comment_root_id=f"{platform}-c0" if index < 3 else None,
                    )
                )
            dm = Thread(
                brand_id=brand.id,
                account_id=account.id,
                contact_id=contact.id,
                kind="dm",
                external_id="ui-dm-" + platform,
                last_inbound_at=now,
            )
            session.add(dm)
            session.flush()
            session.add(
                Message(
                    thread_id=dm.id,
                    contact_id=contact.id,
                    external_id="ui-dm-in-" + platform,
                    direction="in",
                    author_type="fan",
                    text="[隔離驗收] 請問服務流程與可預約時間？",
                    sent_at=now,
                )
            )
            for index in range(4):
                session.add(
                    MetricSnapshot(
                        post_id=post.id,
                        captured_at=now - timedelta(hours=4 - index),
                        views=1234567
                        if platform == "instagram" and index == 3
                        else index * 120,
                        reach=index * 90 if index != 1 else None,
                        comments=index * 2,
                        likes=index * 3,
                        shares=0,
                        saves=None,
                    )
                )
        # Threads 與 FB／IG 同樣有粉絲快照與貼文成效，貼文數據頁的粉絲工具列才會顯示數字。
        threads = Account(
            brand_id=brand.id,
            platform="threads",
            external_id="batch2-threads",
            name="[隔離驗收] Threads",
        )
        session.add(threads)
        session.flush()
        for age, count in ((2, 5670), (1, 5675), (0, 5678)):
            session.add(FollowerSnapshot(
                account_id=threads.id,
                captured_at=now - timedelta(days=age, minutes=1),
                followers_count=count,
            ))
        threads_post = Post(
            account_id=threads.id,
            external_id="post-threads",
            caption="[隔離驗收] Threads：新品使用心得與常見問題整理",
            media_type="TEXT_POST",
            published_at=now - timedelta(hours=3),
        )
        session.add(threads_post)
        session.flush()
        for index in range(4):
            session.add(
                MetricSnapshot(
                    post_id=threads_post.id,
                    captured_at=now - timedelta(hours=4 - index),
                    views=index * 150,
                    comments=index,
                    likes=index * 4,
                    shares=index,
                )
            )
        session.flush()
        ids["comment_focus"] = session.scalar(
            select(Message.id).where(Message.external_id == "facebook-c204")
        )
    from stage3_fixture import seed_stage3
    stage3_report, stage3_script = seed_stage3(factory, origin)
    server_log = (folder / "server.log").open("w", encoding="utf-8")
    cleanup(server_log.close)
    server = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--serve",
            str(env_path),
            str(port),
        ],
        cwd=REPO / "backend",
        env={**os.environ, **env},
        stdout=server_log,
        stderr=server_log,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    cleanup(stop_process, server)
    results, errors, external = [], [], []
    shells, conversation_heights = [], []
    try:
        for _ in range(100):
            try:
                with urllib.request.urlopen(origin + "/api/health", timeout=1):
                    break
            except OSError:
                if server.poll() is not None:
                    raise RuntimeError("隔離後台啟動失敗") from None
                time.sleep(0.1)
        with sync_playwright() as pw:
            browser = launch_chromium(pw)
            context = browser.new_context()
            # Prove the detector catches both horizontal ellipsis and vertical hidden clipping.
            detector = context.new_page()
            detector_cases = []
            for name, style in [
                (
                    "ellipsis",
                    "width:45px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis",
                ),
                ("hidden-height", "width:100px;height:8px;overflow:hidden"),
            ]:
                detector.set_content(
                    '<div style="font-size:14px;'
                    + style
                    + '">隔離驗收狀態文字不可裁切</div>'
                )
                violations = detector.evaluate(MEASURE)["failures"]
                assert any("clipped" in item for item in violations), (name, violations)
                detector_cases.append(name)
            choice_detector_cases = []
            for kind in ("checkbox", "radio"):
                for direction, expected in (
                    ("column", "center difference"),
                    ("row-reverse", "left of label"),
                    ("row", None),
                ):
                    detector.set_content(
                        '<label style="display:flex;align-items:center;justify-content:flex-end;'
                        f'flex-direction:{direction};width:200px;font-size:14px;gap:10px">'
                        f'<input type="{kind}" style="width:16px;height:16px;margin:0">'
                        "<span>隔離測試選項</span></label>"
                    )
                    violations = [
                        v
                        for v in detector.evaluate(MEASURE)["failures"]
                        if "choice" in v
                    ]
                    if expected:
                        assert any(expected in v for v in violations), (
                            kind,
                            direction,
                            violations,
                        )
                    else:
                        assert not violations, (kind, direction, violations)
                    choice_detector_cases.append(f"{kind}-{direction}")
            padding_detector_cases = verify_padding_detector(detector)
            numeric_detector_cases = []
            for text in ("1,234,567", "942", "12.5%", "$1,234.50"):
                for wrap in (True, False):
                    detector.set_content(
                        '<div style="width:20px;overflow-wrap:anywhere;white-space:'
                        + ("normal" if wrap else "nowrap")
                        + '">'
                        + text
                        + "</div>"
                    )
                    assert bool(detector.evaluate(NUMBER_MEASURE)["failures"]) == wrap
                    numeric_detector_cases.append({"text": text, "wrap": wrap})
            detector.close()

            def guard(route):
                if route.request.url.endswith('/api/workspace/autostart'):
                    route.fulfill(json={"enabled": False, "supported": True, "task_name": "MWB-AutoStart", "code": None})
                    return
                if route.request.url.endswith('/api/workspace/status'):
                    route.fulfill(json={"autostart": {"enabled": False, "supported": True, "task_name": "MWB-AutoStart", "code": None}})
                    return
                if route.request.url.startswith(origin + "/"):
                    route.continue_()
                else:
                    external.append(route.request.url.split("?")[0])
                    route.abort()

            context.route("**/*", guard)
            draft_state = {"value": None, "hold": False, "needs_edit": False}
            pending = []

            def mock_options(route):
                response = route.fetch()
                data = response.json()
                if route.request.method == "GET":
                    for option in data["options"]:
                        if option["provider"] == "gemini_api":
                            option.update(
                                available=True, reason=None, model="isolated-ui-mock"
                            )
                route.fulfill(response=response, json=data)

            context.route("**/api/ai/settings?*", mock_options)
            context.route("**/api/ai/execution-options?*", mock_options)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))

            def capture(name, width, height, idle=True):
                if idle:
                    page.wait_for_load_state("networkidle")
                # Wait for React layout and finite panel animations before measuring visible text.
                page.evaluate("""async () => {
                    await document.fonts.ready;
                    await new Promise(resolve => requestAnimationFrame(() =>
                        requestAnimationFrame(resolve)));
                    await Promise.all(document.getAnimations().filter(a =>
                        a.effect?.getTiming().iterations !== Infinity)
                        .map(a => a.finished.catch(() => {})));
                }""")
                # Includes below-fold content in scroll containers and expanded details.
                value = page.evaluate(MEASURE)
                tokens = page.evaluate(TOKEN_MEASURE)
                value["tokens"] = tokens
                value["assertions"] += tokens["assertions"]
                value["failures"].extend(tokens["failures"])
                padding = page.evaluate(PADDING_MEASURE)
                value["padding"] = padding
                value["assertions"] += padding["assertions"]
                value["failures"].extend(padding["failures"])
                numbers = page.evaluate(NUMBER_MEASURE)
                value["numbers"] = numbers
                value["assertions"] += numbers["assertions"]
                value["failures"].extend(numbers["failures"])
                if name in SHELL_PAGES:
                    shell = page.evaluate(SHELL_MEASURE)
                    shells.append(
                        {"page": name, "width": width, "height": height, **shell}
                    )
                page.mouse.move(width - 1, height - 1)
                shot = f"{name}-{width}x{height}.png"
                page.screenshot(path=str(artifacts / shot))
                results.append(
                    {
                        "page": name,
                        "width": width,
                        "height": height,
                        "screenshot": shot,
                        **value,
                    }
                )

            for width, height in [(1440, 900), (1609, 914), (390, 844)]:
                page.set_viewport_size({"width": width, "height": height})
                draft_state.update(value=None, hold=False, needs_edit=False)
                page.goto(origin)
                page.locator(".login-panel, .workspace").wait_for(state="visible")
                if page.get_by_label("帳號", exact=True).is_visible():
                    capture("login", width, height)
                    page.get_by_label("帳號", exact=True).fill("admin")
                    page.get_by_label("密碼", exact=True).fill(password)
                    page.get_by_role("button", name="登入工作檯").click()
                expect(page.locator(".dashboard-kpis .kpi strong").first).to_be_visible()
                for label, name, selector in [
                    ("儀表板", "dashboard", ".dashboard-page"),
                    ("貼文數據", "posts", ".posts-panel"),
                    ("訊息分類", "classification", ".classification-settings"),
                    ("AI 設定", "ai-settings", ".ai-settings-page"),
                    ("主題發想", "ideation", ".ideation-page"),
                    ("工作區設定", "workspace-settings", ".general-settings"),
                ]:
                    navigate(page, label)
                    expect(page.locator(selector)).to_be_visible()
                    if name == "dashboard":
                        expect(page.locator(".dashboard-kpis .kpi").first.locator("strong")).to_be_visible()
                    if name == "classification":
                        expect(page.get_by_role("button", name="儲存", exact=True)).to_be_visible()
                    if name == "ai-settings":
                        page.get_by_role("tab", name="AI 金鑰", exact=True).click()
                        expect(page.locator(".key-overview > div")).to_have_count(3)
                        capture("ai-keys", width, height)
                        # 本機 CLI 已移除：只剩基本、品牌說明、AI 金鑰三個分頁，頁面也沒有 CLI 區塊。
                        expect(page.get_by_role("tablist", name="AI 設定", exact=True)
                               .get_by_role("tab")).to_have_text(["基本", "品牌說明", "AI 金鑰"])
                        expect(page.get_by_role("tab", name="本機 CLI", exact=True)).to_have_count(0)
                        expect(page.locator(".cli-entry,.local-cli-settings")).to_have_count(0)
                        page.get_by_role("tab", name="品牌說明", exact=True).click()
                        expect(
                            page.locator(".prompt-editor textarea").first
                        ).to_be_visible()
                        capture("ai-prompt", width, height)
                        page.get_by_role("tab", name="基本", exact=True).click()
                        expect(page.get_by_label("每月 API 預算（美元）")).to_be_visible()
                    if name == "workspace-settings":
                        # uiorder：工作區不再有自己的品牌選單，改用側邊欄品牌。
                        expect(page.locator(".general-settings .brand-toolbar")).to_have_count(0)
                        expect(page.get_by_role("button", name="儲存品牌設定")).to_have_count(0)
                        expect(page.locator("details.workspace-group[open]")).to_have_count(5)
                        expect(page.locator(".routing-table")).to_have_count(0)
                    if name == "posts":
                        expect(page.locator(".post-card").first).to_be_visible()
                    capture(name, width, height)
                    if name == "ideation":
                        page.locator(".ideation-actions button").filter(
                            has_text=f"#{stage3_report} ·"
                        ).click()
                        expect(page.locator(".ideation-card")).to_be_visible()
                        page.locator(".ideation-card").scroll_into_view_if_needed()
                        capture("ideation-report", width, height)
                        page.locator(".ideation-actions button").filter(
                            has_text=f"#{stage3_script} [隔離驗收]"
                        ).click()
                        page.locator(".script-editor").scroll_into_view_if_needed()
                        expect(
                            page.get_by_role("heading", name="腳本編輯", exact=False)
                        ).to_be_visible()
                        capture("ideation-script", width, height)
                        page.locator(".script-shot").first.scroll_into_view_if_needed()
                        capture("ideation-storyboard", width, height)
                        page.get_by_label("拍攝備註", exact=True).fill(
                            "隔離驗收：修改拍攝說明，品牌資料為歷史參考，待品牌覆核"
                        )
                        page.get_by_role("button", name="儲存版本並重新檢查").click()
                        expect(page.get_by_role("button", name="儲存版本並重新檢查")).to_be_enabled(
                            timeout=15000
                        )
                        expect(page.locator(".script-editor")).to_contain_text("jev 檢查不可用")
                        page.locator(".script-editor").scroll_into_view_if_needed()
                        capture("ideation-script-rechecked", width, height)
                        page.locator(selector).evaluate("e => e.scrollTop = 0")
                    if name in (
                        "dashboard",
                        "ai-settings",
                                            "workspace-settings",
                    ):
                        page.locator(selector).evaluate(
                            "e => e.scrollTop = e.scrollHeight"
                        )
                        capture(name + "-bottom", width, height)
                        page.locator(selector).evaluate("e => e.scrollTop = 0")
                    if name == "workspace-settings":
                        from check_csv_ui import exercise_csv

                        exercise_csv(page, width, height, capture)
                        expect(page.get_by_role("heading", name="緊急回覆權限", exact=True)).to_have_count(0)
                        expect(page.get_by_role("region", name="歷史私訊補抓")).to_have_count(0)
                        expect(page.get_by_role("heading", name="匯出資料夾", exact=True)).to_be_visible()
                        capture("comment-data-tools", width, height)
                        page.locator(selector).evaluate("e => e.scrollTop = 0")
                    if name == "posts":
                        page.locator(".post-card").first.click()
                        expect(page.locator(".comment-text").first).to_be_visible()
                        capture("posts-detail", width, height)
                        page.locator(
                            ".post-detail" if width < 600 else ".post-metrics"
                        ).evaluate("e => e.scrollTop = e.scrollHeight")
                        capture("posts-metrics", width, height)
                        page.goto(origin + f"?view=posts&post_id={ids['instagram']}")
                        expect(page.locator(".metric-grid strong").first).to_have_text(
                            "1,234,567"
                        )
                        page.locator(".metric-grid").first.scroll_into_view_if_needed()
                        capture("post-performance", width, height)
                        page.locator(".post-metrics").screenshot(
                            path=str(
                                artifacts
                                / f"post-performance-section-{width}x{height}.png"
                            )
                        )
                page.goto(origin + "?view=posts")
                follower_panel = page.get_by_role("region", name="粉絲數", exact=True)
                expect(follower_panel.locator("dd").first).to_have_text("1,234,567")
                expect(follower_panel.locator("select")).to_have_count(3)
                expect(follower_panel.locator(".follower-stats > div")).to_have_count(3)
                # 發文日期篩選併入粉絲數列（e92902b），位於期間與統計之間。
                assert follower_panel.evaluate("e => [...e.children].map(c => c.className)") == [
                    "follower-period",
                    "post-date-filter",
                    "follower-stats",
                ]
                # uiorder：「粉絲數期間」小標在年月週下拉上方，下拉仍同列。
                assert follower_panel.locator(".follower-period > *").evaluate_all(
                    "es => es.map(e => e.className)"
                ) == ["follower-period-label", "follower-filter"]
                # 日期欄位屬於併入的發文日期篩選，其餘區塊仍不放說明文字或額外控制項。
                assert follower_panel.evaluate(
                    "e => [...e.querySelectorAll('p, h3, svg, input, details, time, label')]"
                    ".filter(x => !x.closest('.post-date-filter')).length"
                ) == 0
                assert follower_panel.locator("dt").all_text_contents() == [
                    "粉絲數",
                    "本週",
                    "本月",
                ]
                assert follower_panel.evaluate(
                    "e => e.scrollHeight <= e.clientHeight + 1 && "
                    "!['auto','scroll','hidden','clip'].includes(getComputedStyle(e).overflowY)"
                )
                # 工具列精簡：桌面一列（控制項高度＋上下內距），窄螢幕最多兩列。
                # uiorder：扣掉新增的「粉絲數期間」小標列（小標高度＋6px 間距），原本的列數與高度門檻不變。
                # 窄於 1100 時併入的發文日期自成一列（e92902b），同 check_followers_frontend 扣掉該列與 8px 列距。
                panel_height = follower_panel.evaluate(
                    "e => e.getBoundingClientRect().height"
                    " - e.querySelector('.follower-period-label').getBoundingClientRect().height - 6"
                    " - (innerWidth <= 1100 ? e.querySelector('.post-date-filter').getBoundingClientRect().height + 8 : 0)"
                )
                assert panel_height <= (66 if width >= 1100 else 2 * 40 + 24 + 2 + 16), (width, panel_height)
                if width == 1440:
                    page.locator(".post-card").first.click()
                    expect(page.locator(".comment-text").first).to_be_visible()
                    expect(page.locator(".metric-grid strong").first).to_have_text("360")
                    page.wait_for_load_state("networkidle")
                    page.evaluate("async () => { await document.fonts.ready; await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); }")
                    # 改版前同視窗三欄容器 474px；三欄各增加至少 150px，欄寬規則維持不變。
                    columns = page.locator(".post-list,.post-conversation,.post-metrics").evaluate_all(
                        "es => es.map(e => ({height:e.getBoundingClientRect().height,width:e.getBoundingClientRect().width}))"
                    )
                    assert len(columns) == 3 and all(c["height"] >= 624 for c in columns), columns
                    # 依文件順序為列表、成效（中間、最寬）、貼文摘要與留言（postcenter）。
                    assert columns[0]["width"] == 280 and columns[2]["width"] == 360, columns
                    assert columns[1]["width"] > columns[2]["width"], columns
                    print("FOLLOWERS_COLUMNS", json.dumps(columns))
                capture("followers-facebook", width, height)
                tabs = page.get_by_role("tablist", name="貼文平台", exact=True)
                tabs.get_by_role("tab", name="IG", exact=True).click()
                expect(follower_panel.locator("dd").first).to_have_text("1,234,567")
                expect(tabs.get_by_role("tab", name="FB", exact=True)).to_have_attribute(
                    "aria-selected", "false"
                )
                capture("followers-instagram", width, height)
                follower_panel.get_by_label("月份", exact=True).select_option("1")
                expect(follower_panel.locator("dt").nth(1)).to_have_text("該週")
                expect(follower_panel.locator("dt").nth(2)).to_have_text("該月")
                expect(follower_panel.locator("dd").nth(1)).to_have_text("—")
                expect(follower_panel.locator("dd").nth(2)).to_have_text("—")
                expect(follower_panel.locator("dd").first).to_have_text("1,234,567")
                capture("followers-past-empty", width, height)
                # Threads 有粉絲數與貼文，工具列與 FB／IG 相同。
                tabs.get_by_role("tab", name="Threads", exact=True).click()
                expect(follower_panel.locator("dd").first).to_have_text("5,678")
                expect(follower_panel.locator("select")).to_have_count(3)
                expect(follower_panel.locator("dt")).to_have_text(["粉絲數", "本週", "本月"])
                expect(page.locator(".post-card")).to_have_count(1)
                if width == 1440:
                    page.locator(".post-card").first.click()
                    expect(page.locator(".metric-grid strong").first).to_have_text("450")
                capture("followers-threads", width, height)
                # 尚未串接的平台精簡成一行提示。
                for label in ("YouTube", "TikTok"):
                    tabs.get_by_role("tab", name=label, exact=True).click()
                    noun = "訂閱數" if label == "YouTube" else "粉絲數"
                    unconnected = page.get_by_role("region", name=noun, exact=True)
                    # 未串接時發文日期篩選仍保留在同一面板（e92902b），只核對提示本身。
                    expect(unconnected.locator(".follower-unconnected")).to_have_text(
                        "尚未串接，串接後開始記錄" + noun
                    )
                    expect(unconnected.locator("select,dl")).to_have_count(0)
                    capture("followers-" + label.lower(), width, height)
                page.goto(
                    origin
                    + f"?view=posts&post_id={ids['facebook']}&comment_id={ids['comment_focus']}"
                )
                focused = page.locator(f"[data-message-id='{ids['comment_focus']}']")
                expect(focused).to_be_visible()
                expect(focused).to_have_class("post-comment focused-comment")
                assert page.locator(".post-comment").count() <= 53
                capture("comment-deep-link", width, height)
                # A failed backend probe must remain visible on every page, including phone detail.
                outage = {
                    "interrupted": True,
                    "message": "收訊通道中斷：新留言可能無法收到",
                    "last_ok_at": now.isoformat(),
                    "checked_at": now.isoformat(),
                    "stale": False,
                    "monitor_enabled": True,
                    "alerts_enabled": False,
                    "history": [],
                }
                context.route(
                    "**/api/receive-health",
                    lambda route, _request, value=outage: route.fulfill(json=value),
                )
                page.goto(origin)
                page.locator(".login-panel, .workspace").wait_for(state="visible")
                expect(page.locator(".receive-banner")).to_be_visible()
                capture("health-dashboard", width, height)
                for label, name in [
                    ("儀表板", "dashboard"),
                    ("貼文數據", "posts"),
                    ("訊息分類", "classification"),
                    ("AI 設定", "ai-settings"),
                    ("主題發想", "ideation"),
                    ("工作區設定", "settings"),
                ]:
                    navigate(page, label)
                    expect(page.locator(".receive-banner")).to_be_visible()
                    capture("health-" + name, width, height)
                context.unroute("**/api/receive-health")
                if width < 600:
                    open_settings(page)
                page.get_by_role("button", name="登出", exact=True).click()
                expect(page.get_by_label("帳號", exact=True)).to_be_visible()
            browser.close()
        failures = [
            {"page": r["page"], "width": r["width"], "failures": r["failures"]}
            for r in results
            if r["failures"]
        ]
        shell_assertions, shell_failures = compare_shells(shells)
        failures.extend(shell_failures)
        padding_assertions, padding_failures = compare_padding(results)
        failures.extend(padding_failures)
        make_comparisons(artifacts)
        report = {
            "viewports": [[1440, 900], [1609, 914], [390, 844]],
            "baseline": "13ced20",
            "fixture": "隔離驗收資料，非真實營運數據",
            "measurements": results,
            "shell_measurements": shells,
            "conversation_heights": conversation_heights,
            "screenshots": len(results),
            "assertions": sum(r["assertions"] for r in results)
            + shell_assertions
            + padding_assertions,
            "padding_assertions": sum(r["padding"]["assertions"] for r in results)
            + padding_assertions,
            "padding_violations": [
                {"page": r["page"], "width": r["width"], **v}
                for r in results
                for v in r["padding"]["violations"]
            ],
            "shell_assertions": shell_assertions,
            "clipping_detector_cases": detector_cases,
            "choice_detector_cases": choice_detector_cases,
            "padding_detector_cases": padding_detector_cases,
            "numeric_detector_cases": numeric_detector_cases,
            "failures": failures,
            "page_errors": errors,
            "external_requests": external,
        }
        (artifacts / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    k: report[k]
                    for k in (
                        "screenshots",
                        "assertions",
                        "failures",
                        "page_errors",
                        "external_requests",
                    )
                },
                ensure_ascii=True,
            )
        )
        assert not failures and not errors and not external
    finally:
        stop_process(server)
        server_log.close()
        engine.dispose()


SHELL_PAGES = (
    "posts",
    "dashboard",
    "classification",
    "ai-settings",
    "workspace-settings",
    "ideation",
)

NUMBER_MEASURE = (REPO / "scripts/ui_numbers.js").read_text(encoding="utf-8")
PADDING_MEASURE = (REPO / "scripts/ui_padding.js").read_text(encoding="utf-8")
TOKEN_MEASURE = (REPO / "scripts/ui_tokens.js").read_text(encoding="utf-8")


def verify_padding_detector(page):
    cases = []
    for width in (1440, 390):
        page.set_viewport_size({"width": width, "height": 900})
        good = 16 if width < 600 else 24
        for name, content, fails in (
            ("flush", '<div style="background:#eee">visible text</div>', True),
            (
                "inset",
                f'<div style="background:#eee;padding:0 {good}px">visible text</div>',
                False,
            ),
            (
                "nested",
                f'<div style="background:#eee;padding:0 {good}px">'
                '<div style="border:1px solid">nested text</div></div>',
                True,
            ),
            ("border-only", '<div style="border:1px solid">border text</div>', True),
            (
                "inline-comment-window",
                f'<div style="background:#eee;padding:0 {good}px">'
                '<div class="post-date-filter ideation-comment-window">range</div></div>',
                False,
            ),
            (
                "inline-comment-window-extra-inset",
                f'<div style="background:#eee;padding:0 {good}px">'
                '<div class="post-date-filter ideation-comment-window" '
                f'style="padding:0 {good}px">range</div></div>',
                True,
            ),
            (
                "inline-comment-window-painted",
                f'<div style="background:#eee;padding:0 {good}px">'
                '<div class="post-date-filter ideation-comment-window" '
                'style="background:#fff">range</div></div>',
                True,
            ),
            ("ideation-chip-small", '<span class="ideation-chip" style="display:inline-block;'
             'background:#eee;padding:0 8px">keyword</span>', False),
            ("ideation-chip-missing-padding", '<span class="ideation-chip" '
             'style="display:inline-block;background:#eee;padding:0">keyword</span>', True),
            ("ideation-notice-inset", '<p class="legacy-note ideation-notice warning" '
             'style="background:#eee;padding:12px 16px">notice</p>', False),
            ("ideation-notice-missing-inset", '<p class="legacy-note ideation-notice warning" '
             'style="background:#eee;padding:0">notice</p>', True),
            (
                "card-button",
                '<button class="post-card" style="background:#eee;padding:0">card text</button>',
                True,
            ),
            (
                "controls-badges",
                '<div style="background:#eee"><button>action</button><input value="field">'
                '<span class="state">badge</span></div>',
                False,
            ),
            (
                "hidden",
                '<div style="display:none;background:#eee">hidden text</div>',
                False,
            ),
            (
                "wrapped",
                f'<div style="background:#eee;padding:0 {good}px;width:90px">'
                "visible text over several lines</div>",
                False,
            ),
        ):
            page.set_content(
                '<div class="workspace"><main>' + content + "</main></div>"
            )
            result = page.evaluate(PADDING_MEASURE)
            assert bool(result["failures"]) == fails, (width, name, result)
            cases.append(f"{width}-{name}")
    for spread, fails in ((2, False), (3, True)):
        result = [
            {
                "width": 1440,
                "padding": {
                    "containers": [{"kind": "panel", "left": 24, "right": 24 + spread}]
                },
            }
        ]
        assert bool(compare_padding(result)[1]) == fails
        cases.append(f"spread-{spread}")
    return cases


def compare_padding(results):
    groups = {}
    for result in results:
        for row in result["padding"]["containers"]:
            groups.setdefault((result["width"], row["kind"]), []).append(row)
    failures = []
    for (width, kind), rows in groups.items():
        values = [row[side] for row in rows for side in ("left", "right")]
        if max(values) - min(values) > 2:
            failures.append(
                {"padding": f"{width}/{kind}: spread {max(values) - min(values)}px"}
            )
    return len(groups), failures


SHELL_MEASURE = r"""() => {
    const rect = selector => {
        const e = document.querySelector(selector); if (!e) return null; const r = e.getBoundingClientRect();
        return {left:r.left, top:r.top, width:r.width, height:r.height,
            font:parseFloat(getComputedStyle(e).fontSize)};
    };
    const header = document.querySelector('.page-header');
    const container = header.parentElement;
    const content = document.querySelector('.inbox-column,.posts-layout')
        || header.nextElementSibling;
    const title = rect('.page-header h1');
    const actions = [...header.querySelectorAll('button')].map(e => {
        const r=e.getBoundingClientRect(), h=header.getBoundingClientRect();
        return r.top >= h.top && r.bottom <= h.bottom && r.right <= h.right && r.left >= h.left;
    });
    const top = header.getBoundingClientRect().top;
    const empty_actions = [...header.querySelectorAll('.page-actions')].filter(e => !e.children.length && !e.textContent.trim() && e.getBoundingClientRect().height > 0).length;
    const fill = Math.max(...[...header.children].map(e => e.getBoundingClientRect().bottom)) - top;
    return {sidebar:rect('.sidebar'),
        nav:[...document.querySelectorAll(innerWidth < 600 ? '.mobile-bottom-nav button' : '.workspace-nav button')].map(e => ({
            font:parseFloat(getComputedStyle(e).fontSize),
            height:e.getBoundingClientRect().height})),
        brand:rect('.sidebar .wordmark'), user:rect('.user-card'), footer:rect('.sidebar-note'),
        menu:innerWidth < 600 ? rect('.mobile-bottom-nav') : {left:0,top:0,height:0}, logout:rect(innerWidth < 600 ? '.mobile-logout' : '.user-card button'),
        header:rect('.page-header'), header_fill:fill, empty_actions, title, content_x:content.getBoundingClientRect().left,
        padding_left:parseFloat(getComputedStyle(container).paddingLeft),
        padding_right:parseFloat(getComputedStyle(container).paddingRight),
        header_count:document.querySelectorAll('.page-header').length,
        brand_input:rect(innerWidth < 600 ? '.mobile-brand-picker select' : '.brand-picker select'),
        h1_count:document.querySelectorAll('.workspace h1').length,
        actions_fit:actions.every(Boolean),
        taglines:header.querySelectorAll('.eyebrow').length};
}"""


def compare_shells(shells):
    count, failures = 0, []

    def check(pass_, message):
        nonlocal count
        count += 1
        if not pass_:
            failures.append({"shell": message})

    def near(a, b):
        return abs(a - b) <= 1

    for width in (1440, 1609, 390):
        group = [row for row in shells if row["width"] == width and row["page"] != "ideation"]
        check(len(group) == len(SHELL_PAGES) - 1, f"{width}: five primary pages measured")
        check({row['page'] for row in group} == set(SHELL_PAGES) - {'ideation'}, f"{width}: page coverage")
        additions = [row for row in shells if row["width"] == width and row["page"] == "ideation"]
        check(len(additions) == 1, f"{width}: ideation page measured")
        baseline = group[0]
        for row in group + additions:
            label = f"{width}/{row['page']}"
            for key in ("header_count", "h1_count"):
                check(row[key] == 1, f"{label}: {key}")
            check(
                row["actions_fit"] and row["taglines"] == 0, f"{label}: header contents"
            )
            for key in ("content_x", "padding_left", "padding_right"):
                check(near(row[key], baseline[key]), f"{label}: {key} differs")
            check(
                near(row["content_x"], 16 if width < 600 else 252),
                f"{label}: content origin",
            )
            check(
                near(row["padding_left"], 16 if width < 600 else 32),
                f"{label}: content padding",
            )
            for key, fields in {
                "sidebar": ("width", "height"),
                # 手機頁首高度隨內容（有無動作列）變化，另外檢查不留多餘空白。
                "header": ("left", "top") if width < 600 else ("height", "left", "top"),
                "title": ("left", "top", "font", "height"),
                "brand": ("left", "top", "font", "height"),
                "user": ("left", "top", "height"),
                "footer": ("left", "top", "font", "height"),
                "menu": ("left", "top", "height"),
                "logout": ("left", "top", "height", "font"),
            }.items():
                if width < 600 and key == "logout":
                    check(row[key] is not None, f"{label}: logout on every mobile page")
                    if row[key]:
                        check(near(row[key]["height"], 36) and near(row[key]["font"], 14), f"{label}: logout control tokens")
                    continue
                for field in fields:
                    check(
                        near(row[key][field], baseline[key][field]),
                        f"{label}: {key}.{field} differs",
                    )
            check(
                near(row["sidebar"]["width"], width if width < 600 else 220),
                f"{label}: sidebar width",
            )
            if width < 600:
                check(
                    row["header"]["height"] - row["header_fill"] <= 17,
                    f"{label}: mobile header has no blank space",
                )
                check(row["empty_actions"] == 0, f"{label}: no empty action row on mobile")
            else:
                check(near(row["header"]["height"], 96), f"{label}: header height")
            check(near(row["title"]["font"], 26), f"{label}: title font")
            if width < 600:
                # uiorder：單一品牌時手機沒有品牌選單（選單字級改在 check_brand_scope 的多品牌情境驗證）。
                check(row["brand_input"] is None, f"{label}: no mobile brand input for a single brand")
                check(
                    near(row["sidebar"]["height"], 56), f"{label}: mobile topbar height"
                )
            for nav in row["nav"]:
                check(near(nav["font"], 14), f"{label}: nav font")
                check(near(nav["height"], 44), f"{label}: nav height")
    return count, failures


def make_comparisons(artifacts):
    import base64

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = launch_chromium(pw)
        page = browser.new_page()
        for width, height in ((1440, 900), (1609, 914), (390, 844)):
            strips = []
            for name in SHELL_PAGES:
                data = base64.b64encode(
                    (artifacts / f"{name}-{width}x{height}.png").read_bytes()
                ).decode()
                strips.append(
                    f'<div class="label">{name}</div><img src="data:image/png;base64,{data}">'
                )
            page.set_viewport_size({"width": width, "height": 224 * len(SHELL_PAGES)})
            page.set_content(
                "<style>body{margin:0}.label{height:24px;font:14px sans-serif}"
                "img{display:block;width:100%;height:200px;object-fit:none;"
                "object-position:top left}</style>" + "".join(strips)
            )
            page.locator("img").evaluate_all(
                "els => Promise.all(els.map(e => e.decode()))"
            )
            page.screenshot(
                path=str(artifacts / f"headers-{width}x{height}.png"), full_page=True
            )
        browser.close()


MEASURE = r"""() => {
    const rows = [], failures = [], counts = {}, sizes = {};
    let assertions = 0;
    const check = (pass, message) => { assertions++; if (!pass) failures.push(message); };
    const rendered = e => {
        if (e.closest('.sr-only, [aria-hidden=true]')) return false;
        for (let a=e; a; a=a.parentElement) {
            const style=getComputedStyle(a);
            if (style.clip === 'rect(0px, 0px, 0px, 0px)'
                || style.clipPath === 'inset(100%)') return false;
        }
        const s = getComputedStyle(e), r = e.getBoundingClientRect();
        return s.visibility !== 'hidden' && s.display !== 'none' && r.width > 0 && r.height > 0
            && !e.closest('details:not([open]) > :not(summary)');
    };
    const label = e => e.tagName.toLowerCase()
        + (e.classList.length ? '.' + [...e.classList].join('.') : '');
    const near = (a, b) => Math.abs(a - b) <= 1;
    const minimum = (e, s, suffix='') => {
        const font = parseFloat(s.fontSize);
        let scale = 1;
        if (e instanceof SVGTextElement) scale = Math.abs(e.getScreenCTM().a);
        check(font * scale >= 11.99, `${label(e)}${suffix}: minimum ${font * scale}px`);
    };
    for (const e of document.querySelectorAll('body *')) {
        if (!rendered(e)) continue;
        const s = getComputedStyle(e), r = e.getBoundingClientRect();
        if (e.matches('input[type=checkbox],input[type=radio]')) {
            const textBoxes = [];
            for (const owner of e.labels || []) {
                const walker = document.createTreeWalker(owner, NodeFilter.SHOW_TEXT);
                while (walker.nextNode()) {
                    const node = walker.currentNode;
                    if (!node.textContent.trim() || !rendered(node.parentElement)) continue;
                    const range = document.createRange(); range.selectNodeContents(node);
                    textBoxes.push(...range.getClientRects());
                }
            }
            const firstLine = textBoxes.find(box => box.width > 0 && box.height > 0);
            check(!!firstLine, `${label(e)}: choice has visible label text`);
            if (firstLine) {
                const delta = Math.abs(r.top + r.height / 2 - firstLine.top - firstLine.height / 2);
                check(delta <= 6, `${label(e)}: choice label center difference ${delta}px`);
                check(r.right <= firstLine.left, `${label(e)}: choice must be left of label text`);
                rows.push({element:label(e),role:'choice',centerDifference:delta,
                    right:r.right,textLeft:firstLine.left});
            }
        }
        const directText = [...e.childNodes].some(
            n => n.nodeType === Node.TEXT_NODE && n.textContent.trim());
        const labelledEllipsis = e.matches('.ideation-post-caption') && s.textOverflow === 'ellipsis'
            && e.title === e.textContent && e.title.length > 0;
        if (directText) minimum(e, s);
        if (directText && e instanceof HTMLElement && !e.matches('option,textarea,input')) {
            if (e.clientWidth) check(e.scrollWidth <= e.clientWidth + 1 || labelledEllipsis,
                `${label(e)}: clipped width ${e.scrollWidth}/${e.clientWidth}`);
            for (const node of e.childNodes) {
                if (node.nodeType !== Node.TEXT_NODE || !node.textContent.trim()) continue;
                const range = document.createRange(); range.selectNodeContents(node);
                for (const text of range.getClientRects()) {
                    let scrollX = false, scrollY = false;
                    for (let a=e; a; a=a.parentElement) {
                        const style=getComputedStyle(a), box=a.getBoundingClientRect();
                        if (['auto','scroll'].includes(style.overflowX)) scrollX=true;
                        if (['auto','scroll'].includes(style.overflowY)) scrollY=true;
                        if (!scrollX && ['hidden','clip'].includes(style.overflowX))
                            check((text.left >= box.left-1 && text.right <= box.right+1) || labelledEllipsis,
                                `${label(e)}: text clipped horizontally by ${label(a)}`);
                        if (!scrollY && ['hidden','clip'].includes(style.overflowY))
                            check(text.top >= box.top-1 && text.bottom <= box.bottom+1,
                                `${label(e)}: text clipped vertically by ${label(a)}`);
                    }
                }
            }
        }
        for (const pseudo of ['::before', '::after']) {
            const p = getComputedStyle(e, pseudo);
            if (p.content && !['none','normal','""',"''"].includes(p.content)) minimum(e,p,pseudo);
        }
        if (['auto','scroll'].includes(s.overflowX)) {
            check(e.scrollWidth <= e.clientWidth + 1 || (e.matches('.segmented-control,.tabs,.ideation-platform-tabs')
                && e.getBoundingClientRect().right <= innerWidth && e.clientWidth > 0),
                 `${label(e)}: horizontal overflow ${e.scrollWidth}/${e.clientWidth}`);
        }
        if (e.closest('.sidebar')) continue;
        let role, expectedFont, expectedHeight;
        const control = e.matches('input:not([type=checkbox]):not([type=radio]),select,textarea');
        const card = e.matches('.conversation,.post-card,.ranked-post,.settings-shortcuts button');
        if (control) {
            role = e.tagName === 'TEXTAREA' ? 'textarea' : 'input';
            expectedFont = innerWidth < 600 || e.matches('.reply-composer > textarea') ? 16 : 14;
            if (role === 'input') expectedHeight = 40;
        } else if (e.matches('button') && !card) {
            role = e.matches(['.filter-choice button,.mode-switch button,.stage-buttons button',
                '.color-buttons button,.post-platforms button,.mobile-filter-button'].join(','))
                ? 'small-button' : 'button';
            expectedFont = 14; expectedHeight = role === 'small-button' ? 32 : 36;
            if (e.matches('.segmented-control [role=radio],.segmented-control [role=tab]')) { role = 'segmented-radio'; expectedFont = 13; expectedHeight = 40; }
            // 工具列內嵌篩選（粉絲數列的發文日期）：整組外框對齊下拉的 40px，扣掉 3px 內距與框線後按鈕為 32px（UI規格例外）。
            if (e.matches('.follower-panel .post-date-filter .segmented-control [role=radio]')) { role = 'segmented-radio-toolbar'; expectedHeight = 32; }
            if (e.matches('.tabs [role=tab]')) { role = 'underline-tab'; expectedFont = 14; expectedHeight = 40; }
            if (e.matches('.credential-controls button,.credential-status button')) expectedHeight = 40;
            if (e.matches('.report-row .danger')) { role = 'report-delete'; expectedFont = 13; expectedHeight = 32; }
            if (e.matches('.report-select')) { expectedFont = innerWidth < 600 ? 12 : 13; }
            if (e.matches('.ideation-execution-row button,.ideation-platform-tabs button')) { expectedHeight = 40; }
            if (e.matches('.ideation-post-expand')) { expectedFont = 18; expectedHeight = 32; }
            if (e.closest('.mobile-bottom-nav,.mobile-more-nav')) { role = 'navigation-button'; expectedHeight = 44; }
            if (e.matches('.follower-hint button')) { role = 'icon-button'; expectedFont = 12; expectedHeight = 18; }
        } else if (e.matches('.stat-tile > strong,.stat-tile > dd')) { role = 'stat-value'; expectedFont = e.matches('.category-kpi') ? 18 : 28;
        } else if (e.matches('h1,.login-panel h2')) { role = 'page-title'; expectedFont = 26;
        } else if (e.matches('h2,h3')) { role = 'section-title'; expectedFont = 18;
        } else if (e.matches('.bubble p,.comment-text')) { role = 'conversation'; expectedFont = 16;
        } else if (e.matches(['.conversation-copy > p,.settings-page > p,.settings-page label',
            '.post-card strong,.brand-people p,.intent-bars>div>div'].join(','))) {
            role = 'body'; expectedFont = e.matches('.ideation-step label,.section-card label,.brand-toolbar label') ? 13 : 14;
        } else if (directText && !e.closest('button,svg')
            && e.matches('p,label,td,th,strong,small,span,time,pre,code,summary')) {
            role = 'text';
        }
        if (!role) continue;
        const font = parseFloat(s.fontSize), height = r.height;
        if (expectedFont) check(near(font, expectedFont),
             `${label(e)}: ${role} font ${font} expected ${expectedFont}`);
        else check([12,13,14,16,18,26].some(n => near(font,n)), `${label(e)}: text font ${font}`);
        if (expectedHeight) check(near(height, expectedHeight),
             `${label(e)}: ${role} height ${height} expected ${expectedHeight}`);
        counts[role] = (counts[role] || 0) + 1;
        sizes[role] ||= {font: new Set(), height: new Set()};
        sizes[role].font.add(font); sizes[role].height.add(Math.round(height*100)/100);
        rows.push({element:label(e),role,font,height:Math.round(height*100)/100,expectedFont,expectedHeight});
    }
    check(document.documentElement.scrollWidth <= innerWidth, 'document horizontal overflow');
    for (const [role,value] of Object.entries(sizes)) sizes[role] = {
        font:[...value.font].sort((a,b)=>a-b),
        height:[...value.height].sort((a,b)=>a-b)};
    return {sizes,counts,rows,assertions,failures};
}"""


def serve():
    import uvicorn

    from app.config import Settings
    from app.main import create_app

    # Never inherit the workstation's provider credentials into acceptance screenshots.
    settings = Settings(
        _env_file=sys.argv[2],
        openai_api_key=None,
        gemini_api_key=None,
        anthropic_api_key=None,
        jev_api_key=None,
        notify_line_channel_access_token=None,
    )
    uvicorn.run(
        create_app(settings),
        host="127.0.0.1",
        port=int(sys.argv[3]),
        timeout_keep_alive=KEEP_ALIVE_SECONDS,
    )


def seed_records(session, settings, *, include_content=False):
    import sys
    from pathlib import Path
    sys.path.insert(
        0,
        str(Path(__file__).resolve().parents[2] / "scripts")
        if "tests" in Path(__file__).parts
        else str(Path(__file__).resolve().parent),
    )
    from test_prices import seed_prices
    from test_records import seed_records as seed_base_records
    counts = seed_base_records(session, settings, include_content=include_content)
    seed_prices(session)
    return counts


if __name__ == "__main__":
    serve() if len(sys.argv) > 1 and sys.argv[1] == "--serve" else main()

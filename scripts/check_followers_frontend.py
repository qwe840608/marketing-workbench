"""Follower toolbar (one compact row), platform and calendar controls with isolated HTTP responses."""

import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import check_polish_frontend as polish
from browser_harness import main
from playwright.sync_api import expect

from app.services.followers import month_weeks

# 改版前（同一份假資料、同一視窗，由改版前的建置以 FOLLOWERS_MEASURE=1 量得）貼文三欄區塊 .posts-layout 的高度（粉絲區塊本身 1440 為 241px、390 為 619px）。
# 桌面 1440×900 要比改版前至少高出 MIN_GAIN。768／390 的版面是單欄流動、高度隨內容而定；
# 發文日期移入粉絲數列後清單內容變少，改由上方「最多兩列＋發文日期一列」的高度門檻把關。
BEFORE_LAYOUT_HEIGHT = {1440: 474}
MIN_GAIN = {1440: 150}

MEASURE_COLORS = """e => {
    const color = value => { const p = document.createElement('span'); p.style.color = value; document.body.append(p); const c = getComputedStyle(p).color; p.remove(); return c; };
    return {
        dd: [...e.querySelectorAll('dd')].map(d => getComputedStyle(d).color),
        main: color('var(--text-main)'), danger: color('var(--state-danger)'), success: color('var(--state-success)'),
        subtle: color('var(--text-subtle)'),
    };
}"""

MEASURE_GEOMETRY = """e => {
    const box = x => x.getBoundingClientRect(), panel = box(e);
    const filter = box(e.querySelector('.follower-filter')), stats = box(e.querySelector('.follower-stats'));
    const dates = box(e.querySelector('.post-date-filter'));
    const selects = [...e.querySelectorAll('select')].map(box);
    const probe = document.createElement('div'); probe.style.cssText = 'height:var(--ui-height-input);position:absolute;visibility:hidden';
    document.body.append(probe); const inputHeight = probe.getBoundingClientRect().height; probe.remove();
    const layout = document.querySelector('.posts-layout');
    const inside = r => r.left >= panel.left - 0.5 && r.right <= panel.right + 0.5 && r.top >= panel.top - 0.5 && r.bottom <= panel.bottom + 0.5;
    return {
        // uiorder：「粉絲數期間」小標占一列（高度＋6px 間距），原本只量下拉與數字的高度門檻不變，所以扣掉小標列。
        panelHeight: panel.height - box(e.querySelector('.follower-period-label')).height - 6, inputHeight,
        // 發文日期併入同一面板：桌面與下拉同列（底部對齊），窄版自成一列，量高度時扣掉它那一列。
        datesHeight: dates.height, datesSameRow: Math.abs(dates.bottom - filter.bottom) <= 1,
        datesInside: inside(dates),
        // 同一列的控制項（下拉、分段、日期欄位）上下緣與標籤高度都要一致，統計與控制項垂直置中。
        controls: [...e.querySelectorAll('select,.segmented-control,input[type=date]')].map(x => [Math.round(box(x).top), Math.round(box(x).bottom)]),
        labelTops: [...e.querySelectorAll('.follower-period-label,.post-date-filter .filter-label')].map(x => Math.round(box(x).top)),
        statsCenter: (box(e.querySelector('.follower-stats dd')).top + box(e.querySelector('.follower-stats dd')).bottom) / 2,
        controlCenter: (selects[0].top + selects[0].bottom) / 2,
        labelAbove: box(e.querySelector('.follower-period-label')).bottom <= filter.top + 0.5,
        selectTops: selects.map(r => Math.round(r.top)), selectHeights: selects.map(r => r.height),
        inside: selects.every(inside), statsInside: inside(stats),
        sameRow: stats.top < filter.bottom - 1, statsBelow: stats.top >= filter.bottom - 1,
        layoutHeight: layout ? box(layout).height : null,
    };
}"""


def check_followers(page, open_thread, shot, checks):
    expect(page.locator(".workspace")).to_be_visible()
    origin = urlsplit(page.url)._replace(path="", query="", fragment="").geturl()
    page.clock.set_fixed_time(datetime(2026, 10, 5, 2, tzinfo=UTC))
    queries, listed = [], []

    def posts(route):
        path = urlsplit(route.request.url).path
        query = parse_qs(urlsplit(route.request.url).query)
        assert route.request.method == "GET"
        if path.endswith("/followers"):
            queries.append(query)
            platform = query["platform"][0]
            year, month, week = (int(query[name][0]) for name in ("year", "month", "week"))
            current_month = (year, month) == (2026, 10)
            value = dict(
                platform=platform,
                connected=platform in ("facebook", "instagram", "threads"),
                years=[2026, 2025],
                year=year,
                month=month,
                week=week,
                weeks=[
                    {k: v.isoformat() if hasattr(v, "isoformat") else v for k, v in w.items()}
                    for w in month_weeks(year, month)
                ],
                is_current_month=current_month,
                is_current_week=current_month and week == 2,
                current_count={"facebook": 41, "instagram": 80, "threads": 1234}.get(platform),
                week_delta=-3 if current_month and week == 2 else 5 if current_month else None,
                month_delta=2 if current_month else None,
            )
            route.fulfill(json=value)
        elif path.endswith("/platforms"):
            route.fulfill(json={"default_platform": "facebook"})
        else:
            # 每個平台分頁都會讀貼文清單（TikTok 只同步影片與成效）。
            listed.append(query.get("platform", ["facebook"])[0])
            assert listed[-1] in ("facebook", "instagram", "threads", "youtube", "tiktok"), listed
            route.fulfill(json=[])

    page.route("**/api/posts**", posts)
    page.route("**/api/accounts**", lambda route: route.fulfill(json=[]))
    page.goto(origin + "/?view=posts&post_platform=facebook")
    panel = page.get_by_role("region", name="粉絲數", exact=True)
    expect(panel.locator("dd").first).to_have_text("41")
    expect(panel.get_by_label("年份")).to_have_value("2026")
    expect(panel.get_by_label("月份")).to_have_value("10")
    expect(panel.get_by_label("週次")).to_have_value("2")
    expect(panel.get_by_label("年份").locator("option")).to_have_text(["2026年", "2025年"])
    expect(panel.get_by_label("月份").locator("option")).to_have_count(12)
    expect(panel.get_by_label("週次").locator("option").first).to_have_text("第1週")
    expect(panel.get_by_label("週次").locator("option").first).to_have_attribute("title", "第1週（10/1–10/4）")
    # 標籤與數值併成「標籤＋數值」的小型行內；原本三張卡的「目前粉絲數／淨增減」縮成短標籤。
    expect(panel.locator("dt")).to_have_text(["粉絲數", "本週", "本月"])
    expect(panel.locator("dd")).to_have_text(["41", "−3", "+2"])
    hint = panel.get_by_role("button", name="粉絲數說明")
    box = hint.bounding_box()
    assert box and abs(box["width"] - box["height"]) < 1 and box["width"] <= 20, box
    mark = hint.locator(".follower-hint-mark").bounding_box()
    # 驚嘆號必須在圓圈正中央（水平、垂直誤差各 1px 內）。
    assert mark and abs((mark["x"] + mark["width"] / 2) - (box["x"] + box["width"] / 2)) <= 1, (mark, box)
    assert abs((mark["y"] + mark["height"] / 2) - (box["y"] + box["height"] / 2)) <= 1, (mark, box)
    tip = panel.locator(".follower-hint [role=tooltip]")
    expect(tip).to_be_hidden()
    hint.hover()
    expect(tip).to_have_text("平台官方統計，可能比 App 晚更新或略有差異")
    page.mouse.move(0, 0)
    expect(tip).to_be_hidden()
    hint.click()
    expect(tip).to_be_visible()
    expect(hint).to_have_attribute("aria-expanded", "true")
    tip_box, width = tip.bounding_box(), page.viewport_size["width"]
    assert tip_box and tip_box["x"] >= 0 and tip_box["x"] + tip_box["width"] <= width, tip_box
    shot("followers-hint")
    hint.click()
    expect(hint).to_have_attribute("aria-expanded", "false")
    # 點擊收合後滑鼠仍停在按鈕；先離開 hover 區域才驗隱藏，保留點擊與 hover 兩種行為。
    page.mouse.move(0, 0)
    expect(tip).to_be_hidden()
    # 面板依序為期間、發文日期、統計；發文日期以外的部分仍維持精簡，不得出現段落或輸入框。
    assert panel.evaluate("e => [...e.children].map(c => c.className)") == [
        "follower-period", "post-date-filter", "follower-stats"]
    assert panel.evaluate(
        "e => [...e.children].filter(c => !c.matches('.post-date-filter'))"
        ".every(c => !c.querySelector('p,svg,input,details,time,h3,label'))")
    assert panel.locator(".stat-tile,.stat-grid").count() == 0
    # 等價取代舊 KPI 卡片的共用內距檢查：行內數字不能再有卡片外框或內距。
    assert panel.locator(".follower-stats > div").evaluate_all(
        "es => es.every(e => { const s = getComputedStyle(e); return "
        "[s.paddingTop,s.paddingRight,s.paddingBottom,s.paddingLeft,"
        "s.borderTopWidth,s.borderRightWidth,s.borderBottomWidth,s.borderLeftWidth].every(v => parseFloat(v) === 0); })"
    )
    assert panel.evaluate("e => e.scrollHeight <= e.clientHeight + 1")
    # 語意色：減少紅、成長綠；粉絲數本身維持一般文字色。
    colors = panel.evaluate(MEASURE_COLORS)
    assert colors["dd"] == [colors["main"], colors["danger"], colors["success"]], colors
    original_size = page.viewport_size
    measured = {}
    for width, height in ((1440, 900), (768, 1024), (390, 844)):
        page.set_viewport_size({'width': width, 'height': height})
        page.wait_for_load_state('networkidle')
        page.evaluate('async () => { await document.fonts.ready; await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); }')
        expect(panel).to_have_attribute('aria-busy', 'false')
        expect(panel.locator("dd").first).to_have_text("41")
        measured[width] = geometry = panel.evaluate(MEASURE_GEOMETRY)
        fits = panel.locator('select').evaluate_all('''elements => elements.map(e => {
            const s = getComputedStyle(e), ctx = document.createElement('canvas').getContext('2d');
            ctx.font = `${s.fontWeight} ${s.fontSize} ${s.fontFamily}`;
            const need = Math.max(...[...e.options].map(o =>
                ctx.measureText(o.text).width + parseFloat(s.paddingLeft) + parseFloat(s.paddingRight) + 24));
            return [e.scrollWidth <= e.clientWidth, need, e.clientWidth];
        })''')
        assert all(ok and need <= wide for ok, need, wide in fits), ('calendar text clipped', width, fits)
        # 粉絲數說明在每個尺寸都要完整落在視窗內。
        hint_button = panel.get_by_role("button", name="粉絲數說明")
        hint_button.click()
        tip_box = panel.locator(".follower-hint [role=tooltip]").bounding_box()
        assert tip_box and tip_box["x"] >= 0 and tip_box["x"] + tip_box["width"] <= width, ("hint overflow", width, tip_box)
        hint_button.click()
        page.mouse.move(0, 0)
        # 所有尺寸三個下拉同列，週次採短標籤、完整日期保留在 option.title。
        # 等價取代舊版「768 時週次獨占下一列」，仍驗字寬與原生箭頭不裁切。
        assert geometry["selectHeights"] == [geometry["inputHeight"]] * 3, (width, geometry)
        assert geometry["inside"] and geometry["statsInside"] and geometry["datesInside"], (width, geometry)
        assert geometry["labelAbove"], (width, geometry)
        expect(panel.locator(".follower-period-label")).to_have_text("粉絲數期間")
        tops = geometry["selectTops"]
        assert len(set(tops)) == 1, (width, geometry)
        if width == 1440:
            # 桌面一列：數字與下拉同列，高度約一個控制項加上下內距（含 2px 框線）。
            assert geometry["sameRow"] and geometry["datesSameRow"], geometry
            assert len(set(map(tuple, geometry["controls"]))) == 1, geometry
            assert len(set(geometry["labelTops"])) == 1, geometry
            assert abs(geometry["statsCenter"] - geometry["controlCenter"]) <= 1.5, geometry
            assert geometry["panelHeight"] <= geometry["inputHeight"] + 24 + 2 + 1, geometry
        else:
            # 768／390：下拉一列、數字一列，最多兩列。
            rows = 2
            assert geometry["panelHeight"] - geometry["datesHeight"] - 8 <= rows * geometry["inputHeight"] + 24 + 2 + 8 * rows, (width, geometry)
            assert geometry["statsBelow"], (width, geometry)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
        assert panel.evaluate('e => e.scrollWidth <= e.clientWidth'), width
    page.set_viewport_size(original_size)
    # 釋出的高度要讓下方三欄變高：與改版前的量測值比較（見檔頭常數）。
    for width, before in BEFORE_LAYOUT_HEIGHT.items():
        now = measured[width]["layoutHeight"]
        assert now >= before + MIN_GAIN[width], (width, now, before)
    print("FOLLOWERS_LAYOUT", json.dumps(measured))
    checks.append('toolbar-one-row-1440-two-rows-768-390-no-overflow-taller-columns')
    checks.append('calendar-select-text-and-native-arrow-fit-1440-768-390')
    panel.get_by_label("週次").select_option("1")
    expect(panel.locator("dt").nth(1)).to_have_text("該週")
    expect(panel.locator("dd").nth(1)).to_have_text("+5")
    colors = panel.evaluate(MEASURE_COLORS)
    assert colors["dd"][1] == colors["success"], colors
    panel.get_by_label("月份").select_option("2")
    expect(panel.locator("dd")).to_have_text(["41", "—", "—"])
    expect(panel.locator("dt")).to_have_text(["粉絲數", "該週", "該月"])
    # 無資料的「—」用灰色。
    colors = panel.evaluate(MEASURE_COLORS)
    assert colors["dd"][1:] == [colors["subtle"]] * 2, colors
    panel.get_by_label("年份").select_option("2025")
    expect(panel.get_by_label("週次")).to_have_value("1")
    shot("followers-history")
    tabs = page.get_by_role("tablist", name="貼文平台", exact=True)
    tabs.get_by_role("tab", name="IG", exact=True).click()
    expect(panel.locator("dd").first).to_have_text("80")
    expect(panel.get_by_label("週次")).to_have_value("2")
    expect(panel.get_by_label("月份")).to_have_value("10")
    expect(page.locator(".follower-panel")).to_have_count(1)
    shot("followers-instagram")
    # Threads 現在有粉絲數與增減，樣式與 FB／IG 相同。
    tabs.get_by_role("tab", name="Threads", exact=True).click()
    expect(panel.locator("dd")).to_have_text(["1,234", "−3", "+2"])
    expect(panel.locator("dt")).to_have_text(["粉絲數", "本週", "本月"])
    assert queries[-1]["platform"] == ["threads"]
    shot("followers-threads")
    # 尚未串接的分頁同樣精簡成一行，沒有下拉與數字。
    for label, platform in [("YouTube", "youtube"), ("TikTok", "tiktok")]:
        tabs.get_by_role("tab", name=label, exact=True).click()
        panel = page.locator(".follower-panel")
        expect(panel.locator(".follower-unconnected")).to_have_text("尚未串接，串接後開始記錄" + ("訂閱數" if platform == "youtube" else "粉絲數"))
        expect(panel.locator("select,dl")).to_have_count(0)
        assert queries[-1]["platform"] == [platform]
        # 未串接仍保留發文日期篩選（貼文清單照常可篩）；扣掉篩選器（窄版另含 8px 列距）後維持一行高度。
        assert panel.evaluate("e => e.getBoundingClientRect().height - "
                              "e.querySelector('.post-date-filter').getBoundingClientRect().height") <= 40 + 24 + 2 + 8 + 1
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert all("date_from" not in q and "date_to" not in q for q in queries)
    assert {"threads", "youtube", "tiktok"} <= set(listed), listed
    checks.append("followers-platform-calendar-defaults-history-negative-empty-one-row-threads")


if __name__ == "__main__":
    polish.run_checks = check_followers
    polish.check_polling = lambda *args: None
    main(polish=True)

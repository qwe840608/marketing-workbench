"""End-to-end publishing on runtime SQLite; provider sockets are blocked by the harness."""

import json
import os
from datetime import timedelta

from browser_harness import REPO, main
from playwright.sync_api import expect
from publish_http_mock import seed_connections, seed_tiktok, seed_youtube, unseed_tiktok, unseed_youtube, video_bytes
from ui_navigation import navigate


def check_editor_layout(page, scheduled=False, reason=False):
    """uiorder：排程設定與送出按鈕同在底部動作列；「新貼文／新限時動態」在標題列右側。"""
    import re

    editor = page.locator('.publish-editor')
    footer = editor.locator('.publish-footer')
    expect(footer).to_have_count(1)
    schedule, submit = footer.locator('.publish-schedule'), footer.locator('.publish-submit')
    # 立即發佈／排程切換（含排程日期欄）、按鈕、停用原因都在同一個動作列內。
    expect(schedule.get_by_role('radiogroup', name='發佈時間', exact=True)).to_have_count(1)
    expect(schedule.get_by_label('排程時間（台北）', exact=True)).to_have_count(1 if scheduled else 0)
    expect(submit.locator('.publish-actions .primary')).to_have_count(1)
    expect(footer.locator('#publish-disabled-reason')).to_have_count(1 if reason else 0)
    wide = page.viewport_size['width'] > 600
    sb, ab, fb = schedule.bounding_box(), submit.locator('.publish-actions').bounding_box(), footer.bounding_box()
    if wide:
        # 桌機同一列：時間設定靠左、按鈕靠右。
        assert sb['y'] < ab['y'] + ab['height'] and ab['y'] < sb['y'] + sb['height'], (sb, ab)
        assert sb['x'] < ab['x'] and abs(sb['x'] - fb['x']) <= 1 and abs(ab['x'] + ab['width'] - fb['x'] - fb['width']) <= 1, (sb, ab, fb)
    else:
        # 手機兩列但仍在同一個動作列內，不橫向溢出。
        assert sb['y'] + sb['height'] <= ab['y'] + 1, (sb, ab)
        assert sb['x'] >= fb['x'] - 1 and ab['x'] + ab['width'] <= fb['x'] + fb['width'] + 1
    if reason:
        rb = footer.locator('#publish-disabled-reason').bounding_box()
        # 原因只有一處：獨占一列，在「立即發佈／排程」與送出按鈕上方，靠左對齊動作列。
        assert rb['y'] + rb['height'] <= min(sb['y'], ab['y']) + 1, (rb, sb, ab)
        assert abs(rb['x'] - fb['x']) <= 1 and rb['x'] + rb['width'] <= fb['x'] + fb['width'] + 1, (rb, fb)
    expect(editor.locator('.publish-composer-panel .publish-reasons[role=status]:not(#publish-disabled-reason):not(.publish-over-limit)')).to_have_count(0)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    # 「新貼文／新限時動態」：桌機與平台分頁同一列、在分頁右側；手機在分頁上方且靠右。
    heading = editor.locator('.publish-editor-heading')
    button = heading.get_by_role('button', name=re.compile('^新(貼文|限時動態)$'))
    expect(button).to_have_count(1)
    hb, bb, tb = heading.bounding_box(), button.bounding_box(), editor.locator('.publish-composer-tabs').bounding_box()
    assert abs(bb['x'] + bb['width'] - hb['x'] - hb['width']) <= 1, (bb, hb)
    if page.viewport_size['width'] >= 768:
        assert abs(bb['y'] - tb['y']) <= 2 and bb['x'] >= tb['x'] + 1, (bb, tb)
        assert bb['x'] + bb['width'] <= editor.bounding_box()['x'] + editor.bounding_box()['width'], (bb,)
    else:
        assert bb['y'] + bb['height'] <= tb['y'] + 1, (bb, tb)


def check_idea_drafts(page, settings, checks):
    from urllib.parse import parse_qs, urlsplit

    from app.db import build_engine, session_factory
    from app.models import AIRun, PublishPost
    from app.models.base import utc_now
    from app.models.ideation import IdeationReport, VideoScript
    from sqlalchemy import select
    from stage3_fixture import seed_stage3

    origin = urlsplit(page.url)._replace(path='', query='', fragment='').geturl()
    engine = build_engine(settings)
    try:
        factory = session_factory(engine)
        report_id, script_id = seed_stage3(factory, origin)
        with factory.begin() as session:
            report = session.get(IdeationReport, report_id)
            brand_id = report.brand_id
            idea = report.data_json['ideas'][0]
            report.data_json = {**report.data_json, 'ideas': [idea, {
                **idea, 'title': '[隔離驗收] 無腳本主題', 'hook': '先確認需求。', 'quote_ids': [],
            }]}
            script = session.get(VideoScript, script_id)
            script.content_json = {**script.content_json, 'ending': '隔離腳本結尾，請確認現場條件。'}
        folder = REPO / '.runtime/pubfix-screens/after'
        folder.mkdir(parents=True, exist_ok=True)
        size = page.viewport_size

        def capture(name, focus=None):
            page.wait_for_load_state('networkidle')
            page.evaluate('async () => { await document.fonts.ready; await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); }')
            for width, height in [(1440, 900), (768, 1024), (390, 844)]:
                page.set_viewport_size({'width': width, 'height': height})
                page.evaluate('async () => { await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); }')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (name, width)
                for actions in page.locator('.idea-card-actions,.idea-card-tools').all():
                    assert actions.evaluate('e => e.scrollWidth <= e.clientWidth + 1'), width
            page.set_viewport_size(size)
            if focus:
                page.locator(focus).first.scroll_into_view_if_needed()
            page.screenshot(path=str(folder / f'{name}-{size["width"]}x{size["height"]}.png'))
            checks.append('pubfix-' + name)

        def no_ai_interface():
            # 發佈頁不得出現任何 AI 文案狀態或按鈕，即使資料庫裡還留有舊的文案任務。
            expect(page.locator('.publish-caption-progress,.publish-caption-notice,.publish-ai-badge')).to_have_count(0)
            expect(page.get_by_text('AI 正在撰寫文案', exact=False)).to_have_count(0)
            expect(page.get_by_text('AI 文案已完成', exact=False)).to_have_count(0)
            for name in ('套用 AI 文案', '重新撰寫'):
                expect(page.get_by_role('button', name=name)).to_have_count(0)

        idea_url = origin + f'/?view=ideation&brand_id={brand_id}&report_id={report_id}'
        page.goto(idea_url)
        cards = page.locator('.ideation-card')
        expect(cards).to_have_count(2)
        action = cards.first.locator('.idea-card-actions')
        # 底部：有腳本時先「查看腳本」，再「建立發佈草稿」，兩顆都是 secondary；沒有腳本只剩後者。
        expect(action.get_by_role('button')).to_have_text(['查看腳本', '建立發佈草稿'])
        expect(action.locator('.primary')).to_have_count(0)
        assert action.get_by_role('button').evaluate_all('es => es.map(e => e.className)') == ['secondary', 'secondary']
        expect(cards.nth(1).locator('.idea-card-actions').get_by_role('button')).to_have_text(['建立發佈草稿'])
        tools = cards.first.locator('.idea-card-tools')
        expect(tools.get_by_role('button')).to_have_text(['編輯'])
        tools.get_by_role('button', name='編輯', exact=True).click()
        editor = cards.first.get_by_role('form', name='編輯主題')
        expect(editor).to_be_visible()
        expect(editor.locator('.primary')).to_have_count(1)
        editor.get_by_label('標題', exact=True).fill('')
        expect(editor.get_by_role('button', name='儲存', exact=True)).to_be_disabled()
        editor.get_by_label('標題', exact=True).fill('[隔離驗收] 自行編輯主題')
        editor.get_by_label('開場', exact=True).fill('先確認需求與現場。')
        capture('card-edit', '.idea-editor')
        editor.get_by_role('button', name='儲存', exact=True).click()
        expect(cards.first.locator('h3')).to_have_text('[隔離驗收] 自行編輯主題')
        expect(cards.first.locator('.idea-edited')).to_have_text('已編輯')
        capture('card-edited', '.ideation-card')
        button = action.get_by_role('button', name='建立發佈草稿', exact=True)
        expect(button).to_have_class('secondary')
        button.click()
        # 不再有參考腳本的對話框，也不呼叫 AI：直接建立草稿並開啟發佈頁。
        expect(page.get_by_role('tab', name='新增貼文')).to_have_attribute('aria-selected', 'true')
        expect(page.get_by_role('dialog')).to_have_count(0)
        # uiorder：發佈頁沒有自己的品牌選單，品牌來自網址／側邊欄（brand_id 與草稿品牌一致）。
        expect(page.get_by_label('發佈品牌', exact=True)).to_have_count(0)
        assert f'brand_id={brand_id}' in page.url
        caption = page.get_by_label('主文案', exact=True)
        # 初稿只由標題、開場與 hashtag 組成，不含腳本結尾。
        expect(caption).to_have_value('[隔離驗收] 自行編輯主題\n\n先確認需求與現場。\n\n#客製方案服務評估')
        expect(caption).not_to_contain_text('隔離腳本結尾')
        expect(page.locator('.notice.success')).to_have_text('已從主題建立草稿，請上傳影片並確認平台')
        expect(page.get_by_role('radio', name='影片', exact=True)).to_be_checked()
        expect(page.get_by_role('button', name='拖曳或點選上傳')).to_be_enabled()
        expect(page.locator('.publish-platform input').first).to_be_enabled()
        no_ai_interface()
        capture('draft-created', '.publish-step:has(textarea[aria-label="主文案"])')
        post_id = int(parse_qs(urlsplit(page.url).query)['publish_post_id'][0])
        # 舊資料：資料庫裡仍有 AI 文案任務（排隊中與已完成）時，發佈頁與草稿列表都不顯示 AI 狀態。
        with factory.begin() as session:
            session.get(PublishPost, post_id).caption_job_json = {
                'id': 'legacy', 'status': 'processing', 'started_at': utc_now().isoformat(),
                'caption': '舊 AI 候選文案', 'applied': False, 'error': '舊錯誤',
            }
        page.reload()
        expect(caption).to_have_value('[隔離驗收] 自行編輯主題\n\n先確認需求與現場。\n\n#客製方案服務評估')
        no_ai_interface()
        page.get_by_role('tab', name='草稿', exact=True).click()
        row = page.locator('.publish-record').filter(has_text='自行編輯主題')
        expect(row.locator('.publish-source')).to_have_text('來自主題')
        expect(row.locator('.publish-source')).to_have_class('status-badge neutral publish-source')
        expect(row).to_contain_text('0 個媒體')
        no_ai_interface()
        capture('drafts', '.publish-record:has(.publish-source)')
        row.get_by_role('button', name='編輯', exact=True).click()
        expect(caption).to_contain_text('自行編輯主題')
        page.get_by_role('tab', name='排程中', exact=True).click()
        expect(page.get_by_role('tab', name='排程中', exact=True)).to_have_attribute('aria-selected', 'true')
        expect(page.locator('.publish-switch button')).to_be_enabled()
        page.get_by_role('tab', name='新增貼文', exact=True).click()
        expect(page.get_by_role('tab', name='新增貼文', exact=True)).to_have_attribute('aria-selected', 'true')
        # switchTab 會在顯示編輯器後繼續 reload；等 busy 結束，避免離頁被 beforeLeave 忽略。
        expect(page.locator('.publish-editor')).to_have_attribute('aria-busy', 'false')
        expect(caption).to_contain_text('自行編輯主題')
        navigate(page, '儀表板')
        expect(page.locator('.dashboard-kpis .kpi')).to_have_count(2)
        navigate(page, '發佈')
        expect(caption).to_contain_text('自行編輯主題')
        for _ in range(2):
            page.reload()
            expect(caption).to_contain_text('自行編輯主題')
        with factory() as session:
            posts = list(session.scalars(select(PublishPost).where(PublishPost.report_id == report_id)))
            assert len(posts) == 1 and posts[0].id == post_id
            assert not session.scalar(select(AIRun.id).where(AIRun.task == 'publish_caption'))
        page.get_by_role('tab', name='發佈紀錄', exact=True).click()
        expect(page.locator('.publish-record').filter(has_text='自行編輯主題')).to_have_count(0)
        page.goto(idea_url)
        page.locator('.ideation-card').first.get_by_role('button', name='開啟發佈草稿', exact=True).click()
        expect(caption).to_contain_text('自行編輯主題')
        expect(page.get_by_role('dialog')).to_have_count(0)
        checks.append('pubfix-reuse-reload-tabs-navigation-no-ai-no-extra-draft')
        page.goto(idea_url)
        page.locator('.ideation-card').nth(1).get_by_role('button', name='建立發佈草稿', exact=True).click()
        expect(caption).to_contain_text('無腳本主題')
        expect(page.get_by_role('dialog')).to_have_count(0)
        caption.fill('隔離人工文案，保留我的修改')
        page.get_by_role('button', name='存成草稿', exact=True).click()
        expect(page.locator('.notice.success')).to_have_text('草稿已儲存')
        # 沒有任何背景工作會覆寫人工文案。
        page.wait_for_timeout(1200)
        expect(caption).to_have_value('隔離人工文案，保留我的修改')
        no_ai_interface()
        page.get_by_role('tab', name='草稿', exact=True).click()
        rows = page.locator('.publish-record').filter(has=page.locator('.publish-source'))
        expect(rows).to_have_count(2)
        rows.first.get_by_role('button', name='刪除', exact=True).click()
        expect(page.get_by_role('dialog')).to_contain_text('刪除此草稿？')
        page.get_by_role('button', name='取消', exact=True).click()
        expect(rows).to_have_count(2)
        rows.first.get_by_role('button', name='刪除', exact=True).click()
        page.get_by_role('button', name='確認刪除', exact=True).click()
        expect(rows).to_have_count(1)
        page.get_by_role('tab', name='新增貼文', exact=True).click()
        page.get_by_role('button', name='新貼文', exact=True).click()
        expect(caption).to_have_value('')
        with factory() as session:
            count = len(list(session.scalars(select(PublishPost))))
        for tab in ('排程中', '草稿', '新增貼文'):
            page.get_by_role('tab', name=tab, exact=True).click()
        page.reload()
        expect(caption).to_have_value('')
        page.wait_for_timeout(900)
        with factory() as session:
            assert len(list(session.scalars(select(PublishPost)))) == count
            assert not session.scalar(select(AIRun.id).where(AIRun.task == 'publish_caption'))
        # Leaving before the debounce still saves and restores the first human input.
        caption.fill('隔離離頁前輸入')
        navigate(page, '儀表板')
        expect(page.locator('.dashboard-kpis .kpi')).to_have_count(2)
        navigate(page, '發佈')
        expect(caption).to_have_value('隔離離頁前輸入')
        checks.append('pubfix-manual-edit-delete-new-blank-reload-and-leave-flush')
        with factory.begin() as session:
            post = session.get(PublishPost, post_id)
            post.status = 'scheduled'
            post.scheduled_at = utc_now() + timedelta(hours=2)
        page.get_by_role('tab', name='排程中', exact=True).click()
        expect(page.locator('.publish-record').filter(has_text='自行編輯主題').locator('.publish-source')).to_have_text('來自主題')
        checks.append('pubfix-scheduled-source')
    finally:
        engine.dispose()


def check_presence(page, settings, checks):
    """偵測平台已刪除：檢查列、實心按鈕、結果提示、已刪除膠囊與連結隱藏、部分刪除。"""
    import re

    from app.db import build_engine, session_factory
    from app.models import Brand, PublishPost, PublishTarget, Setting, Staff
    from app.models.base import utc_now
    from sqlalchemy import select

    from urllib.parse import urlsplit

    origin = urlsplit(page.url)._replace(path='', query='', fragment='').geturl()
    size = page.viewport_size
    width = size['width']
    folder = REPO / '.runtime/pubdeleted-screens'
    folder.mkdir(parents=True, exist_ok=True)
    listing = settings.database_path.parent / 'presence-threads.json'
    old = utc_now() - timedelta(minutes=30)
    names = {'all': f'隔離刪除偵測-全部-{width}', 'keep': f'隔離刪除偵測-保留-{width}',
             'part': f'隔離刪除偵測-部分-{width}'}
    link = 'https://www.threads.net/@isolated/post/'
    engine = build_engine(settings)
    factory = session_factory(engine)

    def seed(caption, rows):
        with factory.begin() as session:
            brand = session.scalar(select(Brand).where(Brand.slug == 'TEST'))
            staff = session.scalar(select(Staff).where(Staff.username == 'admin'))
            post = PublishPost(brand_id=brand.id, creator_id=staff.id, format='text', caption=caption,
                               platforms_json=[r[0] for r in rows], status='done', completed_at=utc_now())
            session.add(post)
            session.flush()
            from app.models import Account

            for platform, identity, deleted in rows:
                account = session.scalar(select(Account).where(
                    Account.brand_id == brand.id, Account.external_id == {'facebook': '100', 'threads': '300'}[platform]))
                session.add(PublishTarget(
                    post_id=post.id, platform=platform, account_id=account.id, status='succeeded',
                    platform_post_id=identity, permalink=link + identity, attempts=1,
                    last_attempt_at=old, deleted_at=old if deleted else None))

    def reset():
        with factory.begin() as session:
            for post in session.scalars(select(PublishPost).where(PublishPost.caption.like('隔離刪除偵測%'))):
                for target in session.scalars(select(PublishTarget).where(PublishTarget.post_id == post.id)):
                    session.delete(target)
                session.delete(post)
            session.flush()
            # 先前流程發佈的目標視為剛發佈，不納入本次檢查。
            for target in session.scalars(select(PublishTarget)):
                target.last_attempt_at = utc_now()
                target.deleted_at = target.presence_checked_at = None
            for row in session.scalars(select(Setting).where(Setting.key.like('publish.presence.manual.%'))):
                session.delete(row)

    def capture(name):
        page.wait_for_load_state('networkidle')
        page.evaluate('async () => { await document.fonts.ready; await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); }')
        for w, h in [(1440, 900), (768, 1024), (390, 844)]:
            page.set_viewport_size({'width': w, 'height': h})
            page.evaluate('async () => { await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); }')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (name, w)
            assert page.locator('.publish-presence').evaluate('e => e.scrollWidth <= e.clientWidth + 1'), (name, w)
        page.set_viewport_size(size)
        page.locator('.publish-presence').scroll_into_view_if_needed()
        page.screenshot(path=str(folder / f'{name}-{size["width"]}x{size["height"]}.png'))
        checks.append('pubdeleted-' + name)

    def open_history():
        # 不帶先前草稿的網址參數，避免畫面被帶回「新增貼文」。
        page.goto(origin)
        expect(page.locator('.dashboard-kpis .kpi')).to_have_count(2)
        navigate(page, '發佈')
        page.get_by_role('tab', name='發佈紀錄', exact=True).click()

    try:
        reset()
        seed(names['keep'], [('threads', f'keep-{width}', False)])
        seed(names['all'], [('threads', f'gone-{width}', False)])
        listing.write_text(json.dumps([f'keep-{width}', f'keep2-{width}']), encoding='utf-8')
        open_history()
        bar = page.locator('.publish-presence')
        button = bar.locator('button')
        expect(button).to_have_text('檢查平台貼文')
        expect(bar).to_contain_text('上次檢查：尚未檢查')
        expect(button).to_have_class('primary')
        expect(page.locator('#publish-panel-history .primary')).to_have_count(1)
        expect(bar.get_by_role('button', name='檢查平台貼文', exact=True)).to_have_count(1)
        expect(button).to_be_enabled()
        button.click()
        expect(button).to_have_text('檢查中…')
        expect(button).to_be_disabled()
        expect(page.locator('.notice.success')).to_have_text('已檢查 2 篇，1 篇已在平台刪除')
        expect(button).to_have_text('檢查平台貼文')
        expect(bar).to_contain_text(re.compile(r'上次檢查：\d{4}/\d+/\d+'))
        gone = page.locator('.publish-record').filter(has_text=names['all'])
        keep = page.locator('.publish-record').filter(has_text=names['keep'])
        expect(gone.locator('.status-badge.neutral').last).to_have_text('已在平台刪除')
        expect(gone).not_to_contain_text('成功')
        expect(keep).to_contain_text('成功')
        expect(keep).not_to_contain_text('已在平台刪除')
        keep.get_by_role('button', name='各平台結果').click()
        expect(keep.locator('.publish-targets a')).to_have_count(1)
        gone.get_by_role('button', name='各平台結果').click()
        expect(gone.locator('.publish-targets a')).to_have_count(0)
        expect(gone.locator('.publish-targets')).to_contain_text('Threads · 已在平台刪除')
        expect(gone.locator('.publish-targets')).to_contain_text('偵測於')
        capture('history-all-deleted')
        button.click()
        expect(page.locator('.notice.danger')).to_have_text('剛檢查過，請稍後再試')
        checks.append('pubdeleted-throttle-message')
        # 部分刪除：Facebook 已先標記刪除，Meta 清單在隔離環境無法取得，不得改變既有判定。
        seed(names['part'], [('facebook', f'100_part-{width}', True), ('threads', f'keep2-{width}', False)])
        with factory.begin() as session:
            for row in session.scalars(select(Setting).where(Setting.key.like('publish.presence.manual.%'))):
                session.delete(row)
        open_history()
        page.locator('.publish-presence button').click()
        warning = page.locator('.notice.warning')
        expect(warning).to_contain_text('無法判定')
        expect(warning).to_contain_text('Facebook')
        part = page.locator('.publish-record').filter(has_text=names['part'])
        expect(part).to_contain_text('成功 · 部分已刪除')
        part.get_by_role('button', name='各平台結果').click()
        expect(part.locator('.publish-targets a')).to_have_count(1)
        expect(part.locator('.publish-targets')).to_contain_text('Facebook · 已在平台刪除')
        capture('history-partial-deleted')
        with factory() as session:
            assert session.scalar(select(PublishTarget.deleted_at).where(
                PublishTarget.platform_post_id == f'100_part-{width}')) is not None
    finally:
        listing.unlink(missing_ok=True)
        engine.dispose()


def check_unpublished(page, settings, checks):
    """存成 FB 草稿：勾選框只在選 Facebook 時出現、確認內容、發佈紀錄標示、鎖定停用、刪除偵測略過。"""
    import re
    from urllib.parse import urlsplit

    from app.db import build_engine, session_factory
    from app.models import Account, Brand, PublishPost, PublishTarget, Setting, Staff
    from app.models.base import utc_now
    from sqlalchemy import select

    origin = urlsplit(page.url)._replace(path='', query='', fragment='').geturl()
    size = page.viewport_size
    folder = REPO / '.runtime/fbunpub-screens'
    folder.mkdir(parents=True, exist_ok=True)
    label = '存成 FB 草稿（不發佈，可在 Meta Business Suite 草稿編輯後再發）'
    title = f'隔離未發佈貼文-{size["width"]}'
    option = page.get_by_label(label, exact=True)
    caption = page.get_by_label('主文案', exact=True)

    def platform(name):
        return page.get_by_role('switch', name='發佈到 ' + name, exact=True)

    def capture(name, focus):
        page.wait_for_load_state('networkidle')
        settle = 'async () => { await document.fonts.ready; await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); }'
        page.evaluate(settle)
        for width, height in [(1440, 900), (768, 1024), (390, 844)]:
            page.set_viewport_size({'width': width, 'height': height})
            page.evaluate(settle)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (name, width)
            assert page.locator(focus).first.evaluate('e => e.scrollWidth <= e.clientWidth + 1'), (name, width)
        page.set_viewport_size(size)
        page.evaluate(settle)
        page.locator(focus).first.evaluate("e => e.scrollIntoView({block: 'center'})")
        page.screenshot(path=str(folder / f'{name}-{size["width"]}x{size["height"]}.png'))
        checks.append('fbunpub-' + name)

    # FB 草稿選項在 Facebook 分頁；平台未開啟仍可編輯，關閉 Facebook 仍重置選項。
    page.get_by_role('tab', name='新增貼文', exact=True).click()
    page.get_by_role('button', name='新貼文', exact=True).click()
    page.get_by_role('radio', name='純文字', exact=True).click()
    caption.fill(title)
    expect(option).to_have_count(0)
    platform('Threads').check()
    expect(option).to_have_count(0)
    platform('Facebook').check()
    page.get_by_role('tab', name='Facebook', exact=True).click()
    expect(option).to_be_visible()
    expect(option).not_to_be_checked()
    expect(option).to_be_enabled()
    expect(page.locator('#composer-panel-facebook .publish-unpublished')).to_have_count(1)
    expect(page.locator('.publish-unpublished')).to_have_count(1)
    option.check()
    platform('Facebook').uncheck()
    expect(option).to_be_visible()
    expect(option).not_to_be_checked()
    expect(page.locator('#composer-panel-facebook')).to_contain_text('未開啟')
    platform('Facebook').check()
    expect(option).not_to_be_checked()
    option.check()
    checks.append('fbunpub-checkbox-only-with-facebook-default-off')
    # 勾選會跟著草稿保存：存成草稿、重新整理後仍是勾選。
    page.get_by_role('button', name='存成草稿', exact=True).click()
    expect(page.locator('.notice.success')).to_have_text('草稿已儲存')
    page.reload()
    expect(caption).to_have_value(title)
    page.get_by_role('tab', name='Facebook', exact=True).click()
    expect(option).to_be_checked()
    expect(page.locator('#publish-panel-new .primary')).to_have_count(1)
    capture('editor', '.publish-unpublished')
    publish_button = page.locator('.publish-actions').get_by_role('button', name='發佈', exact=True)
    expect(publish_button).to_be_enabled()
    publish_button.click()
    dialog = page.get_by_role('dialog')
    expect(dialog).to_contain_text('存成草稿，不發佈')
    dialog.get_by_role('button', name='確認發佈').click()
    # 發佈紀錄：清單列與各平台結果都標示草稿；Threads 不受影響。
    row = page.locator('.publish-record').filter(has_text=title)
    expect(row).to_contain_text('成功')
    expect(row).to_contain_text('Threads、Facebook · 草稿')
    row.get_by_role('button', name='各平台結果').click()
    targets = row.locator('.publish-targets .status-badge')
    expect(targets.filter(has_text='Facebook')).to_have_text('Facebook · 成功 · 草稿')
    expect(targets.filter(has_text='Facebook')).to_have_class(re.compile(r'\bneutral\b'))
    expect(targets.filter(has_text='Threads')).to_have_text('Threads · 成功')
    expect(page.locator('.publish-record').filter(has_text='隔離影片發佈')).not_to_contain_text(' · 草稿')
    capture('history', '.publish-record:has(.publish-targets)')
    checks.append('fbunpub-confirm-and-history-labels')

    engine = build_engine(settings)
    factory = session_factory(engine)
    old = utc_now() - timedelta(minutes=30)
    try:
        def seed(caption_text, status, unpublished, target_status, attempt):
            with factory.begin() as session:
                brand = session.scalar(select(Brand).where(Brand.slug == 'TEST'))
                staff = session.scalar(select(Staff).where(Staff.username == 'admin'))
                account = session.scalar(select(Account).where(
                    Account.brand_id == brand.id, Account.external_id == '100'))
                post = PublishPost(brand_id=brand.id, creator_id=staff.id, format='text', caption=caption_text,
                                   platforms_json=['facebook'], facebook_unpublished=unpublished, status=status,
                                   completed_at=utc_now() if status == 'done' else None)
                session.add(post)
                session.flush()
                session.add(PublishTarget(post_id=post.id, platform='facebook', account_id=account.id,
                                          status=target_status, platform_post_id='100_' + caption_text,
                                          attempts=1, last_attempt_at=attempt))

        # Facebook 已成功的草稿（部分成功後重新排程再取消）：公開方式鎖定，勾選框停用。
        locked_title = f'隔離未發佈已送出-{size["width"]}'
        seed(locked_title, 'draft', True, 'succeeded', utc_now())
        page.goto(origin)
        expect(page.locator('.dashboard-kpis .kpi')).to_have_count(2)
        navigate(page, '發佈')
        page.get_by_role('tab', name='草稿', exact=True).click()
        page.locator('.publish-record').filter(has_text=locked_title).get_by_role('button', name='編輯', exact=True).click()
        page.get_by_role('tab', name='Facebook', exact=True).click()
        expect(option).to_be_visible()
        expect(option).to_be_checked()
        expect(option).to_be_disabled()
        checks.append('fbunpub-locked-checkbox-disabled')
        # 刪除偵測：FB 草稿不在任何清單內，改為逐篇查詢；隔離環境連不到 Meta，
        # 所以列為無法判定，不計入檢查也不標為已刪除。
        hidden_title = f'隔離未發佈不判定-{size["width"]}'
        seed(hidden_title, 'done', True, 'succeeded', old)
        with factory.begin() as session:
            for item in session.scalars(select(Setting).where(Setting.key.like('publish.presence.manual.%'))):
                session.delete(item)
        page.goto(origin)
        expect(page.locator('.dashboard-kpis .kpi')).to_have_count(2)
        navigate(page, '發佈')
        page.get_by_role('tab', name='發佈紀錄', exact=True).click()
        page.locator('.publish-presence button').click()
        warning = page.locator('.notice.warning')
        expect(warning).to_contain_text('已檢查 0 篇，0 篇已在平台刪除')
        expect(warning).to_contain_text('無法判定：Facebook')
        hidden = page.locator('.publish-record').filter(has_text=hidden_title)
        expect(hidden).to_contain_text('成功')
        expect(hidden).not_to_contain_text('已在平台刪除')
        with factory() as session:
            target = session.scalar(select(PublishTarget).where(PublishTarget.platform_post_id == '100_' + hidden_title))
            assert target.deleted_at is None and target.presence_checked_at is None
        checks.append('fbunpub-presence-skips-unpublished')
        # 清掉這兩筆測試資料，避免影響後續檢查。
        with factory.begin() as session:
            for text in (locked_title, hidden_title):
                for item in session.scalars(select(PublishTarget).where(PublishTarget.platform_post_id == '100_' + text)):
                    post_id = item.post_id
                    session.delete(item)
                    session.flush()
                    session.delete(session.get(PublishPost, post_id))
    finally:
        engine.dispose()


def check_composer(page, settings, checks):
    """新編輯器所有操作皆在隔離後端／假 HTTP，包含兩個尺寸的改版後截圖。"""
    from urllib.parse import urlsplit

    origin = urlsplit(page.url)._replace(path='', query='', fragment='').geturl()
    size = page.viewport_size
    folder = REPO / '.runtime/composer2-screens'
    folder.mkdir(parents=True, exist_ok=True)

    def tab(name):
        page.get_by_role('tab', name=name, exact=True).click()
        expect(page.locator('.publish-editor')).to_have_attribute('aria-busy', 'false')
        expect(page.get_by_role('tab', name=name, exact=True)).to_have_attribute('aria-selected', 'true')

    def switch(name):
        return page.get_by_role('switch', name='發佈到 ' + name, exact=True)

    def capture(name):
        expect(page.locator('.publish-editor')).to_have_attribute('data-check-state', 'checked')
        page.wait_for_load_state('networkidle')
        # 錯誤只在動作列上方列一次：分頁裡沒有錯誤清單，前端即時檢查與後端理由不得重複。
        expect(page.locator('.publish-composer-panel .publish-reasons[role=status]:not(#publish-disabled-reason):not(.publish-over-limit)')).to_have_count(0)
        for text in page.locator('#publish-disabled-reason').all_inner_texts():
            items = text.split('；')
            assert len(items) == len(set(items)), (name, text)
        settle ='async () => { await document.fonts.ready; await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); }'
        page.evaluate(settle)
        for width, height in [(1440, 900), (768, 1024), (390, 844)]:
            page.set_viewport_size({'width': width, 'height': height})
            page.evaluate(settle)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (name, width)
            assert page.locator('.publish-composer-panel').evaluate('e => e.scrollWidth <= e.clientWidth + 1'), (name, width)
            if page.locator('.publish-preview').count():
                preview = page.locator('.publish-preview').bounding_box()
                fields = page.locator('.publish-composer-fields').bounding_box()
                if width <= 767:
                    assert preview['y'] + preview['height'] <= fields['y'] + 1, (name, width, preview, fields)
                else:
                    assert preview['x'] >= fields['x'] + fields['width'] - 1, (name, width)
        page.set_viewport_size(size)
        page.evaluate(settle)
        focus = '.publish-composer-panel' if size['width'] <= 767 else '.publish-editor'
        if size['width'] <= 767 and name == 'threads-over-limit':
            focus = '.publish-segments'
        if size['width'] <= 767 and name in {'facebook-reels', 'instagram'}:
            focus = '.publish-composer-fields'
        page.locator(focus).evaluate("e => e.scrollIntoView({block: 'start'})")
        page.screenshot(path=str(folder / f'{name}-{size["width"]}x{size["height"]}.png'))
        checks.append('composer2-' + name)

    page.goto(origin)
    expect(page.locator('.dashboard-kpis .kpi')).to_have_count(2)
    navigate(page, '發佈')
    page.get_by_role('button', name='新貼文', exact=True).click()
    expect(page.get_by_role('tablist', name='文案平台').get_by_role('tab')).to_have_text(['共用', 'Facebook', 'Instagram', 'Threads', 'YouTube', 'TikTok'])
    for name in ('Facebook', 'Instagram', 'Threads'):
        expect(switch(name)).to_be_enabled()
        expect(switch(name)).not_to_be_checked()
        switch(name).check()
    for name in ('YouTube', 'TikTok'):
        expect(switch(name)).to_be_disabled()
        expect(page.locator('.publish-composer-tab.off').filter(has_text=name)).to_have_count(1)
    # 影片格式還沒有素材：錯誤只在動作列上方顯示一次（分頁裡不再另列）。
    page.get_by_role('radio', name='影片', exact=True).click()
    for name in ('Instagram', 'Threads'):
        switch(name).uncheck()
    reason = page.locator('#publish-disabled-reason')
    expect(reason).to_contain_text('Facebook：此格式需 1 個媒體檔')
    tab('Facebook')
    expect(page.locator('#composer-panel-facebook .publish-reasons')).to_have_count(0)
    expect(reason).to_have_text('Facebook：此格式需 1 個媒體檔')
    # 單一平台分頁只列該平台的錯誤；共用分頁才列出全部已開啟平台。
    switch('Instagram').check()
    expect(reason).to_have_text('Facebook：此格式需 1 個媒體檔')
    tab('共用')
    expect(reason).to_have_text('Facebook：此格式需 1 個媒體檔；Instagram：此格式需 1 個媒體檔')
    # TikTok 分頁：後端與前端同一條原因只列一次，不重複平台名稱，也不列其他平台。
    tab('TikTok')
    expect(reason).to_contain_text('TikTok：此格式需 1 個媒體檔')
    assert reason.inner_text().count('此格式需 1 個媒體檔') == 1, reason.inner_text()
    expect(reason).not_to_contain_text('TikTok：TikTok')
    expect(reason).not_to_contain_text('Facebook')
    tab('Facebook')
    switch('Facebook').uncheck()
    switch('Instagram').uncheck()
    expect(reason).to_have_text('請開啟要發佈的平台；Facebook：此格式需 1 個媒體檔')
    switch('Facebook').check()
    switch('Instagram').check()
    switch('Threads').check()
    tab('共用')
    checks.append('publish-reason-not-repeated-under-button')
    page.get_by_label('上傳媒體', exact=True).set_input_files({'name': 'composer2-isolated.mp4', 'mimeType': 'video/mp4', 'buffer': video_bytes()})
    expect(page.locator('.publish-media-row')).to_contain_text('12.0 秒')
    main = page.get_by_label('主文案', exact=True)
    main.fill('隔離新發佈畫面 @帳號 #主題\n\n共用文案可預覽。\n\n#結尾標籤 #第二個')
    expect(page.locator('.publish-preview')).to_contain_text('共用文案可預覽')
    # 超過平台折疊行數時，結尾 hashtag 收在「更多」裡，展開後才看得到，和平台實際行為一致。
    expect(page.locator('.publish-preview-highlight')).to_have_count(2)
    page.locator('.publish-preview-more').click()
    expect(page.locator('.publish-preview-highlight')).to_have_count(4)
    # 預覽照各平台真實排版：FB／Threads 文案在上、素材在下；IG 素材在上、互動列、帳號名稱＋文案在下。
    def preview_order():
        return page.locator('.publish-preview-post').first.evaluate(
            "e => [...e.children].map(c => c.className.baseVal ?? c.className).filter(n => /publish-preview-(media|caption|actions)/.test(n)).map(n => n.split(' ')[0])")
    preview_group = page.get_by_role('group', name='預覽平台')
    for name, expected_order in (('Facebook', ['publish-preview-caption', 'publish-preview-media', 'publish-preview-actions']),
                                 ('Threads', ['publish-preview-caption', 'publish-preview-media', 'publish-preview-actions']),
                                 ('Instagram', ['publish-preview-media', 'publish-preview-actions', 'publish-preview-caption'])):
        preview_group.get_by_role('button', name=name, exact=True).click()
        assert preview_order() == expected_order, (name, preview_order())
        capture('preview-' + name.lower())
    expect(page.locator('.publish-preview-caption .publish-preview-author')).to_have_count(1)
    page.locator('.publish-preview-more').click()
    expect(page.locator('.publish-preview-caption')).to_contain_text('#結尾標籤 #第二個')
    preview_group.get_by_role('button', name='Facebook', exact=True).click()
    expect(page.locator('.publish-preview-actions.is-facebook')).to_contain_text('讚')
    # 直式影片預覽高度：桌面 480px、手機 320px（寬度受限時依比例縮小）。
    media_box = page.locator('.publish-preview-media > div').first.bounding_box()
    expected = 480 if page.viewport_size['width'] > 767 else 320
    assert abs(media_box['height'] - expected) <= 2 or media_box['width'] >= page.locator('.publish-preview-media').bounding_box()['width'] - 1, media_box
    main.fill('隔離新發佈畫面 @帳號 #主題\n\n共用文案可預覽。')
    # Markdown：偵測到語法才說明發佈時會轉換；文案框保留原稿，預覽顯示轉換後實際送出的文字。
    expect(page.locator('.publish-markdown-hint')).to_have_count(0)
    main.fill('**New** 新品 *now*\n**測試**\n- 項目')
    hint = page.locator('.publish-markdown-hint')
    expect(hint).to_contain_text('發佈時會把 Markdown 轉成')
    expect(hint.get_by_role('button')).to_have_count(0)
    page.locator('.publish-preview-more').click() if page.locator('.publish-preview-more').count() else None
    expect(page.locator('.publish-preview-caption')).to_contain_text('𝗡𝗲𝘄 新品 𝘯𝘰𝘸\n測試\n• 項目')
    expect(main).to_have_value('**New** 新品 *now*\n**測試**\n- 項目')
    capture('markdown-hint')
    # 全形符號可直接輸入；格式按鈕（圖示）在選取的行插入 Markdown，預覽顯示轉換後的樣子。
    main.fill('')
    main.press_sequentially('＜新品＞ ')
    page.keyboard.insert_text('第一點\n第二點')
    expect(main).to_have_value('＜新品＞ 第一點\n第二點')
    expect(page.locator('.publish-preview-caption')).to_contain_text('＜新品＞')
    toolbar = page.get_by_role('toolbar', name='文案格式')
    main.evaluate("e => e.setSelectionRange(e.value.indexOf('第一點'), e.value.length)")
    toolbar.get_by_role('button', name='編號清單', exact=True).click()
    expect(main).to_have_value('1. ＜新品＞ 第一點\n2. 第二點')
    # 按鈕在下一個畫格才把選取範圍設回整段；先等它套用，否則之後設的游標會被蓋掉。
    main.evaluate('''e => new Promise(resolve => {
        const done = () => document.activeElement === e && e.selectionStart === 0 && e.selectionEnd === e.value.length;
        const wait = () => done() ? resolve() : requestAnimationFrame(wait);
        wait();
    })''')
    main.evaluate('e => e.setSelectionRange(0, 0)')
    toolbar.get_by_role('button', name='大標題', exact=True).click()
    expect(main).to_have_value('# ＜新品＞ 第一點\n2. 第二點')
    # 同樣先等標題按鈕在下一個畫格把選取範圍設回該行，否則之後填入的內容與游標會被蓋掉。
    main.evaluate('''e => new Promise(resolve => {
        const done = () => document.activeElement === e && e.selectionStart === 0 && e.selectionEnd === e.value.indexOf('\\n');
        const wait = () => done() ? resolve() : requestAnimationFrame(wait);
        wait();
    })''')
    assert toolbar.locator('button svg').count() == 5 and toolbar.locator('button').first.inner_text() == ''
    main.fill('New 新品')
    main.evaluate('e => e.setSelectionRange(0, 3)')
    toolbar.get_by_role('button', name='粗體', exact=True).click()
    expect(main).to_have_value('**New** 新品')
    expect(page.locator('.publish-preview-caption')).to_have_text('𝗡𝗲𝘄 新品')
    capture('caption-format')
    main.fill('隔離新發佈畫面 @帳號 #主題\n\n共用文案可預覽。')
    for name in ('Instagram', 'Threads', 'Facebook'):
        page.get_by_role('group', name='預覽平台').get_by_role('button', name=name, exact=True).click()
        expect(page.get_by_role('group', name='預覽平台').get_by_role('button', name=name, exact=True)).to_have_attribute('aria-pressed', 'true')
        assert page.get_by_role('group', name='預覽平台').get_by_role('button', name=name, exact=True).evaluate('e => getComputedStyle(e).fontWeight') == '600'
        assert page.locator('.publish-preview-avatar').first.evaluate(r"e => /^[\p{L}\p{N}]$/u.test(e.textContent)"), 'avatar must skip punctuation'
    capture('shared')
    # 平台文案預設共用；一改即專屬，還原後即時跟隨。
    tab('Facebook')
    fb = page.get_by_label('Facebook 文案', exact=True)
    expect(fb).to_have_value('隔離新發佈畫面 @帳號 #主題\n\n共用文案可預覽。')
    expect(page.get_by_role('radio', name='Reels', exact=True)).to_be_checked()
    expect(page.locator('#composer-panel-facebook .notice.warning')).to_contain_text('Facebook 發文無法標註')
    fb.fill('隔離 Facebook 專屬 @帳號')
    expect(page.get_by_role('button', name='還原為共用文案')).to_be_visible()
    expect(page.locator('.publish-preview')).to_contain_text('Facebook 專屬')
    page.get_by_role('button', name='還原為共用文案').click()
    expect(fb).to_have_value('隔離新發佈畫面 @帳號 #主題\n\n共用文案可預覽。')
    expect(page.get_by_role('button', name='還原為共用文案')).to_have_count(0)
    page.get_by_role('radio', name='影片貼文', exact=True).click()
    expect(page.get_by_role('radio', name='影片貼文', exact=True)).to_be_checked()
    page.get_by_role('radio', name='Reels', exact=True).click()
    capture('facebook-reels')
    # Facebook 影片封面：上傳後預覽；缺 pages_manage_engagement 時提示重新連結（不影響發佈）。
    import io
    import re

    from PIL import Image

    def jpeg(w, h):
        buffer = io.BytesIO()
        Image.new('RGB', (w, h), (40, 90, 160)).save(buffer, 'JPEG')
        return buffer.getvalue()

    fb_cover = page.locator('#composer-panel-facebook .publish-facebook-cover')
    expect(fb_cover).to_contain_text('JPG／PNG · 8 MB 內 · 建議與影片同比例 · 未上傳則由 Facebook 自動選')
    expect(fb_cover.locator('.publish-cover-hint')).to_contain_text('pages_manage_engagement')
    page.get_by_label('上傳 Facebook 影片封面', exact=True).set_input_files({'name': 'fb.jpg', 'mimeType': 'image/jpeg', 'buffer': jpeg(1080, 1920)})
    expect(fb_cover).to_contain_text('fb.jpg')
    expect(fb_cover.locator('img')).to_be_visible()
    expect(page.get_by_role('button', name='移除封面', exact=True)).to_have_class('primary danger')
    expect(page.locator('.publish-preview video').first).to_have_attribute('poster', re.compile(r'/media/\d+$'))
    capture('facebook-cover')
    checks.append('facebook-cover-upload-hint-preview')
    tab('Instagram')
    feed = page.get_by_role('switch', name='同時顯示在動態', exact=True)
    expect(feed).to_be_checked()
    feed.uncheck()
    expect(feed).not_to_be_checked()
    switch('Instagram').uncheck()
    expect(page.locator('#composer-panel-instagram')).to_contain_text('未開啟')
    ig = page.get_by_label('Instagram 文案', exact=True)
    expect(ig).to_be_enabled()
    ig.fill('隔離 Instagram 專屬')
    switch('Instagram').check()
    feed.check()
    capture('instagram')
    # 先存回再重開，專屬文案與影片選項不得遺失。
    feed.uncheck()
    page.get_by_role('button', name='存成草稿', exact=True).click()
    expect(page.locator('.notice.success')).to_have_text('草稿已儲存')
    page.reload()
    expect(main).to_contain_text('隔離新發佈畫面')
    tab('Instagram')
    expect(ig).to_have_value('隔離 Instagram 專屬')
    expect(feed).not_to_be_checked()
    # Reels 封面：上傳後顯示縮圖並當預覽封面，不算發佈素材；非 9:16 只提示；重開仍在。
    cover_box = page.locator('#composer-panel-instagram .publish-cover')
    expect(cover_box).to_contain_text('JPG／PNG · 8 MB 內 · 建議 9:16 · 未上傳則用影片第一格')
    expect(page.get_by_role('button', name='上傳封面', exact=True)).to_have_class('secondary')
    expect(page.get_by_role('button', name='移除封面', exact=True)).to_have_count(0)
    media_count = page.locator('.publish-media-row').count()
    page.get_by_label('上傳 Reels 封面', exact=True).set_input_files({'name': 'square.jpg', 'mimeType': 'image/jpeg', 'buffer': jpeg(1080, 1080)})
    expect(cover_box.locator('img')).to_be_visible()
    expect(cover_box).to_contain_text('square.jpg')
    idle_state = page.locator('.publish-editor')
    expect(idle_state).to_have_attribute('data-check-state', 'checked')
    expect(page.locator('#composer-panel-instagram .notice.warning')).to_contain_text('Reels 封面建議 9:16')
    assert page.locator('.publish-media-row').count() == media_count
    page.get_by_label('上傳 Reels 封面', exact=True).set_input_files({'name': 'cover.jpg', 'mimeType': 'image/jpeg', 'buffer': jpeg(1080, 1920)})
    expect(cover_box).to_contain_text('cover.jpg')
    expect(page.get_by_role('button', name='更換封面', exact=True)).to_have_class('secondary')
    expect(page.get_by_role('button', name='移除封面', exact=True)).to_have_class('primary danger')
    expect(idle_state).to_have_attribute('data-check-state', 'checked')
    expect(page.locator('#composer-panel-instagram .notice.warning').filter(has_text='Reels 封面')).to_have_count(0)
    expect(page.locator('.publish-preview video').first).to_have_attribute('poster', re.compile(r'/media/\d+$'))
    capture('instagram-cover')
    page.reload()
    tab('Instagram')
    expect(cover_box).to_contain_text('cover.jpg')
    # 移除後回到預設，再上傳一次留給確認視窗。
    page.get_by_role('button', name='移除封面', exact=True).click()
    expect(cover_box).to_contain_text('未上傳則用影片第一格')
    page.get_by_label('上傳 Reels 封面', exact=True).set_input_files({'name': 'cover.jpg', 'mimeType': 'image/jpeg', 'buffer': jpeg(1080, 1920)})
    expect(cover_box).to_contain_text('cover.jpg')
    checks.append('instagram-cover-upload-replace-remove-preview-reload')
    ig.fill('文' * 2201 + ' ' + '#標籤 ' * 31 + '@帳號 ' * 21)
    expect(page.locator('#publish-disabled-reason')).to_contain_text('Instagram：hashtag 超過 1')
    expect(page.locator('#publish-disabled-reason')).to_contain_text('@ 超過 1')
    expect(page.locator('#composer-tab-instagram .publish-tab-error')).to_have_count(1)
    expect(page.locator('.publish-actions .primary')).to_be_disabled()
    page.get_by_role('button', name='還原為共用文案').click()
    # Threads 串文：Threads 文案是第一則、下面是各則回覆；各則獨立、互不同步，不自動分段，超過 500 字只標紅。
    # 用鍵盤逐字輸入，模擬實際打字。
    def type_into(locator, text):
        locator.click()
        page.keyboard.press('Control+End')
        page.keyboard.type(text)
    tab('共用')
    main.fill('隔離串文主文案 #主題 #第二')
    tab('Threads')
    threads_caption = page.get_by_label('Threads 文案', exact=True)
    expect(threads_caption).to_have_value('隔離串文主文案 #主題 #第二')
    expect(page.locator('.publish-segment')).to_have_count(0)
    expect(page.get_by_role('button', name='依主文案重新分段')).to_have_count(0)
    expect(page.locator('.publish-preview-post')).to_have_count(1)
    expect(page.locator('.publish-preview-topic')).to_have_text('主題標籤：主題')
    expect(page.locator('#composer-panel-threads .notice.warning')).to_contain_text('第一個 hashtag')
    # 修改 Threads 文案只改第一則，不會產生分段。
    type_into(threads_caption, '，補充')
    expect(page.locator('.publish-segment')).to_have_count(0)
    expect(page.locator('.publish-preview-caption')).to_have_text(['隔離串文主文案 #主題 #第二，補充'])
    # 新增回覆後各則獨立：輸入回覆不改 Threads 文案、不改主文案、不改前面的回覆。
    page.get_by_role('button', name='新增回覆', exact=True).click()
    type_into(page.get_by_label('Threads 回覆 1', exact=True), '隔離回覆一')
    page.get_by_role('button', name='新增回覆', exact=True).click()
    type_into(page.get_by_label('Threads 回覆 2', exact=True), '隔離回覆二')
    expect(threads_caption).to_have_value('隔離串文主文案 #主題 #第二，補充')
    expect(page.get_by_label('Threads 回覆 1', exact=True)).to_have_value('隔離回覆一')
    expect(page.locator('.publish-preview-caption')).to_have_text(['隔離串文主文案 #主題 #第二，補充', '隔離回覆一', '隔離回覆二'])
    type_into(threads_caption, '再改')
    expect(page.get_by_label('Threads 回覆 1', exact=True)).to_have_value('隔離回覆一')
    expect(page.get_by_label('Threads 回覆 2', exact=True)).to_have_value('隔離回覆二')
    tab('共用')
    expect(main).to_have_value('隔離串文主文案 #主題 #第二')
    tab('Threads')
    # 超過 500 字只標紅並停用發佈，不自動拆；輸入框下方指出從第幾個字開始超出（鍵盤打到第 501 個字）。
    threads_caption.fill('超' * 499)
    expect(page.locator('.publish-over-limit')).to_have_count(0)
    type_into(threads_caption, '過限')
    expect(page.locator('#composer-panel-threads label small.publish-reasons')).to_have_text('501 字／500')
    expect(page.locator('.publish-over-limit')).to_have_text(['Threads 文案超過 500 字上限：共 501 字，從第 501 個字「限」開始超出'])
    # 前端即時檢查與後端理由同一句時只出現一次（輸入框下方已顯示的不再列進分頁錯誤清單）。
    expect(page.locator('#composer-panel-threads').get_by_text('開始超出')).to_have_count(1)
    expect(page.locator('.publish-segment')).to_have_count(2)
    type_into(page.get_by_label('Threads 回覆 2', exact=True), '丙' * 500)
    expect(page.locator('.publish-over-limit').last).to_have_text('回覆 2超過 500 字上限：共 505 字，從第 501 個字「丙丙丙丙丙」開始超出')
    expect(page.locator('#composer-panel-threads').get_by_text('回覆 2超過 500 字上限').first).to_be_visible()
    page.get_by_label('Threads 回覆 2', exact=True).fill('隔離回覆二')
    expect(page.locator('#composer-tab-threads .publish-tab-error')).to_have_count(1)
    expect(page.locator('.publish-actions .primary')).to_be_disabled()
    capture('threads-over-limit')
    # 刪除回覆、還原為共用文案只影響第一則；存回重開後保留。
    page.locator('.publish-segment').last.get_by_role('button', name='刪除回覆').click()
    expect(page.locator('.publish-segment')).to_have_count(1)
    page.get_by_role('button', name='還原為共用文案').click()
    expect(threads_caption).to_have_value('隔離串文主文案 #主題 #第二')
    expect(page.get_by_label('Threads 回覆 1', exact=True)).to_have_value('隔離回覆一')
    tab('共用')
    main.fill('依主文案重新分段後只剩一段 #主題')
    tab('Threads')
    page.get_by_label('Threads 回覆 1', exact=True).fill('隔離回覆內容，不加編號。')
    page.get_by_role('button', name='存成草稿', exact=True).click()
    expect(page.locator('.notice.success')).to_have_text('草稿已儲存')
    page.reload()
    expect(main).to_have_value('依主文案重新分段後只剩一段 #主題')
    tab('Threads')
    expect(threads_caption).to_have_value('依主文案重新分段後只剩一段 #主題')
    expect(page.locator('.publish-segment')).to_have_count(1)
    expect(page.get_by_label('Threads 回覆 1', exact=True)).to_have_value('隔離回覆內容，不加編號。')
    expect(page.locator('.publish-preview-caption')).to_have_text(['依主文案重新分段後只剩一段 #主題', '隔離回覆內容，不加編號。'])
    checks.append('threads-caption-first-post-independent-replies-no-auto-split-save-reopen')
    # TikTok 尚未連結時與其他平台一致：顯示「尚未連結」與前往平台連結。
    tab('TikTok')
    tiktok_panel = page.locator('#composer-panel-tiktok')
    expect(tiktok_panel).to_contain_text('尚未連結')
    expect(tiktok_panel.get_by_role('link', name='設定 → 平台連結', exact=True)).to_be_visible()
    checks.append('tiktok-unlinked-shows-connection-hint')
    tab('YouTube')
    expect(page.locator('#composer-panel-youtube')).to_contain_text('尚未連結')
    link = page.get_by_role('link', name='設定 → 平台連結', exact=True)
    expect(link).to_have_attribute('href', '?view=settings&settings_tab=connections&brand_id=' + page.url.split('brand_id=')[1].split('&')[0] + '&publish_post_id=' + page.url.split('publish_post_id=')[1].split('&')[0])
    capture('youtube-disconnected')
    link.click()
    expect(page.get_by_role('tab', name='平台連線', exact=True)).to_have_attribute('aria-selected', 'true')
    navigate(page, '發佈')
    expect(main).to_have_value('依主文案重新分段後只剩一段 #主題')
    # 權杖失效使用 options 假 HTTP 回應，灰色仍可導覽但不可開啟。
    def unavailable(route):
        response = route.fetch()
        payload = response.json()
        payload['platforms']['facebook']['ready'] = False
        payload['platforms']['facebook']['reasons'] = ['授權無效，請重新連結帳號']
        route.fulfill(response=response, json=payload)
    page.route('**/api/publish/options?*', unavailable)
    page.reload()
    expect(switch('Facebook')).to_be_disabled()
    tab('Facebook')
    expect(page.locator('#composer-panel-facebook')).to_contain_text('尚未連結')
    expect(page.get_by_role('link', name='設定 → 平台連結')).to_be_visible()
    page.unroute('**/api/publish/options?*', unavailable)
    page.reload()
    expect(switch('Facebook')).to_be_enabled()
    tab('Facebook')
    page.get_by_label('存成 FB 草稿（不發佈，可在 Meta Business Suite 草稿編輯後再發）', exact=True).check()
    # FB 草稿同樣支援 Reels，不再出現「已改用影片貼文」提示。
    expect(page.locator('#composer-panel-facebook')).not_to_contain_text('已改用')
    button = page.locator('.publish-actions .primary')
    expect(button).to_be_enabled()
    button.click()
    dialog = page.get_by_role('dialog')
    expect(dialog).to_contain_text('Reels · 自訂封面 · 草稿')
    expect(dialog).to_contain_text('Reels · 不顯示在動態 · 自訂封面')
    expect(dialog).to_contain_text('串文 · 2 段')
    expect(dialog).to_contain_text('存成草稿，不發佈')
    capture('confirmation')
    dialog.get_by_role('button', name='取消', exact=True).click()
    checks.append('composer2-tabs-switches-unlinked-copy-options-rules-preview-confirm')
    # composer1 detail 進度不回送已完成段落；紀錄呈現完整段數。
    from app.db import build_engine, session_factory
    from app.models import Account, Brand, PublishPost, PublishTarget, Staff
    from sqlalchemy import select

    engine = build_engine(settings)
    try:
        with session_factory(engine).begin() as session:
            brand = session.scalar(select(Brand).where(Brand.slug == 'TEST'))
            staff = session.scalar(select(Staff).where(Staff.username == 'admin'))
            row = PublishPost(brand_id=brand.id, creator_id=staff.id, format='text', caption='隔離串文進度-' + str(size['width']), platforms_json=['threads'], status='partial')
            session.add(row)
            session.flush()
            account = session.scalar(select(Account).where(Account.brand_id == brand.id, Account.platform == 'threads'))
            session.add(PublishTarget(post_id=row.id, account_id=account.id, platform='threads', status='failed', detail_json={'successful_segments': 2, 'total_segments': 3}))
            # FB 封面套用失敗：貼文仍成功。與串文進度一起先建好，再開發佈紀錄（重新整理後馬上點分頁在高負載時會偶發逾時）。
            facebook = session.scalar(select(Account).where(Account.brand_id == brand.id, Account.platform == 'facebook'))
            row = PublishPost(brand_id=brand.id, creator_id=staff.id, format='video', caption='隔離 FB 封面未套用-' + str(size['width']), platforms_json=['facebook'], status='done')
            session.add(row)
            session.flush()
            session.add(PublishTarget(post_id=row.id, account_id=facebook.id, platform='facebook', status='succeeded', platform_post_id='9901',
                                      permalink='https://www.facebook.com/reel/9901', detail_json={'cover': {'status': 'failed', 'code': 'permission_missing'}}))
        page.get_by_role('tab', name='發佈紀錄', exact=True).click()
        progress = page.locator('.publish-record').filter(has_text='隔離串文進度-' + str(size['width']))
        progress.get_by_role('button', name='各平台結果').click()
        expect(progress.locator('.publish-targets')).to_contain_text('已發 2／3 段')
        checks.append('composer2-thread-history-progress')
        # 紀錄顯示「封面未套用」、中文原因與重新套用（確認視窗可取消）。
        failed = page.locator('.publish-record').filter(has_text='隔離 FB 封面未套用-' + str(size['width']))
        failed.get_by_role('button', name='各平台結果').click()
        targets = failed.locator('.publish-targets')
        expect(targets.locator('.status-badge.pending')).to_have_text('封面未套用')
        expect(targets).to_contain_text('缺少 pages_manage_engagement 權限，請重新連結 Meta 後再重新套用')
        targets.get_by_role('button', name='重新套用封面', exact=True).click()
        dialog = page.get_by_role('dialog')
        expect(dialog).to_contain_text('重新套用封面到 Facebook？只會更換封面，不會重傳影片。')
        dialog.get_by_role('button', name='取消', exact=True).click()
        checks.append('facebook-cover-failed-history-reapply-dialog')
    finally:
        engine.dispose()



def check_stories(page, settings, checks):
    import base64
    from urllib.parse import parse_qs, urlsplit

    from app.db import build_engine, session_factory
    from app.models import PublishPost
    from app.models.base import utc_now
    from app.services import publish, publish_story_insights

    for path in (settings.database_path, settings.export_root, settings.publish_media_root):
        assert path.resolve().is_relative_to(REPO / '.runtime')
    size = page.viewport_size
    folder = REPO / '.runtime/composer3-screens'
    folder.mkdir(parents=True, exist_ok=True)
    settle = 'async () => { await document.fonts.ready; await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); }'

    def capture(name, focus):
        page.wait_for_load_state('networkidle')
        page.evaluate(settle)
        for width, height in [(1440, 900), (768, 1024), (390, 844)]:
            page.set_viewport_size({'width': width, 'height': height})
            page.evaluate(settle)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (name, width)
            if page.locator('.publish-editor').count():
                assert page.locator('.publish-composer-panel').evaluate('e => e.scrollWidth <= e.clientWidth + 1'), (name, width)
        page.set_viewport_size(size)
        page.evaluate(settle)
        page.locator(focus).first.evaluate("e => e.scrollIntoView({block: 'start'})")
        page.screenshot(path=str(folder / f'{name}-{size["width"]}x{size["height"]}.png'))
        checks.append('composer3-' + name)

    page.get_by_role('tab', name='限時動態', exact=True).click()
    expect(page.locator('.publish-editor')).to_have_attribute('aria-busy', 'false')
    expect(page.get_by_role('tablist', name='文案平台').get_by_role('tab')).to_have_text(['Facebook', 'Instagram'])
    expect(page.locator('.publish-editor textarea')).to_have_count(0)
    facebook_tab = page.get_by_role('tab', name='Facebook', exact=True)
    facebook_tab.focus()
    facebook_tab.press('ArrowLeft')
    expect(page.get_by_role('tab', name='Instagram', exact=True)).to_have_attribute('aria-selected', 'true')
    page.get_by_role('tab', name='Instagram', exact=True).press('ArrowRight')
    expect(facebook_tab).to_have_attribute('aria-selected', 'true')
    expect(page.locator('.publish-accounts')).not_to_contain_text('Threads')
    for platform in ('Facebook', 'Instagram'):
        switch = page.get_by_role('switch', name='發佈到 ' + platform, exact=True)
        expect(switch).to_be_enabled()
        switch.check()
    # 用瀏覽器 canvas 產生真正可預覽的隔離 JPEG，不載入外部素材。
    data = page.evaluate("""() => {
        const canvas = document.createElement('canvas'); canvas.width = 360; canvas.height = 640;
        const ctx = canvas.getContext('2d'), tokens = getComputedStyle(document.documentElement);
        ctx.fillStyle = tokens.getPropertyValue('--bg-subtle'); ctx.fillRect(0, 0, 360, 640);
        ctx.fillStyle = tokens.getPropertyValue('--brand-primary'); ctx.fillRect(32, 64, 296, 480);
        ctx.fillStyle = tokens.getPropertyValue('--bg-surface'); ctx.font = '28px sans-serif';
        ctx.fillText('隔離限時動態', 90, 280); ctx.font = '18px sans-serif'; ctx.fillText('素材預覽', 144, 320);
        return canvas.toDataURL('image/jpeg').split(',')[1];
    }""")
    jpeg = base64.b64decode(data)
    def files(count):
        return [{'name': f'story-{index + 1}.jpg', 'mimeType': 'image/jpeg', 'buffer': jpeg} for index in range(count)]
    page.get_by_label('上傳媒體', exact=True).set_input_files(files(3))
    rows = page.locator('.publish-media-row')
    expect(rows).to_have_count(3)
    expect(page.locator('.publish-story-navigation')).to_contain_text('1／3')
    page.get_by_role('button', name='下一則', exact=True).click()
    expect(page.locator('.publish-story-navigation')).to_contain_text('2／3')
    page.get_by_role('button', name='上一則', exact=True).click()
    assert page.locator('.publish-preview-media > div').evaluate("e => getComputedStyle(e).aspectRatio") == '9 / 16'
    # HTML drag/drop 事件與持久化順序（手機也支援上移／下移）。
    first = rows.first.locator('strong').inner_text()
    transfer = page.evaluate_handle('new DataTransfer()')
    rows.first.dispatch_event('dragstart', {'dataTransfer': transfer})
    rows.nth(2).dispatch_event('drop', {'dataTransfer': transfer})
    expect(rows.last.locator('strong')).to_have_text(first)
    expect(page.locator('.publish-editor')).to_have_attribute('aria-busy', 'false')
    rows.last.get_by_role('button', name='上移', exact=True).click()
    expect(rows.nth(1).locator('strong')).to_have_text(first)
    capture('stories', '.publish-editor')
    page.get_by_label('上傳媒體', exact=True).set_input_files(files(7))
    expect(rows).to_have_count(10)
    # 上傳期間的自動存檔不可版本衝突，也不可因等寫入鎖回 503。
    expect(page.locator('.notice.danger')).to_have_count(0)
    expect(page.get_by_role('button', name='拖曳或點選上傳', exact=True)).to_be_disabled()
    page.get_by_label('上傳媒體', exact=True).set_input_files(files(1))
    expect(page.locator('.notice.danger')).to_contain_text('最多 10 則')
    expect(rows).to_have_count(10)
    for _ in range(8):
        rows.last.get_by_role('button', name='移除', exact=True).click()
        expect(page.locator('.publish-editor')).to_have_attribute('aria-busy', 'false')
    expect(rows).to_have_count(2)
    expect(page.get_by_role('button', name='拖曳或點選上傳', exact=True)).to_be_enabled()
    page.get_by_label('上傳媒體', exact=True).set_input_files({'name': 'invalid-61s.mp4', 'mimeType': 'video/mp4', 'buffer': video_bytes(duration=61)})
    expect(rows).to_have_count(3)
    expect(page.locator('#publish-disabled-reason')).to_contain_text('60 秒')
    expect(page.locator('.publish-editor .publish-reasons')).to_have_count(1)
    reason = page.locator('#publish-disabled-reason').inner_text()
    # 限時動態沒有共用分頁：每個平台分頁只列自己的錯誤。
    assert reason.count('Facebook：') == 1 and 'Instagram：' not in reason, reason
    page.get_by_role('tab', name='Instagram', exact=True).click()
    expect(page.locator('#publish-disabled-reason')).to_contain_text('Instagram：')
    expect(page.locator('#publish-disabled-reason')).not_to_contain_text('Facebook：')
    page.get_by_role('tab', name='Facebook', exact=True).click()
    expect(page.locator('.publish-actions .secondary')).to_have_count(0)
    expect(page.locator('.publish-actions .primary')).to_be_disabled()
    check_editor_layout(page, reason=True)
    page.locator('.publish-footer').evaluate("e => e.scrollIntoView({block: 'end'})")
    page.screenshot(path=str(folder / f'story-footer-{size["width"]}x{size["height"]}.png'))
    capture('spec-error', '#publish-disabled-reason' if size['width'] < 600 else '.publish-composer-fields')
    rows.last.get_by_role('button', name='移除', exact=True).click()
    expect(rows).to_have_count(2)
    # 未連結灰色平台仍可開啟分頁，開關停用並可導向設定。
    def unavailable(route):
        response = route.fetch()
        payload = response.json()
        payload['platforms']['instagram']['ready'] = False
        route.fulfill(response=response, json=payload)
    page.route('**/api/publish/options?*', unavailable)
    page.reload()
    expect(page.get_by_role('tab', name='限時動態', exact=True)).to_have_attribute('aria-selected', 'true')
    expect(page.get_by_role('switch', name='發佈到 Instagram', exact=True)).to_be_disabled()
    page.get_by_role('tab', name='Instagram', exact=True).click()
    expect(page.locator('#composer-panel-instagram')).to_contain_text('尚未連結')
    expect(page.get_by_role('link', name='設定 → 平台連結', exact=True)).to_be_visible()
    page.unroute('**/api/publish/options?*', unavailable)
    page.reload()
    expect(page.locator('.publish-editor')).to_have_attribute('aria-busy', 'false')
    expect(page.locator('.publish-editor textarea')).to_have_count(0)
    button = page.locator('.publish-actions .primary')
    expect(button).to_be_enabled()
    button.click()
    dialog = page.get_by_role('dialog')
    expect(dialog).to_contain_text('Facebook')
    expect(dialog).to_contain_text('Instagram')
    expect(dialog.locator('.publish-confirm-options')).to_have_text(['限時動態 · 2 則', '限時動態 · 2 則'])
    expect(dialog).not_to_contain_text('（無文案）')
    capture('confirmation', '[role=dialog]')
    identity = int(parse_qs(urlsplit(page.url).query)['publish_post_id'][0])
    dialog.get_by_role('button', name='確認發佈', exact=True).click()
    history = page.locator('.publish-record').filter(has_text='限時動態')
    expect(history).to_have_count(1)
    expect(history).to_contain_text('成功')
    engine = build_engine(settings)
    try:
        with session_factory(engine).begin() as session:
            assert session.get(PublishPost, identity).format == 'story'
            target = next(t for t in publish.targets(session, identity) if t.platform == 'instagram')
            for position in (1, 2):
                publish_story_insights.store(session, target.id, position, utc_now(), {
                    'views': 1200 * position, 'reach': 900, 'replies': 8, 'shares': 12,
                    'navigation': 20, 'follows': 5, 'profile_visits': 16,
                }, final=position == 2)
    finally:
        engine.dispose()
    page.reload()
    page.get_by_role('tab', name='發佈紀錄', exact=True).click()
    history.get_by_role('button', name='各平台結果', exact=True).click()
    expect(history).to_contain_text('Facebook 不提供限時動態成效')
    expect(history.locator('.publish-story-result')).to_have_count(2)
    expect(history).to_contain_text('1,200')
    expect(history).to_contain_text('最終值')
    capture('history-insights', '.publish-record:has(.publish-story-results)')
    checks.append('composer3-platforms-no-caption-cap-order-delete-spec-preview-confirm-history-insights')

def check_youtube(page, settings, checks):
    """YouTube 發佈：分頁欄位、Shorts、非影片停用、預覽排版、確認視窗、縮圖失敗與重新套用；全部是假 HTTP。"""
    import re
    from urllib.parse import urlsplit

    from app.db import build_engine, session_factory
    from app.models import Account, Brand, PublishPost, PublishTarget, Staff
    from app.models.base import utc_now
    from sqlalchemy import select

    origin = urlsplit(page.url)._replace(path='', query='', fragment='').geturl()
    size = page.viewport_size
    width = size['width']
    folder = REPO / '.runtime/ytpublish-screens'
    folder.mkdir(parents=True, exist_ok=True)
    flag = settings.database_path.parent / 'youtube-thumbnail-error.json'
    flag.unlink(missing_ok=True)
    settle = 'async () => { await document.fonts.ready; await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); }'
    title_text = f'隔離 YouTube 標題-{width}'
    custom = f'隔離自訂標題-{width}'
    caption = title_text + '\n\nYouTube 說明內容 #隔離'
    panel = page.locator('#composer-panel-youtube')

    def switch(name):
        return page.get_by_role('switch', name='發佈到 ' + name, exact=True)

    def tab(name):
        page.get_by_role('tab', name=name, exact=True).click()
        expect(page.locator('.publish-editor')).to_have_attribute('aria-busy', 'false')
        expect(page.get_by_role('tab', name=name, exact=True)).to_have_attribute('aria-selected', 'true')

    def idle():
        # 表單變更後 650 毫秒才會檢查；等檢查完成再斷言按鈕與錯誤。
        expect(page.locator('.publish-editor')).to_have_attribute('aria-busy', 'false')
        expect(page.locator('.publish-editor')).to_have_attribute('data-check-state', 'checked')

    def canvas_jpeg(w, h):
        import base64
        data = page.evaluate("""([w, h]) => {
            const canvas = document.createElement('canvas'); canvas.width = w; canvas.height = h;
            const ctx = canvas.getContext('2d'), tokens = getComputedStyle(document.documentElement);
            ctx.fillStyle = tokens.getPropertyValue('--bg-subtle'); ctx.fillRect(0, 0, w, h);
            ctx.fillStyle = tokens.getPropertyValue('--brand-primary'); ctx.fillRect(w * 0.08, h * 0.12, w * 0.5, h * 0.76);
            ctx.fillStyle = tokens.getPropertyValue('--bg-surface'); ctx.font = (h / 8) + 'px sans-serif';
            ctx.fillText('隔離縮圖', w * 0.14, h * 0.5);
            return canvas.toDataURL('image/jpeg').split(',')[1];
        }""", [w, h])
        return base64.b64decode(data)

    def capture(name, focus):
        page.wait_for_load_state('networkidle')
        page.evaluate(settle)
        for w, h in [(1440, 900), (768, 1024), (390, 844)]:
            page.set_viewport_size({'width': w, 'height': h})
            page.evaluate(settle)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (name, w)
            assert page.locator(focus).first.evaluate('e => e.scrollWidth <= e.clientWidth + 1'), (name, w)
        page.set_viewport_size(size)
        page.evaluate(settle)
        page.locator(focus).first.evaluate("e => e.scrollIntoView({block: 'start'})")
        page.screenshot(path=str(folder / f'{name}-{size["width"]}x{size["height"]}.png'))
        checks.append('ytpublish-' + name)

    engine = build_engine(settings)
    factory = session_factory(engine)
    try:
        with factory.begin() as session:
            brand = session.scalar(select(Brand).where(Brand.slug == 'TEST'))
            seed_youtube(session, settings, brand.id)
        page.goto(origin)
        expect(page.locator('.dashboard-kpis .kpi')).to_have_count(2)
        navigate(page, '發佈')
        page.get_by_role('tab', name='新增貼文', exact=True).click()
        expect(page.locator('.publish-editor')).to_have_attribute('aria-busy', 'false')
        page.get_by_role('button', name='新貼文', exact=True).click()
        # 已連結且有上傳權限的 YouTube：開關可用、頻道名稱出現在發佈帳號。
        expect(page.locator('.publish-accounts')).to_contain_text('隔離 YouTube 頻道')
        expect(switch('YouTube')).to_be_enabled()
        expect(page.locator('.publish-composer-tab.ready').filter(has_text='YouTube')).to_have_count(1)
        page.get_by_label('上傳媒體', exact=True).set_input_files({'name': 'yt-isolated.mp4', 'mimeType': 'video/mp4', 'buffer': video_bytes(1920, 1080)})
        expect(page.locator('.publish-media-row')).to_contain_text('12.0 秒')
        main = page.get_by_label('主文案', exact=True)
        main.fill(caption)
        switch('YouTube').check()
        tab('YouTube')
        # 欄位：標題（預設沿用說明第一行，以灰字顯示）、說明（位元組）、公開狀態、兒童內容、縮圖。
        title = page.get_by_label('YouTube 標題', exact=True)
        expect(title).to_have_value('')
        expect(title).to_have_attribute('placeholder', title_text)
        expect(panel).to_contain_text(re.compile(r'\d+／100 字'))
        description = page.get_by_label('YouTube 說明', exact=True)
        expect(description).to_have_value(caption)
        expect(panel).to_contain_text('／5,000 位元組')
        privacy = page.get_by_role('radiogroup', name='公開狀態', exact=True)
        expect(privacy.get_by_role('radio')).to_have_text(['公開', '不公開', '私人'])
        expect(privacy.get_by_role('radio', name='公開', exact=True)).to_be_checked()
        kids = page.get_by_label('這是為兒童製作的內容', exact=True)
        expect(kids).not_to_be_checked()
        expect(page.locator('.publish-thumbnail')).to_contain_text('未上傳則用自動縮圖')
        expect(page.get_by_role('button', name='上傳縮圖', exact=True)).to_have_class('secondary')
        expect(page.get_by_role('button', name='移除縮圖', exact=True)).to_have_count(0)
        # 縮圖：預覽顯示、不算發佈素材（素材清單仍只有影片）。
        page.get_by_label('上傳縮圖', exact=True).set_input_files({'name': 'thumb.jpg', 'mimeType': 'image/jpeg', 'buffer': canvas_jpeg(1280, 720)})
        expect(page.locator('.publish-thumbnail img')).to_be_visible()
        page.wait_for_function("() => { const e = document.querySelector('.publish-thumbnail img'); return !!e && e.complete && e.naturalWidth === 1280; }")
        expect(page.locator('.publish-thumbnail')).to_contain_text('thumb.jpg')
        expect(page.get_by_role('button', name='更換縮圖', exact=True)).to_have_class('secondary')
        expect(page.get_by_role('button', name='移除縮圖', exact=True)).to_have_class('primary danger')
        idle()
        tab('共用')
        expect(page.locator('.publish-media-row')).to_have_count(1)
        tab('YouTube')
        # 標題 100 字、說明 5000 位元組：超過就紅字並擋發佈。
        title.fill('字' * 101)
        idle()
        expect(page.locator('#publish-disabled-reason')).to_contain_text('YouTube：標題最多 100 字')
        expect(page.locator('#composer-tab-youtube .publish-tab-error')).to_have_count(1)
        expect(page.locator('.publish-actions .primary')).to_be_disabled()
        title.fill('字' * 100)
        idle()
        expect(page.locator('#publish-disabled-reason')).to_have_count(0)
        expect(page.locator('.publish-actions .primary')).to_be_enabled()
        description.fill('字' * 1667)
        idle()
        expect(page.locator('#publish-disabled-reason')).to_contain_text('5,000 位元組')
        expect(page.locator('.publish-actions .primary')).to_be_disabled()
        description.fill('字' * 1666 + 'ab')
        idle()
        expect(page.locator('#publish-disabled-reason')).to_have_count(0)
        page.get_by_role('button', name='還原為共用文案').click()
        expect(description).to_have_value(caption)
        checks.append('ytpublish-fields-limits-thumbnail-not-media')
        # 選項隨草稿保存；縮圖由伺服端保存，重新開啟仍在。
        title.fill(custom)
        privacy.get_by_role('radio', name='不公開', exact=True).click()
        kids.check()
        page.get_by_role('button', name='存成草稿', exact=True).click()
        expect(page.locator('.notice.success')).to_have_text('草稿已儲存')
        page.reload()
        tab('YouTube')
        expect(title).to_have_value(custom)
        expect(privacy.get_by_role('radio', name='不公開', exact=True)).to_be_checked()
        expect(kids).to_be_checked()
        expect(page.locator('.publish-thumbnail img')).to_be_visible()
        idle()
        capture('youtube-tab', '.publish-composer-fields' if width <= 767 else '.publish-editor')
        # 預覽：影片 → 標題（粗體）→ 頻道名稱 → 互動列 → 說明；縮圖當封面，一般影片 16:9。
        preview = page.locator('.publish-preview')
        order = preview.locator('.publish-preview-post').first.evaluate(
            "e => [...e.children].map(c => c.className.baseVal ?? c.className).map(n => n.split(' ')[0])")
        assert order == ['publish-preview-media', 'publish-preview-title', 'publish-preview-identity', 'publish-preview-actions', 'publish-preview-caption'], order
        expect(preview.locator('.publish-preview-title')).to_have_text(custom)
        assert preview.locator('.publish-preview-title').evaluate('e => Number(getComputedStyle(e).fontWeight) >= 600')
        expect(preview.locator('.publish-preview-identity strong')).to_have_text('隔離 YouTube 頻道')
        expect(preview.locator('.publish-preview-actions.is-youtube')).to_contain_text('讚')
        expect(preview.locator('.publish-preview-caption')).to_contain_text('YouTube 說明內容')
        assert preview.locator('.publish-preview-media > div').evaluate('e => getComputedStyle(e).aspectRatio') == '16 / 9'
        expect(preview.locator('video')).to_have_attribute('poster', re.compile(r'/api/publish/posts/\d+/media/\d+$'))
        capture('youtube-preview', '.publish-preview')
        # Shorts：直式且 3 分鐘內只提示「將被歸為 Shorts」；不支援縮圖，帶縮圖就擋；預覽改直式。
        tab('共用')
        page.locator('.publish-media-row').get_by_role('button', name='移除', exact=True).click()
        expect(page.locator('.publish-media-row')).to_have_count(0)
        page.get_by_label('上傳媒體', exact=True).set_input_files({'name': 'yt-short.mp4', 'mimeType': 'video/mp4', 'buffer': video_bytes()})
        expect(page.locator('.publish-media-row')).to_contain_text('1080 × 1920')
        tab('YouTube')
        idle()
        expect(panel.locator('.notice.warning')).to_contain_text('將被歸為 Shorts')
        expect(page.get_by_role('button', name='更換縮圖', exact=True)).to_be_disabled()
        expect(page.locator('.publish-thumbnail')).to_contain_text('Shorts 不支援自訂縮圖')
        expect(page.locator('#publish-disabled-reason')).to_contain_text('Shorts 不支援自訂縮圖，請移除縮圖')
        expect(page.locator('.publish-actions .primary')).to_be_disabled()
        assert preview.locator('.publish-preview-media > div').evaluate('e => getComputedStyle(e).aspectRatio') == '9 / 16'
        assert preview.locator('video').get_attribute('poster') is None
        page.get_by_role('button', name='移除縮圖', exact=True).click()
        expect(page.locator('.publish-thumbnail img')).to_have_count(0)
        idle()
        expect(page.locator('#publish-disabled-reason')).to_have_count(0)
        expect(page.locator('.publish-actions .primary')).to_be_enabled()
        expect(page.locator('.publish-thumbnail')).to_contain_text('Shorts 不支援自訂縮圖')
        checks.append('ytpublish-shorts-notice-no-thumbnail')
        # 換回一般影片並重傳縮圖。
        tab('共用')
        page.locator('.publish-media-row').get_by_role('button', name='移除', exact=True).click()
        expect(page.locator('.publish-media-row')).to_have_count(0)
        page.get_by_label('上傳媒體', exact=True).set_input_files({'name': 'yt-isolated.mp4', 'mimeType': 'video/mp4', 'buffer': video_bytes(1920, 1080)})
        expect(page.locator('.publish-media-row')).to_contain_text('1920 × 1080')
        tab('YouTube')
        page.get_by_label('上傳縮圖', exact=True).set_input_files({'name': 'thumb.jpg', 'mimeType': 'image/jpeg', 'buffer': canvas_jpeg(1280, 720)})
        expect(page.locator('.publish-thumbnail img')).to_be_visible()
        idle()
        # 非影片格式：YouTube 開關停用並移除，分頁只顯示「YouTube 只支援影片」。
        for format_name in ('圖片', '輪播', '純文字'):
            tab('共用')
            page.get_by_role('radio', name=format_name, exact=True).click()
            expect(switch('YouTube')).to_be_disabled()
            expect(switch('YouTube')).not_to_be_checked()
            expect(switch('YouTube')).to_have_attribute('title', 'YouTube 只支援影片')
            tab('YouTube')
            expect(panel).to_contain_text('YouTube 只支援影片')
            expect(title).to_have_count(0)
            expect(page.locator('#composer-tab-youtube .publish-tab-error')).to_have_count(0)
        tab('共用')
        page.get_by_role('radio', name='影片', exact=True).click()
        expect(switch('YouTube')).to_be_enabled()
        expect(switch('YouTube')).not_to_be_checked()
        switch('YouTube').check()
        tab('YouTube')
        expect(title).to_have_value(custom)
        checks.append('ytpublish-non-video-disabled')
        # 缺少上傳權限：灰色並引導重新連結（比照 Threads 的 data_missing）。
        def reconnect(route):
            response = route.fetch()
            payload = response.json()
            payload['platforms']['youtube'].update(ready=False, reasons=['需要重新連結以取得上傳權限'], hint='需要重新連結以取得上傳權限')
            route.fulfill(response=response, json=payload)
        idle()
        page.route('**/api/publish/options?*', reconnect)
        page.reload()
        expect(switch('YouTube')).to_be_disabled()
        tab('YouTube')
        expect(panel).to_contain_text('需要重新連結以取得上傳權限')
        expect(panel).not_to_contain_text('尚未連結')
        expect(page.get_by_role('link', name='設定 → 平台連結', exact=True)).to_be_visible()
        page.unroute('**/api/publish/options?*', reconnect)
        page.reload()
        expect(switch('YouTube')).to_be_enabled()
        checks.append('ytpublish-upload-scope-missing-guides-reconnect')
        # 確認視窗：標題、公開狀態、兒童內容、縮圖。
        idle()
        page.locator('.publish-actions').get_by_role('button', name='發佈', exact=True).click()
        dialog = page.get_by_role('dialog')
        expect(dialog).to_contain_text('隔離 YouTube 頻道')
        expect(dialog).to_contain_text('標題：' + custom)
        expect(dialog.locator('.publish-confirm-options')).to_have_text('影片 · 不公開 · 兒童內容 · 自訂縮圖')
        capture('youtube-confirmation', '[role=dialog]')
        flag.write_text('[403, "forbidden"]', encoding='utf-8')
        dialog.get_by_role('button', name='確認發佈', exact=True).click()
        # 發佈紀錄：影片成功、縮圖未套用＋原因＋重新套用縮圖（只重設縮圖）。
        row = page.locator('.publish-record').filter(has_text=title_text)
        expect(row).to_contain_text('成功')
        row.get_by_role('button', name='各平台結果').click()
        targets = row.locator('.publish-targets')
        expect(targets).to_contain_text('YouTube · 成功')
        expect(targets.locator('.status-badge.pending')).to_have_text('縮圖未套用')
        expect(targets).to_contain_text('電話驗證')
        expect(targets.get_by_role('link', name='查看影片', exact=True)).to_have_attribute('href', re.compile(r'^https://www\.youtube\.com/watch\?v=mockvideo'))
        reapply = targets.get_by_role('button', name='重新套用縮圖', exact=True)
        expect(reapply).to_have_class('secondary')
        capture('youtube-history-thumbnail-failed', '.publish-record:has(.publish-targets)')
        with factory() as session:
            target = session.scalar(select(PublishTarget).where(PublishTarget.platform == 'youtube').order_by(PublishTarget.id.desc()))
            assert target.status == 'succeeded' and target.detail_json['thumbnail']['code'] == 'forbidden'
            assert 'upload' not in target.detail_json
            first_video = target.platform_post_id
        reapply.click()
        expect(page.get_by_role('dialog')).to_contain_text('不會重傳影片')
        page.get_by_role('dialog').get_by_role('button', name='取消', exact=True).click()
        def reapplied():
            reapply.click()
            with page.expect_response(lambda r: r.url.endswith('/youtube-thumbnail') and r.request.method == 'POST') as sent:
                page.get_by_role('dialog').get_by_role('button', name='確認套用', exact=True).click()
            assert sent.value.status == 200
            expect(page.locator('.publish-editor, .publish-records').first).to_be_visible()

        reapplied()
        # 縮圖仍被 YouTube 拒絕：維持「縮圖未套用」，影片不受影響。
        expect(targets.locator('.status-badge.pending')).to_have_text('縮圖未套用')
        expect(reapply).to_be_enabled()
        flag.unlink()
        reapplied()
        expect(targets).not_to_contain_text('縮圖未套用')
        expect(targets.get_by_role('button', name='重新套用縮圖')).to_have_count(0)
        with factory() as session:
            target = session.scalar(select(PublishTarget).where(PublishTarget.platform == 'youtube').order_by(PublishTarget.id.desc()))
            assert target.detail_json['thumbnail'] == {'status': 'applied'} and target.platform_post_id == first_video
        checks.append('ytpublish-history-thumbnail-failed-reapply-no-reupload')
        # 另存一筆「縮圖未套用」的紀錄，供稍後的檢視者確認：看得到狀態、沒有重新套用按鈕。
        with factory.begin() as session:
            brand = session.scalar(select(Brand).where(Brand.slug == 'TEST'))
            staff = session.scalar(select(Staff).where(Staff.username == 'admin'))
            account = session.scalar(select(Account).where(Account.brand_id == brand.id, Account.platform == 'youtube'))
            post = PublishPost(brand_id=brand.id, creator_id=staff.id, format='video', caption='隔離檢視者可見縮圖失敗',
                               platforms_json=['youtube'], status='done', completed_at=utc_now())
            session.add(post)
            session.flush()
            session.add(PublishTarget(post_id=post.id, platform='youtube', account_id=account.id, status='succeeded',
                                      platform_post_id='seed_video', permalink='https://www.youtube.com/watch?v=seed_video',
                                      attempts=1, last_attempt_at=utc_now(),
                                      detail_json={'video_id': 'seed_video', 'privacy_status': 'private', 'thumbnail': {'status': 'failed', 'code': 'forbidden'}}))
    finally:
        flag.unlink(missing_ok=True)
        engine.dispose()


def check_tiktok(page, settings, checks):
    """TikTok 發佈（送到收件匣）：連結後開關可用、只支援影片、文案只供複製、確認視窗與發佈紀錄；全部是假 HTTP。"""
    from urllib.parse import urlsplit

    from app.db import build_engine, session_factory
    from app.models import Brand, PublishTarget
    from sqlalchemy import select

    origin = urlsplit(page.url)._replace(path='', query='', fragment='').geturl()
    width = page.viewport_size['width']
    caption = f'隔離 TikTok 文案-{width} #標籤'
    panel = page.locator('#composer-panel-tiktok')

    def switch():
        return page.get_by_role('switch', name='發佈到 TikTok', exact=True)

    def tab(name):
        page.get_by_role('tab', name=name, exact=True).click()
        expect(page.locator('.publish-editor')).to_have_attribute('aria-busy', 'false')

    def idle():
        expect(page.locator('.publish-editor')).to_have_attribute('aria-busy', 'false')
        expect(page.locator('.publish-editor')).to_have_attribute('data-check-state', 'checked')

    engine = build_engine(settings)
    factory = session_factory(engine)
    try:
        with factory.begin() as session:
            brand = session.scalar(select(Brand).where(Brand.slug == 'TEST'))
            seed_tiktok(session, settings, brand.id)
        page.goto(origin)
        navigate(page, '發佈')
        page.get_by_role('tab', name='新增貼文', exact=True).click()
        expect(page.locator('.publish-editor')).to_have_attribute('aria-busy', 'false')
        page.get_by_role('button', name='新貼文', exact=True).click()
        expect(page.locator('.publish-accounts')).to_contain_text('隔離 TikTok 帳號')
        expect(switch()).to_be_enabled()
        # 圖文：開關停用並提示只支援影片，分頁顯示同一句。
        page.get_by_role('radio', name='圖片', exact=True).click()
        expect(switch()).to_be_disabled()
        expect(switch()).to_have_attribute('title', '僅支援影片發布，圖文需從APP上傳')
        tab('TikTok')
        expect(panel).to_contain_text('僅支援影片發布，圖文需從APP上傳')
        tab('共用')
        page.get_by_role('radio', name='影片', exact=True).click()
        page.get_by_label('上傳媒體', exact=True).set_input_files({'name': 'tt-isolated.mp4', 'mimeType': 'video/mp4', 'buffer': video_bytes(1920, 1080)})
        expect(page.locator('.publish-media-row')).to_contain_text('12.0 秒')
        page.get_by_label('主文案', exact=True).fill(caption)
        switch().check()
        tab('TikTok')
        expect(panel.locator('.tiktok-caption-notice')).to_contain_text('收件匣不會帶入文案')
        expect(panel).to_contain_text('影片會送到 TikTok 收件匣')
        expect(page.get_by_label('TikTok 文案', exact=True)).to_have_value(caption)
        # 橫式影片在直式框裡要完整顯示並上下補邊：送出的是原檔，預覽裁成直式會誤導。
        frame = page.locator('.publish-preview .publish-preview-media > div').first
        expect(frame.locator('video')).to_have_css('object-fit', 'contain')
        expect(frame.locator('video')).to_have_css('background-color', 'rgb(15, 23, 42)')
        box = frame.bounding_box()
        assert abs(box['width'] / box['height'] - 9 / 16) < 0.01, box
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        idle()
        page.locator('.publish-actions').get_by_role('button', name='發佈', exact=True).click()
        dialog = page.get_by_role('dialog')
        expect(dialog).to_contain_text('隔離 TikTok 帳號')
        expect(dialog.locator('.publish-confirm-options')).to_contain_text('送到 TikTok 收件匣（文案不會送出')
        dialog.get_by_role('button', name='確認發佈', exact=True).click()
        row = page.locator('.publish-record').filter(has_text=caption)
        expect(row).to_contain_text('成功')
        row.get_by_role('button', name='各平台結果').click()
        targets = row.locator('.publish-targets')
        expect(targets).to_contain_text('TikTok · 成功')
        expect(targets).to_contain_text('已送到收件匣')
        page.evaluate("""() => { window.__copied = [];
            Object.defineProperty(navigator, 'clipboard', { configurable: true,
                value: { writeText: async value => { window.__copied.push(value); } } }); }""")
        copy = targets.get_by_role('button', name='複製文案', exact=True)
        expect(copy).to_have_class('secondary')
        copy.click()
        expect(targets.get_by_role('button', name='已複製', exact=True)).to_be_visible()
        assert page.evaluate('window.__copied') == [caption]
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        with factory() as session:
            target = session.scalar(select(PublishTarget).where(PublishTarget.platform == 'tiktok').order_by(PublishTarget.id.desc()))
            assert target.status == 'succeeded' and target.detail_json['inbox_state'] == 'SEND_TO_USER_INBOX'
        checks.append('tiktok-publish-video-only-inbox-copy-caption-landscape-preview')
    finally:
        engine.dispose()


def exercise(page, unused, shot, checks):
    from sqlalchemy import delete, select
    from app.config import Settings
    from app.db import build_engine, session_factory
    from app.models import Brand, OAuthConnection, PublishLink, PublishMedia, PublishPost, PublishStorySnapshot, PublishTarget, Setting
    from app.models.base import utc_now

    settings = Settings(_env_file=None)
    for path in (settings.database_path, settings.export_root, settings.publish_media_root):
        assert path.resolve().is_relative_to((REPO / '.runtime').resolve())
    engine = build_engine(settings)
    try:
        with session_factory(engine).begin() as session:
            for model in (PublishStorySnapshot, PublishLink, PublishTarget, PublishMedia, PublishPost):
                session.execute(delete(model))
            # 每輪從「YouTube 尚未連結」開始；已連結的狀態由 check_youtube 自己建立。
            unseed_youtube(session)
            unseed_tiktok(session)
            switch = session.scalar(select(Setting).where(Setting.key == 'publishing.enabled'))
            if switch:
                switch.value_json = {'enabled': False}
            if not session.scalar(select(OAuthConnection.id)):
                brand = session.scalar(select(Brand).where(Brand.slug == 'TEST'))
                seed_connections(session, settings, brand.id)
    finally:
        engine.dispose()
    folder = REPO / '.runtime/publish-screens/after'
    folder.mkdir(parents=True, exist_ok=True)
    size = page.viewport_size
    def capture(name):
        page.wait_for_load_state('networkidle')
        page.evaluate('async () => { await document.fonts.ready; await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); }')
        for width, height in [(1440, 900), (768, 1024), (390, 844)]:
            page.set_viewport_size({'width': width, 'height': height})
            page.wait_for_load_state('networkidle')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (name, width)
        page.set_viewport_size(size)
        if size['width'] < 600 and name in {'new-uploaded', 'rules-invalid'}:
            focus = '.publish-media-row' if name == 'new-uploaded' else '.publish-platforms'
            page.locator(focus).scroll_into_view_if_needed()
        shot(name)
        page.screenshot(path=str(folder / f'{name}-{size["width"]}x{size["height"]}.png'))
        checks.append(name)
    navigate(page, '發佈')
    expect(page.locator('.publish-accounts')).to_contain_text('隔離 facebook')
    expect(page.get_by_role('button', name='發佈', exact=True).last).to_be_disabled()
    capture('switch-off')
    page.get_by_role('button', name='開啟發佈', exact=True).click()
    page.get_by_role('button', name='確認開啟').click()
    # uiorder：標題列不再有「已開啟／未開啟」膠囊；已開啟時管理員按鈕為「關閉發佈」。
    expect(page.locator('.publish-switch .status-badge')).to_have_count(0)
    expect(page.locator('.publish-switch')).to_contain_text('關閉發佈')
    capture('new-empty')
    page.get_by_label('上傳媒體', exact=True).set_input_files({
        'name': 'isolated-video.mp4', 'mimeType': 'video/mp4', 'buffer': video_bytes()})
    expect(page.locator('.publish-media-row')).to_contain_text('12.0 秒')
    page.get_by_role('tab', name='Instagram', exact=True).click()
    expect(page.locator('#publish-disabled-reason')).not_to_contain_text('Instagram：')
    expect(page.get_by_label('Instagram 文案', exact=True)).to_be_enabled()
    page.get_by_role('tab', name='共用', exact=True).click()
    capture('new-uploaded')
    page.get_by_label('主文案', exact=True).fill('a' * 2201)
    page.get_by_role('tab', name='Instagram', exact=True).click()
    expect(page.locator('#publish-disabled-reason')).to_contain_text('2,200')
    expect(page.get_by_role('switch', name='發佈到 Instagram', exact=True)).to_be_enabled()
    expect(page.locator('#composer-tab-instagram .publish-tab-error')).to_have_count(1)
    page.get_by_role('switch', name='發佈到 Instagram', exact=True).check()
    expect(page.locator('.publish-actions .primary')).to_be_disabled()
    page.get_by_role('tab', name='共用', exact=True).click()
    capture('rules-invalid')
    page.get_by_label('主文案', exact=True).fill('隔離影片發佈')
    for label in ('Facebook', 'Instagram', 'Threads'):
        page.get_by_role('switch', name='發佈到 ' + label, exact=True).check()
    publish_button = page.locator('.publish-actions').get_by_role('button', name='發佈', exact=True)
    expect(publish_button).to_be_enabled()
    publish_button.click()
    dialog = page.get_by_role('dialog')
    expect(dialog).to_contain_text('isolated-video.mp4')
    expect(dialog).to_contain_text('隔離 instagram')
    capture('confirmation')
    # 沒勾選「存成 FB 草稿」時，確認視窗不出現 Facebook 草稿。
    expect(dialog).not_to_contain_text('存成草稿')
    dialog.get_by_role('button', name='確認發佈').click()
    row = page.locator('.publish-record').filter(has_text='隔離影片發佈')
    expect(row).to_contain_text('成功')
    row.get_by_role('button', name='各平台結果').click()
    expect(row.locator('.publish-targets a')).to_have_count(3)
    capture('history-success')
    page.get_by_role('tab', name='新增貼文', exact=True).click()
    page.get_by_role('radio', name='純文字', exact=True).click()
    page.get_by_label('主文案', exact=True).fill('隔離排程')
    page.get_by_role('tab', name='Instagram', exact=True).click()
    expect(page.locator('#publish-disabled-reason')).to_contain_text('Instagram：Instagram 不支援純文字')
    expect(page.get_by_role('switch', name='發佈到 Instagram', exact=True)).to_be_enabled()
    expect(page.locator('#composer-tab-instagram .publish-tab-error')).to_have_count(1)
    page.get_by_role('tab', name='共用', exact=True).click()
    page.get_by_role('switch', name='發佈到 Facebook', exact=True).check()
    page.get_by_role('radio', name='排程', exact=True).click()
    when = (utc_now() + timedelta(hours=9)).replace(tzinfo=None).isoformat(timespec='minutes')
    page.get_by_label('排程時間（台北）', exact=True).fill(when)
    button = page.locator('.publish-actions').get_by_role('button', name='排程', exact=True)
    expect(button).to_be_enabled()
    check_editor_layout(page, scheduled=True)
    page.locator('.publish-footer').evaluate("e => e.scrollIntoView({block: 'end'})")
    page.screenshot(path=str(folder / f'editor-scheduled-{size["width"]}x{size["height"]}.png'))
    button.click()
    page.get_by_role('button', name='確認發佈').click()
    row = page.locator('.publish-record').filter(has_text='隔離排程')
    expect(row).to_contain_text('排程中')
    capture('scheduled')
    row.get_by_role('button', name='取消排程').click()
    page.get_by_role('button', name='確認取消').click()
    expect(page.locator('.publish-records')).to_contain_text('尚無排程')
    checks.append('schedule-cancel')
    page.get_by_role('tab', name='新增貼文', exact=True).click()
    page.get_by_role('button', name='新貼文', exact=True).click()
    page.get_by_role('radio', name='立即發佈', exact=True).click()
    page.get_by_role('radio', name='純文字', exact=True).click()
    page.get_by_label('主文案', exact=True).fill('partial-case-' + str(size['width']))
    page.get_by_role('switch', name='發佈到 Facebook', exact=True).check()
    page.get_by_role('switch', name='發佈到 Threads', exact=True).check()
    expect(publish_button).to_be_enabled()
    publish_button.click()
    page.get_by_role('button', name='確認發佈').click()
    row = page.locator('.publish-record').filter(has_text='partial-case-' + str(size['width']))
    expect(row).to_contain_text('部分成功')
    row.get_by_role('button', name='各平台結果').click()
    expect(row.locator('.publish-targets')).to_contain_text('暫時限制請求')
    capture('history-partial')
    row.get_by_role('button', name='只重試失敗平台').click()
    expect(page.get_by_role('dialog')).to_contain_text('Threads')
    expect(page.get_by_role('dialog')).not_to_contain_text('Facebook')
    page.get_by_role('button', name='確認發佈').click()
    expect(row).not_to_contain_text('部分成功')
    expect(row).to_contain_text('成功')
    checks.append('retry-failed-only')
    check_unpublished(page, settings, checks)
    check_idea_drafts(page, settings, checks)
    check_presence(page, settings, checks)
    check_composer(page, settings, checks)
    check_stories(page, settings, checks)
    check_youtube(page, settings, checks)
    check_tiktok(page, settings, checks)
    # Viewer session uses the same isolated backend; password never reaches a screenshot.
    from app.services.passwords import hash_password, set_password
    from app.models import Staff, StaffBrand
    from pydantic import SecretStr
    import secrets
    password = SecretStr(secrets.token_urlsafe(24))
    engine = build_engine(settings)
    try:
        with session_factory(engine).begin() as session:
            staff = session.scalar(select(Staff).where(Staff.username == 'publish-viewer'))
            if not staff:
                staff = Staff(username='publish-viewer', display_name='隔離檢視者', role='viewer',
                              password_hash=hash_password(password))
                session.add(staff)
                session.flush()
                brand = session.scalar(select(Brand).where(Brand.slug == 'TEST'))
                session.add(StaffBrand(staff_id=staff.id, brand_id=brand.id))
            else:
                set_password(session, 'publish-viewer', password)
    finally:
        engine.dispose()
    page.locator('.mobile-logout' if size['width'] < 600 else '.user-card button').click()
    page.get_by_label('帳號', exact=True).fill('publish-viewer')
    page.get_by_label('密碼', exact=True).fill(password.get_secret_value())
    page.get_by_role('button', name='登入工作檯').click()
    navigate(page, '發佈')
    expect(page.get_by_role('tab')).to_have_text(['發佈紀錄'])
    expect(page.locator('.publish-editor')).to_have_count(0)
    expect(page.get_by_role('button', name='只重試失敗平台')).to_have_count(0)
    expect(page.locator('.publish-presence')).to_contain_text('上次檢查：')
    expect(page.get_by_role('button', name='檢查平台貼文')).to_have_count(0)
    # 檢視者看得到「縮圖未套用」，但沒有重新套用縮圖的按鈕。
    seeded = page.locator('.publish-record').filter(has_text='隔離檢視者可見縮圖失敗')
    seeded.get_by_role('button', name='各平台結果').click()
    expect(seeded.locator('.publish-targets')).to_contain_text('縮圖未套用')
    # 請求公開但 YouTube 實際設為私人：紀錄標示實際狀態。
    expect(seeded.locator('.publish-targets')).to_contain_text('YouTube 實際為私人')
    expect(page.get_by_role('button', name='重新套用縮圖')).to_have_count(0)
    checks.append('viewer-history-only')
    navigate(page, '主題發想')
    expect(page.locator('.ideation-card').first).to_be_visible()
    expect(page.get_by_role('button', name='建立發佈草稿', exact=True)).to_have_count(0)
    expect(page.get_by_role('button', name='開啟發佈草稿', exact=True)).to_have_count(0)
    checks.append('ideadraft-viewer-hidden')


if __name__ == '__main__':
    os.environ['PUBLISH_CHECK'] = '1'
    main(exercise=exercise)

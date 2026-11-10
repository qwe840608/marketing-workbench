"""發文流程頁：畫布編輯、窄螢幕清單、核准與取消；隔離資料庫，發佈只排程不送出。"""

import os
import re
from datetime import timedelta

from browser_harness import REPO, main
from playwright.sync_api import expect
from publish_http_mock import seed_connections
from ui_navigation import navigate

GRAPH = {
    "nodes": [
        {"id": "t", "type": "trigger", "position": {"x": 0, "y": 80}, "config": {"mode": "weekly", "weekdays": [0, 3], "time": "20:00"}},
        {"id": "d", "type": "draft", "position": {"x": 220, "y": 80}, "config": {"source": "template", "format": "text", "caption": "[隔離驗收] 流程文案"}},
        {"id": "a", "type": "approval", "position": {"x": 440, "y": 80}, "config": {"hours": 24}},
        {"id": "p1", "type": "publish", "position": {"x": 660, "y": 80}, "config": {"platforms": ["facebook"]}},
        {"id": "w", "type": "delay", "position": {"x": 880, "y": 80}, "config": {"amount": 30, "unit": "minutes"}},
        {"id": "p2", "type": "publish", "position": {"x": 1100, "y": 80}, "config": {"platforms": ["threads"]}},
    ],
    "edges": [{"source": a, "target": b} for a, b in [("t", "d"), ("d", "a"), ("a", "p1"), ("p1", "w"), ("w", "p2")]],
}


def exercise(page, unused, shot, checks):
    from sqlalchemy import delete, select

    from app.config import Settings
    from app.db import build_engine, session_factory
    from app.models import Brand, OAuthConnection, PublishFlow, PublishFlowRun, PublishPost, PublishTarget, Setting, Staff
    from app.models.base import utc_now
    from app.services import flows

    settings = Settings(_env_file=None)
    assert settings.database_path.resolve().is_relative_to((REPO / '.runtime').resolve())
    engine = build_engine(settings)
    factory = session_factory(engine)
    wide = page.viewport_size['width'] >= 768
    try:
        with factory.begin() as session:
            for model in (PublishFlowRun, PublishFlow, PublishTarget, PublishPost):
                session.execute(delete(model))
            brand = session.scalar(select(Brand).where(Brand.slug == 'TEST'))
            if not session.scalar(select(OAuthConnection.id)):
                seed_connections(session, settings, brand.id)
            switch = session.scalar(select(Setting).where(Setting.key == 'publishing.enabled'))
            if switch:
                switch.value_json = {'enabled': True}
            else:
                session.add(Setting(key='publishing.enabled', value_json={'enabled': True}))
            if wide:
                # 手動建一篇草稿，讓畫布上的草稿方塊選它；每次執行複製一份，原稿保留。
                admin = session.scalar(select(Staff).where(Staff.username == 'admin'))
                session.add(PublishPost(brand_id=brand.id, creator_id=admin.id, status='draft', format='text', caption='[隔離驗收] 流程文案', platforms_json=['facebook']))
            if not wide:
                # 窄螢幕不能編輯畫布：直接建好一條啟用中的流程，驗收唯讀清單與核准。
                admin = session.scalar(select(Staff).where(Staff.username == 'admin'))
                session.add(PublishFlow(brand_id=brand.id, creator_id=admin.id, name='[隔離驗收] 每週貼文', enabled=True, graph_json=GRAPH, next_run_at=utc_now() + timedelta(days=1)))

        def open_flows():
            # 流程是側邊欄（手機底部導覽）的獨立頁面，不在發佈頁裡；先離開再回來才會重新讀取。
            navigate(page, '發佈')
            navigate(page, '流程')
            expect(page.locator('.flow-page')).to_be_visible()
            page.wait_for_load_state('networkidle')

        with factory() as session:
            source_id = session.scalar(select(PublishPost.id).where(PublishPost.source == 'manual'))
        open_flows()
        if wide:
            expect(page.locator('.flow-page .empty-data').first).to_have_text('還沒有流程')
            shot('flows-empty')
            page.get_by_role('button', name='新增流程', exact=True).click()
            expect(page.locator('.flow-block')).to_have_count(4)
            page.get_by_label('流程名稱', exact=True).fill('[隔離驗收] 每週貼文')
            page.locator('.flow-block.is-draft').click()
            # 建立草稿只剩固定範本／主題發想；選取草稿是另一個方塊。
            expect(page.get_by_role('radiogroup', name='草稿來源').get_by_role('radio')).to_have_count(2)
            page.get_by_label('範本文案', exact=True).fill('[隔離驗收] 流程文案')
            palette = page.get_by_role('toolbar', name='新增方塊')
            palette.get_by_role('button', name='選取草稿', exact=True).click()
            picker = page.get_by_label('草稿', exact=True)
            expect(picker.locator('option')).to_have_count(2)
            picker.select_option(label='#' + str(source_id) + ' [隔離驗收] 流程文案')
            expect(page.locator('.flow-block.is-pick')).to_contain_text('複製草稿 #' + str(source_id))
            # 雙擊選取草稿方塊：在流程頁彈窗編輯這篇草稿，改完自動存回，不跳到發佈頁、沒有發佈按鈕。
            page.locator('.flow-block.is-pick').dblclick()
            dialog = page.get_by_role('dialog', name='編輯草稿 #' + str(source_id))
            expect(dialog).to_be_visible()
            expect(dialog.locator('.publish-footer')).to_have_count(0)
            expect(dialog.get_by_role('tablist', name='發佈分頁')).to_have_count(0)
            dialog.get_by_label('主文案', exact=True).fill('[隔離驗收] 流程文案（彈窗修改）')
            dialog.get_by_role('button', name='完成', exact=True).click()
            expect(dialog).to_have_count(0)
            expect(page.locator('.flow-editor')).to_be_visible()
            with factory() as session:
                assert session.get(PublishPost, source_id).caption == '[隔離驗收] 流程文案（彈窗修改）'
            expect(page.locator('.flow-block.is-pick')).to_have_count(1)
            page.locator('.flow-block.is-pick').click()
            page.get_by_role('button', name='刪除方塊', exact=True).click()
            checks.append('flows-pick-draft-dblclick')
            # 接點 14px，外圍再多 10px 可按範圍（畫布縮放時跟著等比例縮），滑鼠不用貼很近才拉得到線。
            handle = page.locator('.flow-block.is-draft .react-flow__handle').first
            size = handle.evaluate("e => [getComputedStyle(e).width, getComputedStyle(e, '::after').top]")
            assert size == ['14px', '-10px'], size
            page.locator('.flow-block.is-publish').click()
            page.locator('.flow-platforms').get_by_label('Facebook', exact=True).check()
            expect(page.locator('.flow-block.is-publish')).to_contain_text('發佈到 Facebook')
            # 不用按儲存：停手約 1 秒自動存到伺服器。
            save_state = page.locator('.flow-save-state')
            expect(save_state).to_have_text('已自動儲存')
            expect(page.locator('.flow-block.has-error')).to_have_count(0)
            # 重新整理後自動回到剛才的流程，內容都在。
            page.reload()
            expect(page.locator('.flow-block')).to_have_count(4)
            expect(page.get_by_label('流程名稱', exact=True)).to_have_value('[隔離驗收] 每週貼文')
            expect(page.locator('.flow-block.is-publish')).to_contain_text('發佈到 Facebook')
            checks.append('flows-autosave-reload')
            palette = page.get_by_role('toolbar', name='新增方塊')
            # 加一個沒接線的通知方塊：存得下來，但會標出錯誤、不能啟用。
            # 從上方拖進畫布：放在放開的位置，不是排在最右邊。
            canvas = page.locator('.flow-canvas')
            box = palette.bounding_box()
            assert box['x'] - canvas.bounding_box()['x'] < 20, box  # 選單在畫布左側
            palette.get_by_role('button', name='通知', exact=True).drag_to(canvas, target_position={'x': 300, 'y': 300})
            expect(page.locator('.flow-block')).to_have_count(5)
            dropped = page.locator('.flow-block.is-notify').bounding_box()
            area = canvas.bounding_box()
            assert abs(dropped['x'] + dropped['width'] / 2 - (area['x'] + 300)) < 40, (dropped, area)
            checks.append('flows-drag-to-canvas')
            expect(save_state).to_contain_text('流程還有錯誤')
            expect(page.locator('.flow-block.has-error')).to_have_count(1)
            expect(page.locator('.flow-block.has-error small')).to_have_text('沒有接到流程上')
            shot('flows-editor-error')
            page.get_by_role('button', name='刪除方塊', exact=True).click()
            expect(save_state).to_have_text('已自動儲存')
            shot('flows-editor')
            checks.append('flows-canvas-edit-validate')
            page.get_by_role('button', name='返回流程清單', exact=True).click()
            row = page.locator('.flow-row')
            expect(row).to_have_count(1)
            row.get_by_role('button', name='啟用', exact=True).click()
            expect(row).to_contain_text('啟用中')
            expect(row).to_contain_text('下次')
            checks.append('flows-enable')
        else:
            row = page.locator('.flow-row')
            expect(row.locator('.flow-steps li')).to_have_count(6)
            expect(row.locator('.flow-steps')).to_contain_text('每週一、四 20:00')
            shot('flows-list-mobile')
            row.get_by_role('button', name='編輯', exact=True).click()
            expect(page.locator('.flow-editor .notice:not(.warning)')).to_contain_text('較寬的螢幕')
            expect(page.locator('.flow-canvas')).to_have_count(0)
            page.get_by_role('button', name='返回流程清單', exact=True).click()
            checks.append('flows-mobile-readonly')

        with factory.begin() as session:
            flow = session.scalar(select(PublishFlow))
            flow.next_run_at = utc_now() - timedelta(seconds=30)
            flow_id = flow.id
        flows.tick(factory)
        open_flows()
        waiting = page.locator('.flow-waiting .flow-run')
        expect(waiting).to_have_count(1)
        expect(waiting.locator('.flow-plan li')).to_have_count(1 if wide else 2)
        shot('flows-waiting')
        # 待核准的「編輯草稿」也用彈窗，不離開流程頁。
        waiting.get_by_role('button', name='編輯草稿', exact=True).click()
        draft_dialog = page.get_by_role('dialog', name=re.compile('^編輯草稿 #'))
        expect(draft_dialog.get_by_label('主文案', exact=True)).to_have_value('[隔離驗收] 流程文案')
        shot('flows-draft-dialog')
        draft_dialog.get_by_role('button', name='完成', exact=True).click()
        expect(draft_dialog).to_have_count(0)
        checks.append('flows-waiting-draft-dialog')
        waiting.get_by_role('button', name='核准並排程', exact=True).click()
        dialog = page.get_by_role('dialog')
        expect(dialog).to_contain_text('[隔離驗收] 流程文案')
        shot('flows-approve-dialog')
        dialog.get_by_role('button', name='確認核准', exact=True).click()
        expect(page.locator('.notice.success')).to_have_text('已核准，貼文已排程')
        expect(page.locator('.flow-waiting')).to_have_count(0)
        run = page.locator('.flow-run').first
        expect(run).to_contain_text('已排程')
        run.get_by_role('button', name='各步驟', exact=True).click()
        expect(run.locator('.flow-steps')).to_contain_text('排程中')
        shot('flows-scheduled')
        with factory() as session:
            posts = list(session.scalars(select(PublishPost).where(PublishPost.source == 'flow')))
            assert posts and all(p.status == 'scheduled' for p in posts), [p.status for p in posts]
            assert session.get(PublishFlowRun, session.scalar(select(PublishFlowRun.id).where(PublishFlowRun.flow_id == flow_id))).status == 'scheduled'
        checks.append('flows-approve-schedules-only')
        run.get_by_role('button', name='取消這次', exact=True).click()
        page.get_by_role('dialog').get_by_role('button', name='確認取消', exact=True).click()
        expect(page.locator('.notice.success')).to_have_text('已取消這次執行')
        expect(page.locator('.flow-run').first).to_contain_text('已取消')
        with factory() as session:
            assert all(p.status == 'draft' for p in session.scalars(select(PublishPost).where(PublishPost.source == 'flow')))
            if wide:
                assert session.get(PublishPost, source_id).status == 'draft'
        checks.append('flows-cancel-returns-drafts')
        navigate(page, '發佈')
        page.get_by_role('tab', name='草稿', exact=True).click()
        expect(page.locator('.publish-record').first).to_contain_text('來自流程')
        checks.append('flows-draft-source-chip')
    finally:
        engine.dispose()


if __name__ == '__main__':
    os.environ['PUBLISH_CHECK'] = '1'
    main(exercise=exercise)

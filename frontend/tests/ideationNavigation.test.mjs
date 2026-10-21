import test from 'node:test';
import assert from 'node:assert/strict';
import { positiveId, quoteHref, readView, readSettingsTab, reportReturn, selectionQuery, viewQuery, views } from '../src/ideationNavigation.ts';

test('設定四分頁相容舊網址並保留最後分頁', () => {
  assert.deepEqual(views, ['dashboard', 'posts', 'ideation', 'publish', 'settings']);
  for (const [legacy, tab] of [['ai', 'ai'], ['policy', 'policy'], ['settings', 'workspace']]) {
    assert.equal(readView('?view=' + legacy), 'settings');
    assert.equal(readSettingsTab('?view=' + legacy), tab);
  }
  assert.equal(readSettingsTab(''), 'connections');
  assert.equal(readSettingsTab('?view=settings&settings_tab=invalid'), 'connections');
  for (const tab of ['ai', 'connections', 'policy', 'workspace']) {
    const away = viewQuery('?view=settings&settings_tab=' + tab, 'posts');
    assert.equal(readSettingsTab(viewQuery(away, 'settings')), tab);
  }
});

test('每個頁面重新整理後都留在原頁，預設為儀表板 且保留其他參數', () => {
  for (const view of views) {
    const query = viewQuery('?brand_id=2&view=posts', view);
    assert.equal(readView(query), view);
    assert.equal(new URLSearchParams(query).get('brand_id'), '2');
    assert.equal(new URLSearchParams(query).get('view'), view);
  }
  assert.equal(viewQuery('?view=ai', 'dashboard'), '?view=dashboard');
  for (const search of ['', '?view=', '?view=unknown', '?view=AI']) assert.equal(readView(search), 'dashboard');
});

test('原話依 ID 和類型定位，忽略舊絕對網址與其他網域', () => {
  const q = { id: 17, kind: 'dm', thread_id: 9, url: 'https://other.invalid' };
  const path = quoteHref(q, 2, 4);
  assert.equal(path, null);
  assert.equal(quoteHref({ id: 1 }, 2, 4), null);
});
test('留言與腳本保留返回報告及腳本資訊', () => {
  const path = quoteHref({ id: 18, kind: 'comment_thread', post_id: 6 }, 2, 4, 8);
  const p = new URLSearchParams(path.slice(2));
  assert.equal(p.get('view'), 'posts'); assert.equal(p.get('post_id'), '6'); assert.equal(p.get('comment_id'), '18');
  const target = reportReturn(path.slice(1));
  const back = new URLSearchParams(target.href.slice(2));
  assert.equal(back.get('report_id'), '4'); assert.equal(back.get('script_id'), '8'); assert.equal(back.get('brand_id'), '2');
});
test('選取報告及腳本可序列化並移除上一個原話定位', () => {
  const query = selectionQuery('?post_id=9&comment_id=17&return_report_id=4', '2', 4, 8);
  const p = new URLSearchParams(query);
  assert.equal(p.get('report_id'), '4'); assert.equal(p.get('script_id'), '8'); assert.equal(p.get('post_id'), null);
  assert.equal(new URLSearchParams(selectionQuery(query, '2', 5, null)).get('script_id'), null);
});
test('無效 ID 不可成為導覽參數', () => {
  for (const value of [null, '', '-1', '1e2', '0', 'https://other.invalid', '9007199254740992']) assert.equal(positiveId(value), null);
  assert.equal(positiveId('17'), 17); assert.equal(reportReturn('?return_report_id=https://other.invalid'), null);
});

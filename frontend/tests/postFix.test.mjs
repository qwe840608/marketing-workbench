import test from 'node:test';
import assert from 'node:assert/strict';
import { commentRows } from '../src/postComments.ts';
import { readDateFilter, writeDateFilter, dateQuery, syncSummary } from '../src/postDateFilters.ts';

test('兩組日期篩選獨立寫入網址並可還原，保留貼文與收件匣參數', () => {
  const params = new URLSearchParams('view=posts&post_id=39&platform=line');
  const posts = { period: 'custom', from: '2026-09-01', to: '2026-09-26' };
  const comments = { period: '7', from: '', to: '' };
  writeDateFilter(params, 'post', posts);
  writeDateFilter(params, 'comment', comments);
  assert.deepEqual(readDateFilter(params.toString(), 'post'), posts);
  assert.deepEqual(readDateFilter(params.toString(), 'comment'), comments);
  assert.equal(params.get('post_id'), '39');
  assert.equal(params.get('platform'), 'line');
  assert.equal(dateQuery(posts), 'period=custom&date_from=2026-09-01&date_to=2026-09-26');
  assert.equal(dateQuery(comments), 'period=7');
});

test('日期預設全部，快速選項清除自訂日期，單側日期可送後端', () => {
  assert.deepEqual(readDateFilter('', 'post'), { period: 'all', from: '', to: '' });
  assert.equal(readDateFilter('post_range=bad&post_from=oops', 'post').period, 'all');
  const params = new URLSearchParams('post_range=custom&post_from=2026-09-01&post_to=2026-09-26');
  writeDateFilter(params, 'post', { period: 'all', from: '', to: '' });
  assert.equal(params.has('post_from'), false);
  assert.equal(params.has('post_to'), false);
  assert.equal(dateQuery({ period: 'custom', from: '', to: '2026-09-26' }), 'period=custom&date_to=2026-09-26');
});

test('最新頂層優先，回覆維持由早到晚且跨頁組合不改順序', () => {
  const msg = (id, parent = null) => ({ id, external_id: 'c' + id, sent_at: new Date(id * 1000).toISOString(),
    comment_parent_known: true, comment_parent_id: parent });
  const result = commentRows([msg(1), msg(4, 'c2'), msg(3, 'c2'), msg(2)], true);
  assert.deepEqual(result.map(row => [row.message.id, row.depth]), [[2, 0], [3, 1], [4, 1], [1, 0]]);
  const cycle = commentRows([msg(1, 'c2'), msg(2, 'c1')], true, [2, 1]);
  assert.deepEqual(cycle.map(row => row.depth), [0, 0]);
});

test('同步說明保留平台零值、缺值不顯示後半句、有差距才說明', () => {
  assert.equal(syncSummary(1296, 19115), '已同步 1,296 則／平台顯示 19,115 則（較舊的留言尚未同步）');
  assert.equal(syncSummary(1296, null), '已同步 1,296 則');
  assert.equal(syncSummary(0, 0), '已同步 0 則／平台顯示 0 則');
  assert.equal(syncSummary(2, 1), '已同步 2 則／平台顯示 1 則');
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { commentRows, readPostPlatform } from '../src/postComments.ts';

const msg = (id, parent = null, known = true, time = id) => ({
  id, external_id: 'c' + id, text: '原文 ' + id, sent_at: new Date(1000 * time).toISOString(),
  comment_parent_id: parent, comment_parent_known: known, comment_root_id: null,
});
test('留言與同層回覆依時間排序並保留三層父子關係與原文', () => {
  const result = commentRows([msg(4, null, true, 0), msg(3, 'c2'), msg(2, 'c1'), msg(1)]);
  assert.deepEqual(result.map(r => [r.message.id, r.depth]), [[4, 0], [1, 0], [2, 1], [3, 2]]);
  assert.equal(result[3].parent.id, 2);
  assert.equal(result[3].message.text, '原文 3');
});
test('無可靠父留言、缺少父留言、重複父 ID 不猜測且不隱藏', () => {
  const result = commentRows([msg(1, 'c2', false), msg(2, 'missing'), msg(3, 'c4'), msg(4), { ...msg(5), external_id: 'c4' }]);
  assert.deepEqual(result.map(r => r.depth), [0, 0, 0, 0, 0]);
  assert.deepEqual(result.slice(0, 3).map(r => r.relation), ['unknown', 'missing', 'missing']);
});
test('循環及超深層關係仍會終止並保留全部訊息', () => {
  const cycle = commentRows([msg(1, 'c2'), msg(2, 'c1'), msg(3, 'c3')]);
  assert.equal(cycle.length, 3);
  assert.ok(cycle.some(r => r.relation === 'cycle'));
  const deep = commentRows(Array.from({ length: 1500 }, (_, i) => msg(i + 1, i ? 'c' + i : null)));
  assert.equal(deep.length, 1500);
  assert.equal(deep.at(-1).depth, 1499);
});
test('貼文平台單選支援五平台，未知回預設，保留收件匣平台', () => {
  assert.equal(readPostPlatform('?post_platform=facebook&post_platform=instagram&platform=line'), 'instagram');
  for (const value of ['youtube', 'tiktok', 'threads']) assert.equal(readPostPlatform('?post_platform=' + value), value);
  for (const value of ['all', '', 'unknown']) assert.equal(readPostPlatform('?post_platform=' + value), null);
});

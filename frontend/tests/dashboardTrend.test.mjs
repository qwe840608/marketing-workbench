import test from 'node:test';
import assert from 'node:assert/strict';
import { trendGeometry, trendDescription } from '../src/dashboardTrend.ts';

const day = (values = {}) => ({ date: '2026-10-04', new_messages: 0, ...values });

test('空序列與全零無座標圖；單日置中，長條高度依訊息數', () => {
  assert.equal(trendGeometry([]).empty, true);
  assert.equal(trendGeometry([day()]).empty, true);
  const geometry = trendGeometry([day({ new_messages: 10 })]);
  assert.equal(geometry.empty, false);
  assert.equal(geometry.points[0].x, 310);
  assert.equal(geometry.points[0].barY, 45);
  assert.equal('replyY' in geometry.points[0], false);
  assert.equal('unit' in geometry, false);
  assert.ok(!/NaN|Infinity/.test(JSON.stringify(geometry)));
});

test('只有訊息長條、零值保留且提示不含客服欄位', () => {
  const geometry = trendGeometry([day({ new_messages: 4 }), day(), day({ new_messages: 2 })]);
  assert.deepEqual(geometry.points.map(point => point.barY), [45, 180, 112.5]);
  assert.equal(geometry.maxMessages, 4);
  assert.equal('segments' in geometry, false);
  assert.equal('maxReply' in geometry, false);
  assert.equal(trendDescription(day()), '2026-10-04 · 新留言 0');
});

test('30 天每五天標一次，7 天逐日標示且座標保持有限', () => {
  const series = Array.from({ length: 30 }, (_, index) => day({ date: `2026-09-${String(index + 1).padStart(2, '0')}` }));
  const geometry = trendGeometry(series);
  assert.deepEqual(geometry.points.filter(point => point.label).map(point => point.label), ['09/01', '09/06', '09/11', '09/16', '09/21', '09/26']);
  assert.equal(trendGeometry(series.slice(0, 7)).points.filter(point => point.label).length, 7);
  assert.ok(geometry.points.every(point => Number.isFinite(point.x) && Number.isFinite(point.barY)));
});

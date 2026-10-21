import test from 'node:test';
import assert from 'node:assert/strict';
import { defaultFollowerSelection, followerWeeks, followerWeekLabel, followerLabels, formatDelta } from '../src/followers.ts';

test('粉絲數正負成長、未知值與零值', () => {
  assert.equal(formatDelta(-3), '−3');
  assert.equal(formatDelta(1234), '+1,234');
  assert.equal(formatDelta(0), '0');
  assert.equal(formatDelta(null), '—');
});

test('預設採台北年月份與週次，午夜跨月與週一', () => {
  assert.deepEqual(defaultFollowerSelection(new Date('2026-09-30T16:00:00Z')), { year: 2026, month: 10, week: 1 });
  assert.deepEqual(defaultFollowerSelection(new Date('2026-09-30T15:59:59Z')), { year: 2026, month: 9, week: 5 });
  assert.deepEqual(defaultFollowerSelection(new Date('2026-10-04T16:00:00Z')), { year: 2026, month: 10, week: 2 });
  assert.deepEqual(defaultFollowerSelection(new Date('2026-12-31T16:00:00Z')), { year: 2027, month: 1, week: 1 });
});

for (const [year, month, ranges] of [
  [2026, 10, [[1,4],[5,11],[12,18],[19,25],[26,31]]],
  [2026, 12, [[1,6],[7,13],[14,20],[21,27],[28,31]]],
  [2027, 1, [[1,3],[4,10],[11,17],[18,24],[25,31]]],
  [2026, 2, [[1,1],[2,8],[9,15],[16,22],[23,28]]],
  [2024, 2, [[1,4],[5,11],[12,18],[19,25],[26,29]]],
  [2026, 3, [[1,1],[2,8],[9,15],[16,22],[23,29],[30,31]]],
  [2026, 6, [[1,7],[8,14],[15,21],[22,28],[29,30]]],
]) test(`${year}/${month} 週一切分且不跨月`, () => {
  assert.deepEqual(followerWeeks(year, month).map(w => [Number(w.date_from.slice(-2)), Number(w.date_to.slice(-2))]), ranges);
});

test('週次選項與過去週月標籤', () => {
  assert.equal(followerWeekLabel(followerWeeks(2026, 10)[0]), '第1週（10/1–10/4）');
  const now = { year: 2026, month: 10, week: 2 };
  assert.deepEqual(followerLabels(now, now), ['本週', '本月']);
  assert.deepEqual(followerLabels({ ...now, week: 1 }, now), ['該週', '本月']);
  assert.deepEqual(followerLabels({ year: 2026, month: 9, week: 1 }, now), ['該週', '該月']);
});

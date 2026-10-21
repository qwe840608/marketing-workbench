import test from 'node:test';
import assert from 'node:assert/strict';
import { barWidth, conversion, growthDirection, growthText } from '../src/growth.ts';

test('成長比較：前期為 0 不算百分比，小於 10% 保留一位小數', () => {
  assert.equal(growthText(3, 2, '上週同期'), '比上週同期增加 50%');
  assert.equal(growthText(1, 4, '上週同期'), '比上週同期減少 75%');
  assert.equal(growthText(103, 100, '前 30 天'), '比前 30 天增加 3%');
  assert.equal(growthText(1052, 1000, '前 30 天'), '比前 30 天增加 5.2%');
  assert.equal(growthText(5, 5, '上週同期'), '與上週同期持平');
  assert.equal(growthText(0, 0, '上週同期'), '上週同期也沒有');
  assert.equal(growthText(4, 0, '上週同期'), '上週同期沒有，無法比較');
  assert.equal(growthDirection(4, 0), 'flat');
  assert.equal(growthDirection(4, 2), 'up');
  assert.equal(growthDirection(1, 2), 'down');
});

test('漏斗：轉換率依上一階計算，長條最小 2% 且不超過 100%', () => {
  assert.equal(conversion(30, 1000), 3);
  assert.equal(conversion(25, 1000), 2.5);
  assert.equal(conversion(1200, 1000), 120);
  assert.equal(conversion(3, 0), null);
  assert.equal(barWidth(0, 1000), 0);
  assert.equal(barWidth(1, 1000), 2);
  assert.equal(barWidth(500, 1000), 50);
  assert.equal(barWidth(1200, 1000), 100);
  assert.equal(barWidth(5, 0), 0);
});

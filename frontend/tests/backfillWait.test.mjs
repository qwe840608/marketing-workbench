import test from 'node:test';
import assert from 'node:assert/strict';
import { backfillWaitText } from '../src/backfillWait.ts';

const now = Date.parse('2026-09-30T04:00:00Z');
const base = { state: 'throttled', retry_at: '2026-09-30T04:05:00Z', usage_percent: 8, calls_per_hour: 180 };
for (const state of ['waiting', 'throttled']) {
  for (const [reason, text] of [
    ['system_budget', '已達本系統每小時 180 次的 Meta 呼叫上限（Meta 實際用量 8%），將於 12:05 自動繼續'],
    ['meta_usage', 'Meta 暫時限制呼叫（用量 8%），將於 12:05 自動繼續'],
    ['meta_unstable', 'Meta 回應逾時或暫時錯誤，將於 12:05 自動重試'],
    ['work_budget', '本輪讀取已達工作預算，將於 12:05 自動繼續'],
  ]) {
    test(`${state} / ${reason} 顯示原因與台北重試時間`, () => {
      assert.equal(backfillWaitText({ ...base, state, wait_reason: reason }, now), text);
    });
  }
}
test('舊資料無原因沿用 Meta 限速；缺少用量不得捏造數值', () => {
  assert.equal(backfillWaitText(base, now), 'Meta 暫時限制呼叫（用量 8%），將於 12:05 自動繼續');
  assert.equal(backfillWaitText({ ...base, usage_percent: null }, now), 'Meta 暫時限制呼叫（未提供用量），將於 12:05 自動繼續');
});
test('冷卻結束仍顯示等待排程；真正錯誤與人工暫停不顯示自動續抓', () => {
  assert.equal(backfillWaitText(base, now + 600000), 'Meta 暫時限制呼叫（用量 8%），已到重試時間，等待排程自動繼續');
  for (const state of ['error', 'paused', 'completed', 'running', 'not_started']) {
    assert.equal(backfillWaitText({ ...base, state, wait_reason: 'meta_auth' }, now), null);
  }
});

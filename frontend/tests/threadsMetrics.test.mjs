import test from 'node:test';
import assert from 'node:assert/strict';
import { defaultMetric, metricFields, metricValue, snapshotColumns, syncLabel } from '../src/metricFields.ts';
import { backfillWaitText } from '../src/backfillWait.ts';

const labels = list => list.map(([, label]) => label);

test('Threads 成效使用自己的指標名稱，沒有的觸及與收藏不顯示', () => {
  assert.deepEqual(labels(metricFields('threads')), ['觀看', '按讚', '回覆', '轉發', '引用', '分享']);
  assert.deepEqual(labels(snapshotColumns('threads')), ['觀看', '按讚', '回覆']);
  assert.equal(defaultMetric('threads'), 'views');
  assert.equal(syncLabel('threads'), 'Threads 回覆');
});

test('FB／IG 的指標、快照欄位與預設曲線維持不變', () => {
  for (const platform of ['facebook', 'instagram', null, undefined]) {
    assert.deepEqual(labels(metricFields(platform)), ['觀看', '觸及', '按讚', '留言', '分享', '收藏']);
    assert.deepEqual(labels(snapshotColumns(platform)), ['觀看', '觸及', '留言']);
    assert.equal(defaultMetric(platform), 'reach');
  }
  assert.equal(syncLabel('facebook'), 'Facebook 留言');
  assert.equal(syncLabel('instagram'), 'Instagram 留言');
});

test('轉發與引用讀 extra_json，缺值或非數字是 null 而不是零', () => {
  const metric = { id: 1, captured_at: '2026-10-12T00:00:00Z', views: 12, reach: null, likes: 0, comments: 3,
    shares: 4, saves: null, extra_json: { reposts: 2, quotes: 0 } };
  assert.equal(metricValue(metric, 'views'), 12);
  assert.equal(metricValue(metric, 'likes'), 0);
  assert.equal(metricValue(metric, 'reposts'), 2);
  assert.equal(metricValue(metric, 'quotes'), 0);
  assert.equal(metricValue(metric, 'reach'), null);
  assert.equal(metricValue({ ...metric, extra_json: {} }, 'reposts'), null);
  assert.equal(metricValue({ ...metric, extra_json: { reposts: '2', quotes: null } }, 'reposts'), null);
  assert.equal(metricValue({ ...metric, views: Number.NaN }, 'views'), null);
  assert.equal(metricValue(undefined, 'views'), null);
});

test('Threads 回覆抓取等待時顯示 Threads，不沿用 Meta 用量字樣', () => {
  const now = Date.parse('2026-10-12T04:00:00Z');
  const job = { state: 'waiting', retry_at: '2026-10-12T04:05:00Z', usage_percent: null, calls_per_hour: null };
  assert.equal(backfillWaitText({ ...job, wait_reason: 'threads_usage' }, now), 'Threads 暫時限制呼叫，將於 12:05 自動繼續');
  assert.equal(backfillWaitText({ ...job, wait_reason: 'threads_unstable' }, now), 'Threads 回應逾時或暫時錯誤，將於 12:05 自動重試');
});

test('YouTube 七項指標、秒數序列化、Analytics extra 與未知值', () => {
  assert.deepEqual(labels(metricFields('youtube')), ['觀看', '按讚', '留言', '分享', '平均觀看時長（秒）', '觀看總時數（小時）', '新增訂閱']);
  assert.deepEqual(labels(snapshotColumns('youtube')), ['觀看', '按讚', '留言']);
  assert.equal(defaultMetric('youtube'), 'views');
  assert.equal(syncLabel('youtube'), 'YouTube 留言');
  const metric = { avg_watch_time: '30.0000', extra_json: { watch_hours: 2.5, subscribers_gained: 0 } };
  assert.equal(metricValue(metric, 'avg_watch_time'), 30);
  assert.equal(metricValue(metric, 'watch_hours'), 2.5);
  assert.equal(metricValue(metric, 'subscribers_gained'), 0);
  assert.equal(metricValue({ ...metric, avg_watch_time: '' }, 'avg_watch_time'), null);
  assert.equal(metricValue({ ...metric, extra_json: {} }, 'watch_hours'), null);
  assert.match(backfillWaitText({state:'waiting', wait_reason:'youtube_usage', retry_at:null}), /^YouTube/);
});

test('TikTok 只有觀看、按讚、留言、分享，預設曲線為觀看', () => {
  assert.deepEqual(labels(metricFields('tiktok')), ['觀看', '按讚', '留言', '分享']);
  assert.deepEqual(labels(snapshotColumns('tiktok')), ['觀看', '按讚', '留言']);
  assert.equal(defaultMetric('tiktok'), 'views');
});

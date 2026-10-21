import test from 'node:test';
import assert from 'node:assert/strict';
import { retentionNotice } from '../src/postComments.ts';

const on = { comment_retention_days: 365, youtube_fresh_days: 30, retention_enabled: true };

test('各平台照實顯示觀眾留言保存期限，天數來自後端設定', () => {
  for (const platform of ['facebook', 'instagram', 'threads']) {
    assert.equal(retentionNotice(platform, on), '觀眾留言自工作檯取得起保留 365 天，到期刪除。');
  }
  assert.equal(retentionNotice('facebook', { ...on, comment_retention_days: 180 }), '觀眾留言自工作檯取得起保留 180 天，到期刪除。');
  assert.match(retentionNotice('youtube', on), /YouTube 規定，30 天內未重新抓取就刪除/);
  assert.equal(retentionNotice('tiktok', on), 'TikTok 留言不會讀取或保存。');
});

test('每日刪除未啟用時說明，設定還沒讀到就不顯示', () => {
  assert.match(retentionNotice('instagram', { ...on, retention_enabled: false }), /每日刪除尚未啟用/);
  assert.equal(retentionNotice('instagram', null), '');
  assert.equal(retentionNotice(null, on), '');
});

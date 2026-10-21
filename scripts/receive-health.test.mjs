import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { createHash, createHmac } from 'node:crypto';
import { resolveNgrok, startupFailure } from './webhooks.mjs';
import { runComments } from './run-meta-comments.mjs';

test('ngrok 搜尋順序 PATH、NGROK_PATH、LOCALAPPDATA；缺少時明列原因', () => {
  const env = { PATH: 'E:/path', LOCALAPPDATA: 'E:/local' }, settings = { NGROK_PATH: 'E:/configured/ngrok.exe' };
  const fromPath = join('E:/path', process.platform === 'win32' ? 'ngrok.exe' : 'ngrok');
  assert.equal(resolveNgrok(settings, env, () => true), fromPath);
  assert.equal(resolveNgrok(settings, env, p => p === settings.NGROK_PATH), settings.NGROK_PATH);
  const fallback = join(env.LOCALAPPDATA, 'ngrok', 'bin', 'ngrok.exe');
  assert.equal(resolveNgrok(settings, env, p => p === fallback), fallback);
  assert.throws(() => resolveNgrok(settings, env, () => false), /找不到 ngrok.*NGROK_PATH/);
});
test('啟動錯誤分類不外洩原始憑證或第三方輸出', () => {
  for (const [code, message] of [['ENOENT','找不到執行檔'], ['ERR_NGROK_105','authtoken'], ['ERR_NGROK_334','其他 session'], ['EACCES','權限不足']]) {
    const result = startupFailure('ngrok', 'raw-secret ' + code, code.startsWith('ERR_') ? '' : code).message;
    assert.ok(result.includes(message)); assert.ok(!result.includes('raw-secret'));
  }
});
test('once 只喚醒後端排程器，簽章綁定原始 body 且 requested_only', async () => {
  const secret='s'.repeat(32); let count=0;
  await runComments('once', { WEBHOOK_PROBE_SECRET: secret }, { checkBackend: async () => {}, checkEndpoint: async () => {},
    request: async (base,path,options) => {
      count++; assert.equal(base,'http://127.0.0.1:8000');
      assert.equal(JSON.parse(options.body).requested_only,true);
      const material='POST\n'+path+'\n'+options.headers['x-mwb-sync-time']+'\n'+createHash('sha256').update(options.body).digest('hex');
      assert.equal(options.headers['x-mwb-sync-signature'],createHmac('sha256',secret).update(material).digest('hex'));
      return {status:200};
    } });
  assert.equal(count,1);
});

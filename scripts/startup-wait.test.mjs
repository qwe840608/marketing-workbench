import test from 'node:test';
import assert from 'node:assert/strict';
import { waitReady, gatewayStartupSeconds, startupTail } from './webhooks.mjs';

const fakeChild = () => ({ serviceName: 'ngrok', diagnostic: '', exitCode: null, signalCode: null, kill() { this.signalCode = 'SIGTERM'; } });
test('gateway 等待設定拒絕不合法值', () => {
  assert.equal(gatewayStartupSeconds(),120);
  assert.equal(gatewayStartupSeconds({GATEWAY_STARTUP_TIMEOUT_SECONDS:'240'}),240);
  for (const value of ['NaN','-1','0','1.5','3601']) assert.throws(()=>gatewayStartupSeconds({GATEWAY_STARTUP_TIMEOUT_SECONDS:value}));
});
test('ngrok HTTP 就緒可等超過 60 秒；逾時保留秒數與日誌位置', async () => {
  let elapsed = 0;
  const runtime = { now: () => elapsed, sleep: async ms => { elapsed += ms; }, progress: () => {}, saveTail: () => 'isolated-tail.log', request: async () => ({ status: elapsed >= 90000 ? 200 : 503 }) };
  assert.equal((await waitReady(fakeChild(), '', '', r => r.status === 200, 180, runtime)).status, 200);
  elapsed = 0;
  await assert.rejects(waitReady(fakeChild(), '', '', () => false, 2, runtime), /已等待 2 秒.*isolated-tail.log/);
});
test('尾端日誌不保存密碼、token、payload 或任意錯誤原文', () => {
  const tail = startupTail({ diagnostic: 'token=secret password=secret\nSQLITE_BUSY payload=private\n' });
  assert.match(tail, /SQLITE_BUSY/);
  assert.doesNotMatch(tail, /secret|private|token|password|payload/);
});

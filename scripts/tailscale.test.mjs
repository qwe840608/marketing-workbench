import test from 'node:test';
import assert from 'node:assert/strict';
import { checkServe, mergedOrigins } from './tailscale.mjs';

const dns = 'mwb.example.ts.net';
test('拒絕公開 Funnel 與覆寫其他服務', () => {
  assert.throws(() => checkServe({ AllowFunnel: { [`${dns}:443`]: true } }, dns));
  assert.throws(() => checkServe({ Web: { [`${dns}:443`]: { Handlers: { '/': { Proxy: 'http://127.0.0.1:3000' } } } } }, dns));
  assert.throws(() => checkServe({ TCP: { '443': { TCPForward: 'localhost:3000' } } }, dns));
});
test('重跑保持本機與 HTTPS 來源、其他已明列主機', () => {
  const config = { APP_ORIGIN: 'http://127.0.0.1:8000', ALLOWED_HOSTS: '["127.0.0.1","localhost"]' };
  const first = mergedOrigins(config, dns), second = mergedOrigins(first, dns);
  assert.deepEqual(first, second);
  assert.equal(first.APP_ORIGIN, 'http://127.0.0.1:8000,https://mwb.example.ts.net');
  assert.equal(first.SESSION_COOKIE_SECURE, 'true');
  assert.deepEqual(JSON.parse(first.ALLOWED_HOSTS), ['127.0.0.1', 'localhost', dns]);
  assert.throws(() => mergedOrigins(config, 'mwb.example.ts.net.evil.test'));
  assert.throws(() => mergedOrigins({ ALLOWED_HOSTS: '["*"]' }, dns));
});
test('只有自己的內部 HTTPS 代理可重用', () => {
  assert.equal(checkServe({}, dns), false);
  assert.equal(checkServe({ TCP: { '443': { HTTPS: true } }, Web: { [`${dns}:443`]: { Handlers: { '/': { Proxy: 'http://127.0.0.1:8000' } } } } }, dns), true);
});
test('改用其他後端埠號時只認該埠號的代理', () => {
  const serve = (proxy) => ({ TCP: { '443': { HTTPS: true } }, Web: { [`${dns}:443`]: { Handlers: { '/': { Proxy: proxy } } } } });
  assert.equal(checkServe(serve('http://127.0.0.1:8010'), dns, 'http://127.0.0.1:8010'), true);
  assert.throws(() => checkServe(serve('http://127.0.0.1:8000'), dns, 'http://127.0.0.1:8010'));
});

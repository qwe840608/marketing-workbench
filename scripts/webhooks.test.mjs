import assert from 'node:assert/strict';
import { createHmac, randomBytes } from 'node:crypto';
import crypto from 'node:crypto';
import { readFileSync } from 'node:fs';
import http from 'node:http';
import { join } from 'node:path';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import vm from 'node:vm';
import { fixedUrl, publicUrl, gatewayKind, gatewayAgent, tunnelTokenValid, resolveCloudflared, request, checkBackend, checkEndpoint, accessLogin, gatewayEnvironment, backendPort, portSettings } from './webhooks.mjs';
import { readPlatformSettings } from './platform-credentials.mjs';

const secret = randomBytes(32).toString('hex');

test('公開政策只額外允許 43 字元 media 權杖，驗收列含拒絕穿越與無效路徑', async (t) => {
  const policy = JSON.parse(readFileSync(new URL('../config/ngrok-traffic-policy.json', import.meta.url), 'utf8'));
  const expression = policy.on_http_request[0].expressions[0];
  const patterns = [...expression.matchAll(/matches\('([^']+)'\)/g)].map(m => new RegExp(m[1]));
  assert.equal(patterns.length, 2);
  for (const pattern of patterns) {
    assert.ok(pattern.test('/media/' + 'a'.repeat(43)));
    // Instagram 用的 PNG 轉 JPEG 衍生檔：只多允許精確的 .jpg 後綴。
    assert.ok(pattern.test('/media/' + 'a'.repeat(43) + '.jpg'));
    for (const suffix of ['.png', '.jpg.jpg', '.JPG', '.jpg/', 'xjpg', '.jpgx']) assert.ok(!pattern.test('/media/' + 'a'.repeat(43) + suffix), suffix);
    assert.ok(pattern.test('/webhook/meta-inbound'));
    for (const path of ['/media', '/media/', '/media/short', '/media/' + 'a'.repeat(42), '/media/' + 'a'.repeat(44), '/media/' + 'a'.repeat(43) + '/', '/media/../api/health', '/media/%2e%2e/api/health', '/media/%252e%252e/api/health', '/media/a%2f..%2fapi/health', '/api/health']) assert.ok(!pattern.test(path), path);
  }
  const seen = [];
  const base = await serverFor(t, (req, res) => { seen.push(req.url); res.writeHead(404); res.end(); });
  await assert.rejects(checkEndpoint(base, secret, true));
  for (const path of ['/media', '/media/', '/media/short', '/media/../api/health', '/media/%2e%2e/api/health', '/media/%252e%252e/api/health']) assert.ok(seen.includes(path), path);
});

test('平台 CLI 經共用解析器取得設定，IPC 僅輸出密文且失敗不洩露內容', () => {
  const canary = 'isolated-platform-canary';
  const result = readPlatformSettings({ META_APP_SECRET: 'env', WEBHOOK_PUBLIC_URL: 'fixed' }, (cmd, args, options) => {
    assert.equal(cmd, 'uv');
    assert.equal(args.at(-1), '../scripts/platform_credentials.py');
    assert.equal(options.windowsHide, true);
    const nonce = randomBytes(12);
    const cipher = crypto.createCipheriv('aes-256-gcm', Buffer.from(options.input, 'base64'), nonce);
    cipher.setAAD(Buffer.from('platform-config'));
    const packed = Buffer.concat([nonce, cipher.update(JSON.stringify({ META_APP_SECRET: canary })), cipher.final(), cipher.getAuthTag()]);
    const stdout = packed.toString('base64');
    assert.ok(!stdout.includes(canary));
    return { status: 0, stdout };
  });
  assert.equal(result.META_APP_SECRET, canary);
  assert.equal(result.WEBHOOK_PUBLIC_URL, 'fixed');
  for (const run of [() => ({ status: 1, stdout: canary, stderr: canary }), () => { throw new Error(canary); }]) {
    assert.throws(() => readPlatformSettings({}, run), e => !e.message.includes(canary) && e.message.includes('平台憑證'));
  }
});

test('固定網址設定拒絕任意主機、HTTP、userinfo、port、path、query 及 wildcard', () => {
  assert.equal(fixedUrl('https://example.ngrok.app/'), 'https://example.ngrok.app');
  for (const value of ['https://', 'http://example.ngrok.app', 'https://user:pass@example.ngrok.app',
    'https://example.ngrok.app:8443', 'https://example.ngrok.app/webhook/x',
    'https://example.ngrok.app?x=1', 'https://example.ngrok.app#x',
    'https://example.ngrok.app.evil.invalid', 'https://*.ngrok.app']) {
    assert.throws(() => fixedUrl(value));
  }
});

test('Cloudflare 固定網址只接受自有網域的根網址', () => {
  assert.equal(fixedUrl('https://mwb.example.com/', 'cloudflare'), 'https://mwb.example.com');
  assert.equal(publicUrl({ WEBHOOK_GATEWAY: 'cloudflare', WEBHOOK_PUBLIC_URL: 'https://mwb.example.com' }), 'https://mwb.example.com');
  for (const value of ['http://mwb.example.com', 'https://user:pass@mwb.example.com', 'https://mwb.example.com:8443',
    'https://mwb.example.com/webhook/x', 'https://mwb.example.com?x=1', 'https://mwb.example.com#x',
    'https://203.0.113.5', 'https://[::1]', 'https://localhost', 'https://mwb.localhost', 'https://mwb.example.ts.net',
    'https://example.ngrok.app', 'https://*.example.com', 'https://example']) {
    assert.throws(() => fixedUrl(value, 'cloudflare'), undefined, value);
  }
  // 設成 ngrok 時不接受自有網域，避免一半設定就送出探測金鑰。
  assert.throws(() => publicUrl({ WEBHOOK_PUBLIC_URL: 'https://mwb.example.com' }));
});

test('閘道種類與本機狀態埠依 WEBHOOK_GATEWAY 決定', () => {
  assert.equal(gatewayKind({}), 'ngrok');
  assert.equal(gatewayKind({ WEBHOOK_GATEWAY: ' Cloudflare ' }), 'cloudflare');
  assert.throws(() => gatewayKind({ WEBHOOK_GATEWAY: 'tailscale' }), /WEBHOOK_GATEWAY/);
  assert.deepEqual(gatewayAgent({}), { name: 'ngrok', port: 4040, url: 'http://127.0.0.1:4040/api/tunnels' });
  assert.deepEqual(gatewayAgent({ WEBHOOK_GATEWAY: 'cloudflare' }), { name: 'cloudflared', port: 20241, url: 'http://127.0.0.1:20241/ready' });
});

test('Tunnel token 格式檢查不接受空白或亂碼', () => {
  const good = Buffer.from(JSON.stringify({ a: 'account', t: 'tunnel', s: 'secret' })).toString('base64');
  assert.equal(tunnelTokenValid(good), true);
  for (const value of [undefined, '', 'not-a-token', Buffer.from('{"a":"x"}').toString('base64')]) assert.equal(tunnelTokenValid(value), false);
});

test('cloudflared 搜尋順序 PATH、CLOUDFLARED_PATH、Program Files；缺少時提示安裝', () => {
  const exe = process.platform === 'win32' ? 'cloudflared.exe' : 'cloudflared';
  const env = { PATH: 'E:/path', ProgramFiles: 'E:/pf', 'ProgramFiles(x86)': 'E:/pf86' }, settings = { CLOUDFLARED_PATH: 'E:/configured/cloudflared.exe' };
  assert.equal(resolveCloudflared(settings, env, () => true), join('E:/path', exe));
  assert.equal(resolveCloudflared(settings, env, p => p === settings.CLOUDFLARED_PATH), settings.CLOUDFLARED_PATH);
  assert.equal(resolveCloudflared(settings, env, p => p === join('E:/pf86', 'cloudflared', exe)), join('E:/pf86', 'cloudflared', exe));
  assert.throws(() => resolveCloudflared(settings, env, () => false), /找不到 cloudflared.*winget/);
});

async function serverFor(t, handler) {
  const server = http.createServer(handler);
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => { server.close(resolve); server.closeAllConnections(); }));
  return `http://127.0.0.1:${server.address().port}`;
}

test('HTTP 驗收保留原始穿越路徑且不跟隨 redirect', async (t) => {
  const seen = [];
  const base = await serverFor(t, (req, res) => {
    seen.push(req.url);
    res.writeHead(302, { Location: '/redirected' });
    res.end();
  });
  for (const path of ['/webhook/../rest/settings', '/webhook/%2e%2e/rest/settings']) {
    assert.equal((await request(base, path)).status, 302);
  }
  assert.deepEqual(seen, ['/webhook/../rest/settings', '/webhook/%2e%2e/rest/settings']);
});

test('排程器首輪尚未完成時重試，逾時仍失敗', async () => {
  let clock = 0, calls = 0;
  const runtime = (healthyAt) => ({
    now: () => clock, sleep: async ms => { clock += ms; },
    request: async (_base, _path, options) => {
      if (!options) return { status: 401, body: '' };
      calls += 1;
      return { status: 200, body: JSON.stringify({ healthy: clock >= healthyAt }) };
    },
  });
  await checkBackend({}, 'http://backend.invalid', runtime(3000));
  assert.equal(calls, 4);
  clock = 0;
  await assert.rejects(checkBackend({}, 'http://backend.invalid', { ...runtime(Infinity), timeoutMs: 5000 }), /尚未就緒/);
});

test('驗收不接受公開管理 API 或 HTTP 200 提示頁冒充成功', async (t) => {
  const base = await serverFor(t, (_req, res) => {
    res.writeHead(200, { 'Content-Type': 'text/html' });
    res.end('<html>not a webhook response</html>');
  });
  await assert.rejects(checkBackend({}, base), /尚未就緒/);
  await assert.rejects(checkEndpoint(base, secret, true), /公開路徑未被拒絕/);
  await assert.rejects(checkEndpoint(base, secret, false), /未通過/);
});

test('ngrok 子程序僅接收 tunnel 憑證與必要系統變數', () => {
  const env = gatewayEnvironment({ NGROK_AUTHTOKEN:'isolated-token' }, { PATH:'fixture-path', JEV_API_KEY:'private', META_PAGE_ACCESS_TOKEN:'private', ADMIN_INITIAL_PASSWORD:'private' });
  assert.deepEqual(env, { PATH:'fixture-path', NGROK_AUTHTOKEN:'isolated-token' });
  // cloudflared 只拿 Tunnel token，而且經環境變數，不出現在命令列。
  const cf = gatewayEnvironment({ WEBHOOK_GATEWAY:'cloudflare', CLOUDFLARE_TUNNEL_TOKEN:'tunnel-token', NGROK_AUTHTOKEN:'other' }, { PATH:'fixture-path', JEV_API_KEY:'private' });
  assert.deepEqual(cf, { PATH:'fixture-path', TUNNEL_TOKEN:'tunnel-token' });
});

test('後端埠號取自 BACKEND_INTERNAL_URL，且 APP_ORIGIN 本機網址要同埠', () => {
  assert.equal(backendPort({}), 8000);
  assert.equal(backendPort({ BACKEND_INTERNAL_URL: 'http://127.0.0.1:8010', APP_ORIGIN: 'http://127.0.0.1:8010,https://mwb.example.ts.net' }), 8010);
  assert.equal(backendPort({ BACKEND_INTERNAL_URL: 'http://127.0.0.1:8010', APP_ORIGIN: 'https://mwb.example.ts.net' }), 8010);
  assert.throws(() => backendPort({ BACKEND_INTERNAL_URL: 'http://127.0.0.1:8010', APP_ORIGIN: 'http://127.0.0.1:8000' }), /8010/);
  assert.throws(() => backendPort({ BACKEND_INTERNAL_URL: 'http://example.com:8010' }));
});

test('改用其他埠號時只換本機網址，保留 Tailscale 來源', () => {
  assert.deepEqual(portSettings({ APP_ORIGIN: 'http://127.0.0.1:8000,https://mwb.example.ts.net' }, 8010),
    { BACKEND_INTERNAL_URL: 'http://127.0.0.1:8010', APP_ORIGIN: 'http://127.0.0.1:8010,https://mwb.example.ts.net' });
  assert.equal(portSettings({}, 8010).APP_ORIGIN, 'http://127.0.0.1:8010');
  assert.equal(portSettings({ APP_ORIGIN: 'https://mwb.example.ts.net' }, 8010).APP_ORIGIN, 'http://127.0.0.1:8010,https://mwb.example.ts.net');
  assert.equal(backendPort(portSettings({ APP_ORIGIN: 'http://localhost:8000' }, 8010)), 8010);
  assert.throws(() => portSettings({}, 80));
  assert.throws(() => portSettings({}, Number('abc')));
});

test('only a Cloudflare Access login redirect counts as blocked', () => {
  const r = (status, location) => ({ status, headers: location ? { location } : {} });
  assert.equal(accessLogin(r(302, 'https://team-1.cloudflareaccess.com/cdn-cgi/access/login/mwb.example.com?kid=x')), true);
  assert.equal(accessLogin(r(303, 'https://team.cloudflareaccess.com/cdn-cgi/access/login/h')), true);
  assert.equal(accessLogin(r(200, 'https://team.cloudflareaccess.com/cdn-cgi/access/login/h')), false);
  assert.equal(accessLogin(r(302)), false);
  assert.equal(accessLogin(r(302, '/signin')), false);
  assert.equal(accessLogin(r(302, 'http://team.cloudflareaccess.com/cdn-cgi/access/login/h')), false);
  assert.equal(accessLogin(r(302, 'https://team.cloudflareaccess.com.evil.test/cdn-cgi/access/login/h')), false);
  assert.equal(accessLogin(r(302, 'https://evil.test/cdn-cgi/access/login/?x=.cloudflareaccess.com')), false);
  assert.equal(accessLogin(r(302, 'https://team.cloudflareaccess.com:8443/cdn-cgi/access/login/h')), false);
  assert.equal(accessLogin(r(302, 'https://team.cloudflareaccess.com/other')), false);
});

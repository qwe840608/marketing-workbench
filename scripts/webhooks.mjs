import { spawn } from 'node:child_process';
import { createHmac, randomBytes } from 'node:crypto';
import { readFileSync, writeFileSync, appendFileSync, existsSync, mkdirSync } from 'node:fs';
import http from 'node:http';
import https from 'node:https';
import { dirname, join, isAbsolute, delimiter } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { parseEnv } from 'node:util';
import { setTimeout as delay } from 'node:timers/promises';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const envPath = join(root, '.env');
const backendUrl = 'http://127.0.0.1:8000';
const agentUrl = 'http://127.0.0.1:4040';
const probePath = '/webhook/mwb-gateway-probe';
const children = new Set();

export function readSettings() {
  if (!existsSync(envPath)) throw new Error('請先將 .env.example 複製成 .env。');
  return parseEnv(readFileSync(envPath, 'utf8'));
}

export function saveSettings(values) {
  let content = readFileSync(envPath, 'utf8');
  for (const [key, value] of Object.entries(values)) {
    if (!/^[A-Z][A-Z0-9_]*$/.test(key) || /[\r\n'\x00]/.test(value)) {
      throw new Error('無法安全保存設定。');
    }
    const line = `${key}='${value}'`;
    const pattern = new RegExp(`^${key}=.*$`, 'gm');
    content = pattern.test(content) ? content.replace(pattern, () => line) : `${content.trimEnd()}\n${line}\n`;
  }
  // 機密只寫回 .env，不產生副本或暫存輸出。
  writeFileSync(envPath, content, { mode: 0o600 });
}

export function fixedUrl(value) {
  const url = new URL(value);
  if (url.protocol !== 'https:' || url.username || url.password || url.port ||
      url.pathname !== '/' || url.search || url.hash ||
      !/^[a-z0-9-]+\.ngrok(?:-free)?\.(?:app|dev)$/.test(url.hostname)) {
    throw new Error('WEBHOOK_PUBLIC_URL 必須是 ngrok 的固定 HTTPS 網址。');
  }
  return url.origin;
}

function prepare() {
  const settings = readSettings();
  const defaults = {
    INGEST_API_KEY: randomBytes(32).toString('base64url'),
    WEBHOOK_PROBE_SECRET: settings.N8N_PROBE_SECRET || randomBytes(32).toString('hex'),
  };
  const missing = Object.fromEntries(Object.entries(defaults).filter(([key]) => !settings[key]));
  if (Object.keys(missing).length) saveSettings(missing);
  // Deployment calls prepare only after backing up .env; preserve the probe key during rename.
  const content = readFileSync(envPath, 'utf8');
  writeFileSync(envPath, content.replace(/^N8N_[A-Z0-9_]*=.*(?:\r?\n|$)/gm, ''), {mode:0o600});
  console.log('後端 Webhook 與 Ingest 金鑰已就緒；機密僅保存在 .env。');
}

export function gatewayEnvironment(settings, environment = process.env) {
  const keep = ['PATH','Path','SystemRoot','WINDIR','TEMP','TMP','LOCALAPPDATA','USERPROFILE','HOME'];
  return { ...Object.fromEntries(keep.filter(k => environment[k]).map(k => [k,environment[k]])), NGROK_AUTHTOKEN: settings.NGROK_AUTHTOKEN };
}
export function backendAddress(settings = {}) {
  const base = settings.BACKEND_INTERNAL_URL || backendUrl;
  if (!/^http:\/\/(127\.0\.0\.1|localhost):\d{1,5}$/.test(base)) throw new Error('BACKEND_INTERNAL_URL 必須為 loopback。');
  return base;
}
// 後端埠號以 BACKEND_INTERNAL_URL 為準，同一台電腦可並存另一份工作檯（例如測試安裝）。
export function backendPort(settings = {}) {
  const base = backendAddress(settings), port = Number(new URL(base).port || 80);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('BACKEND_INTERNAL_URL 的連接埠不合法。');
  // APP_ORIGIN 的本機網址埠號不同時，瀏覽器送出的 Origin 會被後端拒絕，登入後所有寫入都失敗。
  const local = (settings.APP_ORIGIN || '').split(',').map(v => v.trim()).filter(v => /^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?\/?$/.test(v));
  if (local.length && !local.some(v => Number(new URL(v).port || 80) === port)) throw new Error(`APP_ORIGIN 的本機網址必須使用 BACKEND_INTERNAL_URL 的連接埠 ${port}。`);
  return port;
}
// 改用其他埠號時，後端位址與 APP_ORIGIN 的本機網址一起換；HTTPS 來源（Tailscale）不動。
export function portSettings(settings, port) {
  if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('連接埠須為 1024～65535 的整數。');
  const origins = (settings.APP_ORIGIN || 'http://127.0.0.1:8000').split(',').map(v => v.trim()).filter(Boolean)
    .map(v => /^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?\/?$/.test(v) ? `http://${new URL(v).hostname}:${port}` : v);
  if (!origins.some(v => v.startsWith('http://127.0.0.1:') || v.startsWith('http://localhost:'))) origins.unshift(`http://127.0.0.1:${port}`);
  return { BACKEND_INTERNAL_URL: `http://127.0.0.1:${port}`, APP_ORIGIN: [...new Set(origins)].join(',') };
}
export function gatewayStartupSeconds(settings = {}) {
  const seconds = Number(settings.GATEWAY_STARTUP_TIMEOUT_SECONDS || 120);
  if (!Number.isInteger(seconds) || seconds < 1 || seconds > 3600) throw new Error('GATEWAY_STARTUP_TIMEOUT_SECONDS 必須為 1～3600 整數秒。');
  return seconds;
}

export function request(base, path, { headers = {}, method = 'GET', body } = {}) {
  const origin = new URL(base);
  return new Promise((resolve, reject) => {
    // path 直接交給 HTTP client，保留驗收用的編碼與 ..，不先由 URL 正規化。
    const req = (origin.protocol === 'https:' ? https : http).request({
      protocol: origin.protocol, hostname: origin.hostname, port: origin.port,
      method, path, headers, timeout: 12000,
    }, (res) => {
      const chunks = [];
      let size = 0;
      res.on('data', (chunk) => {
        size += chunk.length;
        if (size > 2 * 1024 * 1024) { res.destroy(); reject(new Error('驗收回應超過大小限制。')); }
        else chunks.push(chunk);
      });
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks).toString('utf8') }));
      res.on('error', () => reject(new Error('讀取驗收回應失敗。')));
    });
    req.on('timeout', () => req.destroy(new Error('驗收連線逾時。')));
    req.on('error', () => reject(new Error('驗收端點無法連線。')));
    req.end(body);
  });
}

export function resolveNgrok(settings, environment = process.env, exists = existsSync) {
  const path = environment.PATH || environment.Path || '';
  const candidates = path.split(delimiter).filter(Boolean).map(p => join(p.replace(/^"|"$/g, ''), process.platform === 'win32' ? 'ngrok.exe' : 'ngrok'));
  if (settings.NGROK_PATH && isAbsolute(settings.NGROK_PATH)) candidates.push(settings.NGROK_PATH);
  if (environment.LOCALAPPDATA) candidates.push(join(environment.LOCALAPPDATA, 'ngrok', 'bin', 'ngrok.exe'));
  const found = candidates.find(exists);
  if (!found) throw new Error('找不到 ngrok 執行檔：已依序檢查 PATH、.env 的 NGROK_PATH、LOCALAPPDATA\\ngrok\\bin\\ngrok.exe。NGROK_PATH 須填完整路徑。');
  return found;
}

export function startupFailure(name, diagnostic = '', launchCode = '') {
  const code = diagnostic.match(/ERR_NGROK_\d+/)?.[0] || launchCode || diagnostic.match(/\b(?:SQLITE_[A-Z_]+|EADDRINUSE|EACCES|EPERM|MODULE_NOT_FOUND|ERR_[A-Z_]+)\b/)?.[0];
  let reason = code || '程序提早結束或未提供錯誤代碼';
  if (code === 'ENOENT') reason = '找不到執行檔';
  else if (['EACCES', 'EPERM'].includes(code)) reason = '執行權限不足';
  else if (/ERR_NGROK_(?:105|106|107|108|4018)\b/.test(code || '') || /invalid authtoken|authentication failed/i.test(diagnostic)) reason = 'authtoken 無效、驗證失敗或帳號連線數已達上限（' + (code || 'authentication') + '）';
  else if (/ERR_NGROK_334\b/.test(code || '') || /already online|already.*session/i.test(diagnostic)) reason = '固定網址被其他 session 佔用（' + (code || 'endpoint_in_use') + '）';
  return new Error(`${name} 啟動失敗：${reason}；已停止公開連線。`);
}

function childProcess(name, executable, args, env) {
  const cwd = root;
  const child = spawn(executable, args, { cwd, env, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  children.add(child);
  child.serviceName = name;
  child.diagnostic = '';
  const capture = (data) => {
    // 原始子程序輸出僅留記憶體，避免憑證、query 或 payload 流入日誌。
    child.diagnostic = (child.diagnostic + data.toString()).slice(-32000);
  };
  child.stdout.on('data', capture);
  child.stderr.on('data', capture);
  child.on('error', error => { child.launchFailed = true; child.launchCode = error.code; });
  child.on('exit', () => children.delete(child));
  return child;
}

function failure(child) {
  return startupFailure(child.serviceName, child.diagnostic, child.launchCode);
}

async function stop(child) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  child.kill('SIGTERM');
  for (let i = 0; i < 50 && child.exitCode === null && child.signalCode === null; i++) await delay(100);
}

export function startupTail(child) {
  return child.diagnostic.trim().split(/\r?\n/).slice(-12).map((line, index) => {
    const safe = line.match(/\b(?:SQLITE_BUSY|SQLITE_ERROR|EACCES|ENOENT|EADDRINUSE|ETIMEDOUT)\b/g);
    return `${index + 1}: ${safe?.join(' ') || '[原始內容已遮蔽]'}`;
  }).join('\n');
}

function saveTail(child) {
  const path = join(root, '.runtime', 'gateway-startup-tail.log');
  mkdirSync(dirname(path), { recursive: true });
  // 子程序可印出任意 payload；只留下白名單事件／錯誤碼，其餘整行遮蔽。
  writeFileSync(path, `${child.serviceName}\n${startupTail(child)}\n`, 'utf8');
  return path;
}

export async function waitReady(child, base, path, accept, seconds = 60, runtime = {}) {
  const now = runtime.now || Date.now, sleep = runtime.sleep || delay, started = now();
  let nextProgress = 0;
  while (now() - started < seconds * 1000) {
    if (child.launchFailed || child.exitCode !== null || child.signalCode !== null) throw failure(child);
    const elapsed = Math.floor((now() - started) / 1000);
    if (elapsed >= nextProgress) {
      (runtime.progress || console.log)(`${child.serviceName} 就緒：已等待 ${elapsed}／${seconds} 秒`);
      nextProgress = elapsed + 10;
    }
    try {
      const res = await (runtime.request || request)(base, path);
      if (accept(res)) return res;
    } catch { /* 等待本機服務完成啟動。 */ }
    await sleep(500);
  }
  const waited = Math.round((now() - started) / 1000);
  const log = (runtime.saveTail || saveTail)(child);
  throw new Error(`${child.serviceName} 未就緒，已等待 ${waited} 秒；日誌最後 12 行（遮罩摘要）：${log}`);
}

export async function checkBackend(settings, base = backendAddress(settings), runtime = {}) {
  // The scheduler turns healthy only after its first tick, which can lag behind HTTP readiness.
  const send = runtime.request || request, now = runtime.now || Date.now, sleep = runtime.sleep || delay;
  const deadline = now() + (runtime.timeoutMs ?? 60000);
  for (;;) {
    const response = await send(base, '/api/scheduler/status', { headers: {'X-Api-Key':settings.INGEST_API_KEY || ''} });
    let data; try { data = JSON.parse(response.body); } catch {}
    if (response.status === 200 && data?.healthy === true) break;
    if (response.status !== 200 || data?.healthy !== false || now() >= deadline) throw new Error('後端排程器尚未就緒。');
    await sleep(1000);
  }
  const anonymous = await send(base, '/api/scheduler/status');
  if (anonymous.status !== 401) throw new Error('後端排程 API 未登入未回 401。');
  console.log('PASS 後端排程器運作及內部 API 權限。');
}

export async function checkEndpoint(base, secret, external = true) {
  const headers = { 'ngrok-skip-browser-warning': '1', 'User-Agent': 'marketing-workbench-acceptance/1' };
  let count = 0;
  if (external) {
    for (const path of ['/', '/signin', '/setup', '/home/workflows', '/workflow/test',
      '/rest/workflows', '/rest/settings', '/api/health', '/webhook-test/mwb-gateway-probe',
      '/media', '/media/', '/media/short', '/media/../api/health',
      '/media/%2e%2e/api/health', '/media/%252e%252e/api/health',
      '/media/test%2f..%2f..%2fapi/health', '/media/' + 'a'.repeat(43) + '/',
      '/webhook', '/webhook/', '/Webhook/mwb-gateway-probe',
      '/webhook/../rest/settings', '/webhook/%2e%2e/rest/settings',
      '/webhook/%252e%252e/rest/settings', '/webhook/test%2f..%2f..%2frest/settings']) {
      const res = await request(base, path, { headers });
      if (![403, 404].includes(res.status)) throw new Error(`公開路徑未被拒絕：${path}（${res.status}）。`);
      console.log(`PASS ${path} → ${res.status}`);
      count++;
    }
  }
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const signature = createHmac('sha256', secret).update(`GET\n${probePath}\n${timestamp}`).digest('hex');
  const good = await request(base, probePath, { headers: { ...headers, 'x-mwb-probe-time': timestamp, 'x-mwb-probe-signature': signature } });
  let result;
  try { result = JSON.parse(good.body); } catch { /* ngrok 錯誤頁或 後台頁面不能算 Webhook 通過。 */ }
  if (good.status !== 200 || !result?.ok || result.service !== 'backend' || result.purpose !== 'tunnel-check') {
    throw new Error(`已簽章的後端 驗收 Webhook 未通過（${good.status}）。`);
  }
  for (const badHeaders of [{}, { 'x-mwb-probe-time': timestamp, 'x-mwb-probe-signature': '0'.repeat(64) }]) {
    const bad = await request(base, probePath, { headers: { ...headers, ...badHeaders } });
    if (bad.status !== 401) throw new Error('驗收 Webhook 未拒絕缺少／錯誤簽章。');
  }
  count += 3;
  console.log(`PASS ${external ? '公開' : '本機'} Webhook：有效簽章 200，缺少／錯誤簽章 401（${count} checks）。`);
  return count;
}

export function recordStartup(phase, started, details = {}, runtime = {}) {
  const row = { utc: new Date().toISOString(), pid: process.pid, phase,
    seconds: Number((((runtime.now || (() => performance.now()))() - started) / 1000).toFixed(3)), ...details };
  const directory = runtime.directory || join(root, '.runtime');
  mkdirSync(directory, { recursive: true });
  appendFileSync(join(directory, 'gateway-startup-times.jsonl'), `${JSON.stringify(row)}\n`, 'utf8');
  (runtime.progress || console.log)(`Webhook 啟動量測 ${phase}：${row.seconds} 秒；紀錄 .runtime/gateway-startup-times.jsonl`);
  return row;
}

async function startNgrok(settings) {
  if (!settings.NGROK_AUTHTOKEN) throw new Error('請先在 .env 設定 NGROK_AUTHTOKEN。');
  const args = ['http', backendAddress(settings), '--config', join(root, 'config/ngrok.yml'),
    '--traffic-policy-file', join(root, 'config/ngrok-traffic-policy.json'), '--inspect=false', '--log=stdout', '--log-format=json'];
  if (settings.WEBHOOK_PUBLIC_URL) args.push('--url', fixedUrl(settings.WEBHOOK_PUBLIC_URL));
  // 免費方案未指定 --url 時使用帳號固定 dev domain，取回後立即保存並以 --url 重啟驗證。
  const child = childProcess('ngrok', resolveNgrok(settings), args, gatewayEnvironment(settings));
  let address;
  await waitReady(child, agentUrl, '/api/tunnels', (res) => {
    const tunnels = JSON.parse(res.body).tunnels;
    address = tunnels?.find((t) => t.name && t.public_url?.startsWith('https://'))?.public_url;
    return Boolean(address);
  });
  return { child, address: fixedUrl(address) };
}

async function ensurePortsFree() {
  for (const base of [agentUrl]) {
    let occupied = false;
    try { await request(base, '/'); occupied = true; } catch { /* 沒有服務才允許本次啟動。 */ }
    if (occupied) throw new Error(`${base} 已有服務，請先停止該服務，避免改到其他執行中的環境。`);
  }
}

async function main() {
  const started = performance.now(), command = process.argv[2] || 'check';
  if (command === 'prepare') return prepare();
  const settings = readSettings();
  if (command === 'resolve-ngrok') {
    resolveNgrok(settings);
    // 在建置與啟動後端前就擋下：沒有 authtoken 時閘道一定起不來，晚一步失敗還會把剛啟動的後端停掉。
    if (!settings.NGROK_AUTHTOKEN) throw new Error('請先在 .env 設定 NGROK_AUTHTOKEN（ngrok 後台 Your Authtoken 頁面複製）。');
    console.log('ngrok 執行檔與 authtoken 已就緒。'); return;
  }
  if (command === 'check') {
    await checkBackend(settings);
    await checkEndpoint(fixedUrl(settings.WEBHOOK_PUBLIC_URL), settings.WEBHOOK_PROBE_SECRET);
    return;
  }
  if (command !== 'up') throw new Error('用法：node scripts/webhooks.mjs prepare|up|check');
  await ensurePortsFree();
  await checkBackend(settings);
  await checkEndpoint(backendAddress(settings), settings.WEBHOOK_PROBE_SECRET, false);
  const tunnel = await startNgrok(settings);
  if (settings.WEBHOOK_PUBLIC_URL && fixedUrl(settings.WEBHOOK_PUBLIC_URL) !== tunnel.address) throw new Error('ngrok 網址與已保存固定網址不符。');
  if (!settings.WEBHOOK_PUBLIC_URL) saveSettings({ WEBHOOK_PUBLIC_URL:tunnel.address });
  await checkEndpoint(tunnel.address, settings.WEBHOOK_PROBE_SECRET);
  console.log('固定網址驗收通過：' + tunnel.address);
  recordStartup('gateway-ready', started);
  while (true) {
    await delay(1000);
    if (tunnel.child.exitCode !== null || tunnel.child.signalCode !== null) throw failure(tunnel.child);
  }
}

async function cleanup() {
  await Promise.all([...children].map(stop));
}

if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) {
  process.on('SIGINT', async () => { await cleanup(); process.exit(0); });
  process.on('SIGTERM', async () => { await cleanup(); process.exit(0); });
  main().catch(async (error) => {
    // 只輸出自訂驗收訊息，第三方例外可能包含輸入或憑證。
    const safe = /[\u4e00-\u9fff]/.test(error.message) && !error.message.includes('\n');
    console.error(safe ? error.message : 'Webhook 環境設定失敗；未輸出第三方例外內容。');
    await cleanup();
    process.exitCode = 1;
  });
}

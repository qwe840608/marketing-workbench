import { createHmac } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { readSettings, fixedUrl } from './webhooks.mjs';
import { readPlatformSettings } from './platform-credentials.mjs';

const scopes = ['pages_show_list', 'pages_read_engagement', 'pages_read_user_content', 'pages_manage_metadata',
  'read_insights', 'instagram_basic', 'instagram_manage_comments', 'instagram_manage_insights'];
async function graph(s, path, params = {}, app = false, method = 'GET') {
  const url = new URL('https://graph.facebook.com/v26.0/' + path);
  const form = new URLSearchParams(params);
  if (method === 'GET') url.search = form.toString();
  const res = await fetch(url, { method, headers: { Authorization: 'Bearer ' +
    (app ? `${s.META_APP_ID}|${s.META_APP_SECRET}` : s.META_PAGE_ACCESS_TOKEN),
    ...(method === 'POST' ? { 'Content-Type': 'application/x-www-form-urlencoded' } : {}) },
    ...(method === 'POST' ? { body: form } : {}), redirect: 'error', signal: AbortSignal.timeout(20000) });
  const body = await res.json();
  if (!res.ok || body.error) throw new Error(`Meta 官方 API 回應 ${res.status}（代碼 ${Number.isInteger(body.error?.code) ? body.error.code : '無'}）。`);
  return body;
}
async function inspect(s) {
  for (const name of ['META_APP_ID', 'META_APP_SECRET', 'META_PAGE_ID', 'META_PAGE_ACCESS_TOKEN', 'META_IG_ACCOUNT_ID'])
    if (!s[name]) throw new Error(`請先設定 ${name}。`);
  const { data } = await graph(s, 'debug_token', { input_token: s.META_PAGE_ACCESS_TOKEN }, true);
  if (!data?.is_valid || data.app_id !== s.META_APP_ID || data.type !== 'PAGE' || String(data.profile_id) !== s.META_PAGE_ID)
    throw new Error('Meta 權杖無效、App 不符或不是指定測試粉專的權杖。');
  const missing = scopes.filter(scope => !data.scopes?.includes(scope));
  if (missing.length) throw new Error('Meta 權杖缺少權限：' + missing.join(', '));
  const page = await graph(s, s.META_PAGE_ID, { fields: 'id,name,instagram_business_account{id,username}' });
  if (page.id !== s.META_PAGE_ID || page.instagram_business_account?.id !== s.META_IG_ACCOUNT_ID)
    throw new Error('Meta 測試粉專與 IG 連結不符，停止設定。');
  console.log(JSON.stringify({ page: page.name, instagram: page.instagram_business_account.username,
    token_scopes: 'complete', advanced_access: 'not_verified' }));
  return { facebook: { id: page.id, name: page.name },
    instagram: { id: page.instagram_business_account.id, name: page.instagram_business_account.username } };
}
async function endpoint(s, path, { method = 'GET', body, headers = {}, timeout = 20000 } = {}) {
  const response = await fetch(fixedUrl(s.WEBHOOK_PUBLIC_URL) + path, { method, headers: {
    'User-Agent': 'mwb-meta-acceptance/1', 'ngrok-skip-browser-warning': '1', ...headers },
    ...(body !== undefined ? { body } : {}), redirect: 'error', signal: AbortSignal.timeout(timeout) });
  return { status: response.status, body: await response.text() };
}
export async function checkMeta(s) {
  const query = new URLSearchParams({ 'hub.mode': 'subscribe', 'hub.verify_token': s.META_VERIFY_TOKEN, 'hub.challenge': '123480009' });
  let r = await endpoint(s, '/webhook/meta-inbound?' + query);
  if (r.status !== 200 || r.body !== '123480009') throw new Error('Meta 事件登記 challenge 驗收失敗。');
  query.set('hub.verify_token', 'invalid'); r = await endpoint(s, '/webhook/meta-inbound?' + query);
  if (r.status !== 403) throw new Error('Meta 事件登記錯誤 token 未被拒絕。');
  for (const [object, account] of [['page', s.META_PAGE_ID], ['instagram', s.META_IG_ACCOUNT_ID]]) {
    const body = JSON.stringify({ object, entry: [{ id: account, changes: [] }] });
    for (const [valid, expected] of [[true, 200], [false, 401]]) {
      const signature = valid ? 'sha256=' + createHmac('sha256', s.META_APP_SECRET).update(body).digest('hex') : '';
      r = await endpoint(s, '/webhook/meta-inbound', { method: 'POST', body,
        headers: { 'Content-Type': 'application/json', 'X-Hub-Signature-256': signature } });
      if (r.status !== expected || (valid && JSON.parse(r.body).ok !== true)) throw new Error('Meta 公開簽章驗收失敗。');
    }
  }
  for (const path of ['/webhook/meta-sync', '/webhook/meta-comments-sync']) {
    r = await endpoint(s, path, { method: 'POST', body: '{}', headers: { 'Content-Type': 'application/json' } });
    if (r.status !== 401) throw new Error('Meta 手動同步未驗簽請求未被拒絕。');
  }
  console.log('PASS Meta 公開端點：challenge 200、錯誤 token 403、有效簽章 200、缺少簽章 401；兩個手動同步端點均拒絕未驗簽請求。');
}
async function connect(s) {
  await inspect(s);
  await checkMeta(s);
  const callback = fixedUrl(s.WEBHOOK_PUBLIC_URL) + '/webhook/meta-inbound';
  const subscriptions = await graph(s, s.META_APP_ID + '/subscriptions', {}, true);
  if (subscriptions.data?.some(row => ['page', 'instagram'].includes(row.object) && row.callback_url !== callback))
    throw new Error('Meta App 已有其他 Webhook；需先確認切換，不能直接覆寫。');
  for (const [object, fields] of [['page', 'feed'], ['instagram', 'comments']]) {
    await graph(s, s.META_APP_ID + '/subscriptions', { object, fields, callback_url: callback,
      verify_token: s.META_VERIFY_TOKEN, include_values: 'true' }, true, 'POST');
  }
  await graph(s, s.META_PAGE_ID + '/subscribed_apps', { subscribed_fields: 'feed' }, false, 'POST');
  // Facebook Login 使用連結的 Page 事件登記；此 IG User 沒有 Instagram Login 的 subscribed_apps edge。
  const after = await graph(s, s.META_APP_ID + '/subscriptions', {}, true);
  const page = await graph(s, s.META_PAGE_ID + '/subscribed_apps');
  if (!page.data?.some(row => row.id === s.META_APP_ID && ['feed'].every(f => row.subscribed_fields?.includes(f))) ||
      !['page', 'instagram'].every(object => after.data?.some(row => row.object === object && row.active && row.callback_url === callback)))
    throw new Error('Meta 事件登記讀回檢查未通過。');
  console.log(JSON.stringify({ configured: after.data?.map(row => ({ object: row.object,
    callbackMatches: row.callback_url === callback, active: row.active, fields: row.fields?.map(f => f.name) })) }));
}
async function main() {
  const s = readPlatformSettings(readSettings()), command = process.argv[2] || 'inspect';
  if (command === 'check') return checkMeta(s);
  if (command === 'connect') return connect(s);
  if (command === 'sync') {
    const timestamp = Math.floor(Date.now() / 1000).toString();
    const signature = createHmac('sha256', s.WEBHOOK_PROBE_SECRET).update('POST\n/webhook/meta-sync\n' + timestamp).digest('hex');
    const r = await endpoint(s, '/webhook/meta-sync', { method: 'POST', timeout: 300000,
      headers: { 'x-mwb-sync-time': timestamp, 'x-mwb-sync-signature': signature } });
    const body = JSON.parse(r.body);
    console.log(JSON.stringify({ status: r.status, ok: body.ok, posts: body.posts, snapshots: body.snapshots,
      errors: body.errors, error: body.error }));
    if (r.status !== 200 || !body.ok) process.exitCode = 1;
    return;
  }
  if (command !== 'inspect') throw new Error('用法：node scripts/meta.mjs inspect|check|connect|sync');
  const info = await inspect(s);
  const result = spawnSync('uv', ['run', 'python', '../scripts/register_meta_accounts.py'], {
    cwd: fileURLToPath(new URL('../backend', import.meta.url)), input: JSON.stringify(info), encoding: 'utf8', windowsHide: true,
    env: { ...process.env, PYTHONUTF8: '1' } });
  if (result.status !== 0) throw new Error('Meta 後台帳號登記失敗，請先執行 migration。');
  console.log('Meta 測試帳號已登記；未改動 Webhook。');
}
if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) main().catch(error => {
  console.error(/^(Meta |請先設定|用法)/.test(error.message) ? error.message : 'Meta 設定失敗；未輸出第三方例外或憑證。');
  process.exitCode = 1;
});

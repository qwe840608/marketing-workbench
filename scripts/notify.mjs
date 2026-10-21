import { createHmac } from 'node:crypto';
import { fixedUrl, readSettings, request, saveSettings } from './webhooks.mjs';
import { readPlatformSettings } from './platform-credentials.mjs';

const settings = readPlatformSettings(readSettings());
const command = process.argv[2] || 'inspect';
const token = settings.NOTIFY_LINE_CHANNEL_ACCESS_TOKEN;
const base = settings.BACKEND_INTERNAL_URL || 'http://127.0.0.1:8000';
const url = settings.WEBHOOK_PUBLIC_URL && fixedUrl(settings.WEBHOOK_PUBLIC_URL) + '/webhook/line-notify';
async function line(path, method = 'GET', body) {
  if (!token) throw new Error('請先在 .env 填入 NOTIFY_LINE_CHANNEL_ACCESS_TOKEN');
  const response = await request('https://api.line.me', path, { method,
    headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined });
  if (response.status !== 200) throw new Error('LINE API 未完成：HTTP ' + response.status);
  return JSON.parse(response.body);
}
async function main() {
  const bot = await line('/v2/bot/info');
  if (!/^U[a-f0-9]{32}$/.test(bot.userId || '') || bot.userId === settings.LINE_BOT_USER_ID)
    throw new Error('通知帳號必須是獨立的測試官方帳號');
  if (command === 'inspect') {
    saveSettings({ NOTIFY_LINE_BOT_USER_ID: bot.userId });
    console.log('通知帳號：' + bot.displayName + ' (' + bot.basicId + ')；識別碼已保存至 .env');
    return;
  }
  if (settings.NOTIFY_LINE_BOT_USER_ID !== bot.userId) throw new Error('請先執行 inspect 並重新啟動後端');
  if (command === 'configure') {
    if (!settings.NOTIFY_LINE_CHANNEL_SECRET || !url) throw new Error('缺少通知 secret 或固定 Webhook 網址');
    const raw = JSON.stringify({ destination: bot.userId, events: [] });
    const signature = createHmac('sha256', settings.NOTIFY_LINE_CHANNEL_SECRET).update(raw).digest('base64');
    const origin = new URL(url);
    const probe = await request(origin.origin, origin.pathname, { method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Line-Signature': signature }, body: raw });
    if (probe.status !== 200) throw new Error('Webhook 驗簽測試未通過：HTTP ' + probe.status);
    await line('/v2/bot/channel/webhook/endpoint', 'PUT', { endpoint: url });
    const check = await line('/v2/bot/channel/webhook/test', 'POST', { endpoint: url });
    if (!check.success) throw new Error('LINE 官方 Webhook 驗證未通過');
    console.log('通知 Webhook 已設定並通過官方驗證。請在 LINE Developers 開啟 Use webhook，再邀請通知帳號加入測試群組並傳送一則文字。');
    return;
  }
  if (!['groups', 'select-group'].includes(command)) throw new Error('用法：notify.mjs inspect|configure|groups|select-group <群組名稱>');
  if (!/^http:\/\/(127\.0\.0\.1|localhost):\d{1,5}$/.test(base)) throw new Error('後端僅可使用 loopback');
  const response = await request(base, '/api/notify/groups', { headers: { 'X-API-Key': settings.INGEST_API_KEY } });
  if (response.status !== 200) throw new Error('無法取得經驗簽的群組識別碼');
  const groups = [];
  for (const id of Object.keys(JSON.parse(response.body).groups)) {
    const summary = await line('/v2/bot/group/' + encodeURIComponent(id) + '/summary');
    if (summary.groupId === id) groups.push({ id, name: summary.groupName });
  }
  if (command === 'groups') {
    console.log(groups.length ? groups.map(g => g.name).join('\n') : '尚未收到群組事件');
    return;
  }
  const chosen = groups.filter(g => g.name === process.argv[3]);
  if (chosen.length !== 1) throw new Error('群組名稱需與已驗證的唯一測試群組一致');
  saveSettings({ NOTIFY_LINE_GROUP_ID: chosen[0].id });
  console.log('已保存首次搬移用測試群組：' + chosen[0].name + '。新版請到工作區設定，為各品牌選擇已驗證群組並儲存；環境值不會覆寫既有品牌設定。');
}
main().catch(() => { console.error('通知設定失敗，請確認平台連線與 Webhook 設定。'); process.exitCode = 1; });

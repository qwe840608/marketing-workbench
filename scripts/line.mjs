import { createHmac } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { readSettings, fixedUrl, request } from './webhooks.mjs';

export async function checkLine(settings) {
  const body = JSON.stringify({ events: [] });
  const signature = createHmac('sha256', settings.LINE_CHANNEL_SECRET).update(body).digest('base64');
  const base = fixedUrl(settings.WEBHOOK_PUBLIC_URL);
  const common = { 'Content-Type': 'application/json', 'ngrok-skip-browser-warning': '1', 'User-Agent': 'mwb-line-check/1' };
  for (const [value, expected] of [[signature, 200], ['', 401], ['0'.repeat(43) + '=', 401]]) {
    const res = await request(base, '/webhook/line-inbound', { method: 'POST', body, headers: { ...common, 'x-line-signature': value } });
    let parsed; try { parsed = JSON.parse(res.body); } catch { /* 不接受 ngrok 提示頁。 */ }
    if (res.status !== expected || (expected === 200 && (parsed?.ok !== true || parsed.events !== 0))) {
      throw new Error(`LINE 公開端點驗收未通過（預期 ${expected}，收到 ${res.status}）。`);
    }
  }
  console.log('PASS LINE 公開簽章驗收：有效 200、缺少／錯誤 401。');
}

if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) {
  const settings = readSettings();
  Promise.resolve().then(() => {
    if (process.argv[2] !== 'check') throw new Error('用法：node scripts/line.mjs check');
    if (!settings.LINE_CHANNEL_SECRET) throw new Error('請在環境設定 LINE_CHANNEL_SECRET 供舊端點驗簽。');
    return checkLine(settings);
  }).catch(error => { console.error(error.message); process.exitCode = 1; });
}

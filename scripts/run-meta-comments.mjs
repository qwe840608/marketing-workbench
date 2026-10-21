// 留言補抓只喚醒已運行的後端排程器，不建立另一個工作庫或監聽器。
import { createHmac, createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { readSettings, checkBackend, checkEndpoint, request } from './webhooks.mjs';

export async function runComments(mode, settings, io = { checkBackend, checkEndpoint, request }) {
  if (!['once', 'serve'].includes(mode)) throw new Error('用法：node scripts/run-meta-comments.mjs once|serve');
  try {
    await io.checkBackend(settings);
    await io.checkEndpoint('http://127.0.0.1:8000', settings.WEBHOOK_PROBE_SECRET, false);
  } catch { throw new Error('後端排程器 尚未就緒，請執行 scripts/start-all.ps1；禁止啟動留言專用替代服務。'); }
  if (mode === 'serve') {
    console.log('留言續抓由後端排程器 的每分鐘排程負責；此指令不啟動服務，也不佔用 8000。');
    return;
  }
  const path = '/webhook/meta-comments-sync', timestamp = String(Math.floor(Date.now() / 1000));
  const body = JSON.stringify({ requested_only: true });
  const signature = createHmac('sha256', settings.WEBHOOK_PROBE_SECRET).update('POST\n' + path + '\n' + timestamp + '\n' + createHash('sha256').update(body).digest('hex')).digest('hex');
  const result = await io.request('http://127.0.0.1:8000', path, { method: 'POST', body,
    headers: { 'Content-Type': 'application/json', 'x-mwb-sync-time': timestamp, 'x-mwb-sync-signature': signature } });
  if (result.status !== 200) throw new Error(`後端排程器 留言補抓未成功（HTTP ${result.status}）。`);
  console.log('已由後端排程器 執行留言補抓；請使用 meta_backfill.py status 查看進度。');
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  runComments(process.argv[2] || 'once', readSettings()).catch(error => { console.error(error.message); process.exitCode = 1; });
}

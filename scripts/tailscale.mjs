import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { readSettings, saveSettings } from './webhooks.mjs';

export function checkServe(config, dns) {
  if (Object.values(config.AllowFunnel || {}).some(Boolean)) throw new Error('此裝置啟用了公開 Funnel；請先關閉，後台只允許 Tailscale 內部存取。');
  const handler = config.Web?.[`${dns}:443`]?.Handlers?.['/'];
  if (handler && handler.Proxy !== 'http://127.0.0.1:8000') throw new Error('Tailscale 的 443 根路徑已提供其他服務，不會覆寫。');
  if (config.TCP?.['443'] && !config.TCP['443'].HTTPS) throw new Error('Tailscale 443 已用於其他協定，不會覆寫。');
  return Boolean(handler);
}

export function mergedOrigins(settings, dns) {
  if (!/^[a-z0-9-]+\.[a-z0-9-]+\.ts\.net$/.test(dns)) throw new Error('Tailscale 未提供可驗證的裝置 HTTPS 名稱。');
  const origins = (settings.APP_ORIGIN || 'http://127.0.0.1:8000').split(',').map(v => v.trim().replace(/\/$/, ''));
  const hosts = JSON.parse(settings.ALLOWED_HOSTS || '["127.0.0.1","localhost"]');
  if (!Array.isArray(hosts) || hosts.some(v => typeof v !== 'string' || v.includes('*'))) throw new Error('ALLOWED_HOSTS 必須明列主機。');
  return {
    APP_ORIGIN: [...new Set([...origins, `https://${dns}`])].join(','),
    ALLOWED_HOSTS: JSON.stringify([...new Set([...hosts, dns])]),
    SESSION_COOKIE_SECURE: 'true', TAILSCALE_ENABLED: 'true',
  };
}

function cliPath() {
  const installed = join(process.env.ProgramFiles || 'C:/Program Files', 'Tailscale/tailscale.exe');
  return existsSync(installed) ? installed : 'tailscale';
}

function run(args) {
  try { return execFileSync(cliPath(), args, { encoding: 'utf8', timeout: 20000, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] }); }
  catch { throw new Error('Tailscale 指令未完成：請確認已登入；若尚未啟用 HTTPS，請至管理介面 DNS 開啟 HTTPS 憑證後重試。'); }
}

async function main() {
  const mode = process.argv[2] || 'inspect';
  if (!['inspect', 'configure', 'check'].includes(mode)) throw new Error('用法：node scripts/tailscale.mjs inspect|configure|check');
  const status = JSON.parse(run(['status', '--json']));
  if (status.BackendState !== 'Running') {
    if (mode === 'inspect') return console.log(JSON.stringify({ state: status.BackendState }));
    throw new Error('請先在電腦的 Tailscale 登入，再重試。');
  }
  const dns = status.Self?.DNSName?.replace(/\.$/, '');
  const settings = readSettings(), updated = mergedOrigins(settings, dns);
  const exists = checkServe(JSON.parse(run(['serve', 'status', '--json'])), dns);
  if (mode === 'configure') {
    run(['serve', '--bg', '--https=443', '--yes', 'http://127.0.0.1:8000']);
    if (!checkServe(JSON.parse(run(['serve', 'status', '--json'])), dns)) throw new Error('Tailscale 代理未就緒。');
    saveSettings(updated);
    console.log(`Tailscale 內部 HTTPS 已設定：https://${dns}；請重啟後端載入多來源設定。`);
  } else if (mode === 'check') {
    if (!exists) throw new Error('Tailscale 尚未代理到此後端，請先執行 configure。');
    const response = await fetch(`https://${dns}/api/health`, { signal: AbortSignal.timeout(15000) });
    const result = await response.json();
    if (!response.ok || result.status !== 'ok') throw new Error('Tailscale HTTPS 健康檢查失敗。');
    console.log(`Tailscale HTTPS 健康檢查通過：https://${dns}`);
  } else console.log(JSON.stringify({ state: status.BackendState, url: `https://${dns}`, serving: exists }));
}

if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) {
  main().catch(error => {
    console.error(/^[^\n]*[\u4e00-\u9fff]/.test(error.message) ? error.message : 'Tailscale 設定失敗；未輸出可能含帳號資料的原始回應。');
    process.exitCode = 1;
  });
}

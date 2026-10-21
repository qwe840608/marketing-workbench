import { useEffect, useState } from 'react';
import { t } from '../i18n.ts';

// 部署後開著的分頁仍是舊版畫面：定期比對伺服器上 index.html 引用的主程式檔名，不同就提醒重新整理。
const pattern = /\/assets\/index-[A-Za-z0-9_-]+\.js/;
const current = () => document.querySelector<HTMLScriptElement>('script[type="module"][src*="/assets/index-"]')?.getAttribute('src')?.match(pattern)?.[0] ?? null;

export async function latestBuild() {
  const response = await fetch('/', { cache: 'no-store', credentials: 'same-origin' });
  return response.ok ? (await response.text()).match(pattern)?.[0] ?? null : null;
}

export function UpdateNotice() {
  const [stale, setStale] = useState(false);
  useEffect(() => {
    const loaded = current();
    if (!loaded) return; // 開發模式沒有打包檔名。
    let active = true;
    async function check() {
      if (document.hidden) return;
      try { const latest = await latestBuild(); if (active && latest && latest !== loaded) setStale(true); } catch { /* 離線或重啟中，下次再試 */ }
    }
    const timer = window.setInterval(() => void check(), 5 * 60 * 1000);
    const onFocus = () => void check();
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onFocus);
    return () => { active = false; window.clearInterval(timer); window.removeEventListener('focus', onFocus); document.removeEventListener('visibilitychange', onFocus); };
  }, []);
  if (!stale) return null;
  return <div className="update-notice" role="status"><span>{t('工作檯已更新')}</span><button className="secondary" onClick={() => window.location.reload()}>{t('重新整理')}</button></div>;
}

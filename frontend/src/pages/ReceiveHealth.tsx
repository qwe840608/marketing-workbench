import { useEffect, useState } from 'react';
import { api, errorMessage } from '../api';
import { pollWhileVisible } from '../visiblePolling';
import { t } from '../i18n.ts';
import { taipeiDateTime } from '../time.ts';

type Record = { id: number; checked_at: string; healthy: boolean; checks: { scheduler?: boolean; public_probe: boolean; signature_ok: boolean; signature_failures_5m: number }; alert_status: string };
type Health = { interrupted: boolean; message: string; last_ok_at: string | null; checked_at: string | null; stale: boolean; monitor_enabled: boolean; alerts_enabled: boolean; history: Record[] };
type Target = { recipient: string; version: number; source: string; alerts_enabled: boolean };
const date = (v: string | null) => v ? taipeiDateTime(v, { hour12: false }) : t('尚無紀錄');
export function useReceiveHealth() {
  const [health, setHealth] = useState<Health | null>(null);
  useEffect(() => pollWhileVisible(async signal => {
    try {
      const value = await api<Health>('/receive-health', { signal });
      if (!signal.aborted) setHealth(value);
    } catch { /* Preserve the last health result until the next visible refresh. */ }
  }, 60000), []);
  return health;
}
export function ReceiveBanner({ health }: { health: Health | null }) {
  return health?.interrupted ? <aside className="receive-banner" role="alert"><strong>{health.message}</strong><span>{t('上次正常：{time}（台北）', { time: date(health.last_ok_at) })}{health.stale && t(' · 監測紀錄逾時')}</span></aside> : null;
}
export function ReceiveHealthSettings({ canManage }: { canManage: boolean }) {
  const health = useReceiveHealth();
  const [target, setTarget] = useState<Target | null>(null), [notice, setNotice] = useState(''), [busy, setBusy] = useState(false);
  useEffect(() => { if (canManage) api<Target>('/settings/receive-health').then(setTarget).catch(e => setNotice(e.message)); }, [canManage]);
  async function save() {
    if (!target) return;
    setBusy(true); setNotice('');
    try { setTarget(await api<Target>('/settings/receive-health', { method: 'PUT', body: JSON.stringify({ recipient: target.recipient, version: target.version }) })); setNotice(t('系統警示對象已儲存')); }
    catch (e) { setNotice(errorMessage(e, t('儲存失敗'))); }
    finally { setBusy(false); }
  }
  const alerts: { [key: string]: string } = { none: '—', claimed: t('已領取（不重送）'), sent: t('已通知'), failed: t('通知失敗（不重送）'), unknown: t('通知結果不明（不重送）'), unconfigured: t('通知設定未完成'), suppressed: t('驗收期間暫停推播') };
  return <section className="settings-section workspace-subsection receive-health"><h3>{t('收訊健康監測')}</h3>
    <p>{t('後端每 5 分鐘檢查後端排程器、公開簽章探測與驗簽失敗量；同次中斷與恢復各通知一次。啟動後保留 5 分鐘等待完整服務就緒。')}</p>
    <p role="status">{health?.checked_at ? (health.interrupted ? t('收訊通道異常') : t('收訊通道正常')) : t('等待首次檢查')}{t(' · 最近檢查：{time}（台北）', { time: date(health?.checked_at || null) })}</p>
    {health && !health.alerts_enabled && <p className="error">{t('本次服務暫停真實系統警示推播；監測與橫幅仍啟用。')}</p>}
    {target ? <form onSubmit={e => { e.preventDefault(); void save(); }}><label>{t('系統警示對象（LINE 群組、聊天室或用戶 ID）')}<input required pattern="[UCR][a-f0-9]{32}" value={target.recipient} disabled={busy} onChange={e => setTarget({ ...target, recipient: e.target.value })} /></label><p className="muted">{t('使用通知用官方帳號，由後端直接推播。僅管理員可修改。')}</p><button className="primary" disabled={busy}>{t('儲存系統警示對象')}</button></form> : <p className="muted">{t('系統警示對象由管理員設定。')}</p>}
    {notice && <p role="status">{notice}</p>}
    <details><summary>{t('最近 24 小時紀錄（{count} 筆）', { count: health?.history.length || 0 })}</summary>
      <ul className="receive-history">{health?.history.map(r => <li key={r.id}><strong>{date(r.checked_at)} · {r.healthy ? t('正常') : t('異常')}</strong><span>{t('排程器：{scheduler}／公開探測：{probe}／驗簽失敗：{failures} 次', { scheduler: r.checks.scheduler === undefined ? t('舊版紀錄') : r.checks.scheduler ? t('正常') : t('異常'), probe: r.checks.public_probe ? t('正常') : t('異常'), failures: r.checks.signature_failures_5m })}{!r.checks.signature_ok && t('（暴增）')}／{alerts[r.alert_status] || t('尚未確認')}</span></li>)}</ul>
    </details></section>;
}

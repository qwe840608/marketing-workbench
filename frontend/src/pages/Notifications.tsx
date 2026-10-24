import { useEffect, useState } from 'react';
import { api, errorMessage } from '../api';
import { t } from '../i18n.ts';

type Policy = {
  enabled: boolean; urgency_threshold: number; public_reputation_risk_threshold: number;
  version: number; enabled_at: string | null; configured: boolean;
  deliveries: Record<string, number>; backoffice_url: string;
  group_id: string | null; group_name: string; bot_configured: boolean; groups: { id: string; label: string }[];
};
export function Notifications({ brandId, canEdit }: { brandId: string; canEdit: boolean }) {
  const [data, setData] = useState<Policy | null>(null);
  const [error, setError] = useState(''), [notice, setNotice] = useState(''), [busy, setBusy] = useState(false);
  useEffect(() => {
    const c = new AbortController(); setData(null); setError(''); setNotice('');
    if (brandId) api<Policy>('/notify/policy?brand_id=' + brandId, { signal: c.signal }).then(value => { if (!c.signal.aborted) setData(value); }).catch(e => { if (!c.signal.aborted) setError(e.message); });
    return () => c.abort();
  }, [brandId]);
  async function save() {
    if (!data) return;
    setBusy(true); setError(''); setNotice('');
    try {
      setData(await api<Policy>('/notify/policy?brand_id=' + brandId, { method: 'PUT', body: JSON.stringify({ enabled: data.enabled, urgency_threshold: data.urgency_threshold, public_reputation_risk_threshold: data.public_reputation_risk_threshold, version: data.version, group_id: data.group_id, group_name: data.group_name }) }));
      setNotice(t('通知政策已儲存；待送通知會依新門檻重新判斷'));
    } catch (e) { setError(errorMessage(e, t('儲存失敗'))); }
    finally { setBusy(false); }
  }
  return <section className="settings-section workspace-subsection"><h3>{t('LINE 群組通知')}</h3>
    <p className="muted">{t('客訴、高急迫與公開負評立即通知，請至原生 App 處理。')}</p>
    {error && <p className="error" role="alert">{error}</p>}{notice && <p className="success-note notice success" role="status">{notice}</p>}
    {data && <form onSubmit={e => { e.preventDefault(); void save(); }}>
      {!data.configured && <p className="warning-note">{t('尚未設定通知用官方帳號與測試群組，請由管理員完成本機設定。')}</p>}
      <label>{t('此品牌通知群組')}<select disabled={!canEdit || busy} value={data.group_id || ''} onChange={e => setData({ ...data, group_id: e.target.value || null })}><option value="">{t('尚未指定')}</option>{data.groups.map(g => <option key={g.id} value={g.id}>{g.label}</option>)}</select></label>
      <label>{t('群組備註名稱')}<input maxLength={100} disabled={!canEdit || busy} value={data.group_name} onChange={e => setData({ ...data, group_name: e.target.value })} /></label>
      <p className="muted">{t('只列出通知帳號已驗證的群組。新增群組請邀入通知帳號並傳一則訊息，再重新開啟設定。')}</p>
      <label>{t('品牌通知')}<select aria-label={t('品牌通知')} disabled={!canEdit || busy || !data.bot_configured || !data.group_id} value={data.enabled ? 'on' : 'off'} onChange={e => setData({ ...data, enabled: e.target.value === 'on' })}><option value="off">{t('暫停')}</option><option value="on">{t('啟用')}</option></select></label>
      <div className="policy-grid"><label>{t('急迫度通知門檻（0–1）')}<input type="number" min="0" max="1" step="0.05" required disabled={!canEdit || busy} value={data.urgency_threshold} onChange={e => setData({ ...data, urgency_threshold: Number(e.target.value) })} /></label><label>{t('公開聲譽風險門檻（0–1）')}<input type="number" min="0" max="1" step="0.05" required disabled={!canEdit || busy} value={data.public_reputation_risk_threshold} onChange={e => setData({ ...data, public_reputation_risk_threshold: Number(e.target.value) })} /></label></div>
      <p className="muted">{t('公開留言的客訴、急迫度或聲譽風險達門檻時，立即通知。垃圾與釣魚留言、貼圖不通知。啟用時從新留言開始，歷史資料不補發。')}</p>
      <p>{t('LINE 已受理 {sent} 次 · 處理中 {pending} 次 · 失敗 {failed} 次', { sent: data.deliveries.sent || 0, pending: (data.deliveries.pending || 0) + (data.deliveries.sending || 0), failed: data.deliveries.failed || 0 })}</p>
      <p className="muted">{t('「已受理」表示 LINE API 接受請求，是否收到請以測試群組實收確認。')}</p>
      {canEdit && <button className="primary" disabled={busy}>{t('儲存通知政策')}</button>}
    </form>}
  </section>;
}

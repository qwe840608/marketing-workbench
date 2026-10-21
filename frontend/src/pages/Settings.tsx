import { BrandingSettings } from './BrandingSettings';
import { IdeationSettings } from './Ideation';
import { CsvImport } from './CsvImport';
import { ReceiveHealthSettings } from './ReceiveHealth';
import { useEffect, useState } from 'react';
import { api } from '../api';
import type { Brand } from '../api';
import { Notifications } from './Notifications';
import { AutostartSettings } from './AutostartSettings';
import { ObsidianSettings } from './ObsidianSettings';
import { NeedBrand } from './NeedBrand';
import { pollWhileVisible } from '../visiblePolling';
import { locale, t } from '../i18n.ts';

type ExportSettings = { version: number; export_root: string; engine_available: boolean };
type ExportStatus = { last_success_at: string | null; error: string | null; files: number; pending: number; enabled: boolean };
export function SettingsPage({ brand, brands, role }: { brand: string; brands: Brand[]; role: string }) {
  const brandId = brand || String(brands[0]?.id || ''), noBrand = brands.length > 1 && !brand;
  const [exports, setExports] = useState<ExportSettings | null>(null);
  const [error, setError] = useState(''), [notice, setNotice] = useState(''), [busy, setBusy] = useState(false);
  const [templateVersion, setTemplateVersion] = useState(0);
  const canEdit = role !== 'viewer';
  const [exportStatus, setExportStatus] = useState<ExportStatus | null>(null);
  useEffect(() => {
    if (role !== 'admin') return;
    // 分頁隱藏時不輪詢匯出狀態。
    return pollWhileVisible(signal => api<ExportStatus>('/exports/status', { signal }).then(value => { if (!signal.aborted) setExportStatus(value); }).catch(() => {}), 5000);
  }, [role]);
  async function rebuild() {
    setBusy(true); setError('');
    try { setExportStatus(await api<ExportStatus>('/exports/sync', { method: 'POST' })); }
    catch (e) { setError(e instanceof Error ? e.message : t('匯出失敗')); }
    finally { setBusy(false); }
  }
  useEffect(() => {
    const c = new AbortController();
    if (role === 'admin') api<ExportSettings>('/settings/export', { signal: c.signal }).then(value => { if (!c.signal.aborted) setExports(value); }).catch(e => { if (!c.signal.aborted) setError(e.message); });
    return () => c.abort();
  }, [role]);
  async function save() {
    setBusy(true); setError(''); setNotice('');
    try {
        const value = await api<ExportSettings>('/settings/export', { method: 'PUT', body: JSON.stringify({ version: exports!.version, export_root: exports!.export_root }) });
        setExports(value); setNotice(t('匯出目錄已儲存，寫入檢查通過'));

    } catch (e) { setError(e instanceof Error ? e.message : t('設定未儲存')); }
    finally { setBusy(false); }
  }
  return <section className="settings-page general-settings">
    {error && <p className="error" role="alert">{error}</p>}{notice && <p className="success-note notice success" role="status">{notice}</p>}
    {noBrand && <NeedBrand />}
    {!noBrand && <details className="workspace-group section-card" data-group="brand"><summary>{t('品牌範本')}</summary><div className="workspace-group-content">
      <BrandingSettings key={brandId} brandId={brandId} role={role} onApplied={() => setTemplateVersion(v => v + 1)} />
    </div></details>}
    {!noBrand && <details className="workspace-group section-card" data-group="ideation"><summary>{t('主題發想')}</summary><div className="workspace-group-content">
    <IdeationSettings key={"ideation-" + brandId + templateVersion} brandId={brandId} canEdit={canEdit} />
    </div></details>}
    <details className="workspace-group section-card" data-group="data"><summary>{t('資料')}</summary><div className="workspace-group-content">
    {!noBrand && <CsvImport key={'csv-' + brandId} brandId={brandId} canEdit={canEdit} />}
    <ObsidianSettings role={role} />
    <section className="settings-section workspace-subsection"><h3>{t('匯出資料夾')}</h3><p className="muted">{t('實際貼文與用戶紀錄會在資料變更後 30 秒內更新 Markdown。Word 請至品牌儀表板下載，同時保存到此目錄。')}</p>
      {exports ? <form onSubmit={e => { e.preventDefault(); void save(); }}><label>{t('匯出目錄')}<input required maxLength={500} disabled={busy} value={exports.export_root} onChange={e => setExports({ ...exports, export_root: e.target.value })} /></label><button className="primary" disabled={busy}>{t('儲存並檢查寫入權限')}</button></form> : role !== 'admin' && <p>{t('請由管理員設定共用匯出位置。')}</p>}
      {exportStatus && <div className="export-status"><p>{t('已匯出 {files} 份 Markdown · 等待更新 {pending} 份', { files: exportStatus.files, pending: exportStatus.pending })}</p><p className="muted">{exportStatus.last_success_at ? t('最近完成：{time}（台北）', { time: new Date(exportStatus.last_success_at).toLocaleString(locale(), { timeZone: 'Asia/Taipei' }) }) : t('等待首次匯出')}{!exportStatus.enabled && t(' · 自動匯出已停用')}</p>{exportStatus.error && <p className="error" role="alert">{exportStatus.error}</p>}<button className="secondary" disabled={busy} onClick={rebuild}>{t('立即同步 Markdown')}</button></div>}
    </section>
    </div></details>
    {!noBrand && <details className="workspace-group section-card" data-group="notifications"><summary>{t('通知')}</summary><div className="workspace-group-content">
      <Notifications key={'notify-' + brandId} brandId={brandId} canEdit={canEdit} />
    </div></details>}
    <details className="workspace-group section-card" data-group="system"><summary>{t('系統')}</summary><div className="workspace-group-content">
      <AutostartSettings role={role} />
      <ReceiveHealthSettings role={role} />
    </div></details>
  </section>;
}

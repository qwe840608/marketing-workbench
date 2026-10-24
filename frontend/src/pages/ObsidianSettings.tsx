import { useEffect, useState } from 'react';
import { api, errorMessage } from '../api';
import { t } from '../i18n.ts';

type Config = { obsidian_root: string; version: number };
export function ObsidianSettings({ canManage }: { canManage: boolean }) {
  const [config, setConfig] = useState<Config | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  useEffect(() => {
    if (!canManage) return;
    const controller = new AbortController();
    api<Config>('/settings/obsidian', { signal: controller.signal }).then(setConfig).catch(e => {
      if (!controller.signal.aborted) setError(e.message);
    });
    return () => controller.abort();
  }, [canManage]);
  async function execute(sync: boolean) {
    setBusy(true); setError(''); setNotice('');
    try {
      if (sync) {
        const result = await api<{ ok: boolean; written: number; error: string | null }>('/exports/obsidian/sync', { method: 'POST' });
        if (!result.ok) throw new Error(result.error || t('同步失敗'));
        setNotice(t('已同步 {count} 份檔案', { count: result.written }));
      } else if (config) {
        // 只送可寫欄位；讀取回應另含唯讀狀態，後端 extra=forbid 會回 422。
        setConfig(await api<Config>('/settings/obsidian', { method: 'PUT', body: JSON.stringify({ obsidian_root: config.obsidian_root, version: config.version }) }));
        setNotice(t('已儲存，寫入檢查通過'));
      }
    } catch (e) { setError(errorMessage(e, t('操作失敗'))); }
    finally { setBusy(false); }
  }
  return <section className="settings-section workspace-subsection obsidian-settings" aria-label={t('Obsidian 留言資料夾')} aria-busy={busy}>
    <h3>{t('Obsidian 留言資料夾')}</h3>
    {error && <p className="error" role="alert">{error}</p>}{notice && <p className="success-note notice success" role="status">{notice}</p>}
    {canManage ? <form onSubmit={e => { e.preventDefault(); void execute(false); }}>
      <label>{t('Obsidian 留言資料夾')}<input required maxLength={500} disabled={busy || !config} value={config?.obsidian_root || ''} onChange={e => config && setConfig({ ...config, obsidian_root: e.target.value })} /></label>
      <div className="obsidian-actions"><button className="primary" disabled={busy || !config}>{t('儲存 Obsidian 資料夾')}</button><button className="secondary" type="button" disabled={busy || !config} onClick={() => void execute(true)}>{t('立即同步到 Obsidian')}</button></div>
    </form> : <p className="muted">{t('請由管理員設定共用留言資料夾。')}</p>}
  </section>;
}

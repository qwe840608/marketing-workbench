import { useEffect, useState } from 'react';
import { api } from '../api';
import { aiErrorMessage } from '../aiErrors';
import { t } from '../i18n.ts';

type Autostart = { enabled: boolean; supported: boolean; task_name: string; code: string | null };

export function AutostartSettings({ canManage }: { canManage: boolean }) {
  const [state, setState] = useState<Autostart | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  async function read(signal?: AbortSignal) {
    return canManage
      ? api<Autostart>('/workspace/autostart', { signal })
      : (await api<{ autostart: Autostart }>('/workspace/status', { signal })).autostart;
  }
  useEffect(() => {
    const controller = new AbortController();
    setState(null); setError('');
    void read(controller.signal).then(value => {
      if (!controller.signal.aborted) { setState(value); setError(value.supported && value.code ? value.code : ''); }
    }).catch(() => { if (!controller.signal.aborted) setError('autostart_failed'); });
    return () => controller.abort();
  }, [canManage]); // eslint-disable-line react-hooks/exhaustive-deps
  async function toggle(enabled: boolean) {
    setBusy(true); setError('');
    try {
      const value = await api<Autostart>('/workspace/autostart', { method: 'PUT', body: JSON.stringify({ enabled }) });
      setState(value); setError(value.supported && value.code ? value.code : '');
    } catch {
      setError('autostart_failed');
      try { setState(await read()); } catch { setState(null); }
    } finally { setBusy(false); }
  }
  return <section className="settings-section workspace-subsection autostart-settings" aria-labelledby="autostart-title" aria-busy={busy}>
    <h3 id="autostart-title">{t('開機自動啟動')}</h3>
    <div className="autostart-row"><label><input type="checkbox" checked={state?.enabled ?? false}
      disabled={!canManage || busy || !state?.supported || !!state.code}
      onChange={e => void toggle(e.target.checked)} />{t('登入 Windows 後自動啟動工作檯')}</label>
      <span className="muted" role="status">{busy ? t('處理中…') : state && !state.supported ? t('僅支援 Windows') : !state ? t('狀態尚未取得') : ''}</span></div>
    <p className="muted">{t('電腦重新開機後不用手動啟動；需要先登入 Windows 帳號')}</p>
    {error && <p className="error" role="alert">{aiErrorMessage(error)}</p>}
  </section>;
}

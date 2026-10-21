import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type { ReactNode } from 'react';
import { locale, t } from '../i18n.ts';

const providers = { openai: 'OpenAI', gemini: 'Gemini', anthropic: 'Anthropic' };
const hints: Record<string, string> = { openai: 'sk-proj-…', gemini: 'AIza…', anthropic: 'sk-ant-…', jev: 'TypeSafe API key' };
type KeyInfo = { provider: string; source: string; mask: string | null; version: number; error: string | null };
type Verified = { receipt: string | null; mask: string | null };

export function APIKeys({ onChange, fallback }: { onChange: () => void; fallback: (provider: string) => ReactNode }) {
  const [rows, setRows] = useState<KeyInfo[]>([]), [provider, setProvider] = useState('openai');
  const [verified, setVerified] = useState<Verified | null>(null), [busy, setBusy] = useState(false);
  const [error, setError] = useState(''), [notice, setNotice] = useState('');
  // The password input is uncontrolled: plaintext is never copied into React or browser storage.
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { const c = new AbortController(); api<KeyInfo[]>('/ai/keys', { signal: c.signal }).then(setRows).catch(e => { if (!c.signal.aborted) setError(e.message); }); return () => c.abort(); }, []);
  const active = rows.find(row => row.provider === provider);
  async function perform(action: 'test' | 'save' | 'delete') {
    setBusy(true); setError(''); setNotice('');
    try {
      if (action === 'test') {
        const pending = api<Verified>('/ai/keys/' + provider + '/test', { method: 'POST', body: JSON.stringify(input.current?.value ? { key: input.current.value } : {}) });
        if (input.current) input.current.value = '';
        setVerified(null);
        const value = await pending; setVerified(value);
        setNotice(value.receipt ? t('連線成功。請於 5 分鐘內儲存這把金鑰。') : t('目前使用的金鑰連線成功。'));
      } else {
        const value = await api<KeyInfo[]>('/ai/keys/' + provider + (action === 'delete' ? '?version=' + active!.version : ''), { method: action === 'delete' ? 'DELETE' : 'PUT', ...(action === 'save' ? { body: JSON.stringify({ receipt: verified!.receipt }) } : {}) });
        setRows(value); setVerified(null); onChange();
        setNotice(action === 'delete' ? t('UI 金鑰已刪除；未設定時會使用 .env。') : t('金鑰已加密儲存。'));
      }
    } catch (e) { setError(e instanceof Error ? e.message : t('金鑰操作未完成')); }
    finally { setBusy(false); }
  }
  return <section className="settings-section section-card ai-keys" aria-label={t('API 金鑰')}>
    <div className="card-title"><h2>{t('API 金鑰')}</h2><span className="readonly-label">{t('全系統共用 · 管理員')}</span></div>
    <p className="muted">{t('每家供應商一把，費用依品牌統計。金鑰加密保存，只能替換，不能讀回。')}</p>
    <div className="key-overview">{rows.filter(row => row.provider in providers).map(row => <div key={row.provider}><strong>{providers[row.provider as keyof typeof providers]}</strong><span className={'key-source status-badge ' + (row.source === 'UI' ? 'ready' : 'neutral') + (row.source === '未設定' ? ' unset' : '')}>{row.source === '未設定' ? t('未設定') : row.source}</span><code>{row.mask || row.error || t('尚無金鑰')}</code>{fallback(row.provider)}</div>)}</div>
    <div className="policy-grid"><label>{t('金鑰供應商')}<select value={provider} disabled={busy} onChange={e => { setProvider(e.target.value); setVerified(null); setError(''); setNotice(''); if (input.current) input.current.value = ''; }}>{Object.entries(providers).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>{t('新增或替換金鑰')}<input ref={input} type="password" autoComplete="new-password" spellCheck={false} maxLength={512} disabled={busy} placeholder={hints[provider]} onChange={() => { setVerified(null); setNotice(''); }} /></label></div>
    <p className="muted">{t('留空可測試目前使用的金鑰。輸入後按測試連線，欄位即清空；通過後才可儲存。')}</p>
    {verified?.receipt && <p>{t('待儲存：')}<code>{verified.mask}</code></p>}
    <div className="ai-actions"><button className="secondary" disabled={busy} onClick={() => void perform('test')}>{busy ? t('處理中…') : t('測試連線')}</button><button className="primary" disabled={busy || !verified?.receipt} onClick={() => void perform('save')}>{t('儲存已驗證金鑰')}</button>{active?.source === 'UI' && <button className="primary danger" disabled={busy} onClick={() => void perform('delete')}>{t('刪除 UI 金鑰')}</button>}</div>
    {error && <p className="error" role="alert">{error}</p>}{notice && <p className="success-note notice success" role="status">{notice}</p>}
  </section>;
}

type Version = { revision: number; content: string; actor: string; created_at: string; restored_from: number | null; diff: string };
type History = { revision: number; versions: Version[] };
function PromptEditor({ brandId, canEdit }: { brandId?: string; canEdit: boolean }) {
  const [history, setHistory] = useState<History | null>(null), [content, setContent] = useState('');
  const [selected, setSelected] = useState<number | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const query = brandId ? '?brand_id=' + brandId : '';
  function accept(value: History) { setHistory(value); setContent(value.versions[0]?.content || ''); setSelected(value.revision || null); }
  useEffect(() => { const c = new AbortController(); api<History>('/ai/prompts' + query, { signal: c.signal }).then(value => { if (!c.signal.aborted) accept(value); }).catch(e => { if (!c.signal.aborted) setError(e.message); }); return () => c.abort(); }, [query]);
  async function save(restore: boolean) {
    setBusy(true); setError(''); setNotice('');
    try { accept(await api<History>('/ai/prompts' + (restore ? '/restore' : '') + query, { method: restore ? 'POST' : 'PUT', body: JSON.stringify(restore ? { revision: history!.revision, restore_revision: selected } : { revision: history!.revision, content }) })); setNotice(restore ? t('已還原為新的版本，既有歷史保留。') : t('新版本已儲存。')); }
    catch (e) { setError(e instanceof Error ? e.message : t('品牌說明未儲存')); }
    finally { setBusy(false); }
  }
  const version = history?.versions.find(v => v.revision === selected);
  const title = brandId ? t('品牌說明') : t('工作區共用說明');
  return <section className="settings-section section-card prompt-editor" aria-label={title}>
    <div className="card-title"><h3>{title}</h3><span>{brandId ? t('第二層 · 品牌專用') : t('第一層 · 所有品牌共用')}</span></div>
    {history ? <><label>{t('{title}內容', { title })}<textarea rows={6} value={content} maxLength={12000} disabled={!canEdit || busy} onChange={e => setContent(e.target.value)} /></label>
      <div className="ai-actions"><span className="muted">{t('目前版本 {revision}', { revision: history.revision || t('尚未建立') })}</span>{canEdit ? <button className="primary" disabled={busy || content === (history.versions[0]?.content || '')} onClick={() => void save(false)}>{t('儲存新版本')}</button> : <span className="muted">{brandId ? t('此帳號僅能檢視') : t('僅管理員可修改')}</span>}</div>
      {!!history.versions.length && <details className="prompt-history"><summary>{t('版本紀錄與差異')}</summary>
        <label>{t('檢視版本')}<select disabled={busy} value={selected || ''} onChange={e => setSelected(Number(e.target.value))}>{history.versions.map(v => <option key={v.revision} value={v.revision}>{t('版本 {revision} · {actor} · {time}', { revision: v.revision, actor: v.actor, time: new Date(v.created_at).toLocaleString(locale(), { timeZone: 'Asia/Taipei' }) })}</option>)}</select></label>
        {version && <><p className="muted">{t('修改人：{actor} · 台北時間 {time}', { actor: version.actor, time: new Date(version.created_at).toLocaleString(locale(), { timeZone: 'Asia/Taipei' }) })}{version.restored_from && t(' · 還原自版本 {revision}', { revision: version.restored_from })}</p><h4>{t('此版本內容')}</h4><pre>{version.content || t('（空白）')}</pre><h4>{t('與前一版本的差異')}</h4><pre className="prompt-diff">{version.diff || t('內容相同')}</pre>{canEdit && <button className="secondary" disabled={busy || selected === history.revision} onClick={() => void save(true)}>{t('還原此版本')}</button>}</>}
      </details>}</> : !error && <p>{t('正在讀取品牌說明…')}</p>}
    {error && <p className="error" role="alert">{error}</p>}{notice && <p className="success-note notice success" role="status">{notice}</p>}
  </section>;
}

export function PromptSettings({ brandId, role }: { brandId: string; role: string }) {
  return <section className="prompt-settings"><h2>{t('品牌說明')}</h2><p className="muted">{t('AI 產生主題與腳本時參考的品牌背景與語氣')}</p>
    <PromptEditor canEdit={role === 'admin'} /><PromptEditor key={brandId} brandId={brandId} canEdit={role === 'admin' || role === 'marketing'} />
  </section>;
}

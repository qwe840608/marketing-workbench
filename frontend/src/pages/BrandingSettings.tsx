import { useEffect, useState } from 'react';
import { api } from '../api';
import { useWorkspace } from '../branding';
import { t, tx } from '../i18n.ts';
type Rules = { forbidden_phrases: string[] };
type Preview = { before: Record<string, unknown>; after: Record<string, unknown>; token: string; template: string };
const labels: Record<string, string> = { topics: tx('list', '主題'), forbidden_phrases: t('禁語'), brand_prompt: t('品牌 prompt') };
const show = (value: unknown): string => Array.isArray(value) ? (value.length ? value.map(v => typeof v === 'object' ? JSON.stringify(v) : String(v)).join(t('、')) : t('空白')) : String(value || t('空白'));
export function BrandingSettings({ brandId, role, onApplied }: { brandId: string; role: string; onApplied: () => void }) {
  const { identity, update } = useWorkspace();
  const [name, setName] = useState(identity.name);
  const [templates, setTemplates] = useState<{ id: string; name: string }[]>([]);
  const [template, setTemplate] = useState('creator'), [preview, setPreview] = useState<Preview | null>(null);
  const [rules, setRules] = useState<Rules>({ forbidden_phrases: [] }), [phrases, setPhrases] = useState('');
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  useEffect(() => setName(identity.name), [identity.name]);
  useEffect(() => {
    const c = new AbortController(); setPreview(null); setNotice('');
    if (role === 'admin') api<typeof templates>('/settings/templates', { signal: c.signal }).then(setTemplates).catch(e => { if (!c.signal.aborted) setError(e.message); });
    if (brandId) api<Rules>('/settings/brand-rules?brand_id=' + brandId, { signal: c.signal }).then(v => { setRules(v); setPhrases(v.forbidden_phrases.join('\n')); }).catch(e => { if (!c.signal.aborted) setError(e.message); });
    return () => c.abort();
  }, [brandId, role]);
  async function run(task: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('');
    try { await task(); } catch (e) { setError(e instanceof Error ? e.message : t('操作失敗')); } finally { setBusy(false); }
  }
  return <section className="settings-section workspace-subsection branding-settings">
    <h3>{t('工作區名稱與品牌範本')}</h3>
    {error && <p className="error" role="alert">{error}</p>}{notice && <p className="notice success" role="status">{notice}</p>}
    {role === 'admin' && <form className="workspace-subsection" onSubmit={e => { e.preventDefault(); void run(async () => { update(await api('/workspace/identity', { method: 'PUT', body: JSON.stringify({ name, version: identity.version }) })); setNotice(t('工作區名稱已儲存')); }); }}>
      <label>{t('產品顯示名稱')}<input required maxLength={60} value={name} disabled={busy} onChange={e => setName(e.target.value)} /></label>
      <button disabled={busy} className="primary">{t('儲存工作區名稱')}</button>
    </form>}
    <p className="muted">{t('以下設定套用至上方選擇的品牌。套用範本會取代主題、禁語及品牌 prompt；例會時間保持原設定。')}</p>
    {role === 'admin' && brandId && <div className="workspace-subsection">
      <label>{t('品牌範本')}<select value={template} disabled={busy} onChange={e => { setTemplate(e.target.value); setPreview(null); }}>{templates.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <button className="secondary" disabled={busy} onClick={() => void run(async () => { setPreview(await api<Preview>('/settings/templates/' + template + '/preview?brand_id=' + brandId)); })}>{t('預覽差異')}</button>
      {preview && <div aria-label={t('範本差異')}>{Object.keys(labels).map(key => <div key={key}><h3>{labels[key]}</h3><p>{t('目前：{value}', { value: show(preview.before[key]) })}</p><p>{t('套用後：{value}', { value: show(preview.after[key]) })}</p></div>)}
        <button className="primary" disabled={busy} onClick={() => void run(async () => {
          await api('/settings/templates/apply?brand_id=' + brandId, { method: 'POST', body: JSON.stringify({ template: preview.template, token: preview.token }) });
          setPreview(null); const v = await api<Rules>('/settings/brand-rules?brand_id=' + brandId); setRules(v); setPhrases(v.forbidden_phrases.join('\n')); setNotice(t('範本已套用並記錄稽核')); onApplied();
        })}>{t('確認套用此差異')}</button><button className="secondary" disabled={busy} onClick={() => setPreview(null)}>{t('取消')}</button>
      </div>}
    </div>}
    {brandId && <form className="workspace-subsection" onSubmit={e => { e.preventDefault(); void run(async () => {
      const value = await api<Rules>('/settings/brand-rules?brand_id=' + brandId, { method: 'PUT', body: JSON.stringify({ before: rules, forbidden_phrases: phrases.split('\n').map(p => p.trim()).filter(Boolean) }) });
      setRules(value); setPreview(null); setNotice(t('品牌禁語已儲存'));
    }); }}><label>{t('品牌禁語（每行一項）')}<textarea rows={4} disabled={busy || role === 'viewer'} value={phrases} onChange={e => setPhrases(e.target.value)} /></label>
      {role !== 'viewer' && <button className="primary" disabled={busy}>{t('儲存品牌禁語')}</button>}
    </form>}
  </section>;
}

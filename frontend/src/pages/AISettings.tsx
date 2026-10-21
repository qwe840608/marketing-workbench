import { aiErrorMessage } from '../aiErrors';
import { executionLabel, isRetiredProvider } from '../providers';
import { APISetupGuide } from './APISetupGuide';
import { APIKeys, PromptSettings } from './AIConfiguration';
import { useEffect, useState } from 'react';
import { api } from '../api';
import type { Brand } from '../api';
import { t } from '../i18n.ts';
const labels: Record<string, string> = { defaultChoice: t('預設 AI（主題發想）'), gemini_api: 'Gemini API', openai_api: 'OpenAI API', anthropic_api: 'Anthropic API' };
type Option = { provider: string; model: string; available: boolean; reason: string | null };
type Config = { default_provider: string | null; gemini_fallback_model: string; openai_fallback_model: string; anthropic_fallback_model: string; manual_provider: string | null; background_provider: string | null; monthly_budget_usd: number | null; version: number };
type Run = { id: number; task: string; provider: string; model: string; tokens_in: number | null; tokens_out: number | null; cost_usd: string | null; ok: boolean; error: string | null; duration_ms: number | null };
type Settings = { config: Config; options: Option[]; budget: { estimated_usd: number; warning: boolean; unknown_cost_runs: number }; runs: Run[] };
const taskLabels: Record<string, string> = { classify: t('訊息分流'), classification: t('訊息分流'), ideation: t('主題發想'), script: t('腳本'), video_script: t('腳本'), script_review: t('腳本檢查'), publish_caption: t('發佈文案') };

export function AISettingsPage({ brands, brand, canEdit, role }: { brands: Brand[]; brand: string; canEdit: boolean; role: string }) {
  const tabs = [{ id: 'basic', label: t('基本') }, { id: 'brand', label: t('品牌說明') }, { id: 'keys', label: t('AI 金鑰') }];
  const readTab = () => {
    const value = new URLSearchParams(location.search).get('ai_tab') || '';
    return ({ usage: 'basic', prompt: 'brand', keys: 'keys', basic: 'basic', brand: 'brand', advanced: 'keys' } as Record<string, string>)[value] || 'basic';
  };
  const [tab, setTab] = useState<string>(readTab);
  const activeTab = tab;
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    params.set('ai_tab', activeTab);
    history.replaceState(history.state, '', location.pathname + '?' + params + location.hash);
  }, [activeTab]);
  useEffect(() => {
    const restore = () => setTab(readTab());
    window.addEventListener('popstate', restore);
    return () => window.removeEventListener('popstate', restore);
  }, [role]);
  const [keyRevision, setKeyRevision] = useState(0);
  const brandId = brand || String(brands[0]?.id || '');
  const [data, setData] = useState<Settings | null>(null), [config, setConfig] = useState<Config | null>(null), [error, setError] = useState(''), [notice, setNotice] = useState(''), [busy, setBusy] = useState(false);
  useEffect(() => {
    setData(null); setConfig(null); setError(''); setNotice(''); if (!brandId) return;
    const c = new AbortController(); api<Settings>('/ai/settings?brand_id=' + brandId, { signal: c.signal }).then(value => { if (!c.signal.aborted) { setData(value); setConfig(value.config); } }).catch(e => { if (!c.signal.aborted) setError(e.message); }); return () => c.abort();
  }, [brandId, keyRevision]);
  async function save() {
    setBusy(true); setError(''); setNotice('');
    try { const value = await api<Settings>('/ai/settings?brand_id=' + brandId, { method: 'PUT', body: JSON.stringify(config) }); setData(value); setConfig(value.config); setNotice(t('AI 設定已儲存')); }
    catch (e) { setError(e instanceof Error ? e.message : t('儲存失敗')); } finally { setBusy(false); }
  }
  function fallback(name: string) {
    if (!config || !['gemini', 'openai', 'anthropic'].includes(name)) return null;
    const field = `${name}_fallback_model` as 'gemini_fallback_model' | 'openai_fallback_model' | 'anthropic_fallback_model';
    return <label className="provider-fallback">{t('{name} 備援模型', { name: labels[name + '_api'] })}<input disabled={!canEdit || busy} value={config[field] ?? ''} maxLength={120} placeholder={t('留空表示不使用備援')} onChange={e => setConfig({ ...config, [field]: e.target.value })} /></label>;
  }
  return <section className="settings-page ai-settings-page">
    <div className="ai-tabs segmented-control compact" role="tablist" aria-label={t('AI 設定')}>
      {tabs.map((item, index) => <button key={item.id} type="button" role="tab" id={'ai-tab-' + item.id} aria-selected={activeTab === item.id} aria-controls={'ai-panel-' + item.id} tabIndex={activeTab === item.id ? 0 : -1} onClick={() => setTab(item.id)} onKeyDown={event => {
        const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : null;
        if (next === null) return;
        event.preventDefault(); setTab(tabs[next].id);
        document.getElementById('ai-tab-' + tabs[next].id)?.focus();
      }}>{item.label}</button>)}
    </div>
    <div role="tabpanel" id="ai-panel-basic" aria-labelledby="ai-tab-basic" hidden={activeTab !== 'basic'} tabIndex={0}>
    {error && <p className="error" role="alert" title={error}>{aiErrorMessage(error)}</p>}{notice && <p role="status">{notice}</p>}
    {data && config && <><section className="section-card ai-basic-card"><div className="policy-grid">
      <label>{t('預設 AI（主題發想）')}<select aria-label={labels.defaultChoice} value={config.default_provider ?? ''} disabled={!canEdit || busy} onChange={e => setConfig({ ...config, default_provider: e.target.value })}><option value="">{t('請選擇 API 供應者')}</option>{data.options.map(option => <option key={option.provider} value={option.provider} disabled={!option.available}>{labels[option.provider]}</option>)}</select></label>
      <label>{t('每月 API 預算（美元）')}<input type="number" min="0.01" max="100000" step="0.01" disabled={!canEdit || busy} value={config.monthly_budget_usd ?? ''} placeholder={t('尚未設定')} onChange={e => setConfig({ ...config, monthly_budget_usd: e.target.value ? Number(e.target.value) : null })} /></label></div>
      {canEdit && <div className="action-row"><button className="primary" disabled={busy} onClick={() => void save()}>{t('儲存 AI 設定')}</button></div>}
      </section><section className="section-card ai-usage-card"><h2>{t('本月用量')}</h2><p>{t('本月已知估算：US$ {usd} · 未能估價的呼叫：{count} 次', { usd: data.budget.estimated_usd.toFixed(6), count: data.budget.unknown_cost_runs })}</p>
      {data.budget.warning && <p className="error" role="alert">{t('API 估算費用已達預算 80%，請確認用量。')}</p>}
      <div className="usage-table list-box"><table><thead><tr><th>{t('任務／供應商')}</th><th>{t('模型')}</th><th>{t('輸入／輸出')}</th><th>{t('耗時')}</th><th>{t('美元估算')}</th><th>{t('結果')}</th></tr></thead><tbody>{data.runs.length === 0 && <tr><td colSpan={6} className="list-empty">{t('尚無用量資料')}</td></tr>}{data.runs.map(r => <tr key={r.id}><td data-label={t('任務／供應商')}>{taskLabels[r.task] || t('其他任務')} / {executionLabel(r.provider)}</td><td data-label={t('模型')}>{r.model}</td><td data-label={t('輸入／輸出')}>{isRetiredProvider(r.provider) && r.tokens_in == null && r.tokens_out == null ? t('未回報') : `${r.tokens_in ?? (isRetiredProvider(r.provider) ? t('未回報') : '—')} / ${r.tokens_out ?? (isRetiredProvider(r.provider) ? t('未回報') : '—')}`}</td><td data-label={t('耗時')}>{t('{ms} 毫秒', { ms: r.duration_ms ?? '—' })}</td><td data-label={t('美元估算')}>{isRetiredProvider(r.provider) ? t('訂閱') : (r.cost_usd ?? '—')}</td><td data-label={t('結果')}>{r.ok ? t('完成') : t('未完成')}{r.error && <small title={r.error}>{aiErrorMessage(r.error, r.provider)}</small>}</td></tr>)}</tbody></table></div>
      <p className="muted">{t('費用以已知 Standard 付費牌價估算，含思考 token；不折抵免費額度，未知單價保留空值。實際帳單以供應商為準。月上限尚未設定時不會限制 AI 呼叫。')}</p></section></>}
    </div>
    <div role="tabpanel" id="ai-panel-brand" aria-labelledby="ai-tab-brand" hidden={activeTab !== 'brand'} tabIndex={0}>
      {brandId && <PromptSettings key={brandId} brandId={brandId} role={role} />}
    </div>
    <div role="tabpanel" id="ai-panel-keys" aria-labelledby="ai-tab-keys" hidden={activeTab !== 'keys'} tabIndex={0}>
      {data && !data.options.some(o => o.available) && <APISetupGuide />}
      {error && <p className="error" role="alert">{aiErrorMessage(error)}</p>}{notice && <p role="status">{notice}</p>}
      {role === 'admin' ? <APIKeys fallback={fallback} onChange={() => setKeyRevision(v => v + 1)} /> : <section className="settings-section section-card"><div className="key-overview">{['gemini', 'openai', 'anthropic'].map(name => <div key={name}><strong>{labels[name + '_api']}</strong>{fallback(name)}</div>)}</div></section>}
      {config && canEdit && <div className="action-row"><button className="primary" disabled={busy} onClick={() => void save()}>{t('儲存 AI 設定')}</button></div>}
    </div>
  </section>;
}

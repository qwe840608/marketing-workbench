import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { api } from '../api';
import { ConfirmDialog } from './ConfirmDialog';
import { MemberDialog } from './Members';
import './agent-auth.css';
import { locale, t } from '../i18n.ts';

type Connection = { id: number; name: string; kind: 'oauth' | 'token'; created_at: string; last_used_at: string; expires_at: string };
const time = (value: string) => new Date(value).toLocaleString(locale(), { timeZone: 'Asia/Taipei' });

function CreateConnection({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [token, setToken] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState(''), [copied, setCopied] = useState(false);
  // 建立後表單換成權杖畫面，原本聚焦的按鈕消失會讓焦點掉到 body，Esc 與 Tab 循環失效；改聚焦「複製」。
  const copyButton = useRef<HTMLButtonElement>(null);
  useEffect(() => { if (token) copyButton.current?.focus(); }, [token]);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const values = new FormData(event.currentTarget); setBusy(true); setError('');
    try { const result = await api<{ token: string }>('/agent/connections', { method: 'POST', body: JSON.stringify({ name: values.get('name') }) }); setToken(result.token); onCreated(); }
    catch (e) { setError(e instanceof Error ? e.message : t('建立失敗')); }
    finally { setBusy(false); }
  }
  function close() { if (!busy) { setToken(''); onClose(); } }
  return <MemberDialog title={token ? t('連線權杖') : t('建立連線權杖')} onClose={close}>
    {token ? <><div className="agent-token-row"><code className="agent-token">{token}</code><button ref={copyButton} className="secondary" onClick={async () => { try { await navigator.clipboard.writeText(token); setCopied(true); } catch { setError(t('無法複製，請手動選取權杖')); } }}>{copied ? t('已複製') : t('複製')}</button></div><p className="muted">{t('只會顯示這一次')}</p><div className="action-row"><button className="secondary" onClick={close}>{t('關閉')}</button></div></> :
      <form className="member-form" onSubmit={submit}><label>{t('連線名稱')}<input name="name" required maxLength={100} autoComplete="off" disabled={busy} /></label><div className="action-row"><button type="button" className="secondary" disabled={busy} onClick={close}>{t('取消')}</button><button className="primary" disabled={busy}>{busy ? t('建立中…') : t('建立')}</button></div></form>}
    {error && <p className="notice danger" role="alert">{error}</p>}
  </MemberDialog>;
}

export function AgentConnections() {
  const [rows, setRows] = useState<Connection[]>([]), [loading, setLoading] = useState(true), [creating, setCreating] = useState(false), [error, setError] = useState(''), [revoking, setRevoking] = useState<Connection | null>(null), [busy, setBusy] = useState(false);
  async function load() { try { setRows(await api<Connection[]>('/agent/connections')); } catch (e) { setError(e instanceof Error ? e.message : t('載入失敗')); } finally { setLoading(false); } }
  useEffect(() => { void load(); }, []);
  async function revoke() {
    if (!revoking || busy) return; setBusy(true); setError(''); setRevoking(null);
    try { await api('/agent/connections/' + revoking.id, { method: 'DELETE' }); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : t('撤銷失敗')); }
    finally { setBusy(false); }
  }
  return <section className="agent-connections" aria-busy={loading}>
    <div className="member-card-heading"><h2>{t('Agent 連線')}</h2><button className="secondary" disabled={busy} onClick={() => setCreating(true)}>{t('建立連線權杖')}</button></div>
    {error && <p className="notice danger" role="alert">{error}</p>}
    <div className="list-box agent-connection-list">{rows.map(row => <div className="list-row agent-connection-row" key={row.id}><div className="agent-connection-details"><div><strong>{row.name}</strong><span className="status-badge neutral">{row.kind === 'oauth' ? 'OAuth' : t('連線權杖')}</span></div><p>{t('建立 {created} · 最後使用 {used} · 到期 {expires}', { created: time(row.created_at), used: time(row.last_used_at), expires: time(row.expires_at) })}</p></div><button className="primary danger" disabled={busy} onClick={() => setRevoking(row)}>{t('撤銷')}</button></div>)}{!rows.length && <p className="muted">{loading ? t('載入中…') : t('尚無連線')}</p>}</div>
    {creating && <CreateConnection onClose={() => setCreating(false)} onCreated={() => void load()} />}
    {revoking && <ConfirmDialog message={t('撤銷 {name}？此連線將立即失效。', { name: revoking.name })} confirmLabel={t('撤銷')} danger onClose={() => setRevoking(null)} onConfirm={() => void revoke()} />}
  </section>;
}

import { useEffect, useState } from 'react';
import { api, errorMessage } from '../api';
import { roleLabel } from './MyAccount';
import './agent-auth.css';
import { t } from '../i18n.ts';

type Approval = { client_name: string; redirect_uri: string; display_name: string; role: string; role_name?: string | null; can_write?: boolean };

// 授權結果要送到應用程式在本機開的接收網址。工作檯本身也在本機時，於背景送出並顯示中文完成頁；
// 其他情況（例如 Tailscale 網址）瀏覽器可能擋下或詢問權限，改為直接前往該網址。
const loopback = ['127.0.0.1', 'localhost', '[::1]'].includes(location.hostname);

async function deliver(target: string) {
  if (!loopback) return false;
  const timer = new Promise<never>((_, reject) => setTimeout(() => reject(new Error('timeout')), 5000));
  try {
    await Promise.race([fetch(target, { mode: 'no-cors', credentials: 'omit', referrerPolicy: 'no-referrer', cache: 'no-store' }), timer]);
    return true;
  } catch {
    return false;
  }
}

export function AgentApproval({ requestId }: { requestId: string }) {
  const [view, setView] = useState<Approval | null>(null), [csrf, setCsrf] = useState(''), [error, setError] = useState('');
  const [busy, setBusy] = useState(false), [done, setDone] = useState<'approved' | 'denied' | null>(null);
  useEffect(() => {
    let active = true;
    Promise.all([api<Approval>('/agent/authorization?request_id=' + encodeURIComponent(requestId)), api<{ csrf_token: string }>('/auth/csrf')]).then(([value, token]) => { if (active) { setView(value); setCsrf(token.csrf_token); } }).catch(e => { if (active) setError(errorMessage(e, t('載入失敗'))); });
    return () => { active = false; };
  }, [requestId]);
  async function decide(approve: boolean) {
    setBusy(true); setError('');
    try {
      const body = new URLSearchParams({ request_id: requestId, approve: String(approve), csrf_token: csrf });
      const { location: target } = await api<{ location: string }>('/agent/authorization/decision', { method: 'POST', body, headers: { 'Content-Type': 'application/x-www-form-urlencoded' } });
      if (await deliver(target)) setDone(approve ? 'approved' : 'denied');
      else window.location.assign(target);
    } catch (e) {
      setError(errorMessage(e, t('送出失敗'))); setBusy(false);
    }
  }
  if (done) return <main className="agent-approval-page"><section className="section-card agent-approval"><h1>{done === 'approved' ? t('核准完成') : t('已拒絕連線')}</h1>
    <p>{done === 'approved' ? t('已授權「{name}」連線到工作檯。可以關閉這個視窗，回到應用程式繼續。', { name: view?.client_name ?? t('應用程式') }) : t('應用程式不會取得授權。可以關閉這個視窗。')}</p></section></main>;
  return <main className="agent-approval-page"><section className="section-card agent-approval"><h1>{t('核准 Agent 連線')}</h1>
    {error && <p className="notice danger" role="alert">{error}</p>}
    {view && <><dl className="agent-approval-details"><div><dt>{t('應用程式自稱')}</dt><dd>{view.client_name}</dd></div><div><dt>{t('回呼位址')}</dt><dd><code>{view.redirect_uri}</code></dd></div><div><dt>{t('目前成員')}</dt><dd>{view.display_name} · {roleLabel(view.role, view.role_name)}</dd></div><div><dt>{t('可做的事')}</dt><dd>{view.role === 'viewer' || view.can_write === false ? t('查詢資料') : t('查詢資料、建立草稿；發佈需另外確認')}</dd></div></dl>
    <div className="action-row"><button type="button" className="secondary" disabled={!csrf || busy} onClick={() => void decide(false)}>{t('拒絕')}</button><button type="button" className="primary" disabled={!csrf || busy} onClick={() => void decide(true)}>{t('核准')}</button></div></>}
  </section></main>;
}

import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { api, errorMessage } from '../api';
import type { Brand, User } from '../api';
import { AgentConnections } from './AgentConnections';
import { AgentInstall } from './AgentInstall';
import { MemberDialog } from './Members';
import { LanguagePicker } from './LanguagePicker';
import { t } from '../i18n.ts';
import { formatTaipei } from '../time.ts';
import { roleLabel } from '../permissions';

export { roleLabel };

export function PasswordForm({ onChanged }: { onChanged: (user: User) => void }) {
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [message, setMessage] = useState('');
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget, values = new FormData(form);
    setError(''); setMessage('');
    if (values.get('new_password') !== values.get('confirm_password')) { setError(t('兩次輸入的新密碼不一致')); return; }
    setBusy(true);
    try {
      const user = await api<User>('/auth/change-password', { method: 'POST', body: JSON.stringify({ current_password: values.get('current_password'), new_password: values.get('new_password') }) });
      form.reset(); setMessage(t('密碼已變更')); onChanged(user);
    } catch (e) { setError(errorMessage(e, t('變更失敗'))); }
    finally { setBusy(false); }
  }
  return <form className="password-form" onSubmit={submit}>
    <label>{t('目前密碼')}<input name="current_password" type="password" autoComplete="current-password" required maxLength={128} disabled={busy} /></label>
    <label>{t('新密碼')}<input name="new_password" type="password" autoComplete="new-password" required minLength={12} maxLength={128} disabled={busy} placeholder={t('至少 12 字元')} /></label>
    <label>{t('再次輸入新密碼')}<input name="confirm_password" type="password" autoComplete="new-password" required minLength={12} maxLength={128} disabled={busy} /></label>
    {error && <p className="notice danger" role="alert">{error}</p>}{message && <p className="notice success" role="status">{message}</p>}
    <div className="action-row"><button className="primary" disabled={busy}>{busy ? t('儲存中…') : t('變更密碼')}</button></div>
  </form>;
}

export function MyAccount({ user, brands, onChanged }: { user: User; brands: Brand[]; onChanged: (user: User) => void }) {
  return <section className="section-card my-account"><h2>{t('我的帳號')}</h2>
    <p className="account-summary"><strong>{user.display_name}</strong><span>{user.username}</span><span className="status-badge neutral">{roleLabel(user.role, user.role_name)}</span><span>{user.role === 'admin' ? t('全部品牌') : brands.filter(b => user.brand_ids.includes(b.id)).map(b => b.name).join('、') || t('尚未指派品牌')}</span></p>
    <LanguagePicker className="account-language" account />
    <PasswordForm onChanged={onChanged} />
    {user.role === 'admin' && <RecoveryCode />}
    <AgentInstall />
    <AgentConnections />
  </section>;
}

export function RequiredPassword({ onChanged, onLogout }: { onChanged: (user: User) => void; onLogout: () => void }) {
  const [error, setError] = useState('');
  return <main className="password-required"><section className="section-card"><div className="member-card-heading"><h1>{t('請設定新密碼')}</h1><button className="secondary" onClick={async () => { try { await api('/auth/logout', { method: 'POST' }); onLogout(); } catch (e) { setError(errorMessage(e, t('登出失敗'))); } }}>{t('登出')}</button></div>
    {error && <p className="notice danger" role="alert">{error}</p>}<PasswordForm onChanged={onChanged} />
  </section></main>;
}

type RecoveryStatus = { configured: boolean; created_at: string | null };
const takenOn = (value: string) => formatTaipei(value, { year: 'numeric', month: 'long', day: 'numeric' });

// 工作檯沒有寄信管道，管理員忘記密碼時只能靠事先保存的一次性復原碼在登入頁自助重設。
function RecoveryCode() {
  const [status, setStatus] = useState<RecoveryStatus | null>(null), [code, setCode] = useState<string | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    api<RecoveryStatus>('/auth/recovery-code', { signal: controller.signal }).then(setStatus).catch(e => {
      if (!controller.signal.aborted) setError(errorMessage(e, t('復原碼狀態載入失敗')));
    });
    return () => controller.abort();
  }, []);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget, values = new FormData(form);
    setBusy(true); setError('');
    try {
      const result = await api<RecoveryStatus & { recovery_code: string }>('/auth/recovery-code', { method: 'POST', body: JSON.stringify({ current_password: values.get('current_password') }) });
      form.reset(); setStatus({ configured: result.configured, created_at: result.created_at }); setCode(result.recovery_code);
    } catch (e) { setError(errorMessage(e, t('產生失敗'))); }
    finally { setBusy(false); }
  }
  return <section className="recovery-code" aria-labelledby="recovery-code-title">
    <div className="member-card-heading"><h3 id="recovery-code-title">{t('密碼復原碼')}</h3>{status && <span className={'status-badge ' + (status.configured ? 'ready' : 'neutral')}>{status.configured ? t('已設定') : t('尚未設定')}</span>}</div>
    <p className="muted">{t('忘記密碼時，可在登入頁點「忘記密碼？」輸入帳號、復原碼和新密碼自行重設。復原碼只能用一次，用過或重新產生後舊碼就失效。')}{status?.created_at && t('目前的復原碼建立於 {date}。', { date: takenOn(status.created_at) })}</p>
    <form className="password-form" onSubmit={submit}>
      <label>{t('確認目前密碼')}<input name="current_password" type="password" autoComplete="current-password" required maxLength={128} disabled={busy} /></label>
      {error && <p className="notice danger" role="alert">{error}</p>}
      <div className="action-row"><button className="secondary" disabled={busy}>{busy ? t('產生中…') : status?.configured ? t('重新產生復原碼') : t('產生復原碼')}</button></div>
    </form>
    {code !== null && <RecoveryCodeDialog code={code} onClose={() => setCode(null)} />}
  </section>;
}

function RecoveryCodeDialog({ code, onClose }: { code: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false), [error, setError] = useState('');
  return <MemberDialog title={t('密碼復原碼')} onClose={onClose}>
    <div className="temporary-password-row"><code className="temporary-password">{code}</code><button className="secondary" onClick={async () => { try { await navigator.clipboard.writeText(code); setCopied(true); } catch { setError(t('無法複製，請手動選取復原碼')); } }}>{copied ? t('已複製') : t('複製')}</button></div>
    <p className="muted">{t('只會顯示這一次。請存到密碼管理工具或抄在安全的地方，不要和密碼放在一起，也不要傳到聊天或雲端筆記。')}</p>
    {error && <p className="notice danger" role="alert">{error}</p>}
    <div className="action-row"><button className="secondary" onClick={onClose}>{t('我已保存')}</button></div>
  </MemberDialog>;
}

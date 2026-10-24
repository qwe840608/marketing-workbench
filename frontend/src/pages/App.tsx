import { useWorkspace, WorkspaceProvider } from '../branding';
import { readView, readSettingsTab, viewQuery, positiveId } from '../ideationNavigation';
import type { View, SettingsTab } from '../ideationNavigation';
import { IdeationPage } from './Ideation';
import { ReceiveBanner, useReceiveHealth } from './ReceiveHealth';
import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { api, ApiError, refreshCsrf, setCsrf, errorMessage } from '../api';
import type { Brand, User } from '../api';
import { Posts } from './Posts';
import { Publish } from './Publish';
import { Dashboard } from './Dashboard';
import { SettingsHub, settingsTabsFor } from './SettingsHub';
import { can } from '../permissions';
import { RequiredPassword } from './MyAccount';
import { TemporaryPasswordDialog } from './Members';
import { AgentApproval } from './AgentApproval';
import { UpdateNotice } from './UpdateNotice';
import { NeedBrand } from './NeedBrand';
import { LanguagePicker } from './LanguagePicker';
import { applyLanguage, isLanguage, language, t } from '../i18n.ts';
import { PageHeader } from './PageHeader';
const readable = (error: unknown) => errorMessage(error, t('連線失敗，請重試'));
function Wordmark() { const { identity } = useWorkspace(); return <div className="wordmark"><span className="mark" aria-hidden="true">{Array.from(identity.name)[0]}</span><div>{identity.name}<small>{t('品牌營運工作檯')}</small></div></div>; }

export function App() { return <WorkspaceProvider><WorkspaceApp /></WorkspaceProvider>; }

function WorkspaceApp() {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [startupError, setStartupError] = useState('');
  const [temporary, setTemporary] = useState<string | null>(null);
  useEffect(() => {
    const expired = () => setUser(null), required = () => setUser(u => u ? { ...u, must_change_password: true } : u);
    window.addEventListener('auth-expired', expired); window.addEventListener('password-required', required);
    return () => { window.removeEventListener('auth-expired', expired); window.removeEventListener('password-required', required); };
  }, []);
  useEffect(() => {
    let alive = true;
    api<User>('/auth/me').then(value => { if (alive) setUser(value); }).catch(error => {
      if (alive && !(error instanceof ApiError && error.status === 401)) setStartupError(readable(error));
    }).finally(() => { if (alive) setReady(true); });
    return () => { alive = false; };
  }, []);
  // 帳號存的語言優先；帳號還沒設定時，把登入頁選的語言記到帳號上，換裝置也一樣。
  useEffect(() => {
    if (!user || user.must_change_password) return;
    if (isLanguage(user.language)) applyLanguage(user.language);
    else if (language() !== 'zh-TW') api<User>('/auth/language', { method: 'PUT', body: JSON.stringify({ language: language() }) }).catch(() => {});
  }, [user?.id, user?.language, user?.must_change_password]);
  if (!ready) return <div className="loading">{t('正在開啟工作檯…')}</div>;
  if (user && !user.must_change_password && new URLSearchParams(location.search).has('agent_authorize')) return <AgentApproval requestId={new URLSearchParams(location.search).get('agent_authorize') || ''} />;
  return <>{user ? user.must_change_password ? <RequiredPassword onChanged={setUser} onLogout={() => setUser(null)} /> : <Workspace user={user} onChanged={setUser} onLogout={() => setUser(null)} onSelfReset={password => { setTemporary(password); setCsrf(''); setUser(null); }} /> : <Login onLogin={setUser} initialError={startupError} />}{temporary !== null && <TemporaryPasswordDialog password={temporary} onClose={() => setTemporary(null)} />}</>;
}

function Login({ onLogin, initialError }: { onLogin: (u: User) => void; initialError: string }) {
  const [error, setError] = useState(initialError);
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    setBusy(true); setError('');
    try {
      await refreshCsrf();
      const result = await api<{ user: User; csrf_token: string }>('/auth/login', {
        method: 'POST', body: JSON.stringify({ username: values.get('username'), password: values.get('password') }),
      });
      form.reset(); setCsrf(result.csrf_token); onLogin(result.user);
    } catch (err) { setError(readable(err)); }
    finally { setBusy(false); }
  }
  return <main className="login-page"><section className="login-story"><Wordmark />
    <div><span className="eyebrow">{t('每一段對話，都值得好好回應')}</span><h1>{t('聽見需求，')}<br />{t('接住下一步。')}</h1><p>{t('把品牌的訊息整理在一起，')}<br />{t('讓每一次接手都有脈絡。')}</p></div>
    <span className="story-footer">{t('個人與團隊的行銷工作空間')}</span>
  </section><section className="login-panel"><LanguagePicker className="login-language" /><div className="login-box"><form onSubmit={submit}>
    <span className="eyebrow">{t('內部工作檯')}</span><h2>{t('歡迎回來')}</h2><p className="muted">{t('登入後，繼續照顧品牌的每一段對話。')}</p>
    <label>{t('帳號')}<input name="username" autoComplete="username" required maxLength={80} autoFocus /></label>
    <label>{t('密碼')}<input name="password" type="password" autoComplete="current-password" required maxLength={128} /></label>
    {error && <p className="error" role="alert">{error}</p>}
    <button className="primary" disabled={busy}>{busy ? t('正在登入…') : t('登入工作檯')}<span aria-hidden="true">↗</span></button>
    <p className="login-note">{t('限已授權的團隊成員使用')}</p>
  </form><ForgotPassword /></div></section></main>;
}

// 沒有寄信或簡訊管道可以確認身分，所以只接受管理員事先保存的一次性復原碼。
function ForgotPassword() {
  // 收合時不渲染表單，避免隱藏欄位和登入表單的「帳號」「密碼」欄位重名。
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [done, setDone] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget, values = new FormData(form);
    setError('');
    if (values.get('new_password') !== values.get('confirm_password')) { setError(t('兩次輸入的新密碼不一致')); return; }
    setBusy(true);
    try {
      await refreshCsrf();
      await api('/auth/recover', { method: 'POST', body: JSON.stringify({ username: values.get('username'), recovery_code: values.get('recovery_code'), new_password: values.get('new_password') }) });
      form.reset(); setDone(true);
    } catch (err) { setError(readable(err)); }
    finally { setBusy(false); }
  }
  return <details className="login-forgot" onToggle={event => setOpen(event.currentTarget.open)}><summary>{t('忘記密碼？')}</summary>{open && <>
    <p>{t('一般成員：請管理員在「設定 → 成員 → 編輯 → 重設密碼」產生臨時密碼。')}</p>
    <p>{t('管理員：輸入事先在「設定 → 我的帳號」產生的復原碼，即可設定新密碼。')}</p>
    {done ? <p className="notice success" role="status">{t('密碼已重設，請用新密碼登入。復原碼已失效，登入後請到「我的帳號」重新產生。')}</p> : <form onSubmit={submit}>
      <label>{t('管理員帳號')}<input name="username" autoComplete="username" required maxLength={80} disabled={busy} /></label>
      <label>{t('復原碼')}<input name="recovery_code" autoComplete="off" autoCapitalize="characters" spellCheck={false} required maxLength={64} disabled={busy} placeholder="XXXXX-XXXXX-XXXXX-XXXXX" /></label>
      <label>{t('設定新密碼')}<input name="new_password" type="password" autoComplete="new-password" required minLength={12} maxLength={128} disabled={busy} placeholder={t('至少 12 字元')} /></label>
      <label>{t('再次輸入設定的新密碼')}<input name="confirm_password" type="password" autoComplete="new-password" required minLength={12} maxLength={128} disabled={busy} /></label>
      {error && <p className="error" role="alert">{error}</p>}
      <button className="primary" disabled={busy}>{busy ? t('重設中…') : t('重設密碼')}</button>
    </form>}
    <p>{t('沒有復原碼時，請在執行工作檯的主機上，於')} <code>backend</code> {t('資料夾開啟終端機執行下列指令，依提示輸入兩次新密碼，不需重啟服務：')}</p>
    <code className="login-command">uv run python ../scripts/set_password.py {t('你的帳號')}</code>
    <p>{t('連續輸錯 5 次會鎖定 15 分鐘，登入和復原碼共用這個限制。')}</p>
  </>}</details>;
}

function BrandRequired({ title }: { title: string }) {
  return <section className="settings-page"><PageHeader title={title} /><NeedBrand /></section>;
}

function Workspace({ user, onChanged, onLogout, onSelfReset }: { user: User; onChanged: (user: User) => void; onLogout: () => void; onSelfReset: (password: string) => void }) {
  const health = useReceiveHealth();
  const [view, setView] = useState<View>(() => readView(location.search));
  const [settingsTab, setSettingsTab] = useState<SettingsTab>(() => settingsTabsFor(user).length > 1 ? readSettingsTab(location.search) : 'account');
  const [brand, setBrand] = useState(() => String(positiveId(new URLSearchParams(location.search).get('brand_id')) || ''));
  const [brands, setBrands] = useState<Brand[]>([]), [brandsReady, setBrandsReady] = useState(false);
  const [postId, setPostId] = useState<number | null>(null);
  const [publishDraft, setPublishDraft] = useState(() => ({ id: positiveId(new URLSearchParams(location.search).get('publish_post_id')), created: false }));
  const beforePublishLeave = useRef<(() => Promise<boolean>) | null>(null);
  const navigationRequest = useRef(0);
  const [error, setError] = useState('');
  const [mobile, setMobile] = useState(() => matchMedia('(max-width: 599px)').matches);
  useEffect(() => {
    const query = matchMedia('(max-width: 599px)');
    const resize = () => setMobile(query.matches);
    query.addEventListener('change', resize); return () => query.removeEventListener('change', resize);
  }, []);
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    params.set('settings_tab', settingsTab);
    if (brand) params.set('brand_id', brand); else params.delete('brand_id');
    if (publishDraft.id) params.set('publish_post_id', String(publishDraft.id));
    else params.delete('publish_post_id');
    history.replaceState(null, '', location.pathname + viewQuery(params.toString(), view) + location.hash);
  }, [view, brand, settingsTab, publishDraft.id]);
  useEffect(() => {
    const restore = () => { setPublishDraft({ id: positiveId(new URLSearchParams(location.search).get('publish_post_id')), created: false }); setView(readView(location.search)); setSettingsTab(readSettingsTab(location.search)); setBrand(String(positiveId(new URLSearchParams(location.search).get('brand_id')) || '')); };
    window.addEventListener('popstate', restore); return () => window.removeEventListener('popstate', restore);
  }, []);
  useEffect(() => {
    const c = new AbortController();
    async function loadBrands() {
      try {
        const rows: Brand[] = [];
        do {
          const batch = await api<Brand[]>('/brands?limit=200' + (rows.length ? '&offset=' + rows.length : ''), { signal: c.signal });
          rows.push(...batch);
          if (batch.length < 200) break;
        } while (rows.length < user.brand_ids.length && !c.signal.aborted);
        if (!c.signal.aborted) { setBrands(rows); setBrand(current => rows.length === 1 ? String(rows[0].id) : current && !rows.some(b => String(b.id) === current) ? '' : current); setBrandsReady(true); }
      } catch (e) { if (!c.signal.aborted) { setError(readable(e)); setBrandsReady(true); } }
    }
    void loadBrands(); return () => c.abort();
  }, [user.role, user.brand_ids.join(',')]);
  async function refreshUser() { try { onChanged(await api<User>('/auth/me')); } catch (e) { setError(readable(e)); } }
  async function navigate(next: View) {
    const request = ++navigationRequest.current;
    if (next === view) return;
    if (view === 'publish' && beforePublishLeave.current && !await beforePublishLeave.current()) return;
    if (request !== navigationRequest.current) return;
    if (next === 'posts') setPostId(null); setView(next);
  }
  // 使用者只看得到一個品牌時隱藏品牌選單，各頁直接用那一個品牌。
  const needBrand = brands.length > 1 && !brand, single = brands.length === 1, activeBrand = single ? String(brands[0].id) : brand;
  useEffect(() => { if (brands.length === 1) setBrand(String(brands[0].id)); }, [brands]);
  function changeBrand(value: string) { setBrand(value); setPostId(null); setPublishDraft({ id: null, created: false }); }
  async function logout() { try { await api('/auth/logout', { method: 'POST' }); setCsrf(''); onLogout(); } catch (e) { setError(readable(e)); } }
  return <><ReceiveBanner health={health} /><main className={'workspace' + (health?.interrupted ? ' has-receive-banner' : '')}>
    <aside className="sidebar"><Wordmark />
      {brands.length > 1 && <label className="brand-picker"><span>{t('目前品牌')}</span><select value={brand} onChange={e => changeBrand(e.target.value)}>
        <option value="">{t('全部可見品牌')}</option>{brands.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
      </select></label>}
      <nav className="workspace-nav">
        <button className={view === 'dashboard' ? 'current' : ''} onClick={() => void navigate('dashboard')}>{t('儀表板')}</button>
        <button className={view === 'posts' ? 'current' : ''} onClick={() => void navigate('posts')}>{t('貼文數據')}</button>
        <button className={view === 'ideation' ? 'current' : ''} onClick={() => void navigate('ideation')}>{t('主題發想')}</button>
        <button className={view === 'publish' ? 'current' : ''} onClick={() => void navigate('publish')}>{t('發佈')}</button>
        <button className={view === 'settings' ? 'current' : ''} onClick={() => void navigate('settings')}>{t('設定')}</button></nav>
      <div className="sidebar-note"><span className="live-dot" /> {t('品牌營運工作檯')}</div>
      <div className="user-card"><div className="avatar small">{user.display_name[0]}</div><div><strong>{user.display_name}</strong><small>{user.role === 'admin' ? t('管理員') : user.role === 'marketing' ? t('行銷人員') : user.role === 'viewer' ? t('唯讀成員') : user.role_name || t('自訂角色')}</small></div><button className="quiet" onClick={logout}>{t('登出')}</button></div>
    </aside>
    {mobile && <nav className="mobile-bottom-nav" aria-label={t('手機導覽')}>
      {([{ view: 'dashboard', label: t('儀表板') }, { view: 'posts', label: t('貼文數據') }, { view: 'ideation', label: t('主題發想') }, { view: 'publish', label: t('發佈') }, { view: 'settings', label: t('設定') }] as const).map(item => <button key={item.view} className={view === item.view ? 'primary current' : 'quiet'} aria-current={view === item.view ? 'page' : undefined} onClick={() => navigate(item.view)}>{item.label}</button>)}
    </nav>}
    {error && <p className="error" role="alert">{error}</p>}
    {mobile && <div className={'mobile-settings-controls' + (brands.length > 1 ? '' : ' in-topbar')}>{brands.length > 1 && <label className="mobile-brand-picker">{t('目前品牌')}<select value={brand} onChange={e => changeBrand(e.target.value)}><option value="">{t('全部可見品牌')}</option>{brands.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}</select></label>}<button className="secondary mobile-logout" onClick={logout}>{t('登出')}</button></div>}
    {!brandsReady ? null : view === 'settings' ? <SettingsHub tab={settingsTab} onTab={setSettingsTab} brand={activeBrand} brands={brands} user={user} onChanged={onChanged} onUserChanged={() => void refreshUser()} onSelfReset={onSelfReset} /> : user.role !== 'admin' && !user.brand_ids.length ? <section className="section-card no-brands"><p>{t('尚未指派品牌，請聯絡管理員')}</p></section> : view === 'publish' ? (needBrand ? <BrandRequired title={t('發佈')} /> : <Publish brand={activeBrand} brands={brands} user={user} draftId={publishDraft.id} fromIdea={publishDraft.created} onDraftId={id => setPublishDraft(value => value.id === id ? value : { id, created: false })} beforeLeave={beforePublishLeave} onConnections={() => { setSettingsTab('connections'); void navigate('settings'); }} />) : view === 'ideation' ? needBrand ? <BrandRequired title={t('主題發想')} /> : <IdeationPage brand={activeBrand} brands={brands} canEdit={can(user, 'ideation.edit')} canConfigure={can(user, 'settings.manage')} onDraft={(id, brandId, created) => { setBrand(String(brandId)); setPublishDraft({ id, created }); setView('publish'); }} /> : view === 'posts' ? <Posts brand={activeBrand} initialPostId={postId} onLogout={onLogout} canSync={can(user, 'posts.sync')} /> : <Dashboard brand={activeBrand} canExport={can(user, 'reports.export')} onPost={id => { setPostId(id); setView('posts'); }} />}
  </main><UpdateNotice /></>;
}

import { Fragment, Suspense, lazy, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { locale, t, tx } from '../i18n.ts';
import { tiktokCommentNotice, type GuideId } from '../platformGuides';
import { ConfirmDialog } from './ConfirmDialog';
const GuideModal = lazy(() => import('./GuideModal'));
// YouTube 政策要求刪除方式說清楚：只刪工作檯存的資料，不影響 YouTube 上的影片。
export const TIKTOK_DISCONNECT_NOTICE = t('工作檯會撤銷 TikTok 授權，並刪除已同步的 TikTok 影片資料與數據；TikTok 上的影片不受影響，要刪除影片請到 TikTok App 操作。');
export const YOUTUBE_DISCONNECT_NOTICE = t('工作檯會撤銷授權，並刪除已同步的 YouTube 影片資料、縮圖、留言與主題發想報告中的 YouTube 引用；YouTube 上的影片不受影響，要刪除影片請到 YouTube 操作。');

type Credential = { name: string; configured: boolean; source: 'DB' | 'env' | '未設定'; mask: string | null; version: number; error: string | null };
type Configuration = { items: Credential[]; webhook_public_url: string };
type ConnectionStatus = { configured?: boolean; linked: boolean; name: string; ig_username: string; expires_at: string | null; never_expires?: boolean; granted: string[]; missing: string[]; data_missing?: string[]; state: string; verified?: boolean; category_id?: string; categories?: { id: string; name: string }[] };
type OAuthStatus = { backoffice_origin: string; callbacks: Record<string, string>; platforms: Record<string, ConnectionStatus>; pages: { id: string; name: string }[] };
const groups = [
  { id: 'meta', title: t('Meta（FB／IG）'), names: ['META_APP_ID', 'META_APP_SECRET', 'META_VERIFY_TOKEN', 'META_PAGE_ID', 'META_PAGE_ACCESS_TOKEN', 'META_USER_ACCESS_TOKEN', 'META_IG_ACCOUNT_ID'] },
  { id: 'threads', title: 'Threads', names: ['THREADS_APP_ID', 'THREADS_APP_SECRET', 'THREADS_USER_ID', 'THREADS_ACCESS_TOKEN'] },
  { id: 'youtube', title: 'YouTube', names: ['YOUTUBE_CLIENT_ID', 'YOUTUBE_CLIENT_SECRET'] },
  { id: 'tiktok', title: 'TikTok', names: ['TIKTOK_CLIENT_KEY', 'TIKTOK_CLIENT_SECRET'] },
  { id: 'notify', title: t('LINE 通知'), names: ['NOTIFY_LINE_CHANNEL_ACCESS_TOKEN', 'NOTIFY_LINE_CHANNEL_SECRET', 'NOTIFY_LINE_BOT_USER_ID', 'NOTIFY_LINE_GROUP_ID'] },
  { id: 'jev', title: 'jev', names: ['JEV_API_KEY', 'JEV_API_BASE_URL'] },
];

// 畫面顯示中文名稱，.env 名稱以小字對照；欄位的無障礙名稱維持 .env 名稱方便對照與檢查。
const labels: Record<string, string> = {
  META_APP_ID: t('應用程式 ID'), META_APP_SECRET: t('應用程式密鑰'), META_VERIFY_TOKEN: t('Webhook 驗證權杖'),
  META_PAGE_ID: t('粉絲專頁 ID'), META_PAGE_ACCESS_TOKEN: t('粉絲專頁存取權杖'), META_USER_ACCESS_TOKEN: t('使用者存取權杖'),
  META_IG_ACCOUNT_ID: t('Instagram 商業帳號 ID'),
  THREADS_APP_ID: t('應用程式 ID'), THREADS_APP_SECRET: t('應用程式密鑰'), THREADS_USER_ID: t('使用者 ID'), THREADS_ACCESS_TOKEN: t('存取權杖'),
  NOTIFY_LINE_CHANNEL_ACCESS_TOKEN: t('通知用 Channel access token'), NOTIFY_LINE_CHANNEL_SECRET: t('通知用 Channel secret'),
  NOTIFY_LINE_BOT_USER_ID: t('通知用官方帳號 User ID'), NOTIFY_LINE_GROUP_ID: t('接收通知的群組 ID'),
  YOUTUBE_CLIENT_ID: t('OAuth 用戶端 ID'), YOUTUBE_CLIENT_SECRET: t('OAuth 用戶端密鑰'),
  TIKTOK_CLIENT_KEY: 'Client key', TIKTOK_CLIENT_SECRET: 'Client secret',
  JEV_API_KEY: tx('field', 'API 金鑰'), JEV_API_BASE_URL: t('API 網址'),
};

function CredentialField({ row, editing, setEditing, onChange }: { row: Credential; editing: boolean; setEditing: (editing: boolean) => void; onChange: (value: Configuration) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function perform(remove: boolean) {
    setBusy(true); setError('');
    try {
      const pending = api<Configuration>('/credentials/' + row.name + (remove ? '?version=' + row.version : ''), {
        method: remove ? 'DELETE' : 'PUT',
        ...(remove ? {} : { body: JSON.stringify({ value: input.current?.value || '', version: row.version }) }),
      });
      if (input.current) input.current.value = '';
      onChange(await pending); setEditing(false);
    } catch (e) { setError(e instanceof Error ? e.message : t('憑證未儲存')); }
    finally { setBusy(false); }
  }
  return <form className="credential-field" aria-label={row.name} onSubmit={e => { e.preventDefault(); void perform(false); }}>
    <div className="credential-heading"><label htmlFor={'credential-' + row.name}><span className="credential-name">{labels[row.name] || row.name}</span><small className="credential-env">{row.name}</small></label><div className="credential-status"><span className={'key-source status-badge ' + (row.source === 'DB' ? 'ready' : 'neutral') + (row.source === '未設定' ? ' unset' : '')}>{row.source === '未設定' ? t('未設定') : row.source}</span><code>{row.mask || (row.configured ? '••••' : '—')}</code>
      {!editing && <button type="button" className="secondary" disabled={busy} onClick={() => setEditing(true)}>{row.configured ? t('更換') : tx('button', '設定')}</button>}</div>
    </div>
    <div className="credential-controls">
      {editing ? <><input id={'credential-' + row.name} ref={input} type="password" autoComplete="new-password" spellCheck={false} required maxLength={4096} disabled={busy} aria-label={row.name} /><button className="primary" disabled={busy}>{t('儲存')}</button><button type="button" className="secondary" disabled={busy} onClick={() => { if (input.current) input.current.value = ''; setEditing(false); }}>{t('取消')}</button></>
        : null}
      {row.source === 'DB' && !editing && <button type="button" className="primary danger" disabled={busy} onClick={() => void perform(true)}>{t('移除')}</button>}
    </div>
    {(error || row.error) && <p className="error" role="alert">{error || row.error}</p>}
  </form>;
}

function ConnectionGroup({ group, data, onChange, oauth, refresh }: { group: typeof groups[number]; data: Configuration; onChange: (data: Configuration) => void; oauth: OAuthStatus | null; refresh: (force?: boolean) => Promise<OAuthStatus> }) {
  const [busy, setBusy] = useState(false), [notice, setNotice] = useState(''), [error, setError] = useState('');
  const [editingRow, setEditingRow] = useState<string | null>(null);
  const [pageId, setPageId] = useState(''), [guideOpen, setGuideOpen] = useState(false), [confirmDisconnect, setConfirmDisconnect] = useState(false);
  const guide = group.id as GuideId;
  const youtube = group.id === 'youtube', tiktok = group.id === 'tiktok';
  // YouTube 與 TikTok 都是使用者自建的 OAuth 用戶端：卡片上直接設定金鑰、可中斷連結，權杖自動換發。
  const clientApp = youtube || tiktok;
  const oauthPlatform = group.id === 'meta' || group.id === 'threads' || clientApp;
  const status = oauth?.platforms[group.id];
  const correctOrigin = !!oauth && oauth.backoffice_origin.startsWith('https://') && location.origin === oauth.backoffice_origin;
  // 既有 Threads 連結缺少成效與回覆權限、既有 YouTube 連結缺少上傳權限：其餘功能照常，只提示重新連結。
  const dataHint = (group.id === 'threads' || youtube) && !!status?.linked && !status.missing.length && !!status.data_missing?.length;
  async function link() {
    setBusy(true); setError('');
    try { const response = await api<{ url: string }>('/oauth/' + group.id + '/start', { method: 'POST', body: '{}' }); location.assign(response.url); }
    catch (e) { setError(e instanceof Error ? e.message : t('帳號連結失敗')); setBusy(false); }
  }
  async function disconnect() {
    setBusy(true); setError('');
    try { await api('/oauth/' + group.id + '/disconnect', { method: 'POST', body: '{}' }); await refresh(); onChange(await api<Configuration>('/credentials')); }
    catch (e) { setError(e instanceof Error ? e.message : t('中斷連結失敗')); }
    finally { setBusy(false); }
  }
  async function saveCategory(categoryId: string) {
    setBusy(true); setNotice(''); setError('');
    try { await api('/oauth/youtube/category', { method: 'PUT', body: JSON.stringify({ category_id: categoryId }) }); await refresh(); setNotice(t('已儲存上傳類別')); }
    catch (e) { setError(e instanceof Error ? e.message : t('類別未儲存')); }
    finally { setBusy(false); }
  }
  async function choose() {
    setBusy(true); setError('');
    try { await api('/oauth/meta/page', { method: 'POST', body: JSON.stringify({ page_id: pageId || oauth?.pages[0]?.id }) }); await refresh(); onChange(await api<Configuration>('/credentials')); setNotice(t('帳號連結成功')); }
    catch (e) { setError(e instanceof Error ? e.message : t('粉絲專頁未選定')); }
    finally { setBusy(false); }
  }
  async function test() {
    setBusy(true); setNotice(''); setError('');
    try { if (oauthPlatform) { const response = await refresh(true); if (response.platforms[group.id]?.verified === false) throw new Error(t('權限檢查失敗，請重新連結')); setNotice(t('權限檢查完成')); } else { const result = await api<{ ok: boolean; filled?: string[] }>('/credentials/' + group.id + '/test', { method: 'POST', body: '{}' }); if (result.filled?.length) { onChange(await api('/credentials')); setNotice(t('連線成功，已自動填入官方帳號 User ID')); } else setNotice(t('連線成功')); } }
    catch (e) { setError(e instanceof Error ? e.message : t('連線測試失敗')); }
    finally { setBusy(false); }
  }
  return <section className="settings-section section-card connection-card" aria-labelledby={'connection-' + group.id}>
    <div className="card-title"><h2 id={'connection-' + group.id}>{group.title}</h2><div className="card-actions">{guide && <button className="secondary" type="button" onClick={() => setGuideOpen(true)}>{t('設定教學')}</button>}<button className="secondary" disabled={busy} onClick={() => void test()}>{busy ? t('測試中…') : t('測試連線')}</button></div></div>
    {oauthPlatform && <>
      <div className="oauth-account"><span>{status?.name || (status?.linked ? t('已設定帳號') : t('尚未連結'))}{status?.ig_username && ' · @' + status.ig_username}</span><span className={'status-badge ' + (status?.state || 'neutral')}>{status?.state === 'ready' ? t('已連結') : status?.state === 'pending' ? t('即將到期') : status?.state === 'failed' ? t('需重新連結') : t('未連結')}</span>{clientApp && <span className="muted">{status?.state === 'failed' ? t('權杖失效，請重新連結') : status?.linked ? t('存取權杖自動換發') : status?.configured ? t('尚未授權') : t('尚未設定用戶端')}</span>}{status?.expires_at && <time dateTime={status.expires_at}>{t('{time} 到期', { time: new Date(status.expires_at).toLocaleString(locale(), { timeZone: 'Asia/Taipei' }) })}</time>}{status?.never_expires && <span className="muted">{t('授權不會過期')}</span>}</div>
      {!!status?.missing.length && status.linked && <p className="notice danger oauth-permissions">{t('缺少權限：{permissions}', { permissions: status.missing.join(t('、')) })}</p>}
      {dataHint && <p className="notice warning oauth-permissions" role="status">{youtube ? t('需要重新連結以取得上傳權限') : t('需要重新連結以取得數據與回覆權限')}</p>}
      {youtube && status?.linked && !!status.categories?.length && <label className="youtube-category">{t('上傳類別')}<select aria-label={t('YouTube 上傳類別')} value={status.category_id} disabled={busy} onChange={e => void saveCategory(e.target.value)}>{status.categories.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>}
      {group.id === 'meta' && !!oauth?.pages.length ? <form className="oauth-page-choice" onSubmit={e => { e.preventDefault(); void choose(); }}><label>{t('粉絲專頁')}<select value={pageId || oauth.pages[0].id} onChange={e => setPageId(e.target.value)} disabled={busy}>{oauth.pages.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label><button className="primary" disabled={busy}>{t('使用這個粉專')}</button></form>
        : <button className={dataHint || (clientApp && status?.linked) ? 'secondary' : 'primary'} disabled={busy || !correctOrigin || (clientApp && !status?.configured)} onClick={() => void link()}>{status?.linked ? t('重新連結') : t('連結 {platform} 帳號', { platform: group.id === 'meta' ? 'Meta' : youtube ? 'YouTube' : tiktok ? 'TikTok' : 'Threads' })}</button>}
      {oauth && !correctOrigin && <p className="notice oauth-origin">{t('請用內部 https 網址開啟工作檯後再連結')}{oauth.backoffice_origin.startsWith('https://') && <> · <a href={oauth.backoffice_origin}>{t('開啟工作檯')}</a></>}</p>}
      {clientApp && status?.linked && <button className="secondary" disabled={busy} onClick={() => setConfirmDisconnect(true)}>{t('中斷連結')}</button>}
      {confirmDisconnect && <ConfirmDialog heading={t('中斷 {platform} 連結？', { platform: group.title })} confirmLabel={t('中斷並刪除資料')} danger onClose={() => setConfirmDisconnect(false)} onConfirm={() => { setConfirmDisconnect(false); void disconnect(); }}><p className="youtube-disconnect-notice">{tiktok ? TIKTOK_DISCONNECT_NOTICE : YOUTUBE_DISCONNECT_NOTICE}</p></ConfirmDialog>}
      {tiktok && <p className="notice tiktok-comments"><strong>{t('留言（選用）')}</strong>{tiktokCommentNotice}{t('。')}</p>}
    </>}
    {(group.id === 'threads' || clientApp) && <div className="list-box">{data.items.filter(row => group.names.includes(row.name) && (clientApp || ['THREADS_APP_ID', 'THREADS_APP_SECRET'].includes(row.name))).map(row => <CredentialField key={row.name} row={row} editing={editingRow === row.name} setEditing={editing => setEditingRow(editing ? row.name : null)} onChange={value => { onChange(value); void refresh().catch(() => setError(t('無法更新連線狀態'))); }} />)}</div>}
    {!clientApp && <details className="oauth-manual" open={oauthPlatform ? undefined : true}><summary hidden={!oauthPlatform}>{oauthPlatform ? t('手動設定（進階）') : t('憑證設定')}</summary><div className="list-box">{data.items.filter(row => group.names.includes(row.name) && (group.id !== 'threads' || !['THREADS_APP_ID', 'THREADS_APP_SECRET', 'YOUTUBE_CLIENT_ID', 'YOUTUBE_CLIENT_SECRET'].includes(row.name))).map(row => <CredentialField key={row.name} row={row} editing={editingRow === row.name} setEditing={editing => setEditingRow(editing ? row.name : null)} onChange={value => { setNotice(''); onChange(value); void refresh().catch(() => setError(t('無法更新連線狀態'))); }} />)}</div></details>}
    {notice && <p className="success-note notice success" role="status">{notice}</p>}{error && <p className="notice danger" role="alert">{error}</p>}
    {guideOpen && <Suspense fallback={null}><GuideModal id={guide} context={{ callbacks: oauth?.callbacks, webhookUrl: data.webhook_public_url }} onClose={() => setGuideOpen(false)} /></Suspense>}
  </section>;
}

export function PlatformConnections({ role }: { role: string }) {
  const [data, setData] = useState<Configuration | null>(null), [error, setError] = useState('');
  const [oauth, setOAuth] = useState<OAuthStatus | null>(null);
  const [result, setResult] = useState('');
  async function refresh(force = false) { const response = await api<OAuthStatus>('/oauth/status' + (force ? '?force=true' : '')); setOAuth(response); return response; }
  useEffect(() => {
    if (role !== 'admin') return;
    const c = new AbortController();
    api<Configuration>('/credentials', { signal: c.signal }).then(setData).catch(e => { if (!c.signal.aborted) setError(e.message); });
    api<OAuthStatus>('/oauth/status', { signal: c.signal }).then(setOAuth).catch(e => { if (!c.signal.aborted) setError(e.message); });
    const url = new URL(location.href), pending = url.searchParams.get('oauth_pending');
    setResult(url.searchParams.get('oauth_result') || '');
    url.searchParams.delete('oauth_result'); url.searchParams.delete('oauth_pending'); history.replaceState(history.state, '', url);
    // 平台導回時瀏覽器不帶登入 cookie，後端只暫存授權碼；回到頁面後由目前登入的 session 完成連結。
    if (pending === 'meta' || pending === 'threads' || pending === 'youtube' || pending === 'tiktok') {
      api<{ result: string }>('/oauth/' + pending + '/complete', { method: 'POST', body: '{}', signal: c.signal })
        .then(r => { setResult(r.result); return api<OAuthStatus>('/oauth/status', { signal: c.signal }).then(setOAuth); })
        .catch(() => { if (!c.signal.aborted) setResult('failed'); });
    }
    return () => c.abort();
  }, [role]);
  if (role !== 'admin') return <section className="settings-page platform-connections"><p className="muted">{t('平台連線由管理員管理。')}</p></section>;
  return <section className="settings-page platform-connections">
    {result && <p className={'notice ' + (result === 'linked' || result === 'select' ? 'success' : 'danger')} role={result === 'linked' || result === 'select' ? 'status' : 'alert'}>{({ linked: t('帳號連結成功'), select: t('請選擇粉絲專頁'), no_pages: t('沒有可管理的粉絲專頁'), cancelled: t('已取消帳號授權') } as Record<string, string>)[result] || t('帳號連結失敗，請確認應用程式設定與授權後重試')}</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {data && <>{groups.map(group => <Fragment key={group.id}>
        <ConnectionGroup group={group} data={data} onChange={value => { setData(value); setResult(''); }} oauth={oauth} refresh={refresh} />
      </Fragment>)}
      <WebhookCard data={data} oauth={oauth} /></>}
  </section>;
}

function WebhookCard({ data, oauth }: { data: Configuration; oauth: OAuthStatus | null }) {
  const [open, setOpen] = useState(false);
  return <section className="settings-section section-card connection-endpoints" aria-labelledby="connection-webhook">
    <div className="card-title"><h2 id="connection-webhook">Webhook</h2><div className="card-actions"><button className="secondary" type="button" onClick={() => setOpen(true)}>{t('設定教學')}</button></div></div>
      <label>{t('公開網址')}<input readOnly value={data.webhook_public_url} placeholder={t('尚未設定')} /></label>
      {data.webhook_public_url && ([['meta-inbound', t('Meta 留言通知網址')], ['line-notify', t('LINE 通知網址')]] as const).map(([path, name]) => <label key={path}>{name}<input readOnly value={data.webhook_public_url.replace(/\/$/, '') + '/webhook/' + path} /></label>)}
      <p className="muted env-only">{t('僅限 .env：NGROK_AUTHTOKEN（後端啟動前使用）、ACCOUNT_ENCRYPTION_KEY（加密主金鑰）、INGEST_API_KEY／WEBHOOK_PROBE_SECRET（內部驗證）、BACKUP_PASSWORD（備份解密）、各 *_INITIAL_PASSWORD（初始登入）、路徑與排程開關（部署設定）。')}</p>
    {open && <Suspense fallback={null}><GuideModal id="webhook" context={{ callbacks: oauth?.callbacks, webhookUrl: data.webhook_public_url }} onClose={() => setOpen(false)} /></Suspense>}
  </section>;
}

import { aiErrorMessage } from '../aiErrors';
import { agentProvider, executionLabel } from '../providers';
import { ideationChoiceKey, selectIdeationChoice } from '../aiChoice';
import { useEffect, useId, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { positiveId, quoteHref, selectionQuery } from '../ideationNavigation';
import type { Evidence } from '../ideationNavigation';
import { api, errorMessage } from '../api';
import type { Brand } from '../api';
import { APISetupGuide } from './APISetupGuide';
import { PageHeader } from './PageHeader';
import { SegmentedControl } from './SegmentedControl';
import { pollWhileVisible } from '../visiblePolling';
import { handoffLinks } from '../agentHandoff';
import { t } from '../i18n.ts';
import { taipeiDateTime, toLocalInput } from '../time.ts';
import './ideation.css';

type Config = { version: number; enabled: boolean; weekday: number | null; time: string | null; interval_weeks: number; anchor_date: string | null; topics: string[] };
type Quote = Evidence & { text: string; platform: string };
type Exports = { files: { format: string; path: string; available: boolean }[]; error: string | null };
type Group = { topic: string; count: number; previous_count: number; change: number; pain: number; fallback_count: number; selection_method: string; quotes: Quote[] };
type SourcePost = { id: number; platform: string; published_at: string; caption: string; comment_count: number; total_comment_count?: number };
type Idea = { edited?: boolean; regenerated?: boolean; extended_from?: number; topic: string; title: string; goal: string; hook: string; angle: string; keyword: string; element: string; visual: string; quote_ids: number[] };
type Timing = { started_at?: string | null; comments_synced_at?: string | null; finished_at?: string | null };
type AgentSource = { agent: string };
type AgentExclusion = { id: number; reason: string; note?: string };
const exclusionReasons: Record<string, string> = { spam: t('廣告／垃圾'), off_topic: t('與貼文無關'), duplicate: t('重複洗版'), non_audience: t('非觀眾（品牌或合作方）') };
// Agent 自行判斷的排除與使用者排除分開列出，讓人看得出哪些聲音是 Agent 拿掉的。
function ExclusionNote({ excluded, agent }: { excluded: number[]; agent: AgentExclusion[] }) {
  if (!excluded.length) return null;
  return <div className="ideation-notice ideation-exclusions"><p>{t('已排除 {count} 則留言', { count: excluded.length })}{agent.length > 0 && t('（其中 Agent 判斷排除 {count} 則）', { count: agent.length })}</p>
    {agent.length > 0 && <details><summary>{t('查看 Agent 排除理由')}</summary><ul>{agent.map(item => <li key={item.id}>{t('留言 #{id}', { id: item.id })} · {exclusionReasons[item.reason] || item.reason}{item.note ? ` · ${item.note}` : ''}</li>)}</ul></details>}
  </div>;
}
type Report = { source?: AgentSource | null; timing?: Timing; provider?: string; exports?: Exports; can_retry?: boolean; id: number; brand_id: number; status: string; error: string | null; created_at: string; start_at: string; end_at: string; notification_status: string; data?: Timing & { ideas_revision?: number; ideas_history?: Record<string, { idea: Idea }[]>; new_comments?: number; comment_range?: string; comment_start?: string; comment_end?: string; excluded_message_ids?: number[]; agent_exclusions?: AgentExclusion[]; notice: string; ideas: Idea[]; groups: Group[]; quote_note: string; comparison_partial: boolean; empty: boolean } };
type Shot = { number: number; visual: string; camera: string; dialogue: string; subtitle: string; sound: string; seconds: number; b_roll: string };
type Content = { title: string; goal: string; hook: string; duration_seconds: number; shots: Shot[]; ending: string; notes: string; permissions: string };
type Review = { passed: boolean; reasons: string[] };
type Script = { source?: AgentSource | null; exports?: Exports; brand_id: number; report_id: number; topic_index: number; id: number; version: number; content: Content; review: Review; notice: string; quotes: Quote[]; versions: { revision: number; content: Content; actor: string; created_at: string }[] };
const statuses: Record<string, string> = { syncing_comments: t('抓取留言中'), pending: t('等待產生'), processing: t('正在分類與發想'), awaiting_ideas: t('等待 Agent 撰寫主題'), ready: t('已完成並匯出'), failed: t('產生失敗') };
// 狀態為已完成但匯出檔不存在或未全部產生時，不再寫「已完成並匯出」；列表沒有匯出資料時維持原狀態文字。
function statusLabel(r: { status: string; exports?: Exports }) {
  if (r.status === 'ready' && r.exports && !(r.exports.files.length && r.exports.files.every(f => f.available))) return t('已完成・匯出未完成');
  return statuses[r.status] || r.status;
}
const activeStatuses = ['pending', 'processing', 'syncing_comments'];
const pollingStatuses = [...activeStatuses, 'awaiting_ideas'];
const goals = ['變現型', '流量型', '引流型'];
// 目標類型值存在後端並用來比對分組，只在顯示時翻譯。
const goalLabels: Record<string, string> = { '變現型': t('變現型'), '流量型': t('流量型'), '引流型': t('引流型') };
const goalLabel = (goal: string) => goalLabels[goal] || goal;
const cameraLabels: Record<string, string> = { POV: 'POV', '側拍': t('側拍'), 'POV／側拍': t('POV／側拍') };
const cameraLabel = (camera: string) => cameraLabels[camera] || camera;
const platforms: Record<string, string> = { line: 'LINE', facebook: 'Facebook', instagram: 'Instagram', youtube: 'YouTube', threads: 'Threads', tiktok: 'TikTok' };
const date = (s: string) => taipeiDateTime(s, { hour12: false });
const local = toLocalInput;
const failure = (e: unknown) => errorMessage(e, t('操作未完成，請稍後再試'));
const commentRanges = ['7', '30', '60', '90', 'custom'] as const;
type CommentRange = typeof commentRanges[number];
function readCommentWindow() {
  const params = new URLSearchParams(location.search);
  const range = params.get('comment_range');
  return { range: (commentRanges.includes(range as CommentRange) ? range : '30') as CommentRange,
    from: params.get('comment_from') || '', to: params.get('comment_to') || '' };
}

function elapsed(start: string, end: number) {
  const seconds = Math.max(0, Math.floor((end - Date.parse(start)) / 1000));
  return Number.isFinite(seconds) ? `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}` : '0:00';
}
function AgentSourceChip({ source }: { source?: AgentSource | null }) {
  return source ? <span className="agent-source-chip">{t('來自 {agent}', { agent: source.agent })}</span> : null;
}

// 交給 Agent 撰寫（主題或腳本）：開啟桌面 App 並預填接手指令（仍需使用者自己送出），或複製指令貼到其他 Agent。
function AgentHandoff({ slash, plain }: { slash: string; plain: string }) {
  const [copy, setCopy] = useState<'idle' | 'copied' | 'failed'>('idle');
  const links = handoffLinks({ slash, plain });
  const labels = { 'claude-code': t('交給 Claude Code'), 'claude-chat': t('開啟 Claude 對話'), codex: t('開啟 Codex') };
  async function copyPrompt() {
    try { await navigator.clipboard.writeText(plain); setCopy('copied'); } catch { setCopy('failed'); }
  }
  return <div className="agent-handoff"><div className="agent-handoff-actions">{links.map(link => <a key={link.app} className="secondary" href={link.href}>{labels[link.app]}</a>)}<button type="button" className="secondary" onClick={() => void copyPrompt()}>{copy === 'copied' ? t('已複製') : t('複製給其他 Agent')}</button></div>
    <p className="agent-handoff-hint">{t('按鈕會開啟桌面 App 並填好指令，確認後按送出。Antigravity 或其他 Agent 請按「複製給其他 Agent」後貼上。')}</p>
    {copy === 'failed' && <p className="notice danger" role="alert">{t('無法複製，請手動輸入：{prompt}', { prompt: plain })}</p>}</div>;
}
// compact：主題列表列已有狀態膠囊，只顯示時間，避免同一狀態寫兩次。
function ReportTimer({ report, now, compact = false }: { report: Report; now: number; compact?: boolean }) {
  const timing = report.data || report.timing;
  if (!timing?.started_at) return null;
  const active = activeStatuses.includes(report.status) && !timing.finished_at;
  if (!active && !timing.finished_at) return null;
  const duration = elapsed(timing.started_at, active ? now : Date.parse(timing.finished_at!));
  return <span className="ideation-timer" role={active ? 'timer' : undefined} title={active ? t('已執行 {duration}', { duration }) : undefined}>
    {active ? (compact ? '' : (report.status === 'syncing_comments' ? t('抓取留言中') : t('產生主題中')) + ' · ') + t('已執行 {duration}', { duration }) : t('耗時 {duration}', { duration })}
  </span>;
}

type Preview = { items: { id: number; author: string; text: string; sent_at: string }[]; next_offset: number | null };
// 留言預設全部採用；取消勾選者記入 excluded，發想與重新標註都會排除。
function PostComments({ postId, query, excluded, disabled, onToggle }: { postId: number; query: string; excluded: number[]; disabled: boolean; onToggle: (id: number, use: boolean) => void }) {
  const [preview, setPreview] = useState<Preview>({ items: [], next_offset: null });
  const [offset, setOffset] = useState(0), [loading, setLoading] = useState(true), [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    api<Preview>(`/ideation/posts/${postId}/comments?${query}&offset=${offset}`, { signal: controller.signal }).then(result => {
      if (!controller.signal.aborted) setPreview(previous => ({ ...result, items: offset ? [...previous.items, ...result.items] : result.items }));
    }).catch(e => { if (!controller.signal.aborted) setError(failure(e)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [postId, query, offset]);
  return <div id={`ideation-comments-${postId}`} className="ideation-post-preview" aria-busy={loading}>
    {preview.items.map(item => <label className="ideation-preview-item" key={item.id}><input type="checkbox" aria-label={t('使用留言 {id}', { id: item.id })} disabled={disabled} checked={!excluded.includes(item.id)} onChange={e => onToggle(item.id, e.target.checked)} /><span className="ideation-preview-content"><span className="ideation-preview-meta"><span>{item.author}</span><time dateTime={item.sent_at}>{date(item.sent_at)}</time></span><span className="ideation-preview-text">{item.text}</span></span></label>)}
    {loading && <p className="muted" role="status">{t('載入留言中…')}</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {!loading && !error && !preview.items.length && <p className="muted">{t('此範圍沒有已存留言')}</p>}
    {preview.next_offset !== null && <button className="secondary" disabled={loading} onClick={() => setOffset(preview.next_offset!)}>{t('載入更多')}</button>}
  </div>;
}

// 清單只露出前 30 字；「[全文]」與留言都開彈出視窗，長內容在視窗內捲動而不撐高清單。
// 按鈕位於 label 內，須阻止點擊同時勾選貼文。
const CAPTION_PREVIEW = 30;
const platformLabel = (platform: string) => platform === 'facebook' ? 'FB' : platform === 'threads' ? 'Threads' : platform === 'youtube' ? 'YouTube' : 'IG';
function PostCaption({ caption, onOpen }: { caption: string; onOpen: () => void }) {
  const chars = Array.from(caption || '');
  const long = chars.length > CAPTION_PREVIEW;
  return <span className="ideation-post-caption">
    <span className="ideation-caption-text">{!caption ? t('（無內文）') : long ? chars.slice(0, CAPTION_PREVIEW).join('') + '...' : caption}</span>
    {long && <button type="button" className="ideation-caption-more" aria-haspopup="dialog" onClick={event => { event.preventDefault(); event.stopPropagation(); onOpen(); }}>{t('[全文]')}</button>}
  </span>;
}

function PostDialog({ post, title, children, onClose }: { post: SourcePost; title: string; children: ReactNode; onClose: () => void }) {
  const dialog = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const trigger = document.activeElement as HTMLElement | null;
    dialog.current?.querySelector<HTMLButtonElement>('[data-close]')?.focus();
    // 在文件層監聽 Esc：「載入更多」用完消失時焦點會落到 body，仍要能關閉。
    const escape = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.preventDefault(); close.current(); } };
    document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('keydown', escape); if (trigger?.isConnected) trigger.focus(); };
  }, []);
  return <div className="ideation-modal-backdrop" onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
    <div ref={dialog} className="ideation-delete-dialog ideation-post-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId} onKeyDown={e => {
      if (e.key !== 'Tab') return;
      // 與 ConfirmDialog 相同範圍：留言勾選框也要能用 Tab 到達。
      const items = dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex="0"]');
      if (!items?.length) return;
      if (e.shiftKey && document.activeElement === items[0]) { e.preventDefault(); items[items.length - 1].focus(); }
      else if (!e.shiftKey && document.activeElement === items[items.length - 1]) { e.preventDefault(); items[0].focus(); }
    }}>
      <h2 id={titleId} className="confirm-heading">{title}</h2>
      <p className="ideation-dialog-meta"><span className="ideation-platform">{platformLabel(post.platform)}</span>{date(post.published_at)}</p>
      <div className="ideation-dialog-body">{children}</div>
      <div className="action-row"><button type="button" className="secondary" data-close onClick={onClose}>{t('關閉')}</button></div>
    </div>
  </div>;
}

export function IdeationSettings({ brandId, canEdit }: { brandId: string; canEdit: boolean }) {
  const [config, setConfig] = useState<Config | null>(null), [topics, setTopics] = useState('');
  const [history, setHistory] = useState<{ at: string; actor: string; after: Config }[]>([]);
  const [busy, setBusy] = useState(false), [message, setMessage] = useState(''), [error, setError] = useState('');
  useEffect(() => { const c = new AbortController(); if (brandId) api<{ config: Config; history: typeof history }>('/ideation/settings?brand_id=' + brandId, { signal: c.signal }).then(v => { setConfig(v.config); setTopics(v.config.topics.join('\n')); setHistory(v.history); }).catch(e => { if (!c.signal.aborted) setError(failure(e)); }); return () => c.abort(); }, [brandId]);
  async function save() {
    setBusy(true); setError(''); setMessage('');
    try { const result = await api<{ config: Config; history: typeof history }>('/ideation/settings?brand_id=' + brandId, { method: 'PUT', body: JSON.stringify({ ...config, topics: topics.split('\n').map(s => s.trim()).filter(Boolean) }) }); setConfig(result.config); setHistory(result.history); setMessage(t('已儲存；主題變更後，下次發想會更新標註。')); }
    catch (e) { setError(failure(e)); } finally { setBusy(false); }
  }
  return <section className="settings-section workspace-subsection ideation-settings"><h3>{t('例會與觀眾主題')}</h3><p className="muted">{t('例會前一天 18:00（台北）自動發想；背景使用 Gemini API。')}</p>
    {error && <p role="alert" className="error" title={error}>{aiErrorMessage(error)}</p>}{message && <p role="status" className="success-note">{message}</p>}
    {config && <form onSubmit={e => { e.preventDefault(); void save(); }}>
      <label><input type="checkbox" disabled={!canEdit || busy} checked={config.enabled} onChange={e => setConfig({ ...config, enabled: e.target.checked })} />{t('啟用例會前自動發想')}</label>
      <div className="policy-grid"><label>{t('例會星期')}<select disabled={!canEdit || busy} value={config.weekday ?? ""} onChange={e => setConfig({ ...config, weekday: e.target.value === '' ? null : +e.target.value })}><option value="">{t('尚未設定')}</option>{[t('星期一'), t('星期二'), t('星期三'), t('星期四'), t('星期五'), t('星期六'), t('星期日')].map((s, i) => <option key={i} value={i}>{s}</option>)}</select></label>
        <label>{t('例會時間')}<input type="time" required={config.enabled} disabled={!canEdit || busy} value={config.time ?? ""} onChange={e => setConfig({ ...config, time: e.target.value })} /></label>
        <label>{t('頻率')}<select disabled={!canEdit || busy} value={config.interval_weeks} onChange={e => setConfig({ ...config, interval_weeks: +e.target.value })}><option value={1}>{t('每週')}</option><option value={2}>{t('隔週')}</option></select></label>
        {config.interval_weeks === 2 && <label>{t('隔週起算日')}<input type="date" required disabled={!canEdit || busy} value={config.anchor_date || ''} onChange={e => setConfig({ ...config, anchor_date: e.target.value })} /></label>}</div>
      <label>{t('主題清單（每行一項，須保留「其他」）')}<textarea rows={8} disabled={!canEdit || busy} value={topics} onChange={e => setTopics(e.target.value)} /></label>
      {canEdit && <div className="ideation-actions"><button className="primary" disabled={busy}>{t('儲存例會與主題')}</button></div>}
      <details><summary>{t('設定修改紀錄（{count}）', { count: history.length })}</summary>{history.map((h, i) => <p key={i}>{date(h.at)} · {h.actor}<br />{h.after.topics.join('、')}</p>)}</details>
    </form>}
  </section>;
}

function ExportFiles({ exports, kind, id }: { exports?: Exports; kind: 'reports' | 'scripts'; id: number }) {
  return <div className="ideation-exports" aria-label={t('匯出檔案')}>{exports?.error && <p role="alert" className="error">{exports.error}</p>}
    {(exports?.files.length ? exports.files : [{ format: 'md', available: false }, { format: 'docx', available: false }]).map(f => <div className="export-card" key={f.format}>
      {f.available ? <a className="secondary" href={`/api/ideation/${kind}/${id}/download/${f.format}`} download>{t('下載 {format}', { format: f.format === 'md' ? 'Markdown' : 'Word' })}</a> : <span className="ideation-chip">{t('{format} 尚未產生', { format: f.format === 'md' ? 'Markdown' : 'Word' })}</span>}</div>)}
  </div>;
}
function Quotes({ quotes, brandId, reportId, scriptId }: { quotes: Quote[]; brandId: number; reportId: number; scriptId?: number }) {
  return <div className="ideation-quotes">{quotes.map(q => { const href = quoteHref(q, brandId, reportId, scriptId); return <blockquote key={q.id}><p>{q.text}</p>{href ? <a href={href}>{platforms[q.platform] || q.platform} · {t('原話 #{id} →', { id: q.id })}</a> : <span>{t('原話 #{id}（來源已無法存取）', { id: q.id })}</span>}</blockquote>; })}</div>;
}

function DeleteDialog({ id, onClose, onDelete }: { id: number; onClose: () => void; onDelete: () => void }) {
  const dialog = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const trigger = document.activeElement as HTMLElement | null;
    dialog.current?.querySelector<HTMLButtonElement>('[data-cancel]')?.focus();
    return () => { if (trigger?.isConnected) trigger.focus(); };
  }, []);
  return <div className="ideation-modal-backdrop" onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
    <div ref={dialog} className="ideation-delete-dialog" role="dialog" aria-modal="true" aria-labelledby="ideation-delete-title" onKeyDown={e => {
      if (e.key === 'Escape') { e.preventDefault(); onClose(); }
      if (e.key === 'Tab') {
        const buttons = dialog.current?.querySelectorAll<HTMLButtonElement>('button');
        if (!buttons) return;
        if (e.shiftKey && document.activeElement === buttons[0]) { e.preventDefault(); buttons[buttons.length - 1].focus(); }
        else if (!e.shiftKey && document.activeElement === buttons[buttons.length - 1]) { e.preventDefault(); buttons[0].focus(); }
      }
    }}>
      <p id="ideation-delete-title">{t('刪除主題列表 #{id}？由此產生的腳本也會一併隱藏，已匯出的檔案不受影響。', { id })}</p>
      <div className="ideation-actions"><button className="primary danger" onClick={onDelete}>{t('刪除')}</button><button data-cancel className="secondary" onClick={onClose}>{t('取消')}</button></div>
    </div>
  </div>;
}

export function IdeationPage({ brand, brands, canEdit, canConfigure, onDraft }: { brand: string; brands: Brand[]; canEdit: boolean; canConfigure: boolean; onDraft: (id: number, brandId: number, created: boolean) => void }) {
  const [brandId, setBrandId] = useState(brand || String(brands[0]?.id || ''));
  const [reports, setReports] = useState<Report[]>([]), [report, setReport] = useState<Report | null>(null);
  const [selected, setSelected] = useState<number | null>(() => positiveId(new URLSearchParams(location.search).get('report_id')));
  const [scriptId, setScriptId] = useState<number | null>(() => positiveId(new URLSearchParams(location.search).get('script_id')));
  const restoredScript = useRef<number | null>(null);
  const deletedReports = useRef(new Set<number>());
  const previousBrand = useRef(brand);
  const [options, setOptions] = useState<{ provider: string; model: string; available: boolean }[]>([]);
  // 執行方式：已設定的 API 供應者，加上「交給 Agent 撰寫」（不呼叫任何 AI，由 Agent 接手）。
  const choices = [...options, { provider: agentProvider, model: '', available: true }];
  const [provider, setProvider] = useState(''), [start, setStart] = useState(''), [end, setEnd] = useState('');
  const [posts, setPosts] = useState<SourcePost[]>([]), [postIds, setPostIds] = useState<number[]>([]);
  const [postsLoadedKey, setPostsLoadedKey] = useState('');
  const [postPlatform, setPostPlatform] = useState('facebook');
  const [captionPost, setCaptionPost] = useState<SourcePost | null>(null);
  const [commentsPost, setCommentsPost] = useState<SourcePost | null>(null);
  const [excludedIds, setExcludedIds] = useState<number[]>([]);
  const [commentWindow, setCommentWindow] = useState(readCommentWindow);
  const { range: commentRange, from: commentFrom, to: commentTo } = commentWindow;
  const today = local(new Date().toISOString()).slice(0, 10);
  const commentsValid = commentRange !== 'custom' || (!!commentFrom && !!commentTo && commentFrom <= commentTo && commentTo <= today);
  const commentFields = { comment_range: commentRange, ...(commentRange === 'custom' ? { comment_from: commentFrom, comment_to: commentTo } : {}) };
  const postScope = `${brandId}:${start}:${end}`;
  const loadedScope = useRef('');
  const postsKey = `${postScope}:${commentRange}:${commentFrom}:${commentTo}`;
  const postsReady = postsLoadedKey === postsKey;
  const visiblePosts = posts.filter(p => p.platform === postPlatform);
  // Threads 只有在期間內真的有貼文時才多一個頁籤，FB／IG 的版面維持不變。
  const sourcePlatforms = ['facebook', 'instagram', ...['threads', 'youtube'].filter(platform => posts.some(p => p.platform === platform))];
  const visibleSelected = visiblePosts.filter(p => postIds.includes(p.id)).length;
  const previewQuery = new URLSearchParams({ ...commentFields, brand_id: brandId }).toString();
  const [scripts, setScripts] = useState<Script[]>([]), [script, setScript] = useState<Script | null>(null);
  // 腳本交給 Agent 撰寫的接手面板一次只展開一張主題卡。
  const [scriptHandoff, setScriptHandoff] = useState<number | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  // 輪詢失敗的訊息依請求種類記下；同種請求恢復成功時才清掉，且只清仍是那則的橫幅，不會蓋掉操作錯誤。
  const pollErrors = useRef<Record<string, string>>({});
  function pollFailed(kind: string, e: unknown) { const text = failure(e); pollErrors.current[kind] = text; setError(text); }
  function pollRecovered(kind: string) {
    const text = pollErrors.current[kind];
    if (!text) return;
    delete pollErrors.current[kind]; setError(current => current === text ? '' : current);
  }
  const [confirmingDelete, setConfirmingDelete] = useState<number | null>(null);
  const [drafts, setDrafts] = useState<{ id: number; report_id: number; idea_index: number; source: string; status: string }[]>([]);
  const [editing, setEditing] = useState<{ index: number; version: number; idea: Idea } | null>(null);
  useEffect(() => { setEditing(null); }, [selected]);
  const [message, setMessage] = useState('');
  const [submittingAt, setSubmittingAt] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now);
  const currentReport = report || reports.find(r => r.id === selected);
  // 每秒重繪只給 ReportTimer 用；awaiting_ideas 可能等一整天且不顯示計時，不必跟著重繪。
  const timing = !!submittingAt || reports.some(r => activeStatuses.includes(r.status)) || !!(report && activeStatuses.includes(report.status));
  useEffect(() => {
    if (!timing) return;
    setNow(Date.now());
    const interval = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, [timing]);
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    params.set('comment_range', commentRange);
    for (const [key, value] of [['comment_from', commentFrom], ['comment_to', commentTo]]) {
      if (commentRange === 'custom' && value) params.set(key, value); else params.delete(key);
    }
    history.replaceState(null, '', location.pathname + '?' + params + location.hash);
  }, [commentRange, commentFrom, commentTo]);
  useEffect(() => {
    const restore = () => setCommentWindow(readCommentWindow());
    window.addEventListener('popstate', restore);
    return () => window.removeEventListener('popstate', restore);
  }, []);
  useEffect(() => {
    setPostsLoadedKey(''); setConfirmingDelete(null); setMessage('');
    if (!canEdit || !brandId || !start || !end || start >= end || !commentsValid) return;
    const controller = new AbortController();
    const query = new URLSearchParams({ ...commentFields, brand_id: brandId, start_at: new Date(start + ':00+08:00').toISOString(), end_at: new Date(end + ':00+08:00').toISOString() });
    api<SourcePost[]>('/ideation/posts?' + query, { signal: controller.signal }).then(rows => {
      if (!controller.signal.aborted) {
        setPosts(rows);
        if (loadedScope.current !== postScope) {
          setPostIds(rows.map(p => p.id)); setExcludedIds([]); setCommentsPost(null); setCaptionPost(null);
          const count = (platform: string) => rows.filter(p => p.platform === platform).length;
          setPostPlatform(['instagram', 'threads', 'youtube'].reduce((best, platform) => count(platform) > count(best) ? platform : best, 'facebook'));
        }
        loadedScope.current = postScope; setPostsLoadedKey(postsKey);
      }
    }).catch(e => {
      // 失敗也要結束「載入貼文中」：清空清單與選取，避免控制項卡住或帶舊範圍的貼文送出。
      if (!controller.signal.aborted) { setError(failure(e)); setPosts([]); setPostIds([]); loadedScope.current = ''; setPostsLoadedKey(postsKey); }
    });
    return () => controller.abort();
  }, [brandId, start, end, postsKey]);
  useEffect(() => {
    setOptions([]);
    setProvider('');
    if (!canEdit || !brandId) return;
    const c = new AbortController();
    api<{ options: typeof options; draft_provider: string }>('/ai/execution-options?brand_id=' + brandId, { signal: c.signal }).then(v => {
      if (!c.signal.aborted) {
        let saved: unknown = null;
        try { saved = JSON.parse(localStorage.getItem(ideationChoiceKey(brandId)) || 'null'); } catch { /* 儲存不可用時仍可使用工作區預設。 */ }
        setOptions(v.options); setProvider(selectIdeationChoice(v.options, saved, v.draft_provider));
      }
    }).catch(e => { if (!c.signal.aborted) setError(failure(e)); });
    return () => c.abort();
  }, [brandId]);
  useEffect(() => {
    if (previousBrand.current !== brand) { chooseReport(null); history.replaceState(null, '', selectionQuery(location.search, brand, null, null)); }
    previousBrand.current = brand;
    setBrandId(brand || String(brands[0]?.id || ''));
  }, [brand, brands]);
  useEffect(() => {
    if (brandId && selected) history.replaceState(null, '', location.pathname + selectionQuery(location.search, brandId, selected, scriptId));
  }, [brandId, selected, scriptId]);
  useEffect(() => {
    if (!scriptId || selected) return;
    const c = new AbortController();
    api<Script>('/ideation/scripts/' + scriptId, { signal: c.signal }).then(s => { if (!c.signal.aborted) { setBrandId(String(s.brand_id)); setSelected(s.report_id); } }).catch(e => { if (!c.signal.aborted) setError(failure(e)); });
    return () => c.abort();
  }, [scriptId, selected]);
  useEffect(() => {
    setReport(null); setScript(null); setReports([]); setScripts([]); setError(''); pollErrors.current = {}; setStart(''); setEnd('');
    if (!brandId) return;
    return pollWhileVisible(async signal => { try { const v = await api<{ reports: Report[]; defaults: { start_at: string; end_at: string } }>('/ideation/reports?brand_id=' + brandId, { signal }); if (!signal.aborted) { const visible = v.reports.filter(r => !deletedReports.current.has(r.id)); setReports(visible); setSelected(current => current || (scriptId ? null : visible[0]?.id || null)); setStart(s => s || local(v.defaults.start_at)); setEnd(s => s || local(v.defaults.end_at)); pollRecovered('reports'); } } catch (e) { if (!signal.aborted) pollFailed('reports', e); } }, 3000);
  }, [brandId]);
  useEffect(() => {
    setReport(null); setScripts([]); setScript(null); setScriptHandoff(null); restoredScript.current = null;
    if (!selected) return;
    return pollWhileVisible(async signal => { try { const [r, s] = await Promise.all([api<Report>('/ideation/reports/' + selected, { signal }), api<Script[]>('/ideation/reports/' + selected + '/scripts', { signal })]); if (!signal.aborted && !deletedReports.current.has(selected) && String(r.brand_id) === brandId) { setReport(r); setScripts(s); pollRecovered('report'); } } catch (e) { if (!signal.aborted && !deletedReports.current.has(selected)) pollFailed('report', e); } }, 3000);
  }, [selected, brandId]);
  useEffect(() => {
    setDrafts([]);
    if (!brandId || !selected || !canEdit) return;
    return pollWhileVisible(async signal => {
      try {
        const rows = await api<typeof drafts>(`/publish/posts?brand_id=${brandId}&report_id=${selected}`, { signal });
        if (!signal.aborted) { setDrafts(rows.filter(p => p.source === 'ideation' && ['draft', 'scheduled', 'paused', 'missed'].includes(p.status))); pollRecovered('drafts'); }
      } catch (e) { if (!signal.aborted) pollFailed('drafts', e); }
    }, 3000);
  }, [brandId, selected, canEdit]);
  useEffect(() => {
    if (!scriptId || restoredScript.current === scriptId || !scripts.length) return;
    const match = scripts.find(s => s.id === scriptId);
    if (match) { setScript(match); restoredScript.current = scriptId; }
    else setError(t('此報告找不到指定腳本'));
  }, [scriptId, scripts]);
  function chooseReport(id: number | null) { setScriptId(null); setScript(null); restoredScript.current = null; setSelected(id); }
  function chooseProvider(value: string) {
    setProvider(value);
    try { localStorage.setItem(ideationChoiceKey(brandId), JSON.stringify(value)); } catch { /* 不影響本次手動選擇。 */ }
  }
  function chooseScript(s: Script) { setScriptId(s.id); setScript(s); restoredScript.current = s.id; }
  async function generate() {
    setBusy(true); setError(''); setSubmittingAt(new Date().toISOString()); setNow(Date.now());
    try {
      const r = await api<Report>('/ideation/reports?brand_id=' + brandId, { method: 'POST', body: JSON.stringify({
        ...commentFields, provider, post_ids: postIds, excluded_message_ids: excludedIds,
        start_at: new Date(start + ':00+08:00').toISOString(), end_at: new Date(end + ':00+08:00').toISOString(),
      }) });
      setReports(v => [r, ...v.filter(previous => previous.id !== r.id)]); setReport(r); chooseReport(r.id);
    } catch (e) { setError(failure(e)); } finally { setBusy(false); setSubmittingAt(null); }
  }
  async function recalculate() { setBusy(true); setError(''); setMessage(''); try { await api('/ideation/reclassify?brand_id=' + brandId, { method: 'POST', body: JSON.stringify({ ...commentFields, post_ids: postIds, excluded_message_ids: excludedIds, start_at: new Date(start + ':00+08:00').toISOString(), end_at: new Date(end + ':00+08:00').toISOString() }) }); setMessage(t('已排入所選留言範圍與貼文的主題重算。')); } catch (e) { setError(failure(e)); } finally { setBusy(false); } }
  async function createDraft(index: number) {
    if (!report || busy) return;
    const existing = drafts.find(p => p.report_id === report.id && p.idea_index === index);
    if (existing) { onDraft(existing.id, report.brand_id, false); return; }
    setBusy(true); setError('');
    try {
      const result = await api<{ post: { id: number; brand_id: number }; created: boolean }>('/publish/ideation-draft', {
        method: 'POST', body: JSON.stringify({ report_id: report.id, idea_index: index }),
      });
      onDraft(result.post.id, result.post.brand_id, result.created);
    } catch (e) { setError(failure(e)); } finally { setBusy(false); }
  }
  async function restoreIdea(index: number) {
    if (!report) return;
    const reportId = report.id;
    setBusy(true); setError('');
    try {
      const updated = await api<Report>(`/ideation/reports/${reportId}/ideas/${index}/restore`, { method: 'POST' });
      if (updated.id === reportId) { setReport(updated); setReports(rows => rows.map(r => r.id === reportId ? updated : r)); }
    } catch (e) { setError(failure(e)); } finally { setBusy(false); }
  }
  async function saveIdea(value: Pick<Idea, 'title' | 'hook' | 'angle' | 'visual' | 'keyword'>) {
    if (!report || !editing) return;
    setBusy(true); setError('');
    try {
      const updated = await api<Report>(`/ideation/reports/${report.id}/ideas/${editing.index}`, {
        method: 'PUT', body: JSON.stringify({ ...value, version: editing.version }),
      });
      setReport(updated); setReports(rows => rows.map(r => r.id === updated.id ? updated : r)); setEditing(null);
    } catch (e) { setError(failure(e)); } finally { setBusy(false); }
  }
  async function retry() { setBusy(true); setError(''); try { setReport(await api<Report>(`/ideation/reports/${selected}/retry`, { method: 'POST' })); } catch (e) { setError(failure(e)); } finally { setBusy(false); } }
  async function deleteReport() {
    if (busy || confirmingDelete === null) return;
    const id = confirmingDelete;
    setConfirmingDelete(null); setBusy(true); setError('');
    try {
      await api(`/ideation/reports/${id}`, { method: 'DELETE' });
      deletedReports.current.add(id);
      const remaining = reports.filter(r => r.id !== id);
      const next = remaining[Math.min(reports.findIndex(r => r.id === id), remaining.length - 1)]?.id ?? null;
      setReports(current => current.filter(r => r.id !== id));
      if (selected === id) {
        setReport(null); setScripts([]); chooseReport(next);
        history.replaceState(null, '', location.pathname + selectionQuery(location.search, brandId, next, null));
      }
    } catch (e) { setError(failure(e)); } finally { setBusy(false); }
  }
  return <section className="settings-page ideation-page"><PageHeader title={t('主題發想')} />{captionPost && <PostDialog post={captionPost} title={t('貼文全文')} onClose={() => setCaptionPost(null)}><div className="ideation-caption-body">{captionPost.caption}</div></PostDialog>}
    {commentsPost && <PostDialog post={commentsPost} title={t('貼文留言')} onClose={() => setCommentsPost(null)}><PostComments key={`${commentsPost.id}:${previewQuery}`} postId={commentsPost.id} query={previewQuery} excluded={excludedIds} disabled={busy} onToggle={(id, use) => setExcludedIds(ids => use ? ids.filter(x => x !== id) : [...ids, id])} /></PostDialog>}
    {error && <p className="error" role="alert" title={error}>{aiErrorMessage(error, provider)}</p>}

    {canEdit && options.length > 0 && !options.some(o => o.available) && <APISetupGuide canConfigure={canConfigure} />}
    {canEdit && <section className="settings-section ideation-form"><h2>{t('從留言發想主題')}</h2><p className="muted">{t('從所選貼文在留言範圍內的觀眾留言整理問題，產生主題。完成後自動保存 Markdown 與 Word。')}</p>
      <section className="ideation-step" aria-labelledby="ideation-step-posts"><h3 id="ideation-step-posts"><span className="ideation-step-number">1</span> {t('選擇貼文')}</h3>
      <div className="policy-grid ideation-source-fields"><label title={t('台北時間')}>{t('開始時間')}<input type="datetime-local" disabled={busy} value={start} onChange={e => setStart(e.target.value)} /></label><label title={t('台北時間，不含結束時間')}>{t('結束時間')}<input type="datetime-local" disabled={busy} value={end} onChange={e => setEnd(e.target.value)} /></label></div>
      <div className="ideation-platform-tabs" role="tablist" aria-label={t('貼文平台')}>{sourcePlatforms.map(platform => {
        const count = posts.filter(p => p.platform === platform).length;
        return <button key={platform} id={`ideation-tab-${platform}`} role="tab" aria-controls="ideation-post-panel" aria-selected={postPlatform === platform} tabIndex={postPlatform === platform ? 0 : -1} disabled={!postsReady || !count} onClick={() => setPostPlatform(platform)} onKeyDown={e => {
          if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) {
            e.preventDefault();
            const available = sourcePlatforms.filter(p => posts.some(row => row.platform === p));
            const next = e.key === 'Home' ? available[0] : e.key === 'End' ? available[available.length - 1] : available.find(p => p !== platform) || platform;
            setPostPlatform(next); document.getElementById(`ideation-tab-${next}`)?.focus();
          }
        }}>{platforms[platform]} ({count})</button>;
      })}</div>
      <div role="tabpanel" id="ideation-post-panel" aria-labelledby={`ideation-tab-${postPlatform}`}>
      <div className="ideation-posts" role="group" aria-label={t('選擇貼文')} aria-busy={!postsReady}>
        <div className="ideation-post-actions"><label><input type="checkbox" aria-label={t('選取全部貼文')} title={t('只選取目前平台的貼文')} disabled={busy || !postsReady || !visiblePosts.length} checked={!!visiblePosts.length && visibleSelected === visiblePosts.length} ref={el => { if (el) el.indeterminate = visibleSelected > 0 && visibleSelected < visiblePosts.length; }} onChange={e => setPostIds(ids => [...ids.filter(id => !visiblePosts.some(p => p.id === id)), ...(e.target.checked ? visiblePosts.map(p => p.id) : [])])} /><span>{t('已選 {selected} / {total} 篇', { selected: visibleSelected, total: visiblePosts.length })}</span></label><span>{t('範圍內留言 {count} 則', { count: visiblePosts.reduce((sum, p) => sum + p.comment_count, 0) })}</span></div>
        {postsReady && !posts.length && <p className="muted ideation-post-empty">{t('此期間沒有貼文')}</p>}
        {!postsReady && <p className="muted ideation-post-empty" role="status">{!commentsValid ? t('請填寫留言起訖日，起日 ≤ 迄日 ≤ 今天') : start && end && start >= end ? t('開始時間須早於結束時間') : t('載入貼文中…')}</p>}
        <div className="ideation-post-list">{visiblePosts.map(p => <div className="ideation-post-entry" key={p.id}><div className="ideation-post-row"><label className="ideation-post"><input type="checkbox" disabled={busy || !postsReady} checked={postIds.includes(p.id)} onChange={e => setPostIds(ids => e.target.checked ? [...ids, p.id] : ids.filter(id => id !== p.id))} /><span className="ideation-platform">{p.platform === 'facebook' ? 'FB' : p.platform === 'threads' ? 'Threads' : p.platform === 'youtube' ? 'YouTube' : 'IG'}</span><PostCaption caption={p.caption} onOpen={() => setCaptionPost(p)} /><span className="ideation-post-meta" title={t('已存留言總數：{count} 則', { count: p.total_comment_count ?? p.comment_count })}><span>{date(p.published_at)}</span><span className={p.comment_count > 0 ? 'has-comments' : ''}>{t('範圍內 {count} 則留言', { count: p.comment_count })}</span></span></label><button className="secondary ideation-post-expand" aria-label={t('查看貼文 {id} 留言', { id: p.id })} aria-haspopup="dialog" disabled={!postsReady || !commentsValid} onClick={() => setCommentsPost(p)}>▸</button></div></div>)}</div>
      </div></div></section>
      <section className="ideation-step" aria-labelledby="ideation-step-comments"><h3 id="ideation-step-comments"><span className="ideation-step-number">2</span> {t('留言範圍')}</h3>
      <div className="ideation-comment-window post-date-filter" role="group" aria-label={t('留言範圍')}>
        <SegmentedControl label={t('留言範圍')} options={commentRanges.map(range => ({ value: range, label: range === 'custom' ? t('自訂日期') : t('近 {days} 天', { days: range }) }))} value={commentRange} disabled={busy} onChange={range => setCommentWindow({ ...commentWindow, range })} />
        {commentRange === 'custom' && <div className="post-date-inputs">
          <label title={t('台北時間，包含起日')}>{t('留言起日')}<input type="date" value={commentFrom} max={commentTo || today} disabled={busy} onChange={e => setCommentWindow({ ...commentWindow, from: e.target.value })} /></label>
          <span className="ideation-date-separator" aria-hidden="true">～</span>
          <label title={t('台北時間，包含迄日')}>{t('留言迄日')}<input type="date" value={commentTo} min={commentFrom || undefined} max={today} disabled={busy} onChange={e => setCommentWindow({ ...commentWindow, to: e.target.value })} /></label>
        </div>}
      </div></section>
      <section className="ideation-step" aria-labelledby="ideation-step-generate"><h3 id="ideation-step-generate"><span className="ideation-step-number">3</span> {t('產生')}</h3>
      <p className="ideation-selection-summary">{t('將使用 FB {fb} 篇、IG {ig} 篇', { fb: posts.filter(p => p.platform === 'facebook' && postIds.includes(p.id)).length, ig: posts.filter(p => p.platform === 'instagram' && postIds.includes(p.id)).length })}{posts.some(p => p.platform === 'threads') && t('、Threads {count} 篇', { count: posts.filter(p => p.platform === 'threads' && postIds.includes(p.id)).length })}{posts.some(p => p.platform === 'youtube') && t('、YouTube {count} 篇', { count: posts.filter(p => p.platform === 'youtube' && postIds.includes(p.id)).length })}{t('貼文、')}{commentRange === 'custom' ? t('{from} 至 {to}的留言', { from: commentFrom || t('留言起日'), to: commentTo || t('留言迄日') }) : t('近 {days} 天的留言', { days: commentRange })}{excludedIds.length > 0 && t('（已排除 {count} 則）', { count: excludedIds.length })}</p>
      {postsReady && postIds.length > 0 && posts.filter(p => postIds.includes(p.id)).every(p => p.comment_count === 0) && <p className="ideation-notice warning ideation-no-comments" role="status">{t('所選貼文在此留言範圍內目前沒有留言。送出後會先抓取最新留言，仍沒有留言就不會產生主題。')}</p>}
      <div className="ideation-execution-row"><label>{t('執行方式')}<select aria-label={t('執行方式')} disabled={busy || !options.length} value={provider} onChange={e => chooseProvider(e.target.value)}>{choices.map(o => <option key={o.provider} value={o.provider} disabled={!o.available}>{executionLabel(o.provider)}{o.available ? '' : t('（未配置）')}</option>)}</select></label>
      <div className="ideation-actions">{canEdit && <><button className="secondary" disabled={busy || !postsReady || !postIds.length || !brandId || !start || !end} onClick={recalculate}>{t('重新標註所選留言')}</button><button className="primary" disabled={busy || !postsReady || !postIds.length || !brandId || !start || !end || !choices.some(o => o.provider === provider && o.available)} onClick={generate}>{busy ? t('處理中…') : t('立即發想')}</button></>}{message && <span role="status" className="success-note">{message}</span>}
      {submittingAt ? <span className="ideation-timer" role="timer">{t('抓取留言中 · 已執行 {duration}', { duration: elapsed(submittingAt, now) })}</span> : currentReport && activeStatuses.includes(currentReport.status) && <ReportTimer report={currentReport} now={now} />}</div>
      </div>
      </section>
    </section>}
    <section className="settings-section"><h2>{t('主題列表（{count}）', { count: reports.length })}</h2>{!reports.length && <p className="muted">{t('尚無報告。設定例會後自動產生，也可立即發想。')}</p>}<div className="ideation-actions report-history">{reports.map(r => <div className="report-row" key={r.id} data-selected={selected === r.id}><button className="report-select" aria-current={selected === r.id ? 'true' : undefined} onClick={() => chooseReport(r.id)}>#{r.id} · {date(r.created_at)}<span className="report-row-state"><span className={`report-status ${r.status === 'ready' ? 'ready' : r.status === 'failed' ? 'failed' : 'pending'}`}>{statusLabel(selected === r.id && report ? report : r)}</span><AgentSourceChip source={r.source} /><ReportTimer report={selected === r.id && report ? report : r} now={now} compact /></span></button>{canEdit && <button className="primary danger" aria-label={t('刪除主題列表 #{id}', { id: r.id })} disabled={busy || activeStatuses.includes(r.status)} title={activeStatuses.includes(r.status) ? t('報告產生中，完成後才能刪除') : undefined} onClick={() => setConfirmingDelete(r.id)}>{t('刪除')}</button>}</div>)}</div></section>
    {confirmingDelete !== null && <DeleteDialog id={confirmingDelete} onClose={() => setConfirmingDelete(null)} onDelete={() => void deleteReport()} />}
    {report && <><section className="settings-section"><div className="report-heading"><h2>{t('報告 #{id} · {status}', { id: report.id, status: statusLabel(report) })}</h2><div className="report-heading-meta"><AgentSourceChip source={report.source} /><ReportTimer report={report} now={now} /></div></div><p>{t('貼文期間：{start} 至 {end}（台北，不含結束時間）', { start: date(report.start_at), end: date(report.end_at) })}<br />{t('留言範圍：{start} 至 {end}（台北，不含結束時間）', { start: date(report.data?.comment_start || report.start_at), end: date(report.data?.comment_end || report.end_at) })}</p><ExclusionNote excluded={report.data?.excluded_message_ids || []} agent={report.data?.agent_exclusions || []} />{report.error && <p className="error" title={report.error}>{aiErrorMessage(report.error, report.provider)}</p>}{report.can_retry && canEdit && <button className="primary" disabled={busy} onClick={retry}>{t('重試此報告')}</button>}
      {report.status === 'awaiting_ideas' ? <><p className="agent-awaiting" role="status">{t('證據已彙整。請在 Claude Code 用 /mwb:ideas，或在其他 Agent 使用 get_guide("ideas") 接手，24 小時內存回主題。')}</p>{canEdit && <AgentHandoff slash={t('/mwb:ideas 接手主題報告 #{id}', { id: report.id })} plain={t('請用 mwb 工作檯的 get_guide("ideas") 接手主題報告 #{id}（report_id={id}）。', { id: report.id })} />}</> : <ExportFiles exports={report.exports} kind="reports" id={report.id} />}{report.data?.notice && <p className="legacy-note ideation-notice warning">{report.data.notice}</p>}{report.data?.quote_note && <p className="ideation-notice">{report.data.quote_note}</p>}{report.data?.empty && <p className="ideation-notice">{t('此期間沒有可引用的觀眾文字，未生成主題。')}</p>}{report.data?.comparison_partial && <p className="ideation-notice warning">{t('前期有部分時間早於所選貼文發佈，變化僅供參考')}</p>}</section>
      {goals.map(goal => { const ideas = (report.data?.ideas || []).map((idea, index) => ({ idea, index })).filter(({ idea }) => idea.goal === goal); return <section className="ideation-goal" data-goal={goal} key={goal} aria-label={goalLabel(goal)}><h2>{goalLabel(goal)} <span className="muted">{t('{count} 題', { count: ideas.length })}</span></h2><div className="ideation-grid">{ideas.map(({ idea, index }) => {
        const group = report.data?.groups?.find(g => g.topic === idea.topic);
        const quotes = (group?.quotes || []).filter(q => idea.quote_ids.includes(q.id));
        const cardScript = scripts.find(s => s.topic_index === index);
        const hasDraft = drafts.some(p => p.report_id === report.id && p.idea_index === index);
        return <article className="settings-section ideation-card" key={index} data-index={index}>
          <div className="idea-card-heading"><span className="idea-number">#{index + 1}</span>{idea.regenerated && <span className="ideation-chip">{t('已重新生成')}</span>}{idea.extended_from !== undefined && <span className="ideation-chip">{t('延伸自 #{index}', { index: idea.extended_from })}</span>}{canEdit && <span className="idea-card-tools"><button className="secondary small" disabled={busy || report.status !== 'ready' || !!editing} onClick={() => setEditing({ index, version: report.data?.ideas_revision || 1, idea })}>{t('編輯')}</button></span>}</div>
          <div className="ideation-tags"><span className="ideation-chip ideation-type">{goalLabel(idea.goal)}</span><span className="ideation-chip">{idea.element}</span><span className="muted">{idea.topic}</span>{idea.edited && <span className="ideation-chip idea-edited">{t('已編輯')}</span>}{!idea.quote_ids.length && <span className="ideation-chip" title={t('證據不足，依主題延伸')}>{t('延伸主題')}</span>}</div>
          {editing?.index === index ? <IdeaEditor key={report.id + ':' + index} idea={editing.idea} busy={busy || report.status !== 'ready'} onSave={value => void saveIdea(value)} onCancel={() => setEditing(null)} /> : <>
          <h3 title={idea.title}>{idea.title}</h3><dl className="ideation-fields"><div><dt>{t('開場')}</dt><dd className="ideation-hook">{idea.hook}</dd></div><div><dt>{t('切角')}</dt><dd>{idea.angle}</dd></div><div><dt>{t('可拍畫面')}</dt><dd>{idea.visual}</dd></div></dl>
          <div className="ideation-tags" aria-label={t('關鍵字')}><span>{t('關鍵字')}</span>{idea.keyword.split(/[、，,；;\s]+/).filter(Boolean).map((keyword, i) => <span className="ideation-chip" key={i}>{keyword}</span>)}</div>
          </>}
          {!!quotes.length && <details><summary>{t('原話（{count}）', { count: quotes.length })}</summary><Quotes quotes={quotes} brandId={report.brand_id} reportId={report.id} /></details>}
          {canEdit && editing?.index !== index && <div className="idea-card-actions">{cardScript && <button className="secondary" onClick={() => chooseScript(cardScript)}>{t('查看腳本')}</button>}<button className="secondary" disabled={busy || report.status !== 'ready' || !!editing} onClick={() => void createDraft(index)}>{hasDraft ? t('開啟發佈草稿') : t('建立發佈草稿')}</button><button className="secondary" aria-expanded={scriptHandoff === index} disabled={report.status !== 'ready'} onClick={() => setScriptHandoff(v => v === index ? null : index)}>{t('交給 Agent 寫腳本')}</button></div>}
          {canEdit && editing?.index !== index && scriptHandoff === index && report.status === 'ready' && <AgentHandoff slash={t('/mwb:script 為主題報告 #{id} 第 {number} 題寫腳本', { id: report.id, number: index + 1 })} plain={t('請用 mwb 工作檯的 get_guide("script") 為主題報告 #{id}（report_id={id}）第 {number} 題（topic_index={index}）撰寫腳本。', { id: report.id, number: index + 1, index })} />}
          {!!report.data?.ideas_history?.[String(index)]?.length && canEdit && editing?.index !== index && <button className="secondary idea-restore" disabled={busy || report.status !== 'ready' || !!editing} onClick={() => void restoreIdea(index)}>{t('還原上一版')}</button>}
        </article>;
      })}</div></section>; })}
    </>}
    {!!scripts.length && <section className="settings-section"><h2>{t('腳本版本')}</h2><div className="ideation-actions">{scripts.map(s => <button className="secondary" key={s.id} onClick={() => chooseScript(s)}>#{s.id} {s.content.title} · {t('第 {version} 版', { version: s.version })}</button>)}</div></section>}
    {script && <ScriptEditor key={script.id + '-' + script.version} script={script} canEdit={canEdit} onSaved={s => { setScript(s); setScripts(v => v.map(x => x.id === s.id ? s : x)); }} />}
  </section>;
}

function IdeaEditor({ idea, busy, onSave, onCancel }: { idea: Idea; busy: boolean; onSave: (value: Pick<Idea, 'title' | 'hook' | 'angle' | 'visual' | 'keyword'>) => void; onCancel: () => void }) {
  const [value, setValue] = useState({ title: idea.title, hook: idea.hook, angle: idea.angle, visual: idea.visual, keyword: idea.keyword });
  const fields = [['title', t('標題')], ['hook', t('開場')], ['angle', t('切角')], ['visual', t('可拍畫面')], ['keyword', t('關鍵字')]] as const;
  return <form className="idea-editor" aria-label={t('編輯主題')} onSubmit={e => { e.preventDefault(); onSave(value); }}>
    {fields.map(([key, label]) => <label key={key}>{label}<textarea aria-label={label} rows={2} required maxLength={1000} value={value[key]} disabled={busy} onChange={e => setValue({ ...value, [key]: e.target.value })} /></label>)}
    <div className="action-row"><button className="primary" disabled={busy || Object.values(value).some(text => !text.trim())}>{t('儲存')}</button><button className="secondary" type="button" disabled={busy} onClick={onCancel}>{t('取消')}</button></div>
  </form>;
}

const closingLabels = [t('品牌固定結尾口號'), t('拍攝備註'), t('需要的授權')];
function ScriptEditor({ script, canEdit, onSaved }: { script: Script; canEdit: boolean; onSaved: (s: Script) => void }) {
  const [content, setContent] = useState(script.content), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [oldVersion, setOldVersion] = useState('');
  const dirty = JSON.stringify(content) !== JSON.stringify(script.content);
  useEffect(() => { const leaving = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = ''; } }; window.addEventListener('beforeunload', leaving); return () => window.removeEventListener('beforeunload', leaving); }, [dirty]);
  function field<K extends keyof Content>(key: K, value: Content[K]) { setContent(c => ({ ...c, [key]: value })); }
  async function save() { setBusy(true); setError(''); try { onSaved(await api<Script>('/ideation/scripts/' + script.id, { method: 'PUT', body: JSON.stringify({ version: script.version, content }) })); } catch (e) { setError(failure(e)); } finally { setBusy(false); } }
  return <section className="settings-section script-editor"><div className="script-heading"><h2>{t('腳本編輯 · 第 {version} 版', { version: script.version })}</h2><AgentSourceChip source={script.source} /></div><p className="legacy-note">{script.notice}</p><p className={script.review.passed && !dirty ? 'success-note' : 'review-reason'}>{dirty ? t('已修改，尚未重新檢查') : script.review.passed ? t('檢查通過，仍需品牌覆核') : t('檢查未通過，請修改後重檢')}</p>{!dirty && script.review.reasons.map((r, i) => <p className="review-reason" key={i}>{r}</p>)}{error && <p className="error" role="alert" title={error}>{aiErrorMessage(error)}</p>}
    <ExportFiles exports={script.exports} kind="scripts" id={script.id} /><Quotes quotes={script.quotes} brandId={script.brand_id} reportId={script.report_id} scriptId={script.id} /><form onSubmit={e => { e.preventDefault(); void save(); }}>
      <label>{t('主題')}<input value={content.title} disabled={!canEdit || busy} onChange={e => field('title', e.target.value)} /></label><div className="policy-grid"><label>{t('目標類型')}<select disabled={!canEdit || busy} value={content.goal} onChange={e => field('goal', e.target.value)}>{['流量型', '變現型', '引流型'].map(g => <option key={g} value={g}>{goalLabel(g)}</option>)}</select></label><label>{t('片長（秒）')}<input type="number" min={5} max={300} disabled={!canEdit || busy} value={content.duration_seconds} onChange={e => field('duration_seconds', +e.target.value)} /></label></div>
      <label>{t('開頭鉤子')}<textarea rows={3} value={content.hook} disabled={!canEdit || busy} onChange={e => field('hook', e.target.value)} /></label>
      {content.shots.map((shot, i) => <fieldset className="script-shot" key={i}><legend>{t('鏡號 {number}', { number: shot.number })}</legend><div className="policy-grid">{(['visual', 'dialogue', 'subtitle', 'sound', 'b_roll'] as const).map((key, j) => <label key={key}>{[t('畫面'), t('台詞或旁白'), t('字幕'), t('音效（含 ASMR）'), 'B-roll'][j]}<textarea rows={3} disabled={!canEdit || busy} value={shot[key]} onChange={e => field('shots', content.shots.map((s, n) => n === i ? { ...s, [key]: e.target.value } : s))} /></label>)}<label>{t('機位')}<select disabled={!canEdit || busy} value={shot.camera} onChange={e => field('shots', content.shots.map((s, n) => n === i ? { ...s, camera: e.target.value } : s))}>{['POV', '側拍', 'POV／側拍'].map(c => <option key={c} value={c}>{cameraLabel(c)}</option>)}</select></label><label>{t('鏡頭秒數')}<input type="number" min={1} max={120} disabled={!canEdit || busy} value={shot.seconds} onChange={e => field('shots', content.shots.map((s, n) => n === i ? { ...s, seconds: +e.target.value } : s))} /></label></div>{canEdit && content.shots.length > 1 && <button className="secondary" type="button" disabled={busy} onClick={() => { const shots = content.shots.filter((_, n) => n !== i).map((s, n) => ({ ...s, number: n + 1 })); setContent(c => ({ ...c, shots, duration_seconds: shots.reduce((n, s) => n + s.seconds, 0) })); }}>{t('移除此鏡')}</button>}</fieldset>)}
      {canEdit && <button className="secondary" type="button" disabled={busy || content.shots.length >= 20} onClick={() => { const shots = [...content.shots, { number: content.shots.length + 1, visual: '', camera: '側拍', dialogue: '', subtitle: '', sound: '', seconds: 5, b_roll: '' }]; setContent(c => ({ ...c, shots, duration_seconds: shots.reduce((n, s) => n + s.seconds, 0) })); }}>{t('新增分鏡')}</button>}
      {(['ending', 'notes', 'permissions'] as const).map((key, i) => <label key={key}>{closingLabels[i]}<textarea aria-label={closingLabels[i]} rows={3} disabled={!canEdit || busy} value={content[key]} onChange={e => field(key, e.target.value)} /></label>)}
      {canEdit && <button className="primary" disabled={busy}>{busy ? t('正在檢查與匯出…') : t('儲存版本並重新檢查')}</button>}
    </form><label>{t('歷史版本')}<select value={oldVersion} onChange={e => setOldVersion(e.target.value)}><option value="">{t('選擇歷史版本')}</option>{script.versions.map(v => <option key={v.revision} value={v.revision}>{t('第 {version} 版', { version: v.revision })} · {date(v.created_at)} · {v.actor}</option>)}</select></label>
    {oldVersion && <div className="script-history"><p>{t('以下為歷史內容；套用後仍須儲存與重檢。')}</p>{script.versions.filter(v => v.revision === +oldVersion).map(v => <article key={v.revision}><h3>{v.content.title}</h3><p>{goalLabel(v.content.goal)} · {t('{seconds} 秒', { seconds: v.content.duration_seconds })}</p><p>{t('開頭鉤子：{text}', { text: v.content.hook })}</p>{v.content.shots.map(shot => <div key={shot.number}><h3>{t('鏡號 {number}', { number: shot.number })} · {cameraLabel(shot.camera)} · {t('{seconds} 秒', { seconds: shot.seconds })}</h3><p>{t('畫面：{text}', { text: shot.visual })}</p><p>{t('台詞／旁白：{text}', { text: shot.dialogue })}</p><p>{t('字幕：{text}', { text: shot.subtitle })}</p><p>{t('音效：{text}', { text: shot.sound })}</p><p>{t('補充畫面：{text}', { text: shot.b_roll })}</p></div>)}<p>{t('品牌結尾：{text}', { text: v.content.ending })}</p><p>{t('拍攝備註：{text}', { text: v.content.notes })}</p><p>{t('需要的授權：{text}', { text: v.content.permissions })}</p></article>)}{canEdit && <button className="secondary" disabled={busy} onClick={() => { const v = script.versions.find(v => v.revision === +oldVersion); if (v) setContent(v.content); }}>{t('套用此版本供編輯')}</button>}</div>}
  </section>;
}

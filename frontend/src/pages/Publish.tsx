import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type { RefObject } from 'react';
import type { Brand, User } from '../api';
import { PageHeader } from './PageHeader';
import { SegmentedControl } from './SegmentedControl';
import { ConfirmDialog } from './ConfirmDialog';
import { PublishPreview } from './PublishPreview';
import { TIKTOK_IMAGE_REASON, checkComposer, defaultPlatformOptions, isShort, loadedPlatformOptions, overLimitReason, platformLabels, textBytes, textLength, youtubeTitle } from '../publishComposer';
import type { PlatformOptions, Rules } from '../publishComposer';
import { hasMarkdown, toUnicodeStyles } from '../markdownText';
import { locale, t } from '../i18n.ts';
import './publish.css';

type Platform = 'facebook' | 'instagram' | 'threads' | 'youtube' | 'tiktok';
type Format = 'video' | 'image' | 'carousel' | 'text' | 'story';
type Media = { size: number; id: number; name: string; mime: string; width: number; height: number; duration: number | null };
// YouTube 自訂縮圖：不是發佈素材，由伺服端另外保存與綁定。
type Thumbnail = { id: number; name: string; mime: string; size: number; width: number; height: number };
type Target = { platform: Platform; status: string; permalink: string | null; reason: string; deleted_at: string | null; presence_checked_at: string | null; detail?: { total_segments?: number; successful_segments?: number; segment_ids?: string[]; successful_stories?: number; total_stories?: number; failed_story?: number; video_id?: string; privacy_status?: string; publish_id?: string; inbox_state?: string; thumbnail?: { status: string; code?: string; reason?: string }; cover?: { status: string; code?: string; reason?: string } }; stories?: { position: number; media_id: number; published_at: string; final: boolean; metrics: Record<string, number> }[] };
type Presence = { checked: number; newly_deleted: number; restored: number; unresolved: { platform: Platform; reason: string }[] };
type Post = { source: 'manual' | 'ideation' | 'agent'; agent_source?: { agent: string } | null; publish_via?: string | null; report_id: number | null; idea_index: number | null; id: number; brand_id: number; format: Format; caption: string; captions: Partial<Record<Platform, string>>; platforms: Platform[]; facebook_unpublished: boolean; platform_options?: PlatformOptions; warnings?: string[]; media: Media[]; thumbnail?: Thumbnail | null; cover?: Thumbnail | null; facebook_cover?: Thumbnail | null; targets: Target[]; status: string; version: number; locked: boolean; scheduled_at: string | null; created_at: string; updated_at: string };

// 平台都不支援 Markdown：偵測到語法時提示，並可把粗體／斜體轉成 Unicode 字形。
function MarkdownHint({ text, disabled, onConvert }: { text: string; disabled: boolean; onConvert: (value: string) => void }) {
  if (!hasMarkdown(text)) return null;
  return <div className="notice warning publish-markdown-hint" role="status"><span>{t('這些平台不支援 Markdown，*、#、[] 等符號會原樣顯示；英文與數字可轉成 Unicode 粗體／斜體。')}</span><button className="secondary" disabled={disabled} onClick={() => onConvert(toUnicodeStyles(text))}>{t('轉成 Unicode 粗體／斜體')}</button></div>;
}

function AgentSource({ post, history = false }: { post: Post; history?: boolean }) {
  const name = history ? post.publish_via || post.agent_source?.agent : post.agent_source?.agent;
  return name ? <span className="agent-source-chip publish-agent-source">{t('來自 {name}', { name })}</span> : null;
}
type Check = { ok: boolean; supported: boolean; ready: boolean; reasons: string[]; warnings?: string[] };
type Options = { rules: Rules; default_platform_options: PlatformOptions; enabled: boolean; platforms: Record<Platform, { name: string; ready: boolean; reasons: string[]; hint?: string; cover_hint?: string }> };
type Form = Pick<Post, 'format' | 'caption' | 'captions' | 'platforms' | 'facebook_unpublished'> & { platform_options: PlatformOptions };
const labels = platformLabels;
const labelPrefix = new RegExp('^(' + Object.values(labels).join('|') + ')：\\s*');
type ComposerTab = 'shared' | Platform | 'youtube' | 'tiktok';
const composerTabs: ComposerTab[] = ['shared', 'facebook', 'instagram', 'threads', 'youtube', 'tiktok'];
const composerLabels = { shared: t('共用'), ...labels, youtube: 'YouTube', tiktok: 'TikTok' };
const supportedPlatform = (value: ComposerTab): value is Platform => value !== 'shared';
// TikTok 只把影片送到收件匣（收件匣 API 不收文案）：文案留在工作檯供複製到 App。
export const TIKTOK_CAPTION_NOTICE = t('收件匣不會帶入文案：送出後到發佈紀錄按「複製文案」，貼到 TikTok App 再發佈。');
const tiktokStates: Record<string, string> = { PROCESSING_UPLOAD: t('TikTok 處理中'), SEND_TO_USER_INBOX: t('已送到收件匣'), PUBLISH_COMPLETE: t('已在 App 發佈') };
const videoOnly = (p: Platform | 'shared') => p === 'youtube' || p === 'tiktok';
const privacyOptions = [{ value: 'public', label: t('公開') }, { value: 'unlisted', label: t('不公開') }, { value: 'private', label: t('私人') }] as const;
const privacyLabels = { public: t('公開'), unlisted: t('不公開'), private: t('私人') } as const;
const sizeLabel = (bytes: number) => bytes >= 1024 ** 2 ? (bytes / 1024 ** 2).toFixed(1) + ' MB' : Math.max(1, Math.round(bytes / 1024)) + ' KB';
// 確認視窗的 YouTube 摘要：公開狀態、兒童內容、縮圖與是否歸為 Shorts。
function youtubeSummary(row: Post) {
  const options = loadedPlatformOptions(row.platform_options).youtube, short = row.media.length === 1 && isShort(row.media[0]);
  return t('影片') + ' · ' + privacyLabels[options.privacy] + ' · ' + (options.made_for_kids ? t('兒童內容') : t('非兒童內容')) + ' · ' + (row.thumbnail && !short ? t('自訂縮圖') : t('自動縮圖')) + (short ? ' · Shorts' : '');
}
const formats = [{ value: 'video', label: t('影片') }, { value: 'image', label: t('圖片') }, { value: 'carousel', label: t('輪播') }, { value: 'text', label: t('純文字') }] as const;
// 各平台結果：等待與發佈中是進行中狀態（黃色），只有確定失敗才顯示紅色。
const targetLabels: Record<string, string> = { pending: t('等待發佈'), publishing: t('發佈中'), succeeded: t('成功'), failed: t('失敗') };
const targetTone = (status: string) => status === 'succeeded' ? 'ready' : status === 'failed' ? 'failed' : 'pending';
const storyMetricLabels: Record<string, string> = { views: t('觀看'), reach: t('觸及'), replies: t('回覆'), shares: t('分享'), navigation: t('導覽'), follows: t('追蹤'), profile_visits: t('個人檔案瀏覽') };
const states: Record<string, string> = { draft: t('草稿'), scheduled: t('排程中'), publishing: t('發佈中'), done: t('成功'), partial: t('部分成功'), failed: t('失敗'), missed: t('已錯過'), paused: t('已暫停'), cancelled: t('已取消') };
const blank = (): Form => ({ format: 'video', caption: '', captions: {}, platforms: [], facebook_unpublished: false, platform_options: defaultPlatformOptions() });
const taipei = (value: string) => new Date(value).toLocaleString(locale(), { timeZone: 'Asia/Taipei', hour12: false });
const localTime = (value: string) => new Date(new Date(value).getTime() + 8 * 3600000).toISOString().slice(0, 16);
// 已在平台刪除：成功的平台全部刪除（且整篇成功）為 all，其餘有刪除者為 some。
const goneState = (row: Post) => {
  const gone = row.targets.filter(t => t.status === 'succeeded' && t.deleted_at);
  return !gone.length ? '' : row.status === 'done' && gone.length === row.targets.filter(t => t.status === 'succeeded').length ? 'all' : 'some';
};
// 「存成 FB 草稿」的 Facebook 結果：存進 Business Suite 草稿匣、不發佈，紀錄上以「草稿」標示。
const hiddenFacebook = (row: Pick<Post, 'facebook_unpublished'>, platform: Platform) => platform === 'facebook' && row.facebook_unpublished;
const reason = (e: unknown) => e instanceof Error ? e.message : t('操作失敗，請重試');

// 輸入框下方即時提示從第幾個字開始超過上限，與發佈規則同一段文字。
function OverLimit({ label, text, limit }: { label: string; text: string; limit: number }) {
  const reason = overLimitReason(label, text, limit);
  return reason ? <p className="publish-reasons publish-over-limit" role="status">{reason}</p> : null;
}
export function Publish({ brand, brands, user, draftId, fromIdea, onDraftId, beforeLeave, onConnections }: { brand: string; brands: Brand[]; user: User; draftId: number | null; fromIdea: boolean; onDraftId: (id: number | null) => void; beforeLeave: RefObject<(() => Promise<boolean>) | null>; onConnections: () => void }) {
  const canEdit = user.role !== 'viewer';
  const [tab, setTab] = useState(canEdit ? 'new' : 'history');
  const [chosen, setChosen] = useState(brand);
  const brandId = brand || chosen || (brands.length === 1 ? String(brands[0].id) : '');
  const brandScope = useRef(brandId); brandScope.current = brandId;
  const [options, setOptions] = useState<Options | null>(null), [posts, setPosts] = useState<Post[]>([]);
  const [form, setForm] = useState<Form>(blank), [post, setPost] = useState<Post | null>(null);
  const current = useRef<Post | null>(null), fileInput = useRef<HTMLInputElement>(null);
  const [results, setResults] = useState<Partial<Record<Platform, Check>>>({});
  const [mode, setMode] = useState<'now' | 'scheduled'>('now'), [time, setTime] = useState('');
  const [working, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [checking, setChecking] = useState(false), [presence, setPresence] = useState<{ tone: 'success' | 'warning'; text: string } | null>(null);
  const [confirm, setConfirm] = useState<{ post: Post; retry: boolean; scheduled: string | null } | null>(null);
  const [switchConfirm, setSwitchConfirm] = useState(false), [cancelConfirm, setCancelConfirm] = useState<Post | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null), [reschedule, setReschedule] = useState<Post | null>(null);
  const [copied, setCopied] = useState<number | null>(null);
  // TikTok 收件匣不收文案：把 TikTok 文案（未覆寫則用共用文案）複製到剪貼簿，貼到 App。
  async function copyCaption(row: Post) {
    try { await navigator.clipboard.writeText(row.captions.tiktok ?? row.caption); setCopied(row.id); }
    catch { setError(t('無法複製文案，請手動選取文字')); }
  }
  const [loadedScope, setLoadedScope] = useState<string | null>(null);
  const [composerTab, setComposerTab] = useState<ComposerTab>('shared'), [previewPlatform, setPreviewPlatform] = useState<Platform>('facebook');
  const [thumbnailConfirm, setThumbnailConfirm] = useState<Post | null>(null);
  const [coverConfirm, setCoverConfirm] = useState<Post | null>(null);
  const thumbnailInput = useRef<HTMLInputElement>(null);
  const coverInput = useRef<HTMLInputElement>(null);
  const facebookCoverInput = useRef<HTMLInputElement>(null);
  // Threads 串文＝Threads 文案（第一則）＋各則回覆；各則獨立輸入、互不同步，也不自動分段（超過字數只標紅）。
  const repliesOf = (value: Form) => value.platform_options.threads.segments_custom ? value.platform_options.threads.segments.slice(1) : [];
  function normalize(value: Form): Form {
    if (value.format === 'story') return value;
    const segments = [value.captions.threads ?? value.caption, ...repliesOf(value)];
    return { ...value, platform_options: { ...value.platform_options, threads: { segments, segments_custom: true } } };
  }
  function updateForm(value: Form) { setForm(normalize(value)); }
  function changeReplies(replies: string[]) { updateForm({ ...form, platform_options: { ...form.platform_options, threads: { segments: [form.captions.threads ?? form.caption, ...replies], segments_custom: true } } }); }
  function changeCaption(platform: Platform, text: string) { updateForm({ ...form, captions: { ...form.captions, [platform]: text } }); }
  function restoreShared(platform: Platform) { const captions = { ...form.captions }; delete captions[platform]; updateForm({ ...form, captions }); }
  const scopeKey = brandId;
  const busy = working || loadedScope !== scopeKey;
  const generation = useRef(0), queue = useRef<Promise<unknown>>(Promise.resolve());
  function remember(value: Post) { current.current = value; setPost(value); onDraftId(value.id); setPosts(rows => rows.map(row => row.id === value.id ? value : row)); }
  async function reload() {
    setPosts(await api<Post[]>('/publish/posts' + (brandId ? '?brand_id=' + brandId : '')));
    if (brandId) setOptions(await api<Options>('/publish/options?brand_id=' + brandId));
  }
  useEffect(() => {
    if (current.current?.id === draftId && loadedScope === scopeKey) return;
    const controller = new AbortController();
    current.current = null; setPost(null); setForm({ ...blank(), ...(tab === 'story' ? { format: 'story' as const } : {}) }); setComposerTab(tab === 'story' ? 'facebook' : 'shared'); setResults({}); setOptions(null); setLoadedScope(null); setError(''); generation.current++;
    async function load() {
      const [rows, opts, selected] = await Promise.all([
        api<Post[]>('/publish/posts' + (brandId ? '?brand_id=' + brandId : ''), { signal: controller.signal }),
        brandId ? api<Options>('/publish/options?brand_id=' + brandId, { signal: controller.signal }) : null,
        draftId && canEdit ? api<Post>('/publish/posts/' + draftId, { signal: controller.signal }) : null,
      ]);
      if (controller.signal.aborted) return;
      if (selected && !brandId) { setChosen(String(selected.brand_id)); return; }
      if (selected && String(selected.brand_id) !== brandId) throw new Error(t('草稿品牌不符，請重新開啟'));
      setPosts(rows); setOptions(opts);
      if (selected) { edit(selected); if (fromIdea) setNotice(t('已從主題建立草稿，請上傳影片並確認平台')); }
      else if (opts) setForm({ ...blank(), ...(tab === 'story' ? { format: 'story' as const } : {}), platform_options: loadedPlatformOptions(opts.default_platform_options) });
      setLoadedScope(scopeKey);
    }
    void load().catch(e => { if (!controller.signal.aborted) { setError(reason(e)); setLoadedScope(scopeKey); } });
    return () => controller.abort();
  }, [brandId, draftId, canEdit]);
  const formRef = useRef(form); formRef.current = form;
  useEffect(() => {
    if (!posts.some(p => p.status === 'publishing')) return;
    const timer = window.setInterval(() => { void reload().catch(e => setError(reason(e))); }, 1500);
    return () => window.clearInterval(timer);
  }, [posts, brandId]);
  // 媒體上傳／移除也會遞增貼文 version；與存檔排同一佇列，之後的自動存檔才會帶最新版本而不 409。
  function serial<T>(action: () => Promise<T>): Promise<T> {
    const next = queue.current.catch(() => undefined).then(action); queue.current = next; return next;
  }
  async function persist(value = form): Promise<Post> {
    if (!brandId) throw new Error(t('請選擇品牌'));
    const scope = brandId;
    return serial(async () => {
      if (brandScope.current !== scope) throw new Error(t('品牌已變更，請重試'));
      const existing = current.current;
      const saved = await api<Post>('/publish/posts' + (existing ? '/' + existing.id : ''), {
        method: existing ? 'PUT' : 'POST', body: JSON.stringify({ ...normalize(value), ...(value.format === 'story' ? { platform_options: undefined } : {}), brand_id: Number(brandId),
          media_ids: existing?.media.map(m => m.id) || [], version: existing?.version || 1 }),
      });
      if (brandScope.current !== scope) throw new Error(t('品牌已變更，請重試'));
      remember(saved); return saved;
    });
  }
  useEffect(() => {
    setResults({});
    if (!brandId || !canEdit || !['new', 'story'].includes(tab) || loadedScope !== scopeKey) return;
    if (!current.current && !hasContent(form)) return;
    const id = ++generation.current;
    const timer = window.setTimeout(() => {
      // 只是開啟草稿、內容與已存版本相同時只重新檢查不存檔：存檔會遞增 version，
      // 讓 Agent 或其他分頁以剛讀到的版本 prepare_publish 時無故衝突。
      const saved = current.current && !dirty() ? Promise.resolve(current.current) : persist(form);
      void saved.then(p =>api<Record<Platform, Check>>('/publish/posts/' + p.id + '/check', { method: 'POST' }))
        .then(r => { if (generation.current === id) setResults(r); })
        .catch(e => { if (generation.current === id) setError(reason(e)); });
    }, 650);
    return () => { window.clearTimeout(timer); generation.current++; };
  }, [form, brandId, tab, canEdit, loadedScope, scopeKey]);
  function rowForm(row: Post): Form {
    const value: Form = { format: row.format, caption: row.caption, captions: row.captions, platforms: row.platforms, facebook_unpublished: row.facebook_unpublished, platform_options: loadedPlatformOptions(row.platform_options) };
    const first = value.platform_options.threads.segments[0];
    if (value.format === 'story' || !value.platform_options.threads.segments_custom || first === undefined || first === (value.captions.threads ?? value.caption)) return value;
    return { ...value, captions: { ...value.captions, threads: first } };
  }
  function hasContent(value: Form) { return repliesOf(value).length > 0 || !!value.caption.trim() || !!value.platforms.length || Object.values(value.captions).some(text => !!text?.trim()); }
  function dirty() {
    const row = current.current;
    return row ? JSON.stringify(formRef.current) !== JSON.stringify(rowForm(row)) : hasContent(formRef.current);
  }
  beforeLeave.current = async () => {
    if (working) return false;
    if (loadedScope !== scopeKey) return true;
    try { if (dirty()) await persist(formRef.current); await queue.current; return true; }
    catch (e) { setError(reason(e)); return false; }
  };
  async function switchTab(value: string) {
    if (value === tab) return;
    await perform(async () => { if (dirty()) await persist(); if (['new', 'story'].includes(value) && (value === 'story') !== (form.format === 'story')) {
        generation.current++; current.current = null; setPost(null); onDraftId(null);
        setForm({ ...blank(), ...(value === 'story' ? { format: 'story' as const } : {}) });
        setComposerTab(value === 'story' ? 'facebook' : 'shared'); setResults({}); setMode('now'); setTime('');
      }
      setTab(value); await reload(); });
  }
  useEffect(() => {
    const leaving = (e: BeforeUnloadEvent) => { if (dirty()) { e.preventDefault(); e.returnValue = ''; } };
    window.addEventListener('beforeunload', leaving);
    return () => { window.removeEventListener('beforeunload', leaving); beforeLeave.current = null; };
  }, []);
  async function newPost() {
    await perform(async () => {
      if (dirty()) await persist(); await queue.current;
      generation.current++; current.current = null; setPost(null); onDraftId(null);
      setForm({ ...blank(), ...(tab === 'story' ? { format: 'story' as const } : {}), platform_options: options?.default_platform_options ? loadedPlatformOptions(options.default_platform_options) : defaultPlatformOptions() }); setComposerTab(tab === 'story' ? 'facebook' : 'shared'); setResults({}); setMode('now'); setTime('');
    });
  }
  async function checkPresence() {
    setChecking(true); setError(''); setNotice(''); setPresence(null);
    try {
      const result = await api<Presence>('/publish/presence-check', { method: 'POST', body: JSON.stringify({ brand_id: Number(brandId) }) });
      await reload();
      const skipped = result.unresolved.map(item => labels[item.platform] + t('：') + item.reason).join(t('；'));
      setPresence({ tone: result.unresolved.length ? 'warning' : 'success', text: t('已檢查 {checked} 篇，{deleted} 篇已在平台刪除', { checked: result.checked, deleted: result.newly_deleted }) + (result.restored ? t('，{restored} 篇已恢復', { restored: result.restored }) : '') + (skipped ? t('；無法判定：{skipped}', { skipped }) : '') });
    } catch (e) { setError(reason(e)); } finally { setChecking(false); }
  }
  async function perform(action: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('');
    try { await action(); } catch (e) { setError(reason(e)); } finally { setBusy(false); }
  }
  async function upload(files: FileList | File[]) {
    const selected = Array.from(files);
    if (!selected.length) return;
    if (form.format === 'story' && selected.length + (post?.media.length || 0) > 10) { setError(t('限時動態最多 10 則')); return; }
    await perform(async () => {
      let saved = await persist();
      for (const file of selected) {
        const id = saved.id;
        saved = await serial(async () => { const row = await api<Post>('/publish/posts/' + id + '/media?filename=' + encodeURIComponent(file.name), {
          method: 'POST', body: file, headers: { 'Content-Type': 'application/octet-stream' },
        }); remember(row); return row; });
      }
      setResults(await api('/publish/posts/' + saved.id + '/check', { method: 'POST' }));
    });
  }
  // thumbnail＝YouTube 縮圖、cover＝Instagram Reels 封面、fb_cover＝Facebook 影片封面：都是每篇一張、新的取代舊的。
  async function uploadThumbnail(files: FileList | null, role: 'thumbnail' | 'cover' | 'fb_cover' = 'thumbnail') {
    const file = files?.[0];
    if (!file) return;
    await perform(async () => {
      const saved = await persist();
      const updated = await serial(async () => { const row = await api<Post>('/publish/posts/' + saved.id + '/media?role=' + role + '&filename=' + encodeURIComponent(file.name), { method: 'POST', body: file, headers: { 'Content-Type': 'application/octet-stream' } }); remember(row); return row; });
      setResults(await api('/publish/posts/' + updated.id + '/check', { method: 'POST' }));
    });
  }
  async function removeThumbnail(role: 'thumbnail' | 'cover' | 'fb_cover' = 'thumbnail') {
    const thumbnail = role === 'cover' ? post?.cover : role === 'fb_cover' ? post?.facebook_cover : post?.thumbnail;
    if (!post || !thumbnail) return;
    await perform(async () => {
      const saved = await serial(async () => { const row = await api<Post>('/publish/posts/' + post.id + '/media/' + thumbnail.id, { method: 'DELETE' }); remember(row); return row; });
      setResults(await api('/publish/posts/' + saved.id + '/check', { method: 'POST' }));
    });
  }
  async function reapplyCover(row: Post) {
    await perform(async () => { await api('/publish/posts/' + row.id + '/facebook-cover', { method: 'POST', body: JSON.stringify({ confirmed: true }) }); await reload(); });
  }
  async function reapplyThumbnail(row: Post) {
    await perform(async () => { await api('/publish/posts/' + row.id + '/youtube-thumbnail', { method: 'POST', body: JSON.stringify({ confirmed: true }) }); await reload(); });
  }
  async function confirmation(row?: Post, retry = false, scheduled: string | null = null) {
    await perform(async () => {
      const saved = row || await persist();
      const when = scheduled || (!row && mode === 'scheduled' ? new Date(time + '+08:00').toISOString() : null);
      setConfirm({ post: saved, retry, scheduled: when });
    });
  }
  async function send() {
    const snapshot = confirm; if (!snapshot) return; setConfirm(null);
    await perform(async () => {
      await api('/publish/posts/' + snapshot.post.id + (snapshot.retry ? '/retry' : '/submit'), {
        method: 'POST', body: JSON.stringify({ confirmed: true, version: snapshot.post.version, scheduled_at: snapshot.scheduled }),
      });
      current.current = null; setPost(null); onDraftId(null); setForm(blank());
      setTab(snapshot.scheduled ? 'scheduled' : 'history'); await reload();
    });
  }
  function edit(row: Post) {
    remember(row); setForm(rowForm(row)); setComposerTab('shared');
    setMode(row.scheduled_at ? 'scheduled' : 'now'); setTime(row.scheduled_at ? localTime(row.scheduled_at) : ''); setTab(row.format === 'story' ? 'story' : 'new'); if (row.format === 'story') setComposerTab('facebook');
  }
  // 已鎖定，或 Facebook 已送出／發佈中（部分成功後重新排程再取消會回到草稿）時，公開方式不可再改。
  const facebookLocked = !!post?.locked || !!post?.targets.some(t => t.platform === 'facebook' && ['succeeded', 'publishing'].includes(t.status));
  const story = form.format === 'story';
  const activeTabs: ComposerTab[] = story ? ['facebook', 'instagram'] : composerTabs;
  const editorDisabled = busy || !!post?.locked || (story && !!post?.targets.some(t => t.detail?.successful_stories));
  const platformLocked = (p: Platform) => !!post?.locked || !!post?.targets.some(t => t.platform === p && (['succeeded', 'publishing'].includes(t.status) || (p === 'threads' && !!(t.detail?.successful_segments || t.detail?.segment_ids?.length)) || (p === 'youtube' && !!t.detail?.video_id)));
  const normalized = normalize(form);
  const localCheck = (p: Platform) => options?.rules ? checkComposer(p, form.format, form.captions[p] ?? form.caption, post?.media || [], normalized.platform_options, options.rules, form.facebook_unpublished, p === 'youtube' && post?.thumbnail ? { ...post.thumbnail, duration: null } : null, p === 'instagram' && post?.cover ? { ...post.cover, duration: null } : p === 'facebook' && post?.facebook_cover ? { ...post.facebook_cover, duration: null } : null) : { errors: [], warnings: [] };
  const ruleChecks = { facebook: localCheck('facebook'), instagram: localCheck('instagram'), threads: localCheck('threads'), youtube: localCheck('youtube'), tiktok: localCheck('tiktok') };
  const youtubeOptions = form.platform_options.youtube, youtubeCaption = form.captions.youtube ?? form.caption;
  const effectiveTitle = youtubeTitle(youtubeOptions.title, youtubeCaption), videoShort = form.format === 'video' && post?.media.length === 1 && isShort(post.media[0], options?.rules.youtube?.shorts_seconds);
  const captionWord = (p: Platform) => p === 'youtube' ? t('說明') : t('文案');
  const captionSize = (p: Platform, text: string) => p === 'youtube' ? t('{used}／{limit} 位元組', { used: textBytes(text).toLocaleString('en-US'), limit: (options?.rules.youtube?.caption ?? 5000).toLocaleString('en-US') }) : t('{count} 字', { count: textLength(text, p) });
  const setYoutube = (patch: Partial<typeof youtubeOptions>) => updateForm({ ...form, platform_options: { ...form.platform_options, youtube: { ...youtubeOptions, ...patch } } });
  // 後端原因帶「平台名：」前綴，去掉後才能和前端檢查去重；前綴清單取自 labels，新平台不會漏掉。
  // 後端檢查原因是繁中原文；先查翻譯，和已翻譯的前端檢查訊息才能去重。
  const platformErrors = (p: Platform) => [...new Set([...ruleChecks[p].errors, ...(results[p]?.reasons || [])].map(reason => t(reason.replace(labelPrefix, ''))))];
  // Threads 字數超限已顯示在各輸入框下方，分頁的錯誤清單不再重複列出。
  const inlineErrors = (p: Platform) => p === 'threads' ? normalized.platform_options.threads.segments.map((text, i) => overLimitReason(i ? t('回覆 {n}', { n: i }) : t('Threads 文案'), text, options?.rules.threads.caption ?? 500)) : [];
  const panelErrors = (p: Platform) => platformErrors(p).filter(reason => !inlineErrors(p).includes(reason));
  const valid = form.platforms.length > 0 && form.platforms.every(p => options?.platforms[p]?.ready && results[p]?.ok && !ruleChecks[p].errors.length);
  const disabledReason = !options?.enabled ? t('發佈功能尚未開啟') : !form.platforms.length ? t('請開啟要發佈的平台') : form.platforms.flatMap(p => platformErrors(p).map(e => labels[p] + t('：') + e)).join(t('；')) || (!valid ? t('檢查中') : mode === 'scheduled' && !time ? t('請選擇排程時間') : '');
  const activePlatform = supportedPlatform(composerTab) ? composerTab : null;
  const shownPlatform = composerTab === 'shared' ? (form.platforms.includes(previewPlatform) ? previewPlatform : form.platforms[0] || null) : activePlatform;
  const connected = activePlatform ? !!options?.platforms[activePlatform]?.ready : composerTab === 'shared';
  // 錯誤只在「立即發佈／排程」列上方列一次；Threads 字數超限已標在輸入框下方，這裡不重複。
  // 滑鼠提示（title）仍是完整原因。
  const ruleBlocked = !!options?.enabled && form.platforms.length > 0 && form.platforms.some(p => platformErrors(p).length > 0);
  // 在單一平台分頁只列該平台的錯誤（即使還沒開啟）；其他平台的錯誤由分頁紅點提示。共用分頁才列出全部已開啟平台。
  const listedPlatforms = activePlatform ? [activePlatform] : form.platforms;
  const listedErrors = listedPlatforms.flatMap(p => panelErrors(p).map(e => labels[p] + t('：') + e));
  const otherBlocked = form.platforms.filter(p => p !== activePlatform && platformErrors(p).length > 0);
  const blockedHint = activePlatform && otherBlocked.length ? t('請先修正 {platforms} 分頁的錯誤', { platforms: otherBlocked.map(p => labels[p]).join(t('、')) }) : t('請先修正上方標示的錯誤');
  const shownReason = !options?.enabled ? disabledReason : [...(form.platforms.length ? [] : [t('請開啟要發佈的平台')]), ...listedErrors].join(t('；')) || (ruleBlocked ? blockedHint : disabledReason);
  const lastCheck = Math.max(0, ...posts.flatMap(p => p.targets.map(t => t.presence_checked_at ? Date.parse(t.presence_checked_at) : 0)));
  const draggedMedia = useRef<number | null>(null);
  async function moveMedia(id: number, destination: number) {
    if (!post) return;
    await perform(async () => {
      const media = [...post.media], index = media.findIndex(m => m.id === id);
      if (index < 0 || index === destination) return;
      media.splice(destination, 0, media.splice(index, 1)[0]); remember({ ...post, media });
      const saved = await persist(); setResults(await api('/publish/posts/' + saved.id + '/check', { method: 'POST' }));
    });
  }
  function renderMedia() { return <div className="publish-step"><div className="publish-upload" onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); if (!editorDisabled) void upload(e.dataTransfer.files); }}><button className="secondary" disabled={editorDisabled || !brandId || (story && (post?.media.length || 0) >= 10)} onClick={() => fileInput.current?.click()}>{t('拖曳或點選上傳')}</button><input ref={fileInput} type="file" aria-label={t('上傳媒體')} accept="video/mp4,video/quicktime,image/jpeg,image/png" multiple={form.format === 'carousel' || story} hidden onChange={e => { if (e.target.files) void upload(e.target.files); e.target.value = ''; }} /></div>
        <div className="publish-media-list">{post?.media.map((m, i) => <div key={m.id} className="publish-media-row" draggable={!editorDisabled && story} onDragStart={e => { draggedMedia.current = m.id; e.dataTransfer.setData('text/plain', String(m.id)); }} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); e.stopPropagation(); const id = draggedMedia.current; draggedMedia.current = null; if (!editorDisabled && story && id != null) void moveMedia(id, i); }}>{m.mime.startsWith('image/') ? <img alt={m.name} src={'/api/publish/posts/' + post.id + '/media/' + m.id} /> : <video controls preload="metadata" src={'/api/publish/posts/' + post.id + '/media/' + m.id} />}<div><strong>{m.name}</strong><small>{m.width} × {m.height}{m.duration !== null && ' · ' + t('{seconds} 秒', { seconds: m.duration.toFixed(1) })}</small></div><div className="action-row">{(form.format === 'carousel' || story) && <><button className="secondary" disabled={editorDisabled || i === 0} onClick={() => void perform(async () => { const media = [...post.media]; [media[i - 1], media[i]] = [media[i], media[i - 1]]; remember({ ...post, media }); await persist(); })}>{t('上移')}</button><button className="secondary" disabled={editorDisabled || i === post.media.length - 1} onClick={() => void perform(async () => { const media = [...post.media]; [media[i + 1], media[i]] = [media[i], media[i + 1]]; remember({ ...post, media }); await persist(); })}>{t('下移')}</button></>}<button className="primary danger" disabled={editorDisabled} onClick={() => void perform(async () => { const saved = await serial(async () => { const row = await api<Post>('/publish/posts/' + post.id + '/media/' + m.id, { method: 'DELETE' }); remember(row); return row; }); setResults(await api('/publish/posts/' + saved.id + '/check', { method: 'POST' })); })}>{t('移除')}</button></div></div>)}</div></div>; }
  const rows = posts.filter(p => tab === 'drafts' ? p.status === 'draft' : tab === 'scheduled' ? ['scheduled', 'paused'].includes(p.status) : ['publishing', 'done', 'partial', 'failed', 'missed'].includes(p.status));
  return <section className="publish-page settings-page">
    <PageHeader title={t('發佈')} children={<div className="publish-switch">{user.role === 'admin' && brandId && <button className="secondary" disabled={busy || !options} onClick={() => setSwitchConfirm(true)}>{options?.enabled ? t('關閉發佈') : t('開啟發佈')}</button>}</div>} />
    {options && !options.enabled && <p className="notice warning">{t('發佈功能尚未開啟，貼文只能存成草稿')}</p>}
    <div className="publish-brand-row">{options && <ul className="publish-accounts" aria-label={t('發佈帳號')}>{Object.entries(options.platforms).filter(([p]) => tab !== 'story' || (p !== 'threads' && p !== 'youtube' && p !== 'tiktok')).map(([p, v]) => <li key={p} className={'publish-account ' + (v.ready ? 'ready' : 'off')} title={v.ready ? t('可發佈') : v.reasons.join(t('、'))}><span className="publish-account-dot" aria-hidden="true" /><span className="publish-account-platform">{labels[p as Platform]}</span><strong>{v.name}</strong>{!v.ready && <span className="sr-only">{t('（{reasons}）', { reasons: v.reasons.join(t('、')) || t('尚未就緒') })}</span>}</li>)}</ul>}</div>
    <div className="tabs publish-tabs" role="tablist" aria-label={t('發佈分頁')}>{(canEdit ? [['new', t('新增貼文')], ['story', t('限時動態')], ['drafts', t('草稿')], ['scheduled', t('排程中')], ['history', t('發佈紀錄')]] : [['history', t('發佈紀錄')]]).map(([value, label], index, all) => <button key={value} className="secondary" role="tab" id={'publish-tab-' + value} aria-controls={'publish-panel-' + value} aria-selected={tab === value} tabIndex={tab === value ? 0 : -1} onClick={() => void switchTab(value)} onKeyDown={e => { const offset = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0; if (offset || e.key === 'Home' || e.key === 'End') { e.preventDefault(); const next = e.key === 'Home' ? 0 : e.key === 'End' ? all.length - 1 : (index + offset + all.length) % all.length; void switchTab(all[next][0]); document.getElementById('publish-tab-' + all[next][0])?.focus(); } }}>{label}</button>)}</div>
    {error && <p className="notice danger" role="alert">{error}</p>}{notice && <p className="notice success" role="status">{notice}</p>}
    <div role="tabpanel" id={'publish-panel-' + tab} aria-labelledby={'publish-tab-' + tab}>
    {['new', 'story'].includes(tab) && canEdit ? <div className={'section-card publish-editor' + (story ? ' publish-story-editor' : '')} data-check-state={Object.keys(results).length ? 'checked' : 'pending'} aria-busy={busy || loadedScope !== scopeKey}>
      <div className="publish-editor-top">
      <div className="publish-editor-heading">{post && <span className="publish-record-id publish-editing-id">{t('編輯中 #{id}', { id: post.id })} · {states[post.status] || post.status}</span>}{post && <AgentSource post={post} />}<button className="secondary" disabled={busy} onClick={() => void newPost()}>{story ? t('新限時動態') : t('新貼文')}</button></div>
      <div className="publish-composer-tabs publish-platforms" role="tablist" aria-label={t('文案平台')}>{activeTabs.map((p, index) => {
        const platform = supportedPlatform(p) ? p : null, ready = p === 'shared' || !!(platform && options?.platforms[platform]?.ready);
        const errors = platform && ready && (!videoOnly(platform) || form.platforms.includes(platform)) ? platformErrors(platform) : [];
        return <div key={p} className={'publish-platform publish-composer-tab ' + (ready ? 'ready' : 'off')}>
          <button className="secondary" disabled={busy} role="tab" id={'composer-tab-' + p} aria-controls={'composer-panel-' + p} aria-selected={composerTab === p} tabIndex={composerTab === p ? 0 : -1} onClick={() => setComposerTab(p)} onKeyDown={e => {
            const offset = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
            if (offset || e.key === 'Home' || e.key === 'End') { e.preventDefault(); const next = e.key === 'Home' ? 0 : e.key === 'End' ? activeTabs.length - 1 : (index + offset + activeTabs.length) % activeTabs.length; setComposerTab(activeTabs[next]); document.getElementById('composer-tab-' + activeTabs[next])?.focus(); }
          }}>{composerLabels[p]}{errors.length > 0 && <span className="publish-tab-error" aria-hidden="true" title={errors.join(t('；'))} />}</button>
          {p !== 'shared' && <label className="publish-platform-heading publish-platform-toggle"><input type="checkbox" role="switch" aria-label={t('發佈到 {platform}', { platform: composerLabels[p] })} title={videoOnly(p) && form.format !== 'video' ? (p === 'tiktok' ? TIKTOK_IMAGE_REASON : t('YouTube 只支援影片')) : undefined} checked={!!platform && form.platforms.includes(platform)} disabled={editorDisabled || !ready || !!(platform && platformLocked(platform)) || (videoOnly(p) && form.format !== 'video')} onChange={e => { if (platform) updateForm({ ...form, platforms: e.target.checked ? [...form.platforms, platform] : form.platforms.filter(x => x !== platform), ...(platform === 'facebook' && !e.target.checked && !facebookLocked ? { facebook_unpublished: false } : {}) }); }} /><span className="sr-only">{composerLabels[p]}</span></label>}
        </div>;
      })}</div></div>
      <div className="publish-composer-panel" role="tabpanel" id={'composer-panel-' + composerTab} aria-labelledby={'composer-tab-' + composerTab}>
        {/* 非管理員的設定頁只有「我的帳號」，給連結只會落在錯的頁面，改文字請對方找管理員。 */}
        {!connected ? <div className="publish-disconnected"><p>{(activePlatform && options?.platforms[activePlatform]?.hint) || t('尚未連結')}</p>{user.role !== 'admin' ? <p>{t('請聯絡管理員連結平台')}</p> : <a className="secondary" href={'?view=settings&settings_tab=connections&brand_id=' + brandId + (post ? '&publish_post_id=' + post.id : '')} onClick={e => { if (!e.ctrlKey && !e.metaKey && !e.shiftKey && !e.altKey) { e.preventDefault(); onConnections(); } }}>{t('設定 → 平台連結')}</a>}</div> : <div className="publish-composer-grid">
          <div className="publish-composer-fields">
            {story ? <>{renderMedia()}{[...new Set(form.platforms.flatMap(p => ruleChecks[p].warnings))].map(w => <p className="notice warning" key={w}>{w}</p>)}</> : composerTab === 'shared' ? <>
              <div className="publish-step"><SegmentedControl compact label={t('貼文格式')} options={formats} value={form.format} disabled={editorDisabled} onChange={format => updateForm({ ...form, format, platforms: form.platforms.filter(p => !(format === 'text' && p === 'instagram') && !(format !== 'video' && videoOnly(p))) })} /></div>
      {form.format !== 'text' && renderMedia()}

              <div className="publish-step"><label>{t('主文案')} <small>{t('{count} 字', { count: textLength(form.caption, 'facebook') })}</small><textarea aria-label={t('主文案')} rows={8} value={form.caption} disabled={editorDisabled || (platformLocked('threads') && form.captions.threads === undefined)} onChange={e => updateForm({ ...form, caption: e.target.value })} /></label><MarkdownHint text={form.caption} disabled={editorDisabled || (platformLocked('threads') && form.captions.threads === undefined)} onConvert={value => updateForm({ ...form, caption: value })} /></div>
            </> : activePlatform === 'youtube' && form.format !== 'video' ? <p className="notice warning" role="status">{t('YouTube 只支援影片')}</p> : activePlatform === 'tiktok' && form.format !== 'video' ? <p className="notice warning" role="status">{TIKTOK_IMAGE_REASON}</p> : activePlatform && <>
              <div className="publish-caption-heading"><span>{options?.platforms[activePlatform]?.name}</span>{!form.platforms.includes(activePlatform) && <span className="status-badge neutral">{t('未開啟')}</span>}{form.captions[activePlatform] !== undefined && <button className="secondary" disabled={editorDisabled || platformLocked(activePlatform)} onClick={() => restoreShared(activePlatform)}>{t('還原為共用文案')}</button>}</div>
              {activePlatform === 'youtube' && <label>{t('YouTube 標題')} <small>{t('{count}／{limit} 字', { count: Array.from(effectiveTitle).length, limit: options?.rules.youtube?.title ?? 100 })}</small><input aria-label={t('YouTube 標題')} value={youtubeOptions.title} placeholder={effectiveTitle || t('標題')} disabled={editorDisabled || platformLocked('youtube')} onChange={e => setYoutube({ title: e.target.value })} /></label>}
              <label>{labels[activePlatform]} {captionWord(activePlatform)} <small className={activePlatform === 'threads' && textLength(form.captions.threads ?? form.caption) > (options?.rules.threads.caption ?? 500) ? 'publish-reasons' : undefined}>{captionSize(activePlatform, form.captions[activePlatform] ?? form.caption)}{activePlatform === 'threads' && '／' + (options?.rules.threads.caption ?? 500)}</small><textarea aria-label={labels[activePlatform] + ' ' + captionWord(activePlatform)} rows={6} value={form.captions[activePlatform] ?? form.caption} disabled={editorDisabled || platformLocked(activePlatform)} onChange={e => changeCaption(activePlatform, e.target.value)} /></label>{activePlatform === 'threads' && <OverLimit label={t('Threads 文案')} text={form.captions.threads ?? form.caption} limit={options?.rules.threads.caption ?? 500} />}<MarkdownHint text={form.captions[activePlatform] ?? form.caption} disabled={editorDisabled || platformLocked(activePlatform)} onConvert={value => changeCaption(activePlatform, value)} />
              {activePlatform === 'tiktok' && <p className="notice tiktok-caption-notice" role="note">{TIKTOK_CAPTION_NOTICE}</p>}
              {activePlatform === 'facebook' && <div className="publish-platform-options">{form.format === 'video' && <SegmentedControl compact label={t('Facebook 影片形式')} options={[{ value: 'feed', label: t('影片貼文') }, { value: 'reels', label: 'Reels' }]} value={form.platform_options.facebook.video_format} disabled={editorDisabled || facebookLocked} onChange={video_format => updateForm({ ...form, platform_options: { ...form.platform_options, facebook: { video_format } } })} />}<label className="publish-unpublished"><input type="checkbox" checked={form.facebook_unpublished} disabled={editorDisabled || facebookLocked} onChange={e => updateForm({ ...form, facebook_unpublished: e.target.checked })} />{t('存成 FB 草稿（不發佈，可在 Meta Business Suite 草稿編輯後再發）')}</label>{form.format === 'video' && <div className="publish-thumbnail publish-cover publish-facebook-cover"><span>{t('影片封面')}</span>{post?.facebook_cover && <img alt={post.facebook_cover.name} src={'/api/publish/posts/' + post.id + '/media/' + post.facebook_cover.id} />}<small>{post?.facebook_cover ? post.facebook_cover.name + ' · ' + sizeLabel(post.facebook_cover.size) : t('JPG／PNG · 8 MB 內 · 建議與影片同比例 · 未上傳則由 Facebook 自動選')}</small><div className="action-row"><button className="secondary" disabled={editorDisabled || facebookLocked || !brandId} onClick={() => facebookCoverInput.current?.click()}>{post?.facebook_cover ? t('更換封面') : t('上傳封面')}</button>{post?.facebook_cover && <button className="primary danger" disabled={editorDisabled || facebookLocked} onClick={() => void removeThumbnail('fb_cover')}>{t('移除封面')}</button>}</div><input ref={facebookCoverInput} type="file" aria-label={t('上傳 Facebook 影片封面')} accept="image/jpeg,image/png" hidden onChange={e => { void uploadThumbnail(e.target.files, 'fb_cover'); e.target.value = ''; }} />{options?.platforms.facebook?.cover_hint && <p className="notice publish-cover-hint" role="note">{options.platforms.facebook.cover_hint}</p>}</div>}</div>}
              {activePlatform === 'instagram' && form.format === 'video' && <div className="publish-platform-options"><label className="publish-unpublished"><input type="checkbox" role="switch" checked={form.platform_options.instagram.share_to_feed} disabled={editorDisabled || platformLocked('instagram')} onChange={e => updateForm({ ...form, platform_options: { ...form.platform_options, instagram: { share_to_feed: e.target.checked } } })} />{t('同時顯示在動態')}</label>
                <div className="publish-thumbnail publish-cover"><span>{t('Reels 封面')}</span>{post?.cover && <img alt={post.cover.name} src={'/api/publish/posts/' + post.id + '/media/' + post.cover.id} />}<small>{post?.cover ? post.cover.name + ' · ' + sizeLabel(post.cover.size) : t('JPG／PNG · 8 MB 內 · 建議 9:16 · 未上傳則用影片第一格')}</small><div className="action-row"><button className="secondary" disabled={editorDisabled || platformLocked('instagram') || !brandId} onClick={() => coverInput.current?.click()}>{post?.cover ? t('更換封面') : t('上傳封面')}</button>{post?.cover && <button className="primary danger" disabled={editorDisabled || platformLocked('instagram')} onClick={() => void removeThumbnail('cover')}>{t('移除封面')}</button>}</div><input ref={coverInput} type="file" aria-label={t('上傳 Reels 封面')} accept="image/jpeg,image/png" hidden onChange={e => { void uploadThumbnail(e.target.files, 'cover'); e.target.value = ''; }} /></div></div>}
              {activePlatform === 'threads' && <div className="publish-segments">{repliesOf(normalized).map((reply, i, all) => <div className="publish-segment" key={i}>
                <div className="publish-segment-heading"><label htmlFor={'threads-reply-' + i}>{t('回覆 {n}', { n: i + 1 })}</label><span className={textLength(reply) > (options?.rules.threads.caption ?? 500) ? 'publish-reasons' : ''}>{textLength(reply)}／{(options?.rules.threads.caption ?? 500)}</span><button className="primary danger small" disabled={editorDisabled || platformLocked('threads')} onClick={() => changeReplies(all.filter((_, j) => j !== i))}>{t('刪除回覆')}</button></div>
                <textarea id={'threads-reply-' + i} aria-label={t('Threads 回覆 {n}', { n: i + 1 })} rows={4} value={reply} disabled={editorDisabled || platformLocked('threads')} onChange={e => changeReplies(all.map((s, j) => j === i ? e.target.value : s))} /><OverLimit label={t('回覆 {n}', { n: i + 1 })} text={reply} limit={options?.rules.threads.caption ?? 500} />
              </div>)}<div className="action-row"><button className="secondary" disabled={editorDisabled || platformLocked('threads')} onClick={() => changeReplies([...repliesOf(normalized), ''])}>{t('新增回覆')}</button></div></div>}
              {activePlatform === 'youtube' && <div className="publish-platform-options"><SegmentedControl compact label={t('公開狀態')} options={privacyOptions} value={youtubeOptions.privacy} disabled={editorDisabled || platformLocked('youtube')} onChange={privacy => setYoutube({ privacy })} /><label className="publish-unpublished"><input type="checkbox" checked={youtubeOptions.made_for_kids} disabled={editorDisabled || platformLocked('youtube')} onChange={e => setYoutube({ made_for_kids: e.target.checked })} />{t('這是為兒童製作的內容')}</label>
                <div className="publish-thumbnail"><span>{t('自訂縮圖')}</span>{post?.thumbnail && <img alt={post.thumbnail.name} src={'/api/publish/posts/' + post.id + '/media/' + post.thumbnail.id} />}<small>{videoShort ? t('Shorts 不支援自訂縮圖') : post?.thumbnail ? post.thumbnail.name + ' · ' + sizeLabel(post.thumbnail.size) : t('JPG／PNG · 2 MB 內 · 未上傳則用自動縮圖')}</small><div className="action-row"><button className="secondary" disabled={editorDisabled || platformLocked('youtube') || videoShort || !brandId} onClick={() => thumbnailInput.current?.click()}>{post?.thumbnail ? t('更換縮圖') : t('上傳縮圖')}</button>{post?.thumbnail && <button className="primary danger" disabled={editorDisabled || platformLocked('youtube')} onClick={() => void removeThumbnail()}>{t('移除縮圖')}</button>}</div><input ref={thumbnailInput} type="file" aria-label={t('上傳縮圖')} accept="image/jpeg,image/png" hidden onChange={e => { void uploadThumbnail(e.target.files); e.target.value = ''; }} /></div></div>}
              {[...new Set([...ruleChecks[activePlatform].warnings, ...(results[activePlatform]?.warnings || []), ...(activePlatform === 'facebook' ? post?.warnings || [] : [])].map(warning => t(warning)))].map(warning => <p className="notice warning" key={warning}>{warning}</p>)}
            </>}
          </div>
          <PublishPreview platform={shownPlatform} shared={composerTab === 'shared'} enabled={form.platforms} onPlatform={setPreviewPlatform} name={shownPlatform ? options?.platforms[shownPlatform]?.name || '' : ''} brandName={brands.find(b => String(b.id) === brandId)?.name || ''} caption={shownPlatform ? form.captions[shownPlatform] ?? form.caption : form.caption} format={form.format} media={post?.media || []} postId={post?.id} options={normalized.platform_options} unpublished={form.facebook_unpublished} title={effectiveTitle} thumbnail={post?.thumbnail ? '/api/publish/posts/' + post.id + '/media/' + post.thumbnail.id : undefined} cover={post?.cover ? '/api/publish/posts/' + post.id + '/media/' + post.cover.id : undefined} facebookCover={post?.facebook_cover ? '/api/publish/posts/' + post.id + '/media/' + post.facebook_cover.id : undefined} />
        </div>}
      </div>
      <div className="publish-footer">
        {shownReason && <p id="publish-disabled-reason" className="publish-reasons" role="status">{shownReason}</p>}
        <div className="publish-schedule"><SegmentedControl compact label={t('發佈時間')} options={[{ value: 'now', label: t('立即發佈') }, { value: 'scheduled', label: t('排程') }]} value={mode} disabled={busy} onChange={setMode} />{mode === 'scheduled' && <label>{t('日期時間（台北）')}<input type="datetime-local" aria-label={t('排程時間（台北）')} value={time} disabled={busy} onChange={e => setTime(e.target.value)} /></label>}</div>
        <div className="publish-submit">
        <div className="action-row publish-actions">{!story && <button className="secondary" disabled={busy || !brandId} onClick={() => void perform(async () => { await persist(); setNotice(t('草稿已儲存')); await reload(); })}>{t('存成草稿')}</button>}<button className="primary" aria-describedby="publish-disabled-reason" title={disabledReason} disabled={editorDisabled || !options?.enabled || !valid || (mode === 'scheduled' && !time)} onClick={() => void confirmation()}>{mode === 'scheduled' ? t('排程') : t('發佈')}</button></div>
        </div>
      </div>
    </div> : <>{tab === 'history' && <div className="publish-presence"><span>{t('上次檢查：')}{lastCheck ? taipei(new Date(lastCheck).toISOString()) : t('尚未檢查')}</span>{canEdit && <button className="primary" disabled={checking || busy || !brandId} aria-busy={checking} onClick={() => void checkPresence()}>{checking ? t('檢查中…') : t('檢查平台貼文')}</button>}</div>}{tab === 'history' && presence && <p className={'notice ' + presence.tone} role="status">{presence.text}</p>}<div className="list-box publish-records">{rows.length ? rows.map(row => <div className="list-row publish-record" key={row.id}><div className="publish-record-heading"><span className="publish-record-id" title={t('貼文編號')}>#{row.id}</span><time>{taipei(tab === 'drafts' ? row.updated_at : row.scheduled_at || row.created_at)}</time><span className="status-badge neutral">{row.format === 'story' ? t('限時動態') : formats.find(f => f.value === row.format)?.label}</span><AgentSource post={row} history={tab === 'history'} />{row.source === 'ideation' && <span className="status-badge neutral publish-source">{t('來自主題')}</span>}<strong className={tab === 'drafts' ? 'publish-caption-start' : undefined} title={row.caption}>{row.format === 'story' ? t('{count} 則', { count: row.media.length }) : row.caption.slice(0, 60) || t('（無文案）')}</strong>{tab === 'drafts' && <span>{t('{count} 個媒體', { count: row.media.length })}</span>}<span>{row.platforms.map(p => labels[p] + (hiddenFacebook(row, p) ? ' · ' + t('草稿') : '')).join(t('、'))}</span>{goneState(row) === 'all' ? <span className="status-badge neutral">{t('已在平台刪除')}</span> : <span className={'status-badge ' + (row.status === 'done' ? 'ready' : ['failed', 'partial', 'missed'].includes(row.status) ? 'failed' : 'pending')}>{states[row.status]}{row.locked && ' · ' + t('已鎖定')}{goneState(row) === 'some' && ' · ' + t('部分已刪除')}</span>}</div><div className="action-row">{tab === 'scheduled' && canEdit && <><button className="secondary" disabled={row.locked || busy} onClick={() => edit(row)}>{t('編輯')}</button><button className="secondary" disabled={row.locked || busy} onClick={() => setCancelConfirm(row)}>{t('取消排程')}</button></>}{tab === 'history' && <button className="secondary" aria-expanded={expanded === row.id} onClick={() => setExpanded(expanded === row.id ? null : row.id)}>{t('各平台結果')}</button>}{canEdit && row.status === 'draft' && <><button className="secondary" onClick={() => edit(row)}>{t('編輯')}</button><button className="primary danger" onClick={() => setCancelConfirm(row)}>{t('刪除')}</button></>}{canEdit && ['failed', 'partial', 'missed'].includes(row.status) && <><button className="secondary" disabled={busy || !options?.enabled} onClick={() => void confirmation(row, row.status !== 'missed')}>{row.status === 'missed' ? t('立即發佈') : t('只重試失敗平台')}</button><button className="secondary" disabled={busy} onClick={() => { setTime(''); setReschedule(row); }}>{t('重新排程')}</button></>}</div>{expanded === row.id && <div className="publish-targets">{row.targets.map(target => <div key={target.platform}>{target.deleted_at ? <><span className="status-badge neutral">{labels[target.platform]} · {t('已在平台刪除')}</span><span>{t('偵測於 {time}', { time: taipei(target.deleted_at) })}</span></> : <><span className={'status-badge ' + (hiddenFacebook(row, target.platform) && target.status === 'succeeded' ? 'neutral' : targetTone(target.status))}>{labels[target.platform]} · {targetLabels[target.status] || t('失敗')}{hiddenFacebook(row, target.platform) && ' · ' + t('草稿')}</span>{target.platform === 'threads' && target.detail?.total_segments != null && <span>{t('已發 {done}／{total} 段', { done: target.detail?.successful_segments || 0, total: target.detail?.total_segments ?? '' })}</span>}{row.format === 'story' && <><span>{t('已發 {done}／{total} 則', { done: target.detail?.successful_stories || 0, total: target.detail?.total_stories || row.media.length })}{target.detail?.failed_story ? ' · ' + t('第 {n} 則失敗', { n: target.detail.failed_story }) : ''}</span>{target.platform === 'facebook' ? <span className="publish-story-unavailable">{t('Facebook 不提供限時動態成效')}</span> : <div className="publish-story-results">{(target.stories || []).map(item => <div className="publish-story-result" key={item.position}><strong>{t('第 {n} 則', { n: item.position })}{item.final ? ' · ' + t('最終值') : ''}</strong><dl>{Object.entries(storyMetricLabels).map(([key, name]) => <div key={key}><dt>{name}</dt><dd>{item.metrics[key]?.toLocaleString('en-US') ?? '—'}</dd></div>)}</dl></div>)}</div>}</>}{target.platform === 'youtube' && target.status === 'succeeded' && !!target.detail?.privacy_status && target.detail.privacy_status !== row.platform_options?.youtube.privacy && <span className="status-badge pending">{t('YouTube 實際為{privacy}', { privacy: privacyLabels[target.detail.privacy_status as keyof typeof privacyLabels] ?? target.detail.privacy_status })}</span>}{target.platform === 'youtube' && target.status === 'succeeded' && target.detail?.thumbnail?.status === 'failed' && <><span className="status-badge pending">{t('縮圖未套用')}</span><span>{target.detail.thumbnail.reason}</span>{canEdit && <button className="secondary" disabled={busy || !options?.enabled} onClick={() => setThumbnailConfirm(row)}>{t('重新套用縮圖')}</button>}</>}{target.platform === 'facebook' && target.status === 'succeeded' && target.detail?.cover?.status === 'failed' && <><span className="status-badge pending">{t('封面未套用')}</span><span>{target.detail.cover.reason}</span>{canEdit && <button className="secondary" disabled={busy || !options?.enabled} onClick={() => setCoverConfirm(row)}>{t('重新套用封面')}</button>}</>}{target.platform === 'tiktok' && target.status === 'succeeded' && <><span className={'status-badge ' + (target.detail?.inbox_state === 'PUBLISH_COMPLETE' ? 'ready' : 'pending')}>{tiktokStates[target.detail?.inbox_state || ''] || t('已送到收件匣')}</span><button className="secondary" onClick={() => void copyCaption(row)}>{copied === row.id ? t('已複製') : t('複製文案')}</button></>}{target.permalink ? <a href={target.permalink} target="_blank" rel="noreferrer">{target.platform === 'youtube' ? t('查看影片') : t('查看貼文')}</a> : <span>{target.reason}</span>}</>}</div>)}</div>}</div>) : <p className="empty-data">{tab === 'drafts' ? t('尚無草稿') : tab === 'scheduled' ? t('尚無排程') : t('尚無發佈紀錄')}</p>}</div></>}
    </div>
    {reschedule && <div className="section-card"><label>{t('重新排程（台北）')}<input type="datetime-local" aria-label={t('重新排程時間（台北）')} value={time} onChange={e => setTime(e.target.value)} /></label><div className="action-row"><button className="secondary" onClick={() => setReschedule(null)}>{t('取消')}</button><button className="primary" disabled={!time || busy || !options?.enabled} onClick={() => { const row = reschedule; setReschedule(null); void confirmation(row, row.status !== 'missed', new Date(time + '+08:00').toISOString()); }}>{t('排程')}</button></div></div>}
    {confirm && (() => {
      const chosen = confirm.post.platforms.filter(p => !confirm.retry || confirm.post.targets.some(t => t.platform === p && t.status === 'failed'));
      return <ConfirmDialog heading={confirm.scheduled ? t('確認排程到 {count} 個平台', { count: chosen.length }) : t('確認發佈到 {count} 個平台', { count: chosen.length })} confirmLabel={t('確認發佈')} onClose={() => setConfirm(null)} onConfirm={() => void send()}>
        <ul className="list-box publish-confirm-list">{chosen.map(p => <li key={p}>
          <div className="publish-confirm-platform"><strong>{labels[p]}</strong><span>{options?.platforms[p].name || ''}</span>{confirm.post.captions[p] != null && <span className="status-badge neutral">{t('另寫文案')}</span>}</div>
          <p className="publish-confirm-options">{confirm.post.format === 'story' ? t('限時動態') + ' · ' + t('{count} 則', { count: confirm.post.media.length }) : p === 'facebook' ? (confirm.post.format === 'video' ? (loadedPlatformOptions(confirm.post.platform_options).facebook.video_format === 'feed' ? t('影片貼文') : 'Reels') + ' · ' + (confirm.post.facebook_cover ? t('自訂封面') : t('預設封面')) : formats.find(f => f.value === confirm.post.format)?.label) : p === 'instagram' ? (confirm.post.format === 'video' ? 'Reels · ' + (loadedPlatformOptions(confirm.post.platform_options).instagram.share_to_feed ? t('同時顯示在動態') : t('不顯示在動態')) + ' · ' + (confirm.post.cover ? t('自訂封面') : t('預設封面')) : formats.find(f => f.value === confirm.post.format)?.label) : p === 'youtube' ? youtubeSummary(confirm.post) : p === 'tiktok' ? t('影片 · 送到 TikTok 收件匣（文案不會送出，需在 App 內貼上並發佈）') : t('串文') + ' · ' + t('{count} 段', { count: loadedPlatformOptions(confirm.post.platform_options).threads.segments.length || 1 })}{p === 'facebook' && confirm.post.facebook_unpublished && ' · ' + t('草稿')}</p>
           {confirm.post.format !== 'story' && (p === 'youtube' ? <p>{t('標題：')}{youtubeTitle(loadedPlatformOptions(confirm.post.platform_options).youtube.title, confirm.post.captions.youtube ?? confirm.post.caption) || t('（無標題）')}</p> : <p>{(p === 'threads' ? loadedPlatformOptions(confirm.post.platform_options).threads.segments[0] ?? confirm.post.captions[p] ?? confirm.post.caption : confirm.post.captions[p] ?? confirm.post.caption).slice(0, 100) || t('（無文案）')}</p>)}
        </li>)}</ul>
        <dl className="publish-confirm-summary">
          <div><dt>{t('媒體')}</dt><dd>{confirm.post.media.length ? t('{count} 個：{names}', { count: confirm.post.media.length, names: confirm.post.media.map(m => m.name).join(t('、')) }) : t('無')}</dd></div>
          <div><dt>{t('時間')}</dt><dd>{confirm.scheduled ? t('{time}（台北）', { time: taipei(confirm.scheduled) }) : t('立即發佈')}</dd></div>
          {chosen.includes('facebook') && confirm.post.facebook_unpublished && <div><dt>Facebook</dt><dd>{t('存成草稿，不發佈')}</dd></div>}
        </dl>
      </ConfirmDialog>;
    })()}
    {coverConfirm && <ConfirmDialog message={t('重新套用封面到 Facebook？只會更換封面，不會重傳影片。')} confirmLabel={t('確認套用')} onClose={() => setCoverConfirm(null)} onConfirm={() => { const row = coverConfirm; setCoverConfirm(null); void reapplyCover(row); }} />}
    {thumbnailConfirm && <ConfirmDialog message={t('重新套用縮圖到 YouTube？只會更換縮圖，不會重傳影片。')} confirmLabel={t('確認套用')} onClose={() => setThumbnailConfirm(null)} onConfirm={() => { const row = thumbnailConfirm; setThumbnailConfirm(null); void reapplyThumbnail(row); }} />}
    {switchConfirm && <ConfirmDialog message={options?.enabled ? t('關閉發佈？所有排程將暫停。') : t('開啟發佈？已過期的排程會標記為已錯過。')} confirmLabel={options?.enabled ? t('確認關閉') : t('確認開啟')} onClose={() => setSwitchConfirm(false)} onConfirm={() => { setSwitchConfirm(false); void perform(async () => { await api('/publish/switch', { method: 'PUT', body: JSON.stringify({ enabled: !options?.enabled, confirmed: true }) }); await reload(); }); }} />}
    {cancelConfirm && <ConfirmDialog message={cancelConfirm.status === 'draft' ? t('刪除此草稿？') : t('取消此排程？')} confirmLabel={cancelConfirm.status === 'draft' ? t('確認刪除') : t('確認取消')} danger={cancelConfirm.status === 'draft'} onClose={() => setCancelConfirm(null)} onConfirm={() => { const row = cancelConfirm; setCancelConfirm(null); void perform(async () => { await api('/publish/posts/' + row.id + (row.status === 'draft' ? '' : '/cancel'), { method: row.status === 'draft' ? 'DELETE' : 'POST' }); if (row.status === 'draft' && current.current?.id === row.id) { current.current = null; setPost(null); setForm(blank()); onDraftId(null); } await reload(); }); }} />}
  </section>;
}

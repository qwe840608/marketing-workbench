import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { api, errorMessage } from '../api';
import type { CSSProperties, ReactNode, RefObject } from 'react';
import type { Brand, User } from '../api';
import { PageHeader } from './PageHeader';
import { SegmentedControl } from './SegmentedControl';
import { ConfirmDialog } from './ConfirmDialog';
import { PublishPreview } from './PublishPreview';
import { EMOJI_GROUPS } from './emojiGroups';
import { TIKTOK_IMAGE_REASON, checkComposer, xHasUrl, platformCaption, sentCaption, defaultPlatformOptions, isShort, loadedPlatformOptions, overLimitReason, overflowAt, overflowStart, platformLabels, textBytes, textLength, youtubeTitle } from '../publishComposer';
import type { PlatformOptions, Rules } from '../publishComposer';
import { hasMarkdown, toPlatformText } from '../markdownText';
import { applyFormat } from '../captionFormat';
import type { CaptionFormat } from '../captionFormat';
import { t, tx } from '../i18n.ts';
import { taipeiDateTime, toLocalInput } from '../time.ts';
import { can } from '../permissions';
import './publish.css';

type Platform = 'facebook' | 'instagram' | 'threads' | 'youtube' | 'tiktok' | 'x';
type Format = 'video' | 'image' | 'carousel' | 'text' | 'story';
type Media = { size: number; id: number; name: string; mime: string; width: number; height: number; duration: number | null };
// YouTube 自訂縮圖：不是發佈素材，由伺服端另外保存與綁定。
type Thumbnail = { id: number; name: string; mime: string; size: number; width: number; height: number };
type Target = { platform: Platform; status: string; permalink: string | null; reason: string; deleted_at: string | null; presence_checked_at: string | null; detail?: { total_segments?: number; successful_segments?: number; segment_ids?: string[]; post_id?: string; total_comments?: number; successful_comments?: number; successful_stories?: number; total_stories?: number; failed_story?: number; video_id?: string; privacy_status?: string; publish_id?: string; inbox_state?: string; thumbnail?: { status: string; code?: string; reason?: string }; cover?: { status: string; code?: string; reason?: string } }; stories?: { position: number; media_id: number; published_at: string; final: boolean; metrics: Record<string, number> }[] };
type Presence = { checked: number; newly_deleted: number; restored: number; unresolved: { platform: Platform; reason: string }[] };
type Post = { source: 'manual' | 'ideation' | 'agent' | 'flow'; agent_source?: { agent: string } | null; publish_via?: string | null; report_id: number | null; idea_index: number | null; id: number; brand_id: number; format: Format; caption: string; captions: Partial<Record<Platform, string>>; platforms: Platform[]; facebook_unpublished: boolean; platform_options?: PlatformOptions; warnings?: string[]; media: Media[]; thumbnail?: Thumbnail | null; cover?: Thumbnail | null; facebook_cover?: Thumbnail | null; facebook_comment_media?: Thumbnail[]; targets: Target[]; status: string; version: number; locked: boolean; scheduled_at: string | null; created_at: string; updated_at: string };

// 平台都不支援 Markdown：偵測到語法時說明發佈時會自動轉換，實際樣子看右側預覽。
function MarkdownHint({ text }: { text: string }) {
  if (!hasMarkdown(text) && !/^[ \t]*[-*+][ \t]+\S/m.test(text)) return null;
  return <p className="notice publish-markdown-hint" role="status">{t('發佈時會把 Markdown 轉成平台顯示得出來的格式：# 大標題變成「█ 大標題」、## 小標題變成「▍小標題」、- 項目變成「• 」、** 粗體會去掉符號（中文沒有粗體字形，只有英文與數字會變粗）、<u>底線</u> 會在每個字下面加底線，實際樣子請看右側預覽。平台都不能調整文字大小。')}</p>;
}

// 格式按鈕：在選取的文字（沒選取時是游標所在行）插入 Markdown；平台不顯示 Markdown，下方提示可轉成 Unicode 字形。
const FORMAT_ICONS: Record<CaptionFormat, string> = {
  h1: 'M3 5v14M13 5v14M3 12h10M17 9l3-2v12',
  h2: 'M3 5v14M13 5v14M3 12h10M16.5 9.5a2.5 2.5 0 0 1 5 .5c0 2-5 4.5-5 9h5',
  bold: 'M7 4h6a4 4 0 0 1 0 8H7zM7 12h7a4 4 0 0 1 0 8H7z',
  underline: 'M7 4v7a5 5 0 0 0 10 0V4M5 20h14',
  bullet: 'M10 6h11M10 12h11M10 18h11M4 6h1M4 12h1M4 18h1',
  numbered: 'M10 6h11M10 12h11M10 18h11M4 4.5h1.5V9M4 9h3M4 13.5c.4-.6 1-.8 1.6-.6.8.3.9 1.2.3 1.8L4 17h3',
};
const ICONS = {
  media: 'M4 5h16v14H4zM4 16l5-5 4 4 3-3 4 4M15.5 9.5h.01',
  emoji: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM8.5 14.5a4.5 4.5 0 0 0 7 0M9 9.5h.01M15 9.5h.01',
  up: 'M6 15l6-6 6 6',
  down: 'M6 9l6 6 6-6',
  remove: 'M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6',
};
const Icon = ({ d }: { d: string }) => <svg viewBox="0 0 24 24" aria-hidden="true"><path d={d} /></svg>;
// 一則貼文卡片：文字框、框底工具列（媒體、格式、表情、字數）與右側的上移／下移／刪除。
// 平台不顯示 Markdown，格式按鈕插入的語法發佈時會轉成 Unicode 字形（見 MarkdownHint）。
type PostCardProps = { label: string; value: string; rows: number; disabled: boolean; onChange: (value: string) => void; count: string; over?: string; isOver?: (text: string) => boolean; placeholder?: string; boxRef?: RefObject<HTMLTextAreaElement | null>; id?: string; media?: { onClick: () => void; disabled: boolean; title?: string }; onUp?: () => void; onDown?: () => void; onRemove?: () => void; className?: string; children?: ReactNode };
function PostCard({ label, value, rows, disabled, onChange, count, over, isOver, placeholder, boxRef, id, media, onUp, onDown, onRemove, className, children }: PostCardProps) {
  const box = useRef<HTMLTextAreaElement | null>(null), mirror = useRef<HTMLDivElement | null>(null);
  // 超出上限的字標紅：textarea 本身無法部分上色，所以文字改透明，底下疊一層同排版的鏡像來上色。
  const overAt = over && isOver ? overflowStart(value, isOver) : null, marking = overAt !== null;
  const [frame, setFrame] = useState<CSSProperties | null>(null);
  useLayoutEffect(() => {
    const el = box.current;
    if (!marking || !el) return;
    const sync = () => {
      const style = getComputedStyle(el);
      setFrame({ top: el.offsetTop + el.clientTop, left: el.offsetLeft + el.clientLeft, width: el.clientWidth, height: el.clientHeight, font: style.font, letterSpacing: style.letterSpacing, wordSpacing: style.wordSpacing, lineHeight: style.lineHeight, padding: style.padding, tabSize: style.tabSize });
    };
    sync();
    const observer = new ResizeObserver(sync);
    observer.observe(el);
    return () => observer.disconnect();
  }, [marking]);
  useLayoutEffect(() => { if (mirror.current && box.current) mirror.current.scrollTop = box.current.scrollTop; });
  const [emojiOpen, setEmojiOpen] = useState(false), [emojiGroup, setEmojiGroup] = useState(EMOJI_GROUPS[0].id);
  const group = EMOJI_GROUPS.find(g => g.id === emojiGroup) ?? EMOJI_GROUPS[0];
  const buttons: [CaptionFormat, string, string][] = [['h1', t('大標題'), '# '], ['h2', t('小標題'), '## '], ['bold', t('粗體'), '**'], ['underline', t('底線'), '<u></u>'], ['bullet', t('項目清單'), '- '], ['numbered', t('編號清單'), '1. 2. 3.']];
  function edit(next: (text: string, start: number, end: number) => { text: string; start: number; end: number }) {
    const el = box.current;
    if (!el) return;
    const result = next(el.value, el.selectionStart, el.selectionEnd);
    if (result.text === el.value) return;
    onChange(result.text);
    requestAnimationFrame(() => { el.focus(); el.setSelectionRange(result.start, result.end); });
  }
  function insert(emoji: string) {
    setEmojiOpen(false);
    edit((text, start, end) => ({ text: text.slice(0, start) + emoji + text.slice(end), start: start + emoji.length, end: start + emoji.length }));
  }
  return <div className={'publish-post-card' + (className ? ' ' + className : '')}>
    <div className="publish-post-body">
      <div className="publish-post-box">
        {marking && frame && <div ref={mirror} className="publish-post-mirror" aria-hidden="true" style={frame}>{value.slice(0, overAt)}<span className="publish-post-overflow">{value.slice(overAt)}</span>{'\n'}</div>}
        <textarea id={id} className={marking && frame ? 'is-marking' : undefined} ref={el => { box.current = el; if (boxRef) boxRef.current = el; }} aria-label={label} placeholder={placeholder ?? t('請輸入文案')} rows={rows} value={value} disabled={disabled} onChange={e => onChange(e.target.value)} onScroll={e => { if (mirror.current) mirror.current.scrollTop = e.currentTarget.scrollTop; }} />
        <span className={'publish-post-count' + (over ? ' publish-reasons' : '')}>{count}</span>
        <div className="publish-format-bar" role="toolbar" aria-label={t('文案格式')}>
          {media && <><span className="publish-media-wrap" title={media.title}><button type="button" className="secondary publish-media-pill" disabled={disabled || media.disabled} title={media.title} onClick={media.onClick}><Icon d={ICONS.media} />{t('媒體')}</button></span><span className="publish-format-sep" aria-hidden="true" /></>}
          {buttons.map(([kind, name, syntax]) => <button key={kind} type="button" className={'secondary publish-format-button is-' + kind} aria-label={name} title={name + ' ' + syntax.trim()} disabled={disabled} onMouseDown={e => e.preventDefault()} onClick={() => edit((text, start, end) => applyFormat(text, start, end, kind))}><Icon d={FORMAT_ICONS[kind]} /></button>)}
          <span className="publish-emoji">
            <button type="button" className="secondary publish-format-button is-emoji" aria-label={t('表情符號')} title={t('表情符號')} aria-expanded={emojiOpen} disabled={disabled} onMouseDown={e => e.preventDefault()} onClick={() => setEmojiOpen(!emojiOpen)}><Icon d={ICONS.emoji} /></button>
            {emojiOpen && <span className="publish-emoji-menu" role="group" aria-label={t('表情符號')} onKeyDown={e => { if (e.key === 'Escape') setEmojiOpen(false); }}><span className="publish-emoji-tabs" role="group" aria-label={t('表情分類')}>{EMOJI_GROUPS.map(g => <button key={g.id} type="button" aria-pressed={g.id === group.id} onMouseDown={e => e.preventDefault()} onClick={() => setEmojiGroup(g.id)}>{g.label}</button>)}</span><span className={'publish-emoji-grid' + (group.wide ? ' is-wide' : '')}>{group.items.map(emoji => <button key={emoji} type="button" aria-label={emoji} onMouseDown={e => e.preventDefault()} onClick={() => insert(emoji)}>{emoji}</button>)}</span></span>}
          </span>
          {over && <span className="publish-post-alert" role="img" aria-label={over} title={over}>!</span>}
        </div>
      </div>
      {children}
    </div>
    {/* 第一則（主文案）不能移動或刪除，不顯示按鈕；保留同寬的空欄讓右緣和下面的串文／評論卡片對齊。 */}
    {onRemove ? <div className="publish-post-moves">
      {onUp ? <button type="button" className="secondary publish-post-move" aria-label={t('上移')} title={t('上移')} disabled={disabled} onClick={onUp}><Icon d={ICONS.up} /></button> : <span className="publish-post-move-gap" aria-hidden="true" />}
      {onDown ? <button type="button" className="secondary publish-post-move" aria-label={t('下移')} title={t('下移')} disabled={disabled} onClick={onDown}><Icon d={ICONS.down} /></button> : <span className="publish-post-move-gap" aria-hidden="true" />}
      <button type="button" className="secondary publish-post-move is-remove" aria-label={t('刪除這則')} title={t('刪除這則')} disabled={disabled} onClick={onRemove}><Icon d={ICONS.remove} /></button>
    </div> : <div className="publish-post-moves is-empty" aria-hidden="true" />}
  </div>;
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
const composerTabs: Platform[] = ['facebook', 'instagram', 'threads', 'youtube', 'tiktok', 'x'];
// TikTok 只把影片送到收件匣（收件匣 API 不收文案）：文案留在工作檯供複製到 App。
export const TIKTOK_CAPTION_NOTICE = t('收件匣不會帶入文案：送出後到發佈紀錄按「複製文案」，貼到 TikTok App 再發佈。');
const tiktokStates: Record<string, string> = { PROCESSING_UPLOAD: t('TikTok 處理中'), SEND_TO_USER_INBOX: t('已送到收件匣'), PUBLISH_COMPLETE: t('已在 App 發佈') };
const videoOnly = (p: Platform) => p === 'youtube' || p === 'tiktok';
const privacyOptions = [{ value: 'public', label: t('公開') }, { value: 'unlisted', label: t('不公開') }, { value: 'private', label: t('私人') }] as const;
const privacyLabels = { public: t('公開'), unlisted: t('不公開'), private: t('私人') } as const;
const sizeLabel = (bytes: number) => bytes >= 1024 ** 2 ? (bytes / 1024 ** 2).toFixed(1) + ' MB' : Math.max(1, Math.round(bytes / 1024)) + ' KB';
// 確認視窗的 YouTube 摘要：公開狀態、兒童內容、縮圖與是否歸為 Shorts。
function youtubeSummary(row: Post) {
  const options = loadedPlatformOptions(row.platform_options).youtube, short = row.media.length === 1 && isShort(row.media[0]);
  return t('影片') + ' · ' + privacyLabels[options.privacy] + ' · ' + (options.made_for_kids ? t('兒童內容') : t('非兒童內容')) + ' · ' + (row.thumbnail ? t('自訂縮圖') : t('自動縮圖')) + (short ? ' · Shorts' : '');
}
const formats = [{ value: 'video', label: t('影片') }, { value: 'image', label: t('圖片') }, { value: 'carousel', label: t('輪播') }, { value: 'text', label: t('純文字') }] as const;
// 貼文格式不手選，依素材決定：沒有素材＝純文字、一個影片＝影片、一張圖＝圖片、兩個以上＝輪播。
const mediaFormat = (media: { mime: string }[]): Format => !media.length ? 'text' : media.length > 1 ? 'carousel' : media[0].mime.startsWith('video/') ? 'video' : 'image';
// 各平台結果：等待與發佈中是進行中狀態（黃色），只有確定失敗才顯示紅色。
const targetLabels: Record<string, string> = { pending: t('等待發佈'), publishing: t('發佈中'), succeeded: t('成功'), failed: t('失敗') };
const targetTone = (status: string) => status === 'succeeded' ? 'ready' : status === 'failed' ? 'failed' : 'pending';
const storyMetricLabels: Record<string, string> = { views: t('觀看'), reach: t('觸及'), replies: t('回覆'), shares: t('分享'), navigation: t('導覽'), follows: t('追蹤'), profile_visits: t('個人檔案瀏覽') };
const states: Record<string, string> = { draft: t('草稿'), scheduled: t('排程中'), publishing: t('發佈中'), done: t('成功'), partial: t('部分成功'), failed: t('失敗'), missed: t('已錯過'), paused: t('已暫停'), cancelled: t('已取消') };
const blank = (): Form => ({ format: 'text', caption: '', captions: {}, platforms: [], facebook_unpublished: false, platform_options: defaultPlatformOptions() });
const taipei = (value: string) => taipeiDateTime(value, { hour12: false });
const localTime = toLocalInput;
// 已在平台刪除：成功的平台全部刪除（且整篇成功）為 all，其餘有刪除者為 some。
const goneState = (row: Post) => {
  const gone = row.targets.filter(t => t.status === 'succeeded' && t.deleted_at);
  return !gone.length ? '' : row.status === 'done' && gone.length === row.targets.filter(t => t.status === 'succeeded').length ? 'all' : 'some';
};
// 「存成 FB 草稿」的 Facebook 結果：存進 Business Suite 草稿匣、不發佈，紀錄上以「草稿」標示。
const hiddenFacebook = (row: Pick<Post, 'facebook_unpublished'>, platform: Platform) => platform === 'facebook' && row.facebook_unpublished;
const reason = (e: unknown) => errorMessage(e, t('操作失敗，請重試'));

// 輸入框下方即時提示從第幾個字開始超過上限，與發佈規則同一段文字。
function OverLimit({ label, text, limit }: { label: string; text: string; limit: number }) {
  const reason = overLimitReason(label, toPlatformText(text), limit);
  return reason ? <p className="publish-reasons publish-over-limit" role="status">{reason}</p> : null;
}
// embedded：流程頁的草稿彈窗只用編輯器本身（沒有頁首、分頁、清單與發佈按鈕），修改照常自動存回草稿。
export function Publish({ brand, brands, user, draftId, fromIdea, onDraftId, beforeLeave, onConnections, embedded = false }: { brand: string; brands: Brand[]; user: User; draftId: number | null; fromIdea: boolean; onDraftId: (id: number | null) => void; beforeLeave: RefObject<(() => Promise<boolean>) | null>; onConnections: () => void; embedded?: boolean }) {
  const canEdit = can(user, 'publish.edit'), canSubmit = can(user, 'publish.submit');
  const [tab, setTab] = useState(canEdit ? 'new' : 'history');
  const [chosen, setChosen] = useState(brand);
  const brandId = brand || chosen || (brands.length === 1 ? String(brands[0].id) : '');
  const brandScope = useRef(brandId); brandScope.current = brandId;
  const [options, setOptions] = useState<Options | null>(null), [posts, setPosts] = useState<Post[]>([]);
  const captionBox = useRef<HTMLTextAreaElement>(null);
  const [form, setForm] = useState<Form>(blank), [post, setPost] = useState<Post | null>(null);
  const current = useRef<Post | null>(null), fileInput = useRef<HTMLInputElement>(null), commentInput = useRef<HTMLInputElement>(null), commentSlot = useRef<number | null>(null);
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
    try { await navigator.clipboard.writeText(sentCaption(row.captions, row.caption, 'tiktok')); setCopied(row.id); }
    catch { setError(t('無法複製文案，請手動選取文字')); }
  }
  const [loadedScope, setLoadedScope] = useState<string | null>(null);
  // null 代表還沒選分頁：自動落在第一個已開啟且已連結的平台。
  const [composerTab, setComposerTab] = useState<Platform | null>(null);
  const [thumbnailConfirm, setThumbnailConfirm] = useState<Post | null>(null);
  const [coverConfirm, setCoverConfirm] = useState<Post | null>(null);
  const thumbnailInput = useRef<HTMLInputElement>(null);
  const coverInput = useRef<HTMLInputElement>(null);
  const facebookCoverInput = useRef<HTMLInputElement>(null);
  // Threads 串文＝Threads 文案（第一則）＋各則回覆；各則獨立輸入、互不同步，也不自動分段（超過字數只標紅）。
  const repliesOf = (value: Form) => value.platform_options.threads.segments_custom ? value.platform_options.threads.segments.slice(1) : [];
  function normalize(value: Form): Form {
    if (value.format === 'story') return value;
    const segments = [platformCaption(value.captions, value.caption, 'threads'), ...repliesOf(value)];
    return { ...value, platform_options: { ...value.platform_options, threads: { segments, segments_custom: true } } };
  }
  function updateForm(value: Form) { setForm(normalize(value)); }
  function changeReplies(replies: string[]) { updateForm({ ...form, platform_options: { ...form.platform_options, threads: { segments: [platformCaption(form.captions, form.caption, 'threads'), ...replies], segments_custom: true } } }); }
  function changeCaption(platform: Platform, text: string) { updateForm({ ...form, captions: { ...form.captions, [platform]: text } }); }
  function writeOwn(platform: Platform) { updateForm({ ...form, captions: { ...form.captions, [platform]: form.caption } }); }
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
    current.current = null; setPost(null); setForm({ ...blank(), ...(tab === 'story' ? { format: 'story' as const } : {}) }); setComposerTab(tab === 'story' ? 'facebook' : null); setResults({}); setOptions(null); setLoadedScope(null); setError(''); generation.current++;
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
      if (selected && embedded && selected.status !== 'draft') throw new Error(t('這篇貼文已經不是草稿，請到發佈頁查看'));
      if (selected && !['draft', 'scheduled', 'paused'].includes(selected.status)) { setTab('history'); setExpanded(selected.id); }
      else if (selected) { edit(selected); if (fromIdea) setNotice(t('已從主題建立草稿，請上傳影片並確認平台')); }
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
    // 空白的平台文案等於沒有覆寫，載入時就拿掉，平台分頁才會顯示共用文案。
    const captions = Object.fromEntries(Object.entries(row.captions).filter(([, text]) => text?.trim())) as Post['captions'];
    const value: Form = { format: row.format, caption: row.caption, captions, platforms: row.platforms, facebook_unpublished: row.facebook_unpublished, platform_options: loadedPlatformOptions(row.platform_options) };
    const first = value.platform_options.threads.segments[0];
    if (value.format === 'story' || !value.platform_options.threads.segments_custom || !first?.trim() || first === platformCaption(value.captions, value.caption, 'threads')) return value;
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
        setComposerTab(value === 'story' ? 'facebook' : null); setResults({}); setMode('now'); setTime('');
      }
      setTab(value); await reload(); });
  }
  useEffect(() => {
    const leaving = (e: BeforeUnloadEvent) => { if (dirty()) { e.preventDefault(); e.returnValue = ''; } };
    window.addEventListener('beforeunload', leaving);
    // 彈窗被關掉（例如切頁）時把還沒存的內容送出，不等防抖計時。
    return () => { window.removeEventListener('beforeunload', leaving); beforeLeave.current = null; if (embedded && dirty()) void persist(formRef.current).catch(() => undefined); };
  }, []);
  async function newPost() {
    await perform(async () => {
      if (dirty()) await persist(); await queue.current;
      generation.current++; current.current = null; setPost(null); onDraftId(null);
      setForm({ ...blank(), ...(tab === 'story' ? { format: 'story' as const } : {}), platform_options: options?.default_platform_options ? loadedPlatformOptions(options.default_platform_options) : defaultPlatformOptions() }); setComposerTab(tab === 'story' ? 'facebook' : null); setResults({}); setMode('now'); setTime('');
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
      if (form.format !== 'story') saved = await syncFormat(saved);
      setResults(await api('/publish/posts/' + saved.id + '/check', { method: 'POST' }));
    });
  }
  // 素材變動後格式跟著改。平台開關不動：換影片要先刪再傳，YouTube／TikTok 不該因此被關掉；不是影片時由檢查擋下並提示，已開啟的開關仍可關。
  async function syncFormat(saved: Post) {
    const format = mediaFormat(saved.media);
    if (saved.format === format) return saved;
    const next = { ...formRef.current, format };
    updateForm(next); return persist(next);
  }
  async function removeMedia(id: number) {
    if (!post) return;
    await perform(async () => {
      let saved = await serial(async () => { const row = await api<Post>('/publish/posts/' + post.id + '/media/' + id, { method: 'DELETE' }); remember(row); return row; });
      if (!story) saved = await syncFormat(saved);
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
  function withCommentMedia(value: Form, comments: string[], images: (number | null)[]): Form {
    return { ...value, platform_options: { ...value.platform_options, facebook: { ...value.platform_options.facebook, comments, comment_media: images } } };
  }
  // 評論附圖（role=fb_comment）：上傳後把新圖編號放進那則評論並存檔，換掉的舊圖等存好才刪，
  // 避免草稿還引用已刪除的圖。
  async function uploadCommentImage(files: FileList | null) {
    const file = files?.[0], slot = commentSlot.current;
    if (!file || slot === null) return;
    await perform(async () => {
      const saved = await persist(formRef.current);
      const before = new Set((saved.facebook_comment_media ?? []).map(m => m.id));
      const row = await serial(async () => { const r = await api<Post>('/publish/posts/' + saved.id + '/media?role=fb_comment&filename=' + encodeURIComponent(file.name), { method: 'POST', body: file, headers: { 'Content-Type': 'application/octet-stream' } }); remember(r); return r; });
      const added = (row.facebook_comment_media ?? []).find(m => !before.has(m.id));
      const fb = formRef.current.platform_options.facebook;
      if (!added || slot >= fb.comments.length) return;
      const old = fb.comment_media[slot];
      const next = normalize(withCommentMedia(formRef.current, fb.comments, fb.comment_media.map((id, i) => i === slot ? added.id : id)));
      setForm(next); formRef.current = next;
      await persist(next);
      if (old) await serial(async () => { remember(await api<Post>('/publish/posts/' + row.id + '/media/' + old, { method: 'DELETE' })); });
      setResults(await api('/publish/posts/' + row.id + '/check', { method: 'POST' }));
    });
  }
  // 先存好不再引用的草稿，再刪圖片檔。
  async function dropCommentImages(next: Form, removed: number[]) {
    setForm(next); formRef.current = next;
    if (!removed.length) return;
    await perform(async () => {
      const saved = await persist(next);
      for (const id of removed) await serial(async () => { remember(await api<Post>('/publish/posts/' + saved.id + '/media/' + id, { method: 'DELETE' })); });
      setResults(await api('/publish/posts/' + saved.id + '/check', { method: 'POST' }));
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
    remember(row); setForm(rowForm(row)); setComposerTab(null);
    setMode(row.scheduled_at ? 'scheduled' : 'now'); setTime(row.scheduled_at ? localTime(row.scheduled_at) : ''); setTab(row.format === 'story' ? 'story' : 'new'); if (row.format === 'story') setComposerTab('facebook');
  }
  // 已鎖定，或 Facebook 已送出／發佈中（部分成功後重新排程再取消會回到草稿）時，公開方式不可再改。
  const facebookLocked = !!post?.locked || !!post?.targets.some(t => t.platform === 'facebook' && ['succeeded', 'publishing'].includes(t.status));
  const story = form.format === 'story';
  const activeTabs: Platform[] = story ? ['facebook', 'instagram'] : composerTabs;
  const editorDisabled = busy || !!post?.locked || (story && !!post?.targets.some(t => t.detail?.successful_stories));
  const platformLocked = (p: Platform) => !!post?.locked || !!post?.targets.some(t => t.platform === p && (['succeeded', 'publishing'].includes(t.status) || (p === 'threads' && !!(t.detail?.successful_segments || t.detail?.segment_ids?.length)) || (p === 'youtube' && !!t.detail?.video_id) || (p === 'facebook' && !!t.detail?.post_id)));
  const normalized = normalize(form);
  const localCheck = (p: Platform) => options?.rules ? checkComposer(p, form.format, sentCaption(form.captions, form.caption, p), post?.media || [], normalized.platform_options, options.rules, form.facebook_unpublished, p === 'youtube' && post?.thumbnail ? { ...post.thumbnail, duration: null } : null, p === 'instagram' && post?.cover ? { ...post.cover, duration: null } : p === 'facebook' && post?.facebook_cover ? { ...post.facebook_cover, duration: null } : null) : { errors: [], warnings: [] };
  const ruleChecks = { facebook: localCheck('facebook'), instagram: localCheck('instagram'), threads: localCheck('threads'), youtube: localCheck('youtube'), tiktok: localCheck('tiktok'), x: localCheck('x') };
  const youtubeOptions = form.platform_options.youtube, youtubeCaption = sentCaption(form.captions, form.caption, 'youtube');
  const effectiveTitle = youtubeTitle(youtubeOptions.title, youtubeCaption);
  const captionWord = (p: Platform) => p === 'youtube' ? t('說明') : t('文案');
  const captionSize = (p: Platform, text: string) => p === 'youtube' ? textBytes(text).toLocaleString('en-US') + '／' + (options?.rules.youtube?.caption ?? 5000).toLocaleString('en-US') : textLength(text, p).toLocaleString('en-US');
  const setYoutube = (patch: Partial<typeof youtubeOptions>) => updateForm({ ...form, platform_options: { ...form.platform_options, youtube: { ...youtubeOptions, ...patch } } });
  // 後端原因帶「平台名：」前綴，去掉後才能和前端檢查去重；前綴清單取自 labels，新平台不會漏掉。
  // 後端檢查原因是繁中原文；先查翻譯，和已翻譯的前端檢查訊息才能去重。
  const platformErrors = (p: Platform) => [...new Set([...ruleChecks[p].errors, ...(results[p]?.reasons || [])].map(reason => t(reason.replace(labelPrefix, ''))))];
  // 已在畫面上標示的錯誤不再列進錯誤清單：Threads 字數超限在輸入框下方，空白的串文／評論顯示灰字「請輸入文案」，
  // IG 純文字標在預覽帳號列右邊。發佈仍會擋下，滑鼠提示（title）仍是完整原因。
  const inlineErrors = (p: Platform): (string | null)[] => {
    const empty = (count: number) => Array.from({ length: count }, (_, i) => t('評論 {n} 不可空白', { n: i + 1 }));
    if (p === 'threads') return normalized.platform_options.threads.segments.flatMap((text, i) => {
      const label = i ? t('回覆 {n}', { n: i }) : t('Threads 文案');
      return [overLimitReason(label, toPlatformText(text), options?.rules.threads.caption ?? 500), t('{label}不可空白', { label })];
    });
    if (p === 'instagram') return [t('Instagram 不支援純文字'), ...empty(normalized.platform_options.instagram.comments?.length ?? 0)];
    if (p === 'facebook') return empty(normalized.platform_options.facebook.comments.length);
    return [];
  };
  const panelErrors = (p: Platform) => platformErrors(p).filter(reason => !inlineErrors(p).includes(reason));
  const valid = form.platforms.length > 0 && form.platforms.every(p => options?.platforms[p]?.ready && results[p]?.ok && !ruleChecks[p].errors.length);
  const disabledReason = !options?.enabled ? t('發佈功能尚未開啟') : !form.platforms.length ? t('請開啟要發佈的平台') : form.platforms.flatMap(p => platformErrors(p).map(e => labels[p] + t('：') + e)).join(t('；')) || (!valid ? t('檢查中') : mode === 'scheduled' && !time ? t('請選擇排程時間') : '');
  const isReady = (p: Platform) => !!options?.platforms[p]?.ready;
  const activePlatform: Platform = composerTab && activeTabs.includes(composerTab) ? composerTab : form.platforms.find(p => activeTabs.includes(p) && isReady(p)) ?? activeTabs.find(isReady) ?? activeTabs[0];
  const shownPlatform = activePlatform, connected = isReady(activePlatform);
  // 錯誤只在「立即發佈／排程」列上方列一次；Threads 字數超限已標在輸入框下方，這裡不重複。
  // 滑鼠提示（title）仍是完整原因。
  const ruleBlocked = !!options?.enabled && form.platforms.length > 0 && form.platforms.some(p => platformErrors(p).length > 0);
  // 只列目前分頁平台的錯誤（即使還沒開啟）；其他平台的錯誤由分頁紅點提示。
  const listedErrors = [activePlatform].flatMap(p => panelErrors(p).map(e => labels[p] + t('：') + e));
  const otherBlocked = form.platforms.filter(p => p !== activePlatform && platformErrors(p).length > 0);
  const blockedHint = otherBlocked.length ? t('請先修正 {platforms} 分頁的錯誤', { platforms: otherBlocked.map(p => labels[p]).join(t('、')) }) : t('請先修正上方標示的錯誤');
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
  const threadsLimit = options?.rules.threads.caption ?? 500;
  const sharedLocked = editorDisabled || (platformLocked('threads') && form.captions.threads === undefined);
  const mediaButton = { onClick: () => fileInput.current?.click(), disabled: !brandId, title: t('上傳媒體') };
  function platformCard(p: Platform) {
    const sent = sentCaption(form.captions, form.caption, p), limit = options?.rules[p]?.caption;
    const over = p === 'youtube' ? (limit && textBytes(sent) > limit ? t('說明最多 {limit} 位元組（目前 {count}）', { limit: limit.toLocaleString('en-US'), count: textBytes(sent).toLocaleString('en-US') }) : undefined) : limit ? overLimitReason(p === 'threads' ? t('Threads 文案') : labels[p] + ' ' + captionWord(p), sent, limit, p) || undefined : undefined;
    const own = form.captions[p] !== undefined;
    return <PostCard boxRef={captionBox} label={own ? labels[p] + ' ' + captionWord(p) : t('主文案')} value={own ? form.captions[p]! : form.caption} rows={8} disabled={editorDisabled || platformLocked(p) || (!own && sharedLocked)} onChange={value => own ? changeCaption(p, value) : updateForm({ ...form, caption: value })} count={captionSize(p, sent) + (p !== 'youtube' && limit ? '／' + limit.toLocaleString('en-US') : '')} placeholder={p === 'youtube' ? t('請描述這部影片') : undefined} over={over} isOver={limit ? text => p === 'youtube' ? textBytes(toPlatformText(text)) > limit : !!overflowAt(toPlatformText(text), limit, p) : undefined} media={mediaButton}>{p === 'threads' && <OverLimit label={t('Threads 文案')} text={form.captions.threads ?? form.caption} limit={threadsLimit} />}</PostCard>;
  }
  // 「+ 串文」接在第一則下面的回覆只發到 Threads：其他平台的 API 沒有串文，只發第一則。
  // Facebook 沒有串文：「+ 評論」接的是發文成功後由粉專依序留的評論，可調整順序，每則可附一張圖片
  // （Graph API 的評論只收圖片／GIF，不收影片）。
  function renderComments(first: ReactNode) {
    const fb = form.platform_options.facebook, comments = fb.comments, images = fb.comment_media, locked = editorDisabled || platformLocked('facebook');
    const known = new Map((post?.facebook_comment_media ?? []).map(m => [m.id, m]));
    const change = (next: string[], nextImages: (number | null)[]) => updateForm(withCommentMedia(form, next, nextImages));
    const move = (i: number, j: number) => { const next = [...comments], pics = [...images]; [next[i], next[j]] = [next[j], next[i]]; [pics[i], pics[j]] = [pics[j], pics[i]]; change(next, pics); };
    const remove = (i: number) => { const gone = images[i]; void dropCommentImages(normalize(withCommentMedia(form, comments.filter((_, j) => j !== i), images.filter((_, j) => j !== i))), gone ? [gone] : []); };
    const clearImage = (i: number) => { const gone = images[i]; if (gone) void dropCommentImages(normalize(withCommentMedia(form, comments, images.map((id, j) => j === i ? null : id))), [gone]); };
    const note = !form.platforms.includes('facebook') ? t('尚未開啟 Facebook，評論不會發出') : form.facebook_unpublished ? t('存成 FB 草稿時不會留評論') : t('評論會在 Facebook 發文成功後由粉專依序留言');
    return <div className={'publish-chain' + (comments.length ? ' has-replies' : '')}>{first}
      <input ref={commentInput} type="file" aria-label={t('上傳評論圖片')} accept="image/jpeg,image/png" hidden onChange={e => { void uploadCommentImage(e.target.files); e.target.value = ''; }} />
      {comments.length > 0 && <div className="publish-segments">{comments.map((comment, i) => {
        const image = images[i] ? known.get(images[i]!) : undefined;
        return <PostCard key={i} className="publish-segment" id={'facebook-comment-' + i} label={t('Facebook 評論 {n}', { n: i + 1 })} value={comment} rows={4} disabled={locked} onChange={value => change(comments.map((s, j) => j === i ? value : s), images)} count={textLength(toPlatformText(comment), 'facebook').toLocaleString('en-US') + '／' + (options?.rules.facebook.caption ?? 63206).toLocaleString('en-US')} over={overLimitReason(t('評論 {n} ', { n: i + 1 }), toPlatformText(comment), options?.rules.facebook.caption ?? 63206, 'facebook') || undefined} isOver={text => !!overflowAt(toPlatformText(text), options?.rules.facebook.caption ?? 63206, 'facebook')} media={{ onClick: () => { commentSlot.current = i; commentInput.current?.click(); }, disabled: !brandId || busy, title: image ? t('換一張圖片') : t('附上圖片（評論只能放圖片，不能放影片）') }} onUp={i ? () => move(i, i - 1) : undefined} onDown={i < comments.length - 1 ? () => move(i, i + 1) : undefined} onRemove={() => remove(i)}>
          {image && post && <div className="publish-comment-image"><img alt={image.name} src={'/api/publish/posts/' + post.id + '/media/' + image.id} /><small>{image.name}</small><button type="button" className="secondary small" disabled={locked || busy} onClick={() => clearImage(i)}>{t('移除圖片')}</button></div>}
        </PostCard>;
      })}</div>}
      <div className="publish-chain-add"><button type="button" className="primary small" disabled={locked || comments.length >= (options?.rules.facebook.comments ?? 20)} onClick={() => change([...comments, ''], [...images, null])}>{t('+ 評論')}</button>{comments.length > 0 && <small>{note}</small>}</div>
    </div>;
  }
  // Instagram 的「+ 評論」：發文成功後由 IG 帳號依序留言；IG 評論 API 只收文字，所以沒有附圖。
  function renderInstagramComments(first: ReactNode) {
    const comments = form.platform_options.instagram.comments, locked = editorDisabled || platformLocked('instagram');
    const change = (next: string[]) => updateForm({ ...form, platform_options: { ...form.platform_options, instagram: { ...form.platform_options.instagram, comments: next } } });
    const move = (i: number, j: number) => { const next = [...comments]; [next[i], next[j]] = [next[j], next[i]]; change(next); };
    const note = form.platforms.includes('instagram') ? t('評論會在 Instagram 發文成功後依序留言') : t('尚未開啟 Instagram，評論不會發出');
    return <div className={'publish-chain' + (comments.length ? ' has-replies' : '')}>{first}
      {comments.length > 0 && <div className="publish-segments">{comments.map((comment, i) => <PostCard key={i} className="publish-segment" id={'instagram-comment-' + i} label={t('Instagram 評論 {n}', { n: i + 1 })} value={comment} rows={4} disabled={locked} onChange={value => change(comments.map((s, j) => j === i ? value : s))} count={textLength(toPlatformText(comment), 'instagram').toLocaleString('en-US') + '／' + (options?.rules.instagram.caption ?? 2200).toLocaleString('en-US')} over={overLimitReason(t('評論 {n} ', { n: i + 1 }), toPlatformText(comment), options?.rules.instagram.caption ?? 2200, 'instagram') || undefined} isOver={text => !!overflowAt(toPlatformText(text), options?.rules.instagram.caption ?? 2200, 'instagram')} media={{ onClick: () => undefined, disabled: true, title: t('Instagram 評論只能放文字：IG 的評論 API 不支援附圖或影片') }} onUp={i ? () => move(i, i - 1) : undefined} onDown={i < comments.length - 1 ? () => move(i, i + 1) : undefined} onRemove={() => change(comments.filter((_, j) => j !== i))} />)}</div>}
      <div className="publish-chain-add"><button type="button" className="primary small" disabled={locked || comments.length >= (options?.rules.instagram.comments ?? 20)} onClick={() => change([...comments, ''])}>{t('+ 評論')}</button>{comments.length > 0 && <small>{note}</small>}</div>
    </div>;
  }
  function renderChain(first: ReactNode) {
    const replies = repliesOf(normalized), locked = editorDisabled || platformLocked('threads');
    const move = (i: number, j: number) => { const next = [...replies]; [next[i], next[j]] = [next[j], next[i]]; changeReplies(next); };
    return <div className={'publish-chain' + (replies.length ? ' has-replies' : '')}>{first}
      {replies.length > 0 && <div className="publish-segments">{replies.map((reply, i) => <PostCard key={i} className="publish-segment" id={'threads-reply-' + i} label={t('Threads 回覆 {n}', { n: i + 1 })} value={reply} rows={4} disabled={locked} onChange={value => changeReplies(replies.map((s, j) => j === i ? value : s))} count={textLength(reply) + '／' + threadsLimit} over={overLimitReason(t('回覆 {n}', { n: i + 1 }), toPlatformText(reply), threadsLimit) || undefined} isOver={text => !!overflowAt(toPlatformText(text), threadsLimit)} media={{ onClick: () => undefined, disabled: true, title: t('串文回覆目前只能放文字：工作檯還沒做回覆附圖') }} onUp={i ? () => move(i, i - 1) : undefined} onDown={i < replies.length - 1 ? () => move(i, i + 1) : undefined} onRemove={() => changeReplies(replies.filter((_, j) => j !== i))}><OverLimit label={t('回覆 {n}', { n: i + 1 })} text={reply} limit={threadsLimit} /></PostCard>)}</div>}
      <div className="publish-chain-add"><button type="button" className="primary small" disabled={locked} onClick={() => changeReplies([...replies, ''])}>{t('+ 串文')}</button>{replies.length > 0 && <small>{form.platforms.includes('threads') ? t('串文只會發到 Threads，其他平台只發第一則') : t('尚未開啟 Threads，串文不會發出')}</small>}</div>
    </div>;
  }
  function renderMedia() { return <div className="publish-step"><div className="publish-upload" onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); if (!editorDisabled) void upload(e.dataTransfer.files); }}><button className="secondary" disabled={editorDisabled || !brandId || (story && (post?.media.length || 0) >= 10)} onClick={() => fileInput.current?.click()}>{t('拖曳或點選上傳')}</button></div>
        <div className="publish-media-list">{post?.media.map((m, i) => <div key={m.id} className="publish-media-row" draggable={!editorDisabled && story} onDragStart={e => { draggedMedia.current = m.id; e.dataTransfer.setData('text/plain', String(m.id)); }} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); e.stopPropagation(); const id = draggedMedia.current; draggedMedia.current = null; if (!editorDisabled && story && id != null) void moveMedia(id, i); }}>{m.mime.startsWith('image/') ? <img alt={m.name} src={'/api/publish/posts/' + post.id + '/media/' + m.id} /> : <video controls preload="metadata" src={'/api/publish/posts/' + post.id + '/media/' + m.id} />}<div><strong>{m.name}</strong><small>{m.width} × {m.height}{m.duration !== null && ' · ' + t('{seconds} 秒', { seconds: m.duration.toFixed(1) })}</small></div><div className="action-row">{story && <><button className="secondary" disabled={editorDisabled || i === 0} onClick={() => void perform(async () => { const media = [...post.media]; [media[i - 1], media[i]] = [media[i], media[i - 1]]; remember({ ...post, media }); await persist(); })}>{t('上移')}</button><button className="secondary" disabled={editorDisabled || i === post.media.length - 1} onClick={() => void perform(async () => { const media = [...post.media]; [media[i + 1], media[i]] = [media[i], media[i + 1]]; remember({ ...post, media }); await persist(); })}>{t('下移')}</button></>}<button className="primary danger" disabled={editorDisabled} onClick={() => void removeMedia(m.id)}>{t('移除')}</button></div></div>)}</div></div>; }
  const rows = posts.filter(p => tab === 'drafts' ? p.status === 'draft' : tab === 'scheduled' ? ['scheduled', 'paused'].includes(p.status) : ['publishing', 'done', 'partial', 'failed', 'missed'].includes(p.status));
  return <section className={embedded ? 'publish-page publish-embedded' : 'publish-page settings-page'}>
    {!embedded && <>
    <PageHeader title={t('發佈')} children={<div className="publish-switch">{can(user, 'settings.manage') && brandId && <button className="secondary" disabled={busy || !options} onClick={() => setSwitchConfirm(true)}>{options?.enabled ? t('關閉發佈') : t('開啟發佈')}</button>}</div>} />
    {options && !options.enabled && <p className="notice warning">{t('發佈功能尚未開啟，貼文只能存成草稿')}</p>}
    <div className="publish-brand-row">{options && <ul className="publish-accounts" aria-label={t('發佈帳號')}>{Object.entries(options.platforms).filter(([p]) => tab !== 'story' || (p === 'facebook' || p === 'instagram')).map(([p, v]) => <li key={p} className={'publish-account ' + (v.ready ? 'ready' : 'off')} title={v.ready ? t('可發佈') : v.reasons.join(t('、'))}><span className="publish-account-dot" aria-hidden="true" /><span className="publish-account-platform">{labels[p as Platform]}</span><strong>{v.name}</strong>{!v.ready && <span className="sr-only">{t('（{reasons}）', { reasons: v.reasons.join(t('、')) || t('尚未就緒') })}</span>}</li>)}</ul>}</div>
    <div className="tabs publish-tabs" role="tablist" aria-label={t('發佈分頁')}>{(canEdit ? [['new', t('新增貼文')], ['story', t('限時動態')], ['drafts', t('草稿')], ['scheduled', t('排程中')], ['history', t('發佈紀錄')]] : [['history', t('發佈紀錄')]]).map(([value, label], index, all) => <button key={value} className="secondary" role="tab" id={'publish-tab-' + value} aria-controls={'publish-panel-' + value} aria-selected={tab === value} tabIndex={tab === value ? 0 : -1} onClick={() => void switchTab(value)} onKeyDown={e => { const offset = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0; if (offset || e.key === 'Home' || e.key === 'End') { e.preventDefault(); const next = e.key === 'Home' ? 0 : e.key === 'End' ? all.length - 1 : (index + offset + all.length) % all.length; void switchTab(all[next][0]); document.getElementById('publish-tab-' + all[next][0])?.focus(); } }}>{label}</button>)}</div>
    </>}
    {error && <p className="notice danger" role="alert">{error}</p>}{notice && <p className="notice success" role="status">{notice}</p>}
    <div role="tabpanel" id={'publish-panel-' + tab} aria-labelledby={'publish-tab-' + tab}>
    {['new', 'story'].includes(tab) && canEdit && (!embedded || post) ? <div className={'section-card publish-editor' + (story ? ' publish-story-editor' : '')} data-check-state={Object.keys(results).length ? 'checked' : 'pending'} aria-busy={busy || loadedScope !== scopeKey}>
      {/* 素材由文案框的「媒體」上傳，顯示在預覽裡；格式依素材自動判斷。 */}
      <input ref={fileInput} type="file" aria-label={t('上傳媒體')} accept="video/mp4,video/quicktime,image/jpeg,image/png" multiple hidden onChange={e => { if (e.target.files) void upload(e.target.files); e.target.value = ''; }} />
      <div className="publish-editor-top">
      <div className="publish-editor-heading">{post && <span className="publish-record-id publish-editing-id">{t('編輯中 #{id}', { id: post.id })} · {states[post.status] || post.status}</span>}{post && <AgentSource post={post} />}{!embedded && <button className="secondary" disabled={busy} onClick={() => void newPost()}>{story ? t('新限時動態') : t('新貼文')}</button>}</div>
      <div className="publish-composer-tabs publish-platforms" role="tablist" aria-label={t('文案平台')}>{activeTabs.map((p, index) => {
        const platform = p, ready = isReady(p);
        const errors = platform && ready && (!videoOnly(platform) || form.platforms.includes(platform)) ? platformErrors(platform) : [];
        return <div key={p} className={'publish-platform publish-composer-tab ' + (ready ? 'ready' : 'off')}>
          <button className="secondary" disabled={busy} role="tab" id={'composer-tab-' + p} aria-controls={'composer-panel-' + p} aria-selected={activePlatform === p} tabIndex={activePlatform === p ? 0 : -1} onClick={() => setComposerTab(p)} onKeyDown={e => {
            const offset = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
            if (offset || e.key === 'Home' || e.key === 'End') { e.preventDefault(); const next = e.key === 'Home' ? 0 : e.key === 'End' ? activeTabs.length - 1 : (index + offset + activeTabs.length) % activeTabs.length; setComposerTab(activeTabs[next]); document.getElementById('composer-tab-' + activeTabs[next])?.focus(); }
          }}>{labels[p]}{errors.length > 0 && <span className="publish-tab-error" aria-hidden="true" title={errors.join(t('；'))} />}</button>
          <label className="publish-platform-heading publish-platform-toggle"><input type="checkbox" role="switch" aria-label={t('發佈到 {platform}', { platform: labels[p] })} title={videoOnly(p) && form.format !== 'video' ? (p === 'tiktok' ? TIKTOK_IMAGE_REASON : t('YouTube 只支援影片')) : undefined} checked={!!platform && form.platforms.includes(platform)} disabled={editorDisabled || !ready || !!(platform && platformLocked(platform)) || (videoOnly(p) && form.format !== 'video' && !(platform && form.platforms.includes(platform)))} onChange={e => { if (platform) updateForm({ ...form, platforms: e.target.checked ? [...form.platforms, platform] : form.platforms.filter(x => x !== platform), ...(platform === 'facebook' && !e.target.checked && !facebookLocked ? { facebook_unpublished: false } : {}) }); }} /><span className="sr-only">{labels[p]}</span></label>
        </div>;
      })}</div></div>
      <div className="publish-composer-panel" role="tabpanel" id={'composer-panel-' + activePlatform} aria-labelledby={'composer-tab-' + activePlatform}>
        {/* 非管理員的設定頁只有「我的帳號」，給連結只會落在錯的頁面，改文字請對方找管理員。 */}
        {!connected && <div className="publish-disconnected"><p>{(activePlatform && options?.platforms[activePlatform]?.hint) || t('尚未連結')}</p>{!can(user, 'connections.manage') ? <p>{t('請聯絡管理員連結平台')}</p> : <a className="secondary" href={'?view=settings&settings_tab=connections&brand_id=' + brandId + (post ? '&publish_post_id=' + post.id : '')} onClick={e => { if (!e.ctrlKey && !e.metaKey && !e.shiftKey && !e.altKey) { e.preventDefault(); onConnections(); } }}>{t('設定 → 平台連結')}</a>}</div>}
        <div className="publish-composer-grid">
          <div className="publish-composer-fields">
            {story ? <>{renderMedia()}{[...new Set(form.platforms.flatMap(p => ruleChecks[p].warnings))].map(w => <p className="notice warning" key={w}>{w}</p>)}</> : activePlatform === 'youtube' && form.format !== 'video' ? <p className="notice warning" role="status">{t('YouTube 只支援影片')}</p> : activePlatform === 'tiktok' && form.format !== 'video' ? <p className="notice warning" role="status">{TIKTOK_IMAGE_REASON}</p> : <>
              <div className="publish-caption-heading"><span>{options?.platforms[activePlatform]?.name}</span>{!form.platforms.includes(activePlatform) && <span className="status-badge neutral">{t('未開啟')}</span>}{form.captions[activePlatform] !== undefined ? <button className="secondary small" disabled={editorDisabled || platformLocked(activePlatform)} onClick={() => restoreShared(activePlatform)}>{t('改回主文案')}</button> : <><small className="publish-caption-hint">{t('沿用主文案，修改會同步到其他沒有另寫的平台')}</small><button className="secondary small" disabled={editorDisabled || platformLocked(activePlatform)} onClick={() => writeOwn(activePlatform)}>{t('此平台另寫')}</button></>}</div>
              {activePlatform === 'threads' ? renderChain(platformCard(activePlatform)) : activePlatform === 'facebook' ? renderComments(platformCard(activePlatform)) : activePlatform === 'instagram' ? renderInstagramComments(platformCard(activePlatform)) : activePlatform === 'youtube' ? <div className="publish-chain"><div className="publish-youtube-stack">
                {/* 標題和說明卡片同樣是灰底面板裡的白框，上方各有欄名；字數只算標題框實際輸入的字。沒填標題時發佈仍沿用說明第一行（預覽顯示實際標題）。 */}
                <span className="publish-youtube-label" aria-hidden="true">{t('標題：')}</span>
                <div className="publish-post-card publish-youtube-title"><div className="publish-post-body"><div className="publish-post-box"><input aria-label={t('YouTube 標題')} value={youtubeOptions.title} placeholder={t('請輸入標題')} disabled={editorDisabled || platformLocked('youtube')} onChange={e => setYoutube({ title: e.target.value })} /><small className="publish-post-count">{Array.from(youtubeOptions.title).length.toLocaleString('en-US') + '／' + (options?.rules.youtube?.title ?? 100).toLocaleString('en-US')}</small></div></div></div>
                <span className="publish-youtube-label" aria-hidden="true">{t('描述欄：')}</span>
                {platformCard(activePlatform)}
              </div></div> : <div className="publish-chain">{platformCard(activePlatform)}</div>}<MarkdownHint text={form.captions[activePlatform] ?? form.caption} />
              {activePlatform === 'tiktok' && <p className="notice tiktok-caption-notice" role="note">{TIKTOK_CAPTION_NOTICE}</p>}
              {activePlatform === 'facebook' && <div className="publish-platform-options">{form.format === 'video' && <SegmentedControl compact label={t('Facebook 影片形式')} options={[{ value: 'feed', label: t('影片貼文') }, { value: 'reels', label: 'Reels' }]} value={form.platform_options.facebook.video_format} disabled={editorDisabled || facebookLocked} onChange={video_format => updateForm({ ...form, platform_options: { ...form.platform_options, facebook: { ...form.platform_options.facebook, video_format } } })} />}<label className="publish-unpublished"><input type="checkbox" checked={form.facebook_unpublished} disabled={editorDisabled || facebookLocked} onChange={e => updateForm({ ...form, facebook_unpublished: e.target.checked })} />{t('存成 FB 草稿（不發佈，可在 Meta Business Suite 草稿編輯後再發）')}</label>{form.format === 'video' && <div className="publish-thumbnail publish-cover publish-facebook-cover"><span>{t('影片封面')}</span>{post?.facebook_cover && <img alt={post.facebook_cover.name} src={'/api/publish/posts/' + post.id + '/media/' + post.facebook_cover.id} />}<small>{post?.facebook_cover ? post.facebook_cover.name + ' · ' + sizeLabel(post.facebook_cover.size) : t('JPG／PNG · 8 MB 內 · 建議與影片同比例 · 未上傳則由 Facebook 自動選')}</small><div className="action-row"><button className="secondary" disabled={editorDisabled || facebookLocked || !brandId} onClick={() => facebookCoverInput.current?.click()}>{post?.facebook_cover ? t('更換封面') : t('上傳封面')}</button>{post?.facebook_cover && <button className="primary danger" disabled={editorDisabled || facebookLocked} onClick={() => void removeThumbnail('fb_cover')}>{t('移除封面')}</button>}</div><input ref={facebookCoverInput} type="file" aria-label={t('上傳 Facebook 影片封面')} accept="image/jpeg,image/png" hidden onChange={e => { void uploadThumbnail(e.target.files, 'fb_cover'); e.target.value = ''; }} />{options?.platforms.facebook?.cover_hint && <p className="notice publish-cover-hint" role="note">{options.platforms.facebook.cover_hint}</p>}</div>}</div>}
              {activePlatform === 'instagram' && form.format === 'video' && <div className="publish-platform-options"><label className="publish-unpublished"><input type="checkbox" role="switch" checked={form.platform_options.instagram.share_to_feed} disabled={editorDisabled || platformLocked('instagram')} onChange={e => updateForm({ ...form, platform_options: { ...form.platform_options, instagram: { ...form.platform_options.instagram, share_to_feed: e.target.checked } } })} />{t('同時顯示在動態')}</label>
                <div className="publish-thumbnail publish-cover"><span>{t('Reels 封面')}</span>{post?.cover && <img alt={post.cover.name} src={'/api/publish/posts/' + post.id + '/media/' + post.cover.id} />}<small>{post?.cover ? post.cover.name + ' · ' + sizeLabel(post.cover.size) : t('JPG／PNG · 8 MB 內 · 建議 9:16 · 未上傳則用影片第一格')}</small><div className="action-row"><button className="secondary" disabled={editorDisabled || platformLocked('instagram') || !brandId} onClick={() => coverInput.current?.click()}>{post?.cover ? t('更換封面') : t('上傳封面')}</button>{post?.cover && <button className="primary danger" disabled={editorDisabled || platformLocked('instagram')} onClick={() => void removeThumbnail('cover')}>{t('移除封面')}</button>}</div><input ref={coverInput} type="file" aria-label={t('上傳 Reels 封面')} accept="image/jpeg,image/png" hidden onChange={e => { void uploadThumbnail(e.target.files, 'cover'); e.target.value = ''; }} /></div></div>}
                            {activePlatform === 'youtube' && <div className="publish-platform-options"><SegmentedControl compact label={t('公開狀態')} options={privacyOptions} value={youtubeOptions.privacy} disabled={editorDisabled || platformLocked('youtube')} onChange={privacy => setYoutube({ privacy })} /><label className="publish-unpublished"><input type="checkbox" checked={youtubeOptions.made_for_kids} disabled={editorDisabled || platformLocked('youtube')} onChange={e => setYoutube({ made_for_kids: e.target.checked })} />{t('這是為兒童製作的內容')}</label>
                <div className="publish-thumbnail"><span>{t('自訂縮圖')}</span>{post?.thumbnail && <img alt={post.thumbnail.name} src={'/api/publish/posts/' + post.id + '/media/' + post.thumbnail.id} />}<small>{post?.thumbnail ? post.thumbnail.name + ' · ' + sizeLabel(post.thumbnail.size) : t('JPG／PNG · 50 MB 內 · 未上傳則用自動縮圖')}</small><div className="action-row"><button className="secondary" disabled={editorDisabled || platformLocked('youtube') || !brandId} onClick={() => thumbnailInput.current?.click()}>{post?.thumbnail ? t('更換縮圖') : t('上傳縮圖')}</button>{post?.thumbnail && <button className="primary danger" disabled={editorDisabled || platformLocked('youtube')} onClick={() => void removeThumbnail()}>{t('移除縮圖')}</button>}</div><input ref={thumbnailInput} type="file" aria-label={t('上傳縮圖')} accept="image/jpeg,image/png" hidden onChange={e => { void uploadThumbnail(e.target.files); e.target.value = ''; }} /></div></div>}
              {[...new Set([...ruleChecks[activePlatform].warnings, ...(results[activePlatform]?.warnings || []), ...(activePlatform === 'facebook' ? post?.warnings || [] : [])].map(warning => t(warning)))].map(warning => <p className="notice warning" key={warning}>{warning}</p>)}
            </>}
          </div>
          <PublishPreview platform={shownPlatform} name={options?.platforms[shownPlatform]?.name || ''} brandName={brands.find(b => String(b.id) === brandId)?.name || ''} caption={platformCaption(form.captions, form.caption, shownPlatform)} format={form.format} media={post?.media || []} postId={post?.id} onRemoveMedia={story ? undefined : id => void removeMedia(id)} onMoveMedia={story ? undefined : (id, index) => void moveMedia(id, index)} mediaLocked={editorDisabled} options={normalized.platform_options} unpublished={form.facebook_unpublished} title={effectiveTitle} thumbnail={post?.thumbnail ? '/api/publish/posts/' + post.id + '/media/' + post.thumbnail.id : undefined} cover={post?.cover ? '/api/publish/posts/' + post.id + '/media/' + post.cover.id : undefined} facebookCover={post?.facebook_cover ? '/api/publish/posts/' + post.id + '/media/' + post.facebook_cover.id : undefined} />
        </div>
      </div>
      {!embedded && <div className="publish-footer">
        {shownReason && <p id="publish-disabled-reason" className="publish-reasons" role="status">{shownReason}</p>}
        <div className="publish-schedule"><SegmentedControl compact label={t('發佈時間')} options={[{ value: 'now', label: t('立即發佈') }, { value: 'scheduled', label: t('排程') }]} value={mode} disabled={busy} onChange={setMode} />{mode === 'scheduled' && <label>{t('日期時間（台北）')}<input type="datetime-local" aria-label={t('排程時間（台北）')} value={time} disabled={busy} onChange={e => setTime(e.target.value)} /></label>}</div>
        <div className="publish-submit">
        <div className="action-row publish-actions">{!story && <button className="secondary" disabled={busy || !brandId} onClick={() => void perform(async () => { await persist(); setNotice(t('草稿已儲存')); await reload(); })}>{t('存成草稿')}</button>}{canSubmit ? <button className="primary" aria-describedby="publish-disabled-reason" title={disabledReason} disabled={editorDisabled || !options?.enabled || !valid || (mode === 'scheduled' && !time)} onClick={() => void confirmation()}>{mode === 'scheduled' ? t('排程') : t('發佈')}</button> : <span className="muted">{t('此角色只能編輯草稿，發佈需由有權限的成員送出')}</span>}</div>
        </div>
      </div>}
    </div> : embedded ? null : <>{tab === 'history' && <div className="publish-presence"><span>{t('上次檢查：')}{lastCheck ? taipei(new Date(lastCheck).toISOString()) : t('尚未檢查')}</span>{canEdit && <button className="primary" disabled={checking || busy || !brandId} aria-busy={checking} onClick={() => void checkPresence()}>{checking ? t('檢查中…') : t('檢查平台貼文')}</button>}</div>}{tab === 'history' && presence && <p className={'notice ' + presence.tone} role="status">{presence.text}</p>}<div className="list-box publish-records">{rows.length ? rows.map(row => <div className="list-row publish-record" key={row.id}><div className="publish-record-heading"><span className="publish-record-id" title={t('貼文編號')}>#{row.id}</span><time>{taipei(tab === 'drafts' ? row.updated_at : row.scheduled_at || row.created_at)}</time><span className="status-badge neutral">{row.format === 'story' ? t('限時動態') : formats.find(f => f.value === row.format)?.label}</span><AgentSource post={row} history={tab === 'history'} />{row.source === 'ideation' && <span className="status-badge neutral publish-source">{t('來自主題')}</span>}{row.source === 'flow' && <span className="status-badge neutral publish-source">{t('來自流程')}</span>}<strong className={tab === 'drafts' ? 'publish-caption-start' : undefined} title={row.caption}>{row.format === 'story' ? t('{count} 則', { count: row.media.length }) : row.caption.slice(0, 60) || t('（無文案）')}</strong>{tab === 'drafts' && <span>{t('{count} 個媒體', { count: row.media.length })}</span>}<span>{row.platforms.map(p => labels[p] + (hiddenFacebook(row, p) ? ' · ' + t('草稿') : '')).join(t('、'))}</span>{goneState(row) === 'all' ? <span className="status-badge neutral">{t('已在平台刪除')}</span> : <span className={'status-badge ' + (row.status === 'done' ? 'ready' : ['failed', 'partial', 'missed'].includes(row.status) ? 'failed' : 'pending')}>{states[row.status]}{row.locked && ' · ' + t('已鎖定')}{goneState(row) === 'some' && ' · ' + t('部分已刪除')}</span>}</div><div className="action-row">{tab === 'scheduled' && canEdit && <><button className="secondary" disabled={row.locked || busy} onClick={() => edit(row)}>{t('編輯')}</button>{canSubmit && <button className="secondary" disabled={row.locked || busy} onClick={() => setCancelConfirm(row)}>{t('取消排程')}</button>}</>}{tab === 'history' && <button className="secondary" aria-expanded={expanded === row.id} onClick={() => setExpanded(expanded === row.id ? null : row.id)}>{t('各平台結果')}</button>}{canEdit && row.status === 'draft' && <><button className="secondary" onClick={() => edit(row)}>{t('編輯')}</button><button className="primary danger" onClick={() => setCancelConfirm(row)}>{t('刪除')}</button></>}{canSubmit && ['failed', 'partial', 'missed'].includes(row.status) && <><button className="secondary" disabled={busy || !options?.enabled} onClick={() => void confirmation(row, row.status !== 'missed')}>{row.status === 'missed' ? t('立即發佈') : t('只重試失敗平台')}</button><button className="secondary" disabled={busy} onClick={() => { setTime(''); setReschedule(row); }}>{t('重新排程')}</button></>}</div>{expanded === row.id && <div className="publish-targets">{row.targets.map(target => <div key={target.platform}>{target.deleted_at ? <><span className="status-badge neutral">{labels[target.platform]} · {t('已在平台刪除')}</span><span>{t('偵測於 {time}', { time: taipei(target.deleted_at) })}</span></> : <><span className={'status-badge ' + (hiddenFacebook(row, target.platform) && target.status === 'succeeded' ? 'neutral' : targetTone(target.status))}>{labels[target.platform]} · {targetLabels[target.status] || t('失敗')}{hiddenFacebook(row, target.platform) && ' · ' + t('草稿')}</span>{target.platform === 'threads' && target.detail?.total_segments != null && <span>{t('已發 {done}／{total} 段', { done: target.detail?.successful_segments || 0, total: target.detail?.total_segments ?? '' })}</span>}{(target.platform === 'facebook' || target.platform === 'instagram') && !!target.detail?.total_comments && <span>{t('已留 {done}／{total} 則評論', { done: target.detail.successful_comments || 0, total: target.detail.total_comments })}</span>}{row.format === 'story' && <><span>{t('已發 {done}／{total} 則', { done: target.detail?.successful_stories || 0, total: target.detail?.total_stories || row.media.length })}{target.detail?.failed_story ? ' · ' + t('第 {n} 則失敗', { n: target.detail.failed_story }) : ''}</span>{target.platform === 'facebook' ? <span className="publish-story-unavailable">{t('Facebook 不提供限時動態成效')}</span> : <div className="publish-story-results">{(target.stories || []).map(item => <div className="publish-story-result" key={item.position}><strong>{t('第 {n} 則', { n: item.position })}{item.final ? ' · ' + t('最終值') : ''}</strong><dl>{Object.entries(storyMetricLabels).map(([key, name]) => <div key={key}><dt>{name}</dt><dd>{item.metrics[key]?.toLocaleString('en-US') ?? '—'}</dd></div>)}</dl></div>)}</div>}</>}{target.platform === 'youtube' && target.status === 'succeeded' && !!target.detail?.privacy_status && target.detail.privacy_status !== row.platform_options?.youtube.privacy && <span className="status-badge pending">{t('YouTube 實際為{privacy}', { privacy: privacyLabels[target.detail.privacy_status as keyof typeof privacyLabels] ?? target.detail.privacy_status })}</span>}{target.platform === 'youtube' && target.status === 'succeeded' && target.detail?.thumbnail?.status === 'failed' && <><span className="status-badge pending">{t('縮圖未套用')}</span><span>{target.detail.thumbnail.reason}</span>{canSubmit && <button className="secondary" disabled={busy || !options?.enabled} onClick={() => setThumbnailConfirm(row)}>{t('重新套用縮圖')}</button>}</>}{target.platform === 'facebook' && target.status === 'succeeded' && target.detail?.cover?.status === 'failed' && <><span className="status-badge pending">{t('封面未套用')}</span><span>{target.detail.cover.reason}</span>{canSubmit && <button className="secondary" disabled={busy || !options?.enabled} onClick={() => setCoverConfirm(row)}>{t('重新套用封面')}</button>}</>}{target.platform === 'tiktok' && target.status === 'succeeded' && <><span className={'status-badge ' + (target.detail?.inbox_state === 'PUBLISH_COMPLETE' ? 'ready' : 'pending')}>{tiktokStates[target.detail?.inbox_state || ''] || t('已送到收件匣')}</span><button className="secondary" onClick={() => void copyCaption(row)}>{copied === row.id ? t('已複製') : t('複製文案')}</button></>}{target.permalink ? <a href={target.permalink} target="_blank" rel="noreferrer">{target.platform === 'youtube' ? t('查看影片') : t('查看貼文')}</a> : <span>{target.reason}</span>}</>}</div>)}</div>}</div>) : <p className="empty-data">{tab === 'drafts' ? t('尚無草稿') : tab === 'scheduled' ? t('尚無排程') : t('尚無發佈紀錄')}</p>}</div></>}
    </div>
    {reschedule && <div className="section-card"><label>{t('重新排程（台北）')}<input type="datetime-local" aria-label={t('重新排程時間（台北）')} value={time} onChange={e => setTime(e.target.value)} /></label><div className="action-row"><button className="secondary" onClick={() => setReschedule(null)}>{t('取消')}</button><button className="primary" disabled={!time || busy || !options?.enabled} onClick={() => { const row = reschedule; setReschedule(null); void confirmation(row, row.status !== 'missed', new Date(time + '+08:00').toISOString()); }}>{t('排程')}</button></div></div>}
    {confirm && (() => {
      const chosen = confirm.post.platforms.filter(p => !confirm.retry || confirm.post.targets.some(t => t.platform === p && t.status === 'failed'));
      return <ConfirmDialog heading={confirm.scheduled ? t('確認排程到 {count} 個平台', { count: chosen.length }) : t('確認發佈到 {count} 個平台', { count: chosen.length })} confirmLabel={t('確認發佈')} onClose={() => setConfirm(null)} onConfirm={() => void send()}>
        <ul className="list-box publish-confirm-list">{chosen.map(p => <li key={p}>
          <div className="publish-confirm-platform"><strong>{labels[p]}</strong><span>{options?.platforms[p].name || ''}</span>{!!confirm.post.captions[p]?.trim() && <span className="status-badge neutral">{t('另寫文案')}</span>}</div>
          <p className="publish-confirm-options">{confirm.post.format === 'story' ? t('限時動態') + ' · ' + t('{count} 則', { count: confirm.post.media.length }) : p === 'facebook' ? (confirm.post.format === 'video' ? (loadedPlatformOptions(confirm.post.platform_options).facebook.video_format === 'feed' ? t('影片貼文') : 'Reels') + ' · ' + (confirm.post.facebook_cover ? t('自訂封面') : t('預設封面')) : formats.find(f => f.value === confirm.post.format)?.label) : p === 'instagram' ? (confirm.post.format === 'video' ? 'Reels · ' + (loadedPlatformOptions(confirm.post.platform_options).instagram.share_to_feed ? t('同時顯示在動態') : t('不顯示在動態')) + ' · ' + (confirm.post.cover ? t('自訂封面') : t('預設封面')) : formats.find(f => f.value === confirm.post.format)?.label) : p === 'youtube' ? youtubeSummary(confirm.post) : p === 'tiktok' ? t('影片 · 送到 TikTok 收件匣（文案不會送出，需在 App 內貼上並發佈）') : p === 'x' ? formats.find(f => f.value === confirm.post.format)?.label + (xHasUrl(sentCaption(confirm.post.captions, confirm.post.caption, 'x')) ? ' · ' + t('含網址，費用較高') : '') : t('串文') + ' · ' + t('{count} 段', { count: loadedPlatformOptions(confirm.post.platform_options).threads.segments.length || 1 })}{p === 'facebook' && confirm.post.facebook_unpublished && ' · ' + t('草稿')}{confirm.post.format !== 'story' && (p === 'instagram' || (p === 'facebook' && !confirm.post.facebook_unpublished)) && loadedPlatformOptions(confirm.post.platform_options)[p].comments.length > 0 && ' · ' + t('發文後留 {count} 則評論', { count: loadedPlatformOptions(confirm.post.platform_options)[p].comments.length })}</p>
           {confirm.post.format !== 'story' && (p === 'youtube' ? <p>{t('標題：')}{youtubeTitle(loadedPlatformOptions(confirm.post.platform_options).youtube.title, sentCaption(confirm.post.captions, confirm.post.caption, 'youtube')) || t('（無標題）')}</p> : <p>{(p === 'threads' && loadedPlatformOptions(confirm.post.platform_options).threads.segments[0]?.trim() ? toPlatformText(loadedPlatformOptions(confirm.post.platform_options).threads.segments[0]) : sentCaption(confirm.post.captions, confirm.post.caption, p)).slice(0, 100) || t('（無文案）')}</p>)}
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

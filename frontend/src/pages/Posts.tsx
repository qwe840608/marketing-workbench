import { ReportReturn } from './ReportReturn';
import { PageHeader } from './PageHeader';
import { useEffect, useMemo, useRef, useState } from 'react';
import { api, ApiError } from '../api';
import type { CommentSync, Metric, Post } from '../api';
import { commentRows, readPostPlatform, retentionNotice } from '../postComments';
import type { PostComment, Retention } from '../postComments';
import { dateQuery, readDateFilter, syncSummary, writeDateFilter } from '../postDateFilters';
import { PostDateFilter } from './PostDateFilter';
import { MetricChart } from './MetricChart';
import { Followers } from './Followers';
import { MetricSyncButton } from './MetricSyncButton';
import { backfillWaitText } from '../backfillWait';
import { ConfirmDialog } from './ConfirmDialog';
import { SegmentedControl } from './SegmentedControl';
import { metricFields, metricValue, snapshotColumns, syncLabel } from '../metricFields';
import { pollWhileVisible } from '../visiblePolling';
import { locale, t } from '../i18n.ts';

const time = (value: string) => new Intl.DateTimeFormat(locale(), { timeZone: 'Asia/Taipei',
  year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value));
const tiers: Record<string, string> = { hourly: t('每小時'), daily: t('每天'), weekly: t('每週') };
// 這些平台的貼文、成效與留言（回覆）由工作檯同步並可在此查看。
const visibilityLabels: Record<string, string> = { public: t('公開'), unlisted: t('不公開'), private: t('私人') };
const postKind = (post: Post) => (post.media_type === 'SHORTS' ? 'Shorts' : post.media_type === 'VIDEO' ? t('影片') : post.media_type === 'REELS' ? 'Reels' : t('貼文')) + (post.visibility && visibilityLabels[post.visibility] ? ' · ' + visibilityLabels[post.visibility] : '');
// 有貼文同步的平台；TikTok 只同步影片與成效，不讀留言（見 pollable）。
const synced = ['facebook', 'instagram', 'threads', 'youtube', 'tiktok'];
const platforms = [['facebook', 'FB'], ['instagram', 'IG'], ['youtube', 'YouTube'], ['tiktok', 'TikTok'], ['threads', 'Threads']] as const;
const number = (value: number | null | undefined) => value == null ? '—' : value.toLocaleString(locale());
type Account = { id: number; brand_id: number; platform: string; name: string };
export function Posts({ brand, initialPostId, onLogout, canSync }: { brand: string; initialPostId: number | null; onLogout: () => void; canSync: boolean }) {
  const [posts, setPosts] = useState<Post[]>([]), [selected, setSelected] = useState<Post | null>(null);
  const [metrics, setMetrics] = useState<Metric[]>([]), [error, setError] = useState('');
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [sync, setSync] = useState<CommentSync | null>(null), [syncing, setSyncing] = useState(false);
  const [notice, setNotice] = useState('');
  const [confirmRescan, setConfirmRescan] = useState(false);
  const [platform, setPlatform] = useState<string | null>(() => readPostPlatform(location.search));
  const [offset, setOffset] = useState(0), [revision, setRevision] = useState(0), [loading, setLoading] = useState(true);
  const [comments, setComments] = useState<PostComment[]>([]), [commentTotal, setCommentTotal] = useState(0), [commentsLoading, setCommentsLoading] = useState(false);
  const [postDates, setPostDates] = useState(() => readDateFilter(location.search, 'post'));
  const [commentDates, setCommentDates] = useState(() => {
    const value = readDateFilter(location.search, 'comment');
    const params = new URLSearchParams(location.search);
    return { ...value, period: (params.has('comment_range') && ['7', '30', '90', 'all'].includes(value.period) ? value.period : params.has('comment_id') ? '90' : '30') as '7' | '30' | '90' | 'all', from: '', to: '' };
  });
  const [rangeTotal, setRangeTotal] = useState(0), [nextOffset, setNextOffset] = useState<number | null>(null);
  const [rootIds, setRootIds] = useState<number[]>([]);
  const focusId = useRef(Number(new URLSearchParams(location.search).get('comment_id')) || null);
  const focusScrolled = useRef(false);
  const loadMore = useRef<() => void>(() => {});
  const [metricPostId, setMetricPostId] = useState<number | null>(null);
  const [detailId, setDetailId] = useState<number | null>(null);
  const scope = useRef(brand), first = useRef(true);
  const requestedPostId = useRef(initialPostId || Number(new URLSearchParams(location.search).get('post_id')));
  const selectedId = selected?.id;
  // 長內文預設收合，讓留言與成效不被擠到下方；換貼文時重新收合。
  const [captionOpen, setCaptionOpen] = useState(false);
  useEffect(() => setCaptionOpen(false), [selectedId]);
  const caption = selected?.caption || '';
  const longCaption = caption.split('\n').length > 4 || caption.length > 160;
  const latest = metrics.at(-1);
  const rows = useMemo(() => commentRows(comments, true, rootIds), [comments, rootIds]);
  const accountById = new Map(accounts.map(account => [account.id, account]));
  const accountName = (post: Post) => accountById.get(post.account_id)?.name || '';
  // TikTok 留言需要公司身分申請的 API，工作檯不讀，所以沒有抓取留言與同步狀態。
  const pollable = selected && platform !== 'tiktok';
  const query = () => new URLSearchParams({ ...(brand ? { brand_id: brand } : {}), ...(platform ? { platform } : {}) }).toString();
  function fail(error: unknown) {
    if (error instanceof ApiError && error.status === 401) onLogout();
    else setError(error instanceof Error ? error.message : t('讀取失敗，請重試'));
  }
  useEffect(() => {
    const controller = new AbortController();
    async function initialize() {
      try {
        const accountRows: Account[] = [];
        for (let offset = 0; ; offset += 200) {
          const batch = await api<Account[]>('/accounts?limit=200&offset=' + offset, { signal: controller.signal });
          accountRows.push(...batch); if (batch.length < 200) break;
        }
        if (controller.signal.aborted) return;
        setAccounts(accountRows);
        const id = first.current ? initialPostId || requestedPostId.current : null;
        first.current = false;
        if (id && Number.isSafeInteger(id) && id > 0) {
          const post = await api<Post>('/posts/' + id, { signal: controller.signal });
          const account = accountRows.find(a => a.id === post.account_id);
          if (account && (!brand || String(account.brand_id) === brand) && synced.includes(account.platform)) {
            setPlatform(account.platform); setSelected(post); return;
          }
        }
        if (!platform || scope.current !== brand) {
          const result = await api<{ default_platform: string }>('/posts/platforms?' + new URLSearchParams({ ...(brand ? { brand_id: brand } : {}) }), { signal: controller.signal });
          if (!controller.signal.aborted) setPlatform(result.default_platform);
        }
        scope.current = brand;
      } catch (e) {
        // 還沒有平台時清單的讀取 effect 不會執行，要在這裡結束「正在讀取貼文…」才看得到錯誤。
        if (!controller.signal.aborted) { fail(e); if (!platform) setLoading(false); }
      }
    }
    setSelected(null); setPosts([]); setOffset(0);
    void initialize();
    return () => controller.abort();
  }, [brand, initialPostId]);
  const [retention, setRetention] = useState<Retention | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    // 提示文字讀後端實際設定；讀不到就不顯示，避免寫死與規則不一致的天數。
    api<Partial<Retention>>('/posts/platforms?' + new URLSearchParams({ ...(brand ? { brand_id: brand } : {}) }), { signal: controller.signal })
      .then(value => { if (typeof value.comment_retention_days === 'number') setRetention(value as Retention); })
      .catch(() => undefined);
    return () => controller.abort();
  }, [brand]);
  useEffect(() => {
    if (!platform) return;
    const params = new URLSearchParams(location.search);
    params.set('post_platform', platform);
    if (selectedId) params.set('post_id', String(selectedId)); else params.delete('post_id');
    writeDateFilter(params, 'post', postDates); writeDateFilter(params, 'comment', commentDates);
    history.replaceState(null, '', location.pathname + '?' + params + location.hash);
  }, [platform, selectedId, postDates, commentDates]);
  useEffect(() => {
    if (!platform) return;
    if (!synced.includes(platform)) { setPosts([]); setLoading(false); return; }
    // 分頁隱藏時暫停輪詢，回到前景立即重抓。
    setLoading(true);
    return pollWhileVisible(async signal => {
      try {
        const result = await api<Post[]>('/posts?' + query() + '&' + dateQuery(postDates) + '&' + new URLSearchParams({ limit: '50', offset: String(offset) }), { signal });
        if (!signal.aborted) { setPosts(result); setError(''); }
      } catch (e) { if (!signal.aborted) fail(e); }
      finally { if (!signal.aborted) setLoading(false); }
    }, 15000);
  }, [brand, platform, offset, revision, postDates]);
  useEffect(() => {
    setComments([]); setRootIds([]); setNextOffset(null); setDetailId(null);
    setCommentTotal(0); setRangeTotal(0);
    loadMore.current = () => {};
    if (!selectedId) return;
    const controller = new AbortController(); let running = false; let next: number | null = null;
    async function load(offset: number) {
      if (running || controller.signal.aborted) return;
      running = true; setCommentsLoading(true);
      try {
        const page = await api<{ items: PostComment[]; total: number; range_total: number; root_ids: number[]; next_offset: number | null }>(
          '/posts/' + selectedId + '/comment-threads?limit=50&offset=' + offset + '&' + dateQuery(commentDates) + (offset === 0 && focusId.current ? '&focus_id=' + focusId.current : ''),
          { signal: controller.signal });
        if (!controller.signal.aborted) {
          setComments(previous => offset === 0 ? page.items : [...previous, ...page.items.filter(item => !previous.some(old => old.id === item.id))]);
          setRootIds(previous => offset === 0 ? page.root_ids : [...previous, ...page.root_ids]);
          setCommentTotal(page.total); setRangeTotal(page.range_total);
          next = page.next_offset; setNextOffset(next); setDetailId(selectedId!); setError('');
        }
      } catch (e) { if (!controller.signal.aborted) fail(e); }
      finally { if (!controller.signal.aborted) setCommentsLoading(false); running = false; }
    }
    loadMore.current = () => { if (next !== null) void load(next); };
    void load(0);
    return () => controller.abort();
  }, [selectedId, revision, commentDates]);
  useEffect(() => {
    if (!focusId.current || focusScrolled.current || !comments.some(c => c.id === focusId.current)) return;
    const node = document.querySelector(`[data-message-id="${focusId.current}"]`);
    node?.scrollIntoView({ block: 'center' });
    node?.classList.add('focused-comment');
    // Keep the linked tree available on refresh/reload until the user changes scope.
    focusScrolled.current = true;
  }, [comments]);
  useEffect(() => {
    setMetrics([]); setSync(null); setMetricPostId(null);
    if (!selectedId) return;
    return pollWhileVisible(async signal => {
      try {
        const [snapshots, syncState] = await Promise.all([
          api<Metric[]>('/posts/' + selectedId + '/metrics', { signal }),
          pollable ? api<CommentSync>('/posts/' + selectedId + '/comments/sync', { signal }) : Promise.resolve(null),
        ]);
        if (!signal.aborted) { setMetrics(snapshots); setSync(syncState); setMetricPostId(selectedId!); }
      } catch (e) { if (!signal.aborted) fail(e); }
    }, 3000);
  }, [selectedId, revision]);
  function clearFocus() {
    focusId.current = null; focusScrolled.current = false;
    const params = new URLSearchParams(location.search); params.delete('comment_id');
    history.replaceState(null, '', location.pathname + '?' + params + location.hash);
  }
  function choosePlatform(value: string) { clearFocus(); setPlatform(value); setSelected(null); setPosts([]); setOffset(0); setNotice(''); }
  async function syncComments(fullRescan = false) {
    setSyncing(true); setNotice('');
    try {
      const path = '/posts/' + selectedId + '/comments/sync';
      const result = await api<{ queued: number }>(path + '?' + dateQuery(commentDates) + (fullRescan ? '&full_rescan=true' : ''), { method: 'POST' });
      setNotice(result.queued ? t('已排入留言同步，完成後按重新整理查看最新留言。') : t('目前沒有可排入的工作，或已在同步佇列中。'));
      setRevision(x => x + 1);
    } catch (e) { fail(e); } finally { setSyncing(false); }
  }
  async function stopComments() {
    setSyncing(true);
    try {
      await api('/posts/' + selectedId + '/comments/stop', { method: 'POST' });
      setNotice(t('已停止抓取，已保存的留言與回覆仍保留。')); setRevision(x => x + 1);
    } catch (e) { fail(e); } finally { setSyncing(false); }
  }
  return <section className={'posts-panel batch2-posts' + (selected ? ' post-open' : '')} aria-label={t('貼文數據')}>
    <PageHeader title={t('貼文數據')}>
      {canSync && <MetricSyncButton onNotice={setNotice} onError={fail} onFinished={() => { setNotice(t('貼文與成效同步完成，已重新整理。')); setRevision(x => x + 1); }} />}
      {!canSync && <button className="secondary" onClick={() => setRevision(x => x + 1)}>{t('重新整理 ↻')}</button>}</PageHeader>
    {confirmRescan && <ConfirmDialog message={t('完整重抓全部留言與回覆？')} confirmLabel={t('完整重抓')} onClose={() => setConfirmRescan(false)} onConfirm={() => { setConfirmRescan(false); void syncComments(true); }} />}
    <div className="post-toolbar"><div className="post-platforms tabs" role="tablist" aria-label={t('貼文平台')}>{platforms.map(([value, label], index) =>
      <button key={value} role="tab" id={'post-platform-' + value} aria-controls="posts-platform-panel" aria-selected={platform === value} tabIndex={platform === value ? 0 : -1} onClick={() => choosePlatform(value)} onKeyDown={event => {
        const next = event.key === 'ArrowRight' ? (index + 1) % platforms.length : event.key === 'ArrowLeft' ? (index + platforms.length - 1) % platforms.length : event.key === 'Home' ? 0 : event.key === 'End' ? platforms.length - 1 : null;
        if (next === null) return;
        event.preventDefault(); choosePlatform(platforms[next][0]); document.getElementById('post-platform-' + platforms[next][0])?.focus();
      }}>
        {label}</button>)}</div>
      </div>
    <div id="posts-platform-panel" role="tabpanel" aria-labelledby={'post-platform-' + platform} className="posts-platform-panel">
    {platform && <Followers key={brand + ':' + platform} brand={brand} platform={platform} revision={revision} onLogout={onLogout}>
      <PostDateFilter label={t('發文日期')} value={postDates} onChange={value => { setPostDates(value); setOffset(0); }} />
    </Followers>}
    {error && <div className="error" role="alert">{error}</div>}
    {notice && <p className="sync-notice" role="status">{notice}</p>}
    <div className="posts-layout"><div className="post-list">
      <div className="list-box post-items">{loading ? <p className="empty-small">{t('正在讀取貼文…')}</p> : posts.length === 0 ? <p className="empty-small">{postDates.period !== 'all' && (postDates.period !== 'custom' || postDates.from || postDates.to) ? t('這段期間沒有貼文') : t('目前沒有貼文')}</p> : posts.map(post =>
        <button key={post.id} className={'post-card list-row' + (selectedId === post.id ? ' chosen' : '') + (post.thumbnail_url ? ' has-thumb' : '')} onClick={() => { clearFocus(); setSelected(post); setNotice(''); }}>
          {post.thumbnail_url && <img className="post-thumb" src={post.thumbnail_url} alt="" loading="lazy" onError={e => { e.currentTarget.hidden = true; }} />}<span className="post-card-meta"><span className="ideation-platform">{platforms.find(([value]) => value === accountById.get(post.account_id)?.platform)?.[1]}</span><small>{accountName(post)} · {postKind(post)}</small></span><strong>{post.caption || t('無文字貼文')}</strong><time>{time(post.published_at)}</time>
        </button>)}</div>
      <div className="pagination"><button className="secondary" disabled={!offset} onClick={() => setOffset(x => x - 50)}>{t('← 上一頁')}</button>
        <span>{t('第 {page} 頁', { page: offset / 50 + 1 })}</span><button className="secondary" disabled={posts.length < 50} onClick={() => setOffset(x => x + 50)}>{t('下一頁 →')}</button></div>
    </div><div className="post-detail">{selected ? <>
      <div className="post-conversation"><div className="post-intro section-card"><ReportReturn /><button className="mobile-back secondary" onClick={() => setSelected(null)}>{t('← 返回貼文')}</button>
        <p className="eyebrow">{accountName(selected)} · {postKind(selected)}</p>
        {selected.thumbnail_url && <img className="post-detail-thumb" src={selected.thumbnail_url} alt={t('貼文圖片預覽')} onError={e => { e.currentTarget.hidden = true; }} />}
        <h2 id="post-caption" className={'post-caption' + (longCaption && !captionOpen ? ' collapsed' : '')}>{selected.caption || t('無文字貼文')}</h2>
        {longCaption && <button type="button" className="caption-toggle secondary" aria-expanded={captionOpen} aria-controls="post-caption" onClick={() => setCaptionOpen(!captionOpen)}>{captionOpen ? t('收合 ▴') : t('展開全文 ▾')}</button>}
        <p className="post-timing">{time(selected.published_at)} · {t('{tier}更新 · 台北時間', { tier: tiers[selected.schedule_tier] ?? '' })}</p>
        {selected.permalink?.startsWith('https://') && <a className="post-link" href={selected.permalink} target="_blank" rel="noreferrer">{t('開啟原始貼文 ↗')}</a>}
        </div><section className="post-comments section-card" aria-label={t('留言與回覆')}>
          <div className="comment-heading"><h3>{t('留言與回覆')}</h3><span className="readonly-label">{t('唯讀')}</span></div>
          {retentionNotice(platform, retention) && <p className="comment-retention muted">{retentionNotice(platform, retention)}</p>}
          <p className="comment-sync-summary" role="status">{detailId === selectedId ? syncSummary(commentTotal, metricPostId === selectedId ? latest?.comments : null) : t('正在讀取同步狀況…')}</p>
          <div className="post-date-filter" role="group" aria-label={t('留言日期')}><div className="filter-choice"><span className="filter-label">{t('留言日期')}</span>
            <SegmentedControl compact label={t('留言日期')} options={[{ value: '7', label: t('近 7 天') }, { value: '30', label: t('近 30 天') }, { value: '90', label: t('近 90 天') }, { value: 'all', label: t('全部') }]} value={commentDates.period} onChange={period => { clearFocus(); setCommentDates({ period, from: '', to: '' }); }} />
          </div></div>
          <p className="comment-range-total" role="status">{detailId === selectedId ? t('此範圍 {count} 則', { count: number(rangeTotal) }) : t('正在計算範圍…')}</p>
          {pollable && <section className="comment-sync" aria-label={t('留言同步')}><div><strong>{syncLabel(platform)}</strong>
          <p className={sync && backfillWaitText(sync) ? 'backfill-wait' : undefined} role="status">{sync && backfillWaitText(sync) ? backfillWaitText(sync) :
            sync?.state === 'running' ? t('正在同步留言與回覆…') : sync?.state === 'pending' ? t('已排入同步，請稍候…') :
            sync?.state === 'stopped' ? t('已停止抓取，已保存資料保留。') : sync?.state === 'error' ? t('上次抓取未完成，請檢查平台權限後重新抓取。') : sync?.last_completed_at ? t('最近完成：{time}', { time: time(sync.last_completed_at) }) : t('尚未完成留言同步')}</p>
          <p className="muted">{t('按「抓取留言」只讀取目前留言日期範圍內的留言與回覆，完成後結束。')}</p>
          {sync && <p className="muted">{t('已處理 {pages} 頁 · 已存 {saved} 則 · 待續頁回覆 {pending} 組', { pages: sync.progress?.pages ?? 0, saved: sync.progress?.saved_comments ?? 0, pending: sync.progress?.pending_replies ?? 0 })}</p>}</div>
          {canSync && <button className="primary" disabled={syncing || !sync || sync.manual_requested} onClick={() => void syncComments()}>{t('抓取留言')}</button>}
          {canSync && commentDates.period === 'all' && <button className="secondary" disabled={syncing || !sync || sync.manual_requested} onClick={() => setConfirmRescan(true)}>{t('完整重抓')}</button>}
          {canSync && sync?.manual_requested && <button className="secondary" disabled={syncing} onClick={() => void stopComments()}>{t('停止')}</button>}
        </section>}
          <p className="metric-note">{t('最新主留言優先，每次 50 組並附範圍內回覆；同層回覆由早到晚。父留言不在範圍內時，同一父留言的回覆合為一組。')}</p>
          {detailId !== selectedId ? <p className="empty-small">{commentsLoading ? t('正在讀取留言…') : t('留言尚未載入，請重新整理。')}</p> : rows.length === 0 ? <p className="empty-small">{t('這段期間沒有留言')}</p> :
            <ol className="post-comment-list list-box">{rows.map(({ message, depth, relation, parent }) => <li key={message.id} data-message-id={message.id} data-depth={depth} className={'post-comment ' + (message.author_type === 'brand' ? 'brand-comment' : '')} style={{ marginLeft: Math.min(depth, 3) * 16 }}>
              <div className="comment-meta"><strong>{message.author_type === 'brand' ? t('品牌') : t('觀眾')}</strong><span>{message.contact_name}</span><time>{time(message.sent_at)}</time></div>
              {parent && <p className="comment-relation">{t('↳ 回覆 {name} · 第 {depth} 層', { name: parent.contact_name, depth })}</p>}
              {relation !== 'known' && <p className="comment-relation">{relation === 'missing' ? t('父留言不在此範圍、尚未同步或無法唯一辨識，保留獨立顯示') : t('父留言關係未確認，保留原有紀錄')}</p>}
              <p className="comment-text">{message.text || t('（無文字內容）')}</p>
              {message.attachments_json.map((attachment, index) => <small key={index} className="comment-relation">{attachment.fileName || t('附件／貼圖')}</small>)}
              {message.edited_at && <small className="comment-relation">{t('已編輯 · {time}', { time: time(message.edited_at) })}</small>}
            </li>)}</ol>}
          {detailId === selectedId && <div className="comment-pagination">
            <span>{t('已顯示 {count} 則留言與回覆', { count: number(comments.length) })}</span>
            {nextOffset !== null && <button className="secondary" disabled={commentsLoading} onClick={() => loadMore.current()}>{commentsLoading ? t('正在載入…') : t('顯示更多')}</button>}
          </div>}
        </section>
      </div>
      <aside className="post-metrics section-card" aria-label={t('貼文成效')}>
        <h3>{t('貼文成效')}</h3>
        <div className="metric-grid">{metricFields(platform).map(([key, label]) => <div key={key}><span>{label}{platform === 'youtube' && ['shares', 'avg_watch_time', 'watch_hours', 'subscribers_gained'].includes(key) && <small className="metric-delay">{t('約晚 1～2 天')}</small>}</span><strong>{number(metricPostId === selectedId ? metricValue(latest, key) : null)}</strong></div>)}</div>
        <p className="metric-note">{latest ? t('最近抓取：{time}', { time: time(latest.captured_at) }) : t('尚未取得數據快照')}<br />{t('「—」表示平台尚未提供或此貼文不支援；0 表示平台回傳零。')}</p>
        <MetricChart key={platform} metrics={metrics} platform={platform} />
        <h3>{t('數據快照')} <span>{metrics.length}</span></h3><div className="snapshot-table list-box"><table><thead><tr><th>{t('抓取時間')}</th>{snapshotColumns(platform).map(([key, label]) => <th key={key}>{label}</th>)}</tr></thead>
          <tbody>{[...metrics].reverse().map(metric => <tr key={metric.id}><td className="snapshot-time">{time(metric.captured_at)}</td>{snapshotColumns(platform).map(([key]) => <td key={key}>{number(metricValue(metric, key))}</td>)}</tr>)}</tbody></table></div>
        {metrics.length === 100 && <p className="metric-note">{t('顯示最近 100 筆快照。')}</p>}
      </aside>
    </> : <div className="list-empty">{t('選取一篇貼文，查看留言、回覆與數據。')}</div>}</div></div></div>
  </section>;
}

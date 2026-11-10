import { useRef, useState } from 'react';
import { t, tx } from '../i18n.ts';
import { toPlatformText } from '../markdownText';
import { foldCaption, hashtags, platformLabels, previewRatio } from '../publishComposer';
import type { Format, Platform, PlatformOptions, ComposerMedia } from '../publishComposer';

type PreviewMedia = ComposerMedia & { id: number; name: string };
function Highlighted({ text }: { text: string }) {
  const parts = text.split(/((?<![\p{L}\p{N}_])#[\p{L}\p{N}\p{M}_]+|(?<![\p{L}\p{N}_@])@[\p{L}\p{N}_.]+)/gu);
  return <>{parts.map((part, i) => /^[#@]/.test(part) ? <span className="publish-preview-highlight" key={i}>{part}</span> : part)}</>;
}
// 依各平台實際呈現：IG 在文案前加帳號名稱；超過平台折疊長度時顯示「更多」。
function Caption({ text, platform, author }: { text: string; platform: Platform; author?: string }) {
  const [expanded, setExpanded] = useState(false);
  const folded = foldCaption(text, platform, expanded);
  if (!folded.text) return null;
  return <p className="publish-preview-caption">{author && <strong className="publish-preview-author">{author} </strong>}<Highlighted text={folded.text} />{folded.folded && <> <button className="publish-preview-more" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? t('收合') : t('更多')}</button></>}</p>;
}
const ICONS: Record<string, string> = {
  heart: 'M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z',
  comment: 'M20 12a8 8 0 1 1-3.3-6.5A8 8 0 0 1 20 12zM20 12l1 7-5-2',
  share: 'M21 3 3 10l7 3 3 7 8-17zM10 13l11-10',
  repost: 'M7 7h10l-3-3M17 17H7l3 3M17 7v6M7 17v-6',
  bookmark: 'M6 3h12v18l-6-4-6 4z',
  like: 'M7 11v9H4v-9zM7 11l4-8a2 2 0 0 1 2 2v4h6a2 2 0 0 1 2 2l-2 7a2 2 0 0 1-2 2H7',
};
// 帳號列用平台圖示取代平台名稱（線條風格與互動列一致，不是官方商標圖）。
const PLATFORM_ICONS: Record<Platform, string> = {
  facebook: 'M14 8h3V4h-3a4 4 0 0 0-4 4v3H7v4h3v6h4v-6h3l1-4h-4V8z',
  instagram: 'M7 3h10a4 4 0 0 1 4 4v10a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4V7a4 4 0 0 1 4-4zM12 8a4 4 0 1 1 0 8 4 4 0 0 1 0-8zM17.5 6.5h.01',
  threads: 'M16 12c0-2.8-1.8-4.5-4-4.5S8 9.2 8 12s1.8 4.5 4 4.5 4-1.7 4-4.5zM16 12v2a2.5 2.5 0 0 0 5 0v-2a9 9 0 1 0-4 7.5',
  youtube: 'M3 8a3 3 0 0 1 3-3h12a3 3 0 0 1 3 3v8a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3zM10 9l5 3-5 3z',
  tiktok: 'M14 3v12a4 4 0 1 1-4-4M14 3a5 5 0 0 0 5 5',
  x: 'M4 4l16 16M20 4L4 20',
};
function PlatformMark({ platform }: { platform: Platform }) {
  return <svg className="publish-preview-icon publish-preview-platform" viewBox="0 0 24 24" role="img" aria-label={platformLabels[platform]}><title>{platformLabels[platform]}</title><path d={PLATFORM_ICONS[platform]} /></svg>;
}
function Icon({ name }: { name: string }) {
  return <svg className="publish-preview-icon" viewBox="0 0 24 24" aria-hidden="true"><path d={ICONS[name]} /></svg>;
}
// 互動列只畫外觀，不顯示數字。
function Actions({ platform }: { platform: Platform }) {
  if (platform === 'youtube') return <div className="publish-preview-actions is-youtube" aria-hidden="true">{[['like', t('讚')], ['share', tx('preview', '分享')], ['bookmark', t('儲存')]].map(([icon, label]) => <span key={icon}><Icon name={icon} />{label}</span>)}</div>;
  if (platform === 'facebook') return <div className="publish-preview-actions is-facebook" aria-hidden="true">{[['like', t('讚')], ['comment', tx('preview', '留言')], ['share', tx('preview', '分享')]].map(([icon, label]) => <span key={icon}><Icon name={icon} />{label}</span>)}</div>;
  const icons = platform === 'instagram' ? ['heart', 'comment', 'share'] : ['heart', 'comment', 'repost', 'share'];
  return <div className="publish-preview-actions" aria-hidden="true">{icons.map(icon => <Icon key={icon} name={icon} />)}{platform === 'instagram' && <span className="publish-preview-actions-end"><Icon name="bookmark" /></span>}</div>;
}
export function PublishPreview({ platform, name, brandName, caption, format, media, postId, options, unpublished, title = '', thumbnail, cover, facebookCover, onRemoveMedia, onMoveMedia, mediaLocked = false }: { platform: Platform | null; name: string; brandName: string; caption: string; format: Format; media: PreviewMedia[]; postId?: number; options: PlatformOptions; unpublished: boolean; title?: string; thumbnail?: string; cover?: string; facebookCover?: string; onRemoveMedia?: (id: number) => void; onMoveMedia?: (id: number, index: number) => void; mediaLocked?: boolean }) {
  const [storyIndex, setStoryIndex] = useState(0), [slide, setSlide] = useState(0), [allMedia, setAllMedia] = useState(false);
  const dragged = useRef<number | null>(null);
  const position = Math.min(storyIndex, Math.max(0, media.length - 1));
  // 多個素材依平台排版：FB 拼貼（最多 5 格，其餘顯示 +N）、IG 一次一張左右切換、Threads 橫向捲動。
  const many = format !== 'story' && media.length > 1, expanded = allMedia && media.length > 5;
  const layout = !many ? '' : platform === 'facebook' ? 'is-facebook-grid' : platform === 'instagram' ? 'is-slides' : 'is-row';
  const current = Math.min(slide, Math.max(0, media.length - 1));
  const shownMedia = format === 'story' ? media.slice(position, position + 1) : layout === 'is-slides' ? media.slice(current, current + 1) : layout === 'is-facebook-grid' && !expanded ? media.slice(0, 5) : media;
  const hidden = layout === 'is-facebook-grid' && !expanded ? media.length - shownMedia.length : 0;
  // 預覽顯示實際送出的文字：Markdown 已轉成平台顯示得出來的格式。
  const segments = (platform === 'threads' ? options.threads.segments.length ? options.threads.segments : [''] : [caption]).map(toPlatformText);
  return <aside className={'publish-preview' + (format === 'story' ? ' publish-story-preview' : '')} aria-label={format === 'story' ? t('限時動態預覽') : t('貼文預覽')}>
    {platform ? <div className={'publish-preview-thread is-' + platform + ''}>{segments.map((text, i) => {
      const author = name || brandName;
      const identity = <div className="publish-preview-identity"><span className="publish-preview-avatar" aria-hidden="true">{Array.from(author || '').find(c => /[\p{L}\p{N}]/u.test(c)) || t('品')}</span><strong>{author}</strong>{i ? <span>{t('作者')}</span> : <><PlatformMark platform={platform} />{platform === 'facebook' && <span>{unpublished ? t('草稿') : t('剛剛 · 公開')}</span>}</>}{i === 0 && platform === 'instagram' && format === 'text' && <span className="publish-preview-alert" role="note">{t('Instagram 不支援純文字，請新增媒體。')}</span>}</div>;
      // YouTube 的縮圖是影片播放前的封面（Shorts 也一樣，處理完成後套用）。
      const tile = (m: PreviewMedia, index: number) => {
        const ratio = previewRatio(platform, format, layout === 'is-slides' ? media[0] : m, options, unpublished);
        // FB 拼貼的格子比例由 CSS 決定；其他排版沿用平台實際比例。
        const style = layout === 'is-facebook-grid' ? undefined : layout === 'is-row' ? { aspectRatio: ratio } : { aspectRatio: ratio, width: 'min(100%, calc(var(--publish-preview-media-height) * ' + ratio + '))' };
        const movable = !!onMoveMedia && !mediaLocked && many;
        return <div key={m.id} style={style} draggable={movable} onDragStart={e => { dragged.current = m.id; e.dataTransfer.setData('text/plain', String(m.id)); }} onDragOver={e => { if (movable) e.preventDefault(); }} onDrop={e => { e.preventDefault(); const id = dragged.current; dragged.current = null; if (movable && id != null && id !== m.id) onMoveMedia(id, media.findIndex(x => x.id === m.id)); }}>
          {m.mime.startsWith('image/') ? <img alt={m.name} src={'/api/publish/posts/' + postId + '/media/' + m.id} /> : <video controls preload="metadata" aria-label={m.name} poster={platform === 'youtube' && thumbnail ? thumbnail : platform === 'instagram' && format === 'video' && cover ? cover : platform === 'facebook' && format === 'video' && facebookCover ? facebookCover : undefined} src={'/api/publish/posts/' + postId + '/media/' + m.id} />}
          {hidden > 0 && index === shownMedia.length - 1 && <button type="button" className="publish-preview-more-media" aria-label={t('顯示全部 {count} 個素材', { count: media.length })} onClick={() => setAllMedia(true)}>+{hidden}</button>}
          {onRemoveMedia && <button type="button" className="publish-preview-remove" aria-label={t('移除 {name}', { name: m.name })} title={t('移除 {name}', { name: m.name })} disabled={mediaLocked} onClick={() => onRemoveMedia(m.id)}><span aria-hidden="true">×</span></button>}
        </div>;
      };
      const mediaBlock = i === 0 && format !== 'text' && media.length > 0 && <>
        <div className={'publish-preview-media ' + layout} data-count={layout === 'is-facebook-grid' ? (expanded ? 'all' : String(Math.min(media.length, 5))) : undefined}>{shownMedia.map(tile)}</div>
        {layout === 'is-slides' && <div className="publish-preview-slides"><button className="secondary small" aria-label={t('上一張')} disabled={current === 0} onClick={() => setSlide(current - 1)}>‹</button><span className="publish-preview-dots" aria-label={(current + 1) + '／' + media.length}>{media.map((m, n) => <span key={m.id} className={n === current ? 'is-current' : undefined} />)}</span><button className="secondary small" aria-label={t('下一張')} disabled={current === media.length - 1} onClick={() => setSlide(current + 1)}>›</button></div>}
        {layout === 'is-facebook-grid' && expanded && <button className="publish-preview-more" onClick={() => setAllMedia(false)}>{t('收合')}</button>}
      </>;
      // FB／IG 發文後依序留的評論，照平台排版：FB 灰色泡泡（可附圖），IG 在文案下方「帳號 內容」一行。
      const comments = i !== 0 || format === 'story' ? [] : platform === 'facebook' ? options.facebook.comments.map((text, n) => ({ text: toPlatformText(text), image: options.facebook.comment_media?.[n] ?? null })) : platform === 'instagram' ? (options.instagram.comments ?? []).map(text => ({ text: toPlatformText(text), image: null })) : [];
      const shownComments = comments.filter(c => c.text.trim() || c.image);
      const commentList = shownComments.length > 0 && <ul className="publish-preview-comments" aria-label={t('評論')}>{shownComments.map((c, n) => <li key={n} className="publish-preview-comment">
        <span className="publish-preview-avatar" aria-hidden="true">{Array.from(author || '').find(ch => /[\p{L}\p{N}]/u.test(ch)) || t('品')}</span>
        <div>{platform === 'facebook' ? c.text.trim() && <div className="publish-preview-bubble"><strong>{author}</strong><span><Highlighted text={c.text} /></span></div> : <p><strong>{author}</strong> <Highlighted text={c.text} /></p>}
          {c.image && <img alt="" src={'/api/publish/posts/' + postId + '/media/' + c.image} />}
          <span className="publish-preview-comment-meta" aria-hidden="true"><span>{t('剛剛')}</span>{platform === 'facebook' && <span>{t('讚')}</span>}<span>{t('回覆')}</span></span></div>
      </li>)}</ul>;
      const topic = platform === 'threads' && i === 0 && hashtags(segments.join('\n'))[0] && <span className="publish-preview-topic">{t('主題標籤：')}{hashtags(segments.join('\n'))[0].slice(1)}</span>;
      if (format === 'story') return <article key={i} className="publish-preview-post">{identity}{mediaBlock}{media.length > 0 && <div className="publish-story-navigation"><button className="secondary small" aria-label={t('上一則')} disabled={position === 0} onClick={() => setStoryIndex(position - 1)}>{t('上一則')}</button><span>{position + 1}／{media.length}</span><button className="secondary small" aria-label={t('下一則')} disabled={position === media.length - 1} onClick={() => setStoryIndex(position + 1)}>{t('下一則')}</button></div>}</article>;
      // YouTube：影片 → 標題（粗體）→ 頻道名稱 → 互動列 → 說明。
      if (platform === 'youtube') return <article key={i} className="publish-preview-post">{mediaBlock}<h3 className="publish-preview-title">{title || t('（尚無標題）')}</h3><div className="publish-preview-identity"><span className="publish-preview-avatar" aria-hidden="true">{Array.from(author || '').find(c => /[\p{L}\p{N}]/u.test(c)) || t('品')}</span><strong>{author}</strong><PlatformMark platform={platform} /></div><Actions platform={platform} /><Caption key={platform + ':' + i} platform={platform} text={text} /></article>;
      // 各平台實際排版：IG 素材在上、文案在下；FB 與 Threads 文案在上、素材在下。
      if (platform === 'instagram') return <article key={i} className="publish-preview-post">{identity}{mediaBlock}<Actions platform={platform} /><Caption key={platform + ':' + i} platform={platform} text={text} author={author} />{commentList}</article>;
      // Threads 串文照貼文頁：主貼文內文與帳號列同寬；回覆內文縮排在頭像右邊，帳號旁標「作者」，每則都有互動列。
      return <article key={i} className={'publish-preview-post' + (i ? ' is-reply' : '')}>{identity}{topic}<Caption key={platform + ':' + i} platform={platform} text={text} />{mediaBlock}<Actions platform={platform} />{commentList}</article>;
    })}</div> : <p className="publish-preview-empty">{t('尚未開啟平台')}</p>}
  </aside>;
}

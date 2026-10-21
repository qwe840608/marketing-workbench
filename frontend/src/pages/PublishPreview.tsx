import { useState } from 'react';
import { t, tx } from '../i18n.ts';
import { foldCaption, hashtags, isShort, platformLabels, previewRatio } from '../publishComposer';
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
  if (!text) return null;
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
export function PublishPreview({ platform, enabled, shared, onPlatform, name, brandName, caption, format, media, postId, options, unpublished, title = '', thumbnail, cover, facebookCover }: { platform: Platform | null; enabled: Platform[]; shared: boolean; onPlatform: (p: Platform) => void; name: string; brandName: string; caption: string; format: Format; media: PreviewMedia[]; postId?: number; options: PlatformOptions; unpublished: boolean; title?: string; thumbnail?: string; cover?: string; facebookCover?: string }) {
  const [storyIndex, setStoryIndex] = useState(0);
  const position = Math.min(storyIndex, Math.max(0, media.length - 1));
  const shownMedia = format === 'story' ? media.slice(position, position + 1) : media;
  const segments = platform === 'threads' ? options.threads.segments.length ? options.threads.segments : [''] : [caption];
  return <aside className={'publish-preview' + (format === 'story' ? ' publish-story-preview' : '')} aria-label={format === 'story' ? t('限時動態預覽') : t('貼文預覽')}>
    {shared && enabled.length > 0 && <div className="publish-preview-tabs" role="group" aria-label={t('預覽平台')}>{enabled.map(p => <button key={p} className="secondary small" aria-pressed={platform === p} onClick={() => onPlatform(p)}>{platformLabels[p]}</button>)}</div>}
    {platform ? <div className={'publish-preview-thread is-' + platform + (platform === 'threads' && segments.length > 1 ? ' is-thread' : '')}>{segments.map((text, i) => {
      const author = name || brandName;
      const identity = <div className="publish-preview-identity"><span className="publish-preview-avatar" aria-hidden="true">{Array.from(author || '').find(c => /[\p{L}\p{N}]/u.test(c)) || t('品')}</span><strong>{author}</strong><span>{i ? t('回覆') : platform === 'facebook' ? (unpublished ? t('草稿') : t('剛剛 · 公開')) : platformLabels[platform]}</span></div>;
      // YouTube 的縮圖是影片播放前的封面（Shorts 不套用自訂縮圖）。
      const mediaBlock = i === 0 && format !== 'text' && media.length > 0 && <div className="publish-preview-media">{shownMedia.map(m => <div key={m.id} style={{ aspectRatio: previewRatio(platform, format, m, options, unpublished), width: 'min(100%, calc(var(--publish-preview-media-height) * ' + previewRatio(platform, format, m, options, unpublished) + '))' }}>{m.mime.startsWith('image/') ? <img alt={m.name} src={'/api/publish/posts/' + postId + '/media/' + m.id} /> : <video controls preload="metadata" aria-label={m.name} poster={platform === 'youtube' && thumbnail && !isShort(m) ? thumbnail : platform === 'instagram' && format === 'video' && cover ? cover : platform === 'facebook' && format === 'video' && facebookCover ? facebookCover : undefined} src={'/api/publish/posts/' + postId + '/media/' + m.id} />}</div>)}</div>;
      const topic = platform === 'threads' && i === 0 && hashtags(segments.join('\n'))[0] && <span className="publish-preview-topic">{t('主題標籤：')}{hashtags(segments.join('\n'))[0].slice(1)}</span>;
      if (format === 'story') return <article key={i} className="publish-preview-post">{identity}{mediaBlock}{media.length > 0 && <div className="publish-story-navigation"><button className="secondary small" aria-label={t('上一則')} disabled={position === 0} onClick={() => setStoryIndex(position - 1)}>{t('上一則')}</button><span>{position + 1}／{media.length}</span><button className="secondary small" aria-label={t('下一則')} disabled={position === media.length - 1} onClick={() => setStoryIndex(position + 1)}>{t('下一則')}</button></div>}</article>;
      // YouTube：影片 → 標題（粗體）→ 頻道名稱 → 互動列 → 說明。
      if (platform === 'youtube') return <article key={i} className="publish-preview-post">{mediaBlock}<h3 className="publish-preview-title">{title || t('（尚無標題）')}</h3><div className="publish-preview-identity"><span className="publish-preview-avatar" aria-hidden="true">{Array.from(author || '').find(c => /[\p{L}\p{N}]/u.test(c)) || t('品')}</span><strong>{author}</strong></div><Actions platform={platform} /><Caption key={platform + ':' + i} platform={platform} text={text} /></article>;
      // 各平台實際排版：IG 素材在上、文案在下；FB 與 Threads 文案在上、素材在下。
      if (platform === 'instagram') return <article key={i} className="publish-preview-post">{identity}{mediaBlock}<Actions platform={platform} /><Caption key={platform + ':' + i} platform={platform} text={text} author={author} /></article>;
      return <article key={i} className="publish-preview-post">{identity}{topic}<Caption key={platform + ':' + i} platform={platform} text={text} />{mediaBlock}<Actions platform={platform} /></article>;
    })}</div> : <p className="publish-preview-empty">{t('尚未開啟平台')}</p>}
  </aside>;
}

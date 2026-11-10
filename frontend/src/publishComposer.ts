import vectors from '../../shared/publish_threads_vectors.json' with { type: 'json' };
import { t } from './i18n.ts';
import { toPlatformText } from './markdownText.ts';

export type Platform = 'facebook' | 'instagram' | 'threads' | 'youtube' | 'tiktok' | 'x';
export type Format = 'video' | 'image' | 'carousel' | 'text' | 'story';
export type YoutubePrivacy = 'public' | 'unlisted' | 'private';
// title 空白＝沿用說明第一行；縮圖由伺服端維護，不在表單內。
export type YoutubeOptions = { title: string; privacy: YoutubePrivacy; made_for_kids: boolean };
export type PlatformOptions = { facebook: { video_format: 'feed' | 'reels'; comments: string[]; comment_media: (number | null)[] }; instagram: { share_to_feed: boolean; comments: string[] }; threads: { segments: string[]; segments_custom: boolean }; youtube: YoutubeOptions; tiktok: Record<string, never>; x: Record<string, never> };
export type Rule = { caption: number; comments?: number; carousel?: number; video_seconds: number; hashtag?: number; mentions?: number; reels_seconds_min?: number; reels_seconds_max?: number; reels_ratio?: number[]; story_seconds_min?: number; story_seconds_max?: number; story_count?: number; title?: number; hashtag_effective?: number; long_video_seconds?: number; shorts_seconds?: number; thumbnail_bytes?: number; thumbnail_min_width?: number; thumbnail_mimes?: string[]; cover_bytes?: number; cover_mimes?: string[]; side_min?: number; side_max?: number; image_bytes?: number; video_seconds_min?: number; standard_video_seconds?: number; video_ratio?: number[]; video_side_max?: number[]; post_cost_usd?: number; url_post_cost_usd?: number; video_bytes?: number; video_bytes_min?: number; video_mimes?: string[] };
export type Rules = Record<Platform, Rule>;
export type ComposerMedia = { mime: string; width: number; height: number; duration: number | null; size?: number };
export const platformLabels: Record<Platform, string> = { facebook: 'Facebook', instagram: 'Instagram', threads: 'Threads', youtube: 'YouTube', tiktok: 'TikTok', x: 'X' };
export const defaultPlatformOptions = (): PlatformOptions => ({ facebook: { video_format: 'reels', comments: [], comment_media: [] }, instagram: { share_to_feed: true, comments: [] }, threads: { segments: [], segments_custom: false }, youtube: { title: '', privacy: 'public', made_for_kids: false }, tiktok: {}, x: {} });
export function loadedPlatformOptions(value?: Omit<PlatformOptions, 'facebook' | 'instagram' | 'youtube' | 'tiktok' | 'x'> & { tiktok?: Record<string, never>; x?: Record<string, never> } & { facebook?: Partial<PlatformOptions['facebook']> & { cover_media_id?: number | null } } & { instagram?: Partial<PlatformOptions['instagram']> & { cover_media_id?: number | null } } & { youtube?: Partial<YoutubeOptions> & { thumbnail_media_id?: number | null } }): PlatformOptions {
  const defaults = defaultPlatformOptions();
  // 伺服端回傳的 thumbnail_media_id／cover_media_id 不進表單：縮圖與封面只由上傳與移除動作改變。
  const youtube = { title: value?.youtube?.title ?? defaults.youtube.title, privacy: value?.youtube?.privacy ?? defaults.youtube.privacy, made_for_kids: value?.youtube?.made_for_kids ?? defaults.youtube.made_for_kids };
  // comment_media 與 comments 同序（每則評論的附圖編號），長度補齊成一樣。
  const comments = value?.facebook?.comments ?? [], images = value?.facebook?.comment_media ?? [];
  return { facebook: { video_format: value?.facebook?.video_format ?? 'feed', comments, comment_media: comments.map((_, i) => images[i] ?? null) }, instagram: { share_to_feed: value?.instagram?.share_to_feed ?? defaults.instagram.share_to_feed, comments: value?.instagram?.comments ?? [] }, threads: { ...defaults.threads, ...value?.threads }, youtube, tiktok: {}, x: {} };
}
// 平台專用文案只有在有內容時才取代共用文案；空白的覆寫（例如 Agent 存成 ""）沿用共用文案，與後端 publish_rules.platform_caption 一致。
export const platformCaption = (captions: Partial<Record<Platform, string>>, caption: string, platform: Platform) => captions[platform]?.trim() ? captions[platform]! : caption;
// 實際送出的文案：Markdown 轉成平台顯示得出來的純文字（與後端 publish_rules.platform_caption 一致）。
export const sentCaption = (captions: Partial<Record<Platform, string>>, caption: string, platform: Platform) => toPlatformText(platformCaption(captions, caption, platform));
const emoji = new RegExp(vectors.emoji_pattern, 'u');
const encoder = new TextEncoder();
// 使用後端 Unicode 資料，避免瀏覽器 Unicode 版本影響 emoji 與組合字邊界。
export function textUnits(text: string): { text: string; size: number }[] {
  const chars = Array.from(text), units = [];
  for (let i = 0; i < chars.length;) {
    const start = i++, first = chars[start].codePointAt(0)!;
    if (first >= 0x1f1e6 && first <= 0x1f1ff && i < chars.length) {
      const next = chars[i].codePointAt(0)!;
      if (next >= 0x1f1e6 && next <= 0x1f1ff) i++;
    }
    while (i < chars.length) {
      const code = chars[i].codePointAt(0)!;
      if (vectors.combining_ranges.some(([a, b]) => code >= a && code <= b) || [0xfe0e, 0xfe0f, 0x20e3].includes(code) || (code >= 0x1f3fb && code <= 0x1f3ff) || (code >= 0xe0020 && code <= 0xe007f)) i++;
      else if (code === 0x200d && i + 1 < chars.length) i += 2;
      else break;
    }
    const unit = chars.slice(start, i).join('');
    units.push({ text: unit, size: emoji.test(unit) ? encoder.encode(unit).length : Array.from(unit).length });
  }
  return units;
}
// X 加權計字（官方 twitter-text 的簡化版，與後端 publish_rules.x_units 相同）：中日韓字與 emoji 算 2、http(s) 網址一律 23。
const X_LIGHT = [[0x0000, 0x10ff], [0x2000, 0x200d], [0x2010, 0x201f], [0x2032, 0x2037]];
const X_URL = /https?:\/\/\S+/gi;
export const X_URL_WEIGHT = 23;
// 與後端 publish_rules.X_CAPTION_LABEL 同字。
export const X_CAPTION_LABEL = t('文案（加權計字，中文字與 emoji 算 2、網址算 23）');
const xCharWeight = (unit: string) => emoji.test(unit) && (Array.from(unit).length > 1 || unit.codePointAt(0)! > 0xff) ? 2 : Array.from(unit).reduce((n, char) => n + (X_LIGHT.some(([a, b]) => char.codePointAt(0)! >= a && char.codePointAt(0)! <= b) ? 1 : 2), 0);
export function xUnits(raw: string): { text: string; size: number }[] {
  const text = raw.normalize('NFC'), units: { text: string; size: number }[] = [];
  let last = 0;
  for (const match of text.matchAll(X_URL)) {
    units.push(...textUnits(text.slice(last, match.index)).map(u => ({ text: u.text, size: xCharWeight(u.text) })), { text: match[0], size: X_URL_WEIGHT });
    last = match.index! + match[0].length;
  }
  units.push(...textUnits(text.slice(last)).map(u => ({ text: u.text, size: xCharWeight(u.text) })));
  return units;
}
export const xHasUrl = (text: string) => /https?:\/\/\S+/i.test(text);
const weightedUnits = (text: string, platform: Platform) => platform === 'threads' ? textUnits(text) : platform === 'x' ? xUnits(text) : Array.from(text).map(char => ({ text: char, size: 1 }));
export const textLength = (text: string, platform: Platform = 'threads') => platform === 'threads' || platform === 'x' ? weightedUnits(text, platform).reduce((n, u) => n + u.size, 0) : Array.from(text).length;
// YouTube 說明以 UTF-8 位元組計（上限 5000）；標題以字元計（上限 100）。
export const textBytes = (text: string) => encoder.encode(text).length;
// 標題空白時沿用說明的第一個非空行，與後端 youtube_title 一致。
export function youtubeTitle(title: string, caption: string) {
  if (title.trim()) return title.trim();
  return caption.split(/\r\n|[\n\r\v\f\x1c-\x1e\u0085\u2028\u2029]/).map(line => line.trim()).find(line => line) ?? '';
}
// 直式或正方形且 3 分鐘內會被 YouTube 歸為 Shorts（API 無法指定）。
export const isShort = (item: ComposerMedia, limit = 180) => item.mime.startsWith('video/') && item.width > 0 && item.height >= item.width && !!item.duration && item.duration > 0 && item.duration <= limit;
// 超過字數上限時回傳從第幾個字開始超出與該處片段（字數依平台計法，位置以畫面上的字計），與後端 publish_rules.overflow 一致。
export function overflowAt(text: string, limit: number, platform: Platform = 'threads'): { position: number; snippet: string } | null {
  const units = weightedUnits(text, platform);
  let used = 0;
  for (const [i, unit] of units.entries()) {
    used += unit.size;
    if (used > limit) return { position: i + 1, snippet: units.slice(i, i + 10).map(u => u.text).join('') };
  }
  return null;
}
// 超出的字由輸入框直接標紅，提示只說超過上限（與後端 over_limit_reason 相同文字）。
export function overLimitReason(label: string, text: string, limit: number, platform: Platform = 'threads'): string | null {
  const found = overflowAt(text, limit, platform);
  return found ? t('{label}超過 {limit} 字上限', { label, limit: limit.toLocaleString('en-US') }) : null;
}
// 原稿（含 Markdown）從第幾個 UTF-16 位置開始超出：找最長且不超限的前綴（換算平台文字後計數），供輸入框標紅。
export function overflowStart(raw: string, isOver: (text: string) => boolean): number | null {
  if (!isOver(raw)) return null;
  const chars = Array.from(raw);
  let low = 0, high = chars.length;
  while (low < high) {
    const mid = (low + high + 1) >> 1;
    if (isOver(chars.slice(0, mid).join(''))) high = mid - 1; else low = mid;
  }
  return chars.slice(0, low).join('').length;
}
// hashtag 遇到空白或標點即結束（與後端 publish_rules.HASHTAGS 相同），避免「#主題，後文」整串被當成標籤。
export const HASHTAG_PATTERN = /(?<![\p{L}\p{N}_])#[\p{L}\p{N}\p{M}_]+/gu;
export const hashtags = (text: string) => Array.from(text.matchAll(HASHTAG_PATTERN), m => m[0]);
export const mentions = (text: string) => Array.from(text.matchAll(/(?<![\p{L}\p{N}_@])@[\p{L}\p{N}_.]+/gu), m => m[0]);
// YouTube：只支援影片；標題、說明與選填縮圖的規則與後端 check_youtube 相同。
function checkYoutube(format: Format, caption: string, media: ComposerMedia[], options: PlatformOptions, rule: Rule, thumbnail?: ComposerMedia | null) {
  const errors: string[] = [], warnings: string[] = [];
  if (format !== 'video') return { errors: [t('YouTube 只支援影片')], warnings };
  if (media.length !== 1) errors.push(t('此格式需 1 個媒體檔'));
  for (const item of media) {
    if (!item.mime.startsWith('video/')) { errors.push(t('媒體型別與格式不符')); continue; }
    if (item.size && item.size > 1024 ** 3) errors.push(t('影片最多 1 GB'));
    if (!item.duration || item.duration <= 0) errors.push(t('無法讀取影片長度'));
    else if (item.duration > rule.video_seconds) errors.push(t('影片最長 12 小時'));
    else if (item.duration > rule.long_video_seconds!) warnings.push(t('超過 15 分鐘的影片需頻道已通過電話驗證'));
  }
  const title = youtubeTitle(options.youtube.title, caption), titleLimit = rule.title ?? 100, bytes = textBytes(caption);
  if (!title) errors.push(t('標題必填'));
  else if (Array.from(title).length > titleLimit) errors.push(t('標題最多 {limit} 字（目前 {count}）', { limit: titleLimit, count: Array.from(title).length }));
  if (bytes > rule.caption) errors.push(t('說明最多 {limit} 位元組（目前 {count}）', { limit: rule.caption.toLocaleString('en-US'), count: bytes.toLocaleString('en-US') }));
  if (hashtags(caption).length > rule.hashtag_effective!) warnings.push(t('說明超過 15 個 hashtag 時，YouTube 會忽略全部 hashtag'));
  const short = media.length === 1 && isShort(media[0], rule.shorts_seconds);
  if (short) warnings.push(t('將被歸為 Shorts（直式或正方形且 3 分鐘內，無法指定）'));
  if (thumbnail) {
    if (short) warnings.push(t('Shorts 的自訂縮圖要等 YouTube 處理完影片才會套用'));
    if (!(rule.thumbnail_mimes ?? []).includes(thumbnail.mime)) errors.push(t('縮圖只支援 JPG／PNG'));
    if (thumbnail.size && rule.thumbnail_bytes && thumbnail.size > rule.thumbnail_bytes) errors.push(t('縮圖最多 {size} MB', { size: Math.floor(rule.thumbnail_bytes / 1024 ** 2) }));
    if (!short) {
      if (!thumbnail.height || Math.abs(thumbnail.width / thumbnail.height - 16 / 9) > 0.02) warnings.push(t('縮圖建議 16:9（1280×720 以上）'));
      else if (thumbnail.width < rule.thumbnail_min_width!) warnings.push(t('縮圖寬度建議至少 {width} px', { width: rule.thumbnail_min_width! }));
    }
  }
  return { errors: [...new Set(errors)], warnings };
}
// TikTok：只把一支影片送到收件匣；規則與後端 check_tiktok 相同。文案不會送出，只供複製到 App。
export const TIKTOK_INBOX_NOTICE = t('影片會送到 TikTok 收件匣，需要在 App 內補上文案並按發佈');
export const TIKTOK_IMAGE_REASON = t('僅支援影片發布，圖文需從APP上傳');
function checkTiktok(format: Format, caption: string, media: ComposerMedia[], rule: Rule) {
  const errors: string[] = [], warnings: string[] = [TIKTOK_INBOX_NOTICE];
  if (format !== 'video') return { errors: [TIKTOK_IMAGE_REASON], warnings };
  if (media.length !== 1) errors.push(t('此格式需 1 個媒體檔'));
  for (const item of media) {
    if (!item.mime.startsWith('video/')) { errors.push(TIKTOK_IMAGE_REASON); continue; }
    if (item.size && item.size > 1024 ** 3) errors.push(t('影片最多 1 GB'));
    if (!item.duration || item.duration <= 0) errors.push(t('無法讀取影片長度'));
    else if (item.duration > rule.video_seconds) errors.push(t('影片最長 10 分鐘'));
    else if (item.duration > 180) warnings.push(t('超過 3 分鐘：若帳號上限較短，需在 App 內裁剪'));
    const min = rule.side_min ?? 360, max = rule.side_max ?? 4096;
    if (![item.width, item.height].every(side => side >= min && side <= max)) errors.push(t('影片長寬需 {min}–{max} px', { min, max }));
  }
  if (Array.from(caption).length > rule.caption) warnings.push(t('文案超過 {limit} 字，貼到 App 時可能被截斷', { limit: rule.caption }));
  return { errors: [...new Set(errors)], warnings };
}
// X：純文字、1–4 張圖或 1 支影片；規則與後端 check_x 相同。發文按次扣預付點數，含網址的貼文較貴。
function checkX(format: Format, caption: string, media: ComposerMedia[], rule: Rule) {
  const errors: string[] = [], warnings: string[] = [];
  if (format === 'story') return { errors: [t('不支援這個格式')], warnings };
  const over = overLimitReason(X_CAPTION_LABEL, caption, rule.caption, 'x');
  if (over) errors.push(over);
  if (format === 'text' && (media.length || !caption.trim())) errors.push(t('純文字須有文案且不能包含媒體'));
  if (['image', 'video'].includes(format) && media.length !== 1) errors.push(t('此格式需 1 個媒體檔'));
  const most = rule.carousel ?? 4;
  if (format === 'carousel' && (media.length < 2 || media.length > most)) errors.push(t('多圖需 2–{max} 張圖片', { max: most }));
  for (const item of media) {
    const video = item.mime.startsWith('video/');
    if ((format === 'video' && !video) || (format !== 'video' && video)) { errors.push(t('媒體型別與格式不符（影片不能和圖片混用）')); continue; }
    if (!video) { if (item.size && item.size > (rule.image_bytes ?? 5 * 1024 ** 2)) errors.push(t('圖片最多 5 MB')); continue; }
    if (item.size && item.size > 1024 ** 3) errors.push(t('影片最多 1 GB'));
    const seconds = item.duration ?? 0;
    if (seconds < (rule.video_seconds_min ?? 0.5) || seconds > rule.video_seconds) errors.push(t('影片長度需 0.5 秒–20 分鐘'));
    else if (seconds > (rule.standard_video_seconds ?? 140)) warnings.push(t('影片超過 140 秒：非 X Premium 帳號會被拒絕'));
    if (!item.width || !item.height) { errors.push(t('無法讀取影片尺寸')); continue; }
    const [low, high] = rule.video_ratio ?? [1 / 3, 3], [wide, tall] = rule.video_side_max ?? [1280, 1024];
    if (item.width / item.height < low || item.width / item.height > high) errors.push(t('影片比例需 1:3–3:1'));
    if (Math.max(item.width, item.height) > wide || Math.min(item.width, item.height) > tall) warnings.push(t('影片超過官方建議的 1280×1024，X 可能拒收或重新壓縮'));
  }
  if (xHasUrl(caption)) warnings.push(t('文案含網址：這則貼文會扣 ${url}（一般貼文 ${post}）', { url: (rule.url_post_cost_usd ?? 0.2).toFixed(2), post: (rule.post_cost_usd ?? 0.015).toFixed(3) }));
  return { errors: [...new Set(errors)], warnings: [...new Set(warnings)] };
}
const IG_PNG_WARNING = t('Instagram 會自動把 PNG 轉成 JPEG，透明背景會變白底');
// 與後端 publish_rules 的 IG_COVER_* 同字。
export const IG_COVER_PNG_WARNING = t('Reels 封面會轉成 JPEG 送出，透明背景會變白底');
export const IG_COVER_RATIO_WARNING = t('Reels 封面建議 9:16，其他比例會裁切中間；分享到動態時會再裁成 1:1');
export const FB_COVER_RATIO_WARNING = t('Facebook 封面建議與影片同比例');
export function checkComposer(platform: Platform, format: Format, caption: string, media: ComposerMedia[], options: PlatformOptions, rules: Rules, unpublished = false, thumbnail?: ComposerMedia | null, cover?: ComposerMedia | null) {
  const rule = rules[platform], errors: string[] = [], warnings: string[] = [];
  if (platform === 'youtube' && format !== 'story') return checkYoutube(format, caption, media, options, rule, thumbnail);
  if (platform === 'tiktok') return checkTiktok(format, caption, media, rule);
  if (platform === 'x') return checkX(format, caption, media, rule);
  if (format === 'story') {
    if (platform === 'threads') errors.push(t('限時動態僅支援 Facebook／Instagram'));
    if (caption || unpublished) errors.push(t('限時動態不支援文字或存成 FB 草稿'));
    if (media.length < 1 || media.length > 10) errors.push(t('限時動態需 1–10 則素材'));
    media.forEach((item, i) => {
      const prefix = t('第 {n} 則：', { n: i + 1 });
      if (item.mime.startsWith('video/')) {
        const min = platform === 'instagram' ? 3 : 0;
        if (!item.duration || item.duration < min || item.duration > 60) errors.push(prefix + (min ? t('影片長度需 3–60 秒') : t('影片最長 60 秒')));
        if (item.size && item.size > 1024 ** 3) errors.push(prefix + t('影片最多 1 GB'));
        if (platform === 'instagram' && item.width > 1920) errors.push(prefix + t('影片寬度最多 1920 px'));
      } else {
        if (item.size && item.size > 8 * 1024 ** 2) errors.push(prefix + t('圖片最多 8 MB'));
        if (platform === 'instagram' && item.mime === 'image/png') warnings.push(prefix + IG_PNG_WARNING);
        else if (platform === 'instagram' && item.mime !== 'image/jpeg') errors.push(prefix + t('Instagram 圖片只支援 JPEG 或 PNG'));
      }
      if (!item.height || Math.abs(item.width / item.height - 9 / 16) > 0.01) warnings.push(t('第 {n} 則非 9:16，平台會加邊', { n: i + 1 }));
    });
    return { errors: [...new Set(errors)], warnings };
  }
  const segments = platform === 'threads' ? options.threads.segments.map(toPlatformText) : [caption];
  for (const [i, segment] of segments.entries()) {
    // Threads 文案是第一則，之後是各則回覆。
    const label = platform === 'threads' ? (i === 0 ? t('Threads 文案') : t('回覆 {n}', { n: i })) : t('文案');
    const reason = overLimitReason(label, segment, rule.caption, platform);
    if (reason) errors.push(reason);
    if (platform === 'threads' && !segment.trim() && (i > 0 || format === 'text')) errors.push(t('{label}不可空白', { label }));
  }
  const text = platform === 'threads' ? segments.join('\n') : caption, tags = hashtags(text), ats = mentions(text);
  if (platform === 'threads' && !segments.length) errors.push(t('串文至少需要一段'));
  if (platform === 'instagram') {
    if (format === 'text') errors.push(t('Instagram 不支援純文字'));
    if (tags.length > rule.hashtag!) errors.push(t('hashtag 超過 {over} 個（上限 {limit}）', { over: tags.length - rule.hashtag!, limit: rule.hashtag! }));
    if (ats.length > rule.mentions!) errors.push(t('@ 超過 {over} 個（上限 {limit}）', { over: ats.length - rule.mentions!, limit: rule.mentions! }));
    // 發文成功後由 IG 帳號依序留的評論（只有文字）；規則與後端 publish_rules.check 相同。
    const comments = (options.instagram.comments ?? []).map(toPlatformText), limit = rule.comments ?? 20;
    if (comments.length > limit) errors.push(t('評論最多 {limit} 則', { limit }));
    for (const [i, comment] of comments.entries()) {
      if (!comment.trim()) errors.push(t('評論 {n} 不可空白', { n: i + 1 }));
      else { const reason = overLimitReason(t('評論 {n} ', { n: i + 1 }), comment, rule.caption, platform); if (reason) errors.push(reason); }
    }
  }
  if (platform === 'facebook') {
    // 發文成功後由粉專依序留的評論；規則與後端 publish_rules.check 相同。
    const comments = options.facebook.comments.map(toPlatformText), limit = rule.comments ?? 20;
    if (comments.length > limit) errors.push(t('評論最多 {limit} 則', { limit }));
    for (const [i, comment] of comments.entries()) {
      // 有附圖的評論可以不寫字。
      if (!comment.trim() && !options.facebook.comment_media?.[i]) errors.push(t('評論 {n} 不可空白', { n: i + 1 }));
      else { const reason = overLimitReason(t('評論 {n} ', { n: i + 1 }), comment, rule.caption, platform); if (reason) errors.push(reason); }
    }
    if (comments.length && unpublished) warnings.push(t('存成 FB 草稿時不會留評論'));
  }
  if (platform === 'facebook' && caption.includes('@')) warnings.push(t('Facebook 發文無法標註，@ 會顯示為一般文字'));
  if (platform === 'threads' && tags.length > 1) warnings.push(t('Threads 只用第一個 hashtag 當主題標籤，其餘顯示為一般文字'));
  if (platform === 'threads' && tags[0] && (Array.from(tags[0].slice(1)).length > 50 || /[.&]/.test(tags[0]))) errors.push(t('主題標籤最多 50 字，不能含句點或 &'));
  if (format === 'text' && (media.length || !text.trim())) errors.push(t('純文字須有文案且不能包含媒體'));
  if (['image', 'video'].includes(format) && media.length !== 1) errors.push(t('此格式需 1 個媒體檔'));
  if (format === 'carousel' && (media.length < 2 || media.length > rule.carousel!)) errors.push(t('輪播需 2–{max} 個媒體檔', { max: rule.carousel! }));
  for (const item of media) {
    const video = item.mime.startsWith('video/'), ratio = item.width / item.height;
    if ((format === 'video' && !video) || (format === 'image' && video)) errors.push(t('媒體型別與格式不符'));
    if (format === 'carousel' && platform !== 'threads' && video) errors.push(t('本版輪播僅支援圖片'));
    if (video) {
      const reels = platform === 'facebook' && options.facebook.video_format === 'reels';
      const min = reels ? rule.reels_seconds_min! : platform === 'instagram' ? 3 : 0;
      const max = reels ? rule.reels_seconds_max! : rule.video_seconds;
      if (!item.duration || item.duration < min || item.duration > max) errors.push(t('影片長度需 {min}–{max} 秒', { min, max }));
      if (reels && (!item.width || !item.height || Math.abs(ratio - 9 / 16) > 0.01)) errors.push(t('Facebook Reels 影片需為 9:16 直式'));
      if (platform === 'instagram' && !(ratio >= 0.01 && ratio <= 10)) errors.push(t('Reels 影片比例需 0.01:1–10:1（建議 9:16）'));
      if (platform === 'instagram' && format === 'video' && cover) {
        if (!(rule.cover_mimes ?? []).includes(cover.mime)) errors.push(t('封面只支援 JPG／PNG'));
        if (cover.size && rule.cover_bytes && cover.size > rule.cover_bytes) errors.push(t('封面最多 {size} MB', { size: Math.floor(rule.cover_bytes / 1024 ** 2) }));
        if (cover.mime === 'image/png') warnings.push(IG_COVER_PNG_WARNING);
        if (!cover.height || Math.abs(cover.width / cover.height - 9 / 16) > 0.01) warnings.push(IG_COVER_RATIO_WARNING);
      }
      if (platform === 'facebook' && format === 'video' && cover) {
        if (!(rule.cover_mimes ?? []).includes(cover.mime)) errors.push(t('封面只支援 JPG／PNG'));
        if (cover.size && rule.cover_bytes && cover.size > rule.cover_bytes) errors.push(t('封面最多 {size} MB', { size: Math.floor(rule.cover_bytes / 1024 ** 2) }));
        if (!cover.height || !item.height || Math.abs(cover.width / cover.height - ratio) > 0.02) warnings.push(FB_COVER_RATIO_WARNING);
      }
      if (platform !== 'facebook' && item.width > 1920) errors.push(t('影片寬度最多 1920 px'));
      if (item.size && item.size > 1024 ** 3) errors.push(t('影片最多 1 GB'));
    } else {
      if (item.size && item.size > 8 * 1024 ** 2) errors.push(t('圖片最多 8 MB'));
      if (platform === 'instagram') {
        if (item.mime === 'image/png') warnings.push(IG_PNG_WARNING);
        else if (item.mime !== 'image/jpeg') errors.push(t('Instagram 圖片只支援 JPEG 或 PNG'));
        if (!(ratio >= 0.8 && ratio <= 1.91)) errors.push(t('圖片比例需 4:5–1.91:1'));
        if (item.width < 320 || item.width > 1440) errors.push(t('圖片寬度需 320–1440 px'));
      }
      if (platform === 'threads' && !(ratio >= 0.1 && ratio <= 10)) errors.push(t('圖片比例需 0.1:1–10:1'));
    }
  }
  return { errors: [...new Set(errors)], warnings: [...new Set(warnings)], topicTag: platform === 'threads' ? tags[0]?.slice(1) : undefined };
}
// 簡化預覽採字元／行數門檻，避免假裝平台實際像素版面。
export const previewLimits = { facebook: 480, instagram: 125, threads: 280, youtube: 100, tiktok: 100, x: 280 };
export function foldCaption(raw: string, platform: Platform, expanded = false) {
  // 開頭的空行不算在折疊的行數裡，否則前三行都是空白時預覽只剩「…更多」。
  const text = raw.trim();
  // Threads 每段最多 500 字且平台不折疊，整段顯示。
  if (platform === 'threads' || platform === 'x') return { text, folded: false };
  const chars = Array.from(text), lineEnd = text.split('\n').slice(0, platform === 'instagram' ? 2 : 3).join('\n');
  const limit = Math.min(previewLimits[platform], Array.from(lineEnd).length);
  const folded = chars.length > limit;
  return { text: expanded || !folded ? text : chars.slice(0, limit).join('') + '…', folded };
}
export function previewRatio(platform: Platform, format: Format, media: ComposerMedia, options: PlatformOptions, unpublished: boolean) {
  if (format === 'story') return '9 / 16';
  // YouTube：Shorts 用直式，其餘影片一律是 16:9 的播放器。
  if (platform === 'youtube') return isShort(media) ? '9 / 16' : '16 / 9';
  if (platform === 'tiktok') return '9 / 16';
  if (format === 'video' && (platform === 'instagram' || (platform === 'facebook' && options.facebook.video_format === 'reels'))) return '9 / 16';
  if (platform === 'instagram') return media.width === media.height ? '1 / 1' : '4 / 5';
  return media.width > 0 && media.height > 0 ? media.width + ' / ' + media.height : '1 / 1';
}

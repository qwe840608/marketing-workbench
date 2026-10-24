import type { Metric } from './api';
import { locale, t } from './i18n.ts';

export type MetricField = 'views' | 'reach' | 'likes' | 'comments' | 'shares' | 'saves' | 'reposts' | 'quotes' | 'avg_watch_time' | 'watch_hours' | 'subscribers_gained' | 'skip_rate' | 'avg_view_percentage';
export type MetricDefinition = readonly [MetricField, string];

// FB／IG 沿用原有六項；Threads 沒有觸及與收藏，多了轉發與引用（存在 extra_json），留言稱為回覆。
const metaFields: readonly MetricDefinition[] = [['views', t('觀看')], ['reach', t('觸及')], ['likes', t('按讚')], ['comments', t('留言')], ['shares', t('分享')], ['saves', t('收藏')]];
const threadsFields: readonly MetricDefinition[] = [['views', t('觀看')], ['likes', t('按讚')], ['comments', t('回覆')], ['reposts', t('轉發')], ['quotes', t('引用')], ['shares', t('分享')]];

// TikTok 後端只寫觀看、按讚、留言、分享；觸及與收藏標為不提供，不能沿用 Meta 欄位顯示成「—」。
const tiktokFields: readonly MetricDefinition[] = [['views', t('觀看')], ['likes', t('按讚')], ['comments', t('留言')], ['shares', t('分享')]];
const youtubeFields: readonly MetricDefinition[] = [['views', t('觀看')], ['likes', t('按讚')], ['comments', t('留言')], ['shares', t('分享')], ['subscribers_gained', t('新增訂閱')]];

// 影片觀看表現另列一區：FB／IG 只有影片與 Reels 有，YouTube 每支都有；Threads、TikTok 的官方 API 沒有這些數據。
const watchTime: MetricDefinition = ['avg_watch_time', t('平均觀看時長（秒）')];
const watchHours: MetricDefinition = ['watch_hours', t('觀看總時數（小時）')];
const videoFieldsByPlatform: Record<string, readonly MetricDefinition[]> = {
  facebook: [watchTime, watchHours],
  instagram: [watchTime, watchHours, ['skip_rate', t('前 3 秒滑走率（%）')]],
  youtube: [watchTime, ['avg_view_percentage', t('平均觀看百分比（%）')], watchHours],
};
export const videoFields = (platform: string | null | undefined) => videoFieldsByPlatform[platform ?? ''] ?? [];
export const isVideoPost = (platform: string | null | undefined, mediaType: string | null | undefined) =>
  platform === 'youtube' || platform === 'tiktok' || /video|reels/i.test(mediaType ?? '');
// YouTube 數據分析 API 的指標約晚 1～2 天。
export const delayedYoutubeFields: readonly MetricField[] = ['shares', 'subscribers_gained', 'avg_watch_time', 'watch_hours', 'avg_view_percentage'];
const extraFields: readonly MetricField[] = ['reposts', 'quotes', 'watch_hours', 'subscribers_gained', 'skip_rate', 'avg_view_percentage'];

export const metricFields = (platform: string | null | undefined) => platform === 'youtube' ? youtubeFields : platform === 'tiktok' ? tiktokFields : platform === 'threads' ? threadsFields : metaFields;
export const defaultMetric = (platform: string | null | undefined): MetricField => platform === 'threads' || platform === 'youtube' || platform === 'tiktok' ? 'views' : 'reach';
export const syncLabel = (platform: string | null | undefined) => platform === 'youtube' ? t('YouTube 留言') : platform === 'threads' ? t('Threads 回覆') : platform === 'facebook' ? t('Facebook 留言') : t('Instagram 留言');

// 缺值、非數字都回傳 null，畫面顯示「—」，不把沒有的指標當成零。
export function metricValue(row: Metric | null | undefined, field: MetricField): number | null {
  if (!row) return null;
  const value = extraFields.includes(field) ? row.extra_json?.[field as keyof Metric['extra_json']] : row[field as keyof Metric];
  const parsed = field === 'avg_watch_time' && typeof value === 'string' && value.trim() ? Number(value) : value;
  if (typeof parsed !== 'number' || !Number.isFinite(parsed)) return null;
  // FB／IG 的平均觀看時長以毫秒保存，YouTube 以秒保存；畫面一律顯示秒。
  return field === 'avg_watch_time' && row.extra_json?.metric_units?.avg_watch_time === 'milliseconds' ? parsed / 1000 : parsed;
}

// 時長與百分比顯示到小數一位，總時數到小數兩位；計數照原樣。
export function formatMetric(value: number | null, field: MetricField): string {
  if (value == null) return '—';
  const digits = field === 'watch_hours' ? 2 : field === 'avg_watch_time' || field === 'skip_rate' || field === 'avg_view_percentage' ? 1 : 3;
  return value.toLocaleString(locale(), { maximumFractionDigits: digits });
}

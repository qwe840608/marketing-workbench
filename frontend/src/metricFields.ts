import type { Metric } from './api';
import { t } from './i18n.ts';

export type MetricField = 'views' | 'reach' | 'likes' | 'comments' | 'shares' | 'saves' | 'reposts' | 'quotes' | 'avg_watch_time' | 'watch_hours' | 'subscribers_gained';
export type MetricDefinition = readonly [MetricField, string];

// FB／IG 沿用原有六項；Threads 沒有觸及與收藏，多了轉發與引用（存在 extra_json），留言稱為回覆。
const metaFields: readonly MetricDefinition[] = [['views', t('觀看')], ['reach', t('觸及')], ['likes', t('按讚')], ['comments', t('留言')], ['shares', t('分享')], ['saves', t('收藏')]];
const threadsFields: readonly MetricDefinition[] = [['views', t('觀看')], ['likes', t('按讚')], ['comments', t('回覆')], ['reposts', t('轉發')], ['quotes', t('引用')], ['shares', t('分享')]];
const metaColumns: readonly MetricDefinition[] = [['views', t('觀看')], ['reach', t('觸及')], ['comments', t('留言')]];
const threadsColumns: readonly MetricDefinition[] = [['views', t('觀看')], ['likes', t('按讚')], ['comments', t('回覆')]];

// TikTok 後端只寫觀看、按讚、留言、分享；觸及與收藏標為不提供，不能沿用 Meta 欄位顯示成「—」。
const tiktokFields: readonly MetricDefinition[] = [['views', t('觀看')], ['likes', t('按讚')], ['comments', t('留言')], ['shares', t('分享')]];
const youtubeFields: readonly MetricDefinition[] = [['views', t('觀看')], ['likes', t('按讚')], ['comments', t('留言')], ['shares', t('分享')], ['avg_watch_time', t('平均觀看時長（秒）')], ['watch_hours', t('觀看總時數（小時）')], ['subscribers_gained', t('新增訂閱')]];

export const metricFields = (platform: string | null | undefined) => platform === 'youtube' ? youtubeFields : platform === 'tiktok' ? tiktokFields : platform === 'threads' ? threadsFields : metaFields;
export const snapshotColumns = (platform: string | null | undefined) => platform === 'threads' || platform === 'youtube' || platform === 'tiktok' ? threadsColumns.map(([key, label]) => [key, platform !== 'threads' && key === 'comments' ? t('留言') : label] as MetricDefinition) : metaColumns;
export const defaultMetric = (platform: string | null | undefined): MetricField => platform === 'threads' || platform === 'youtube' || platform === 'tiktok' ? 'views' : 'reach';
export const syncLabel = (platform: string | null | undefined) => platform === 'youtube' ? t('YouTube 留言') : platform === 'threads' ? t('Threads 回覆') : platform === 'facebook' ? t('Facebook 留言') : t('Instagram 留言');

// 缺值、非數字都回傳 null，畫面顯示「—」，不把沒有的指標當成零。
export function metricValue(row: Metric | null | undefined, field: MetricField): number | null {
  if (!row) return null;
  const value = field === 'reposts' || field === 'quotes' || field === 'watch_hours' || field === 'subscribers_gained' ? row.extra_json?.[field] : row[field];
  const parsed = field === 'avg_watch_time' && typeof value === 'string' && value.trim() ? Number(value) : value;
  return typeof parsed === 'number' && Number.isFinite(parsed) ? parsed : null;
}

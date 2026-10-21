import { t, locale } from './i18n.ts';

// 與前期比較的文字；前期為 0 時不算百分比（任何成長都是無限大，沒有意義）。
export function growthText(current: number, previous: number, period: string) {
  if (previous === 0) return current === 0 ? t('{period}也沒有', { period }) : t('{period}沒有，無法比較', { period });
  const change = (current - previous) / previous * 100;
  const shown = Math.abs(change) < 10 ? Math.round(Math.abs(change) * 10) / 10 : Math.round(Math.abs(change));
  if (shown === 0) return t('與{period}持平', { period });
  const percent = shown.toLocaleString(locale());
  return change > 0 ? t('比{period}增加 {percent}%', { period, percent }) : t('比{period}減少 {percent}%', { period, percent });
}

export function growthDirection(current: number, previous: number): 'up' | 'down' | 'flat' {
  if (previous === 0 || current === previous) return 'flat';
  return current > previous ? 'up' : 'down';
}

export type FunnelStage = { key: 'reach' | 'engagement' | 'comments' | 'inquiries'; value: number };
export type Funnel = { days: number; timezone: string; posts: number; stages: FunnelStage[] };

export const funnelLabels: Record<FunnelStage['key'], string> = { reach: t('觸及人數'), engagement: t('互動次數'), comments: t('留言'), inquiries: t('消費詢問') };

// 轉換率＝這一階 ÷ 上一階；上一階為 0 時顯示「—」。互動是次數，可能超過觸及，照實顯示。
export function conversion(value: number, previous: number) {
  if (previous <= 0) return null;
  const rate = value / previous * 100;
  return rate < 10 ? Math.round(rate * 10) / 10 : Math.round(rate);
}

export function barWidth(value: number, top: number) {
  if (value <= 0 || top <= 0) return 0;
  return Math.max(2, Math.min(100, value / top * 100));
}

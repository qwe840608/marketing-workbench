import { t } from './i18n.ts';

export type TrendDay = { date: string; new_messages: number };
export type Trends = { days: number; timezone: string; series: TrendDay[]; previous_total?: number };

export function trendGeometry(series: TrendDay[]) {
  const maxMessages = Math.max(1, ...series.map(row => row.new_messages));
  const step = 510 / Math.max(1, series.length);
  const points = series.map((row, index) => ({
    ...row, x: 55 + step * (index + 0.5),
    barY: 180 - row.new_messages / maxMessages * 135,
    label: series.length <= 7 || index % 5 === 0 ? row.date.slice(5).replace('-', '/') : null,
  }));
  return { points, step, maxMessages, empty: series.every(row => row.new_messages === 0) };
}

export function trendDescription(row: TrendDay) {
  return t('{date} · 新留言 {count}', { date: row.date, count: row.new_messages });
}

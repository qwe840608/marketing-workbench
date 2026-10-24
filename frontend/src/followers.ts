import { t, locale } from './i18n.ts';
import { TAIPEI } from './time.ts';

export type FollowerSelection = { year: number; month: number; week: number };
export type FollowerWeek = { week: number; date_from: string; date_to: string };
export type FollowerReport = FollowerSelection & {
  subscriber_hidden?: boolean;
  platform: string; connected: boolean; years: number[]; weeks: FollowerWeek[];
  is_current_month: boolean; is_current_week: boolean;
  current_count: number | null; week_delta: number | null; month_delta: number | null;
};

export function formatDelta(value: number | null) {
  if (value === null) return '—';
  return (value < 0 ? '−' : value > 0 ? '+' : '') + Math.abs(value).toLocaleString(locale());
}

export function followerWeeks(year: number, month: number): FollowerWeek[] {
  const last = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const day = (d: number) => `${year}-${String(month).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
  const weeks: FollowerWeek[] = [];
  for (let start = 1; start <= last;) {
    const weekday = (new Date(Date.UTC(year, month - 1, start)).getUTCDay() + 6) % 7;
    const end = Math.min(start + 6 - weekday, last);
    weeks.push({ week: weeks.length + 1, date_from: day(start), date_to: day(end) });
    start = end + 1;
  }
  return weeks;
}

export function defaultFollowerSelection(now = new Date()): FollowerSelection {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: TAIPEI, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(now);
  const part = (name: string) => Number(parts.find(p => p.type === name)!.value);
  const year = part('year'), month = part('month'), day = part('day');
  const week = followerWeeks(year, month).find(w => Number(w.date_to.slice(-2)) >= day)!.week;
  return { year, month, week };
}

export function followerWeekLabel(week: FollowerWeek) {
  const short = (date: string) => `${Number(date.slice(5, 7))}/${Number(date.slice(8))}`;
  return t('第{week}週（{from}–{to}）', { week: week.week, from: short(week.date_from), to: short(week.date_to) });
}

export function followerLabels(selected: FollowerSelection, current = defaultFollowerSelection()) {
  const month = selected.year === current.year && selected.month === current.month;
  return [month && selected.week === current.week ? t('本週') : t('該週'), month ? t('本月') : t('該月')];
}

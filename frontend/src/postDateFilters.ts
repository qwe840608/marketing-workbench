import { locale, t } from './i18n.ts';

export type DateFilter = { period: 'all' | '7' | '30' | '90' | 'custom'; from: string; to: string };
export const dateOptions = { '7': t('近 7 天'), '30': t('近 30 天'), '90': t('近 90 天'), all: t('全部') } as const;

export function readDateFilter(search: string, prefix: string): DateFilter {
  const params = new URLSearchParams(search);
  const period = params.get(prefix + '_range') || 'all';
  const date = (key: string) => {
    const value = params.get(prefix + key) || '';
    return /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : '';
  };
  return { period: ['all', '7', '30', '90', 'custom'].includes(period) ? period as DateFilter['period'] : 'all',
    from: date('_from'), to: date('_to') };
}

export function writeDateFilter(params: URLSearchParams, prefix: string, filter: DateFilter) {
  params.set(prefix + '_range', filter.period);
  for (const [key, value] of [['_from', filter.from], ['_to', filter.to]]) {
    if (filter.period === 'custom' && value) params.set(prefix + key, value);
    else params.delete(prefix + key);
  }
}

export function dateQuery(filter: DateFilter): string {
  const params = new URLSearchParams({ period: filter.period });
  if (filter.period === 'custom') {
    if (filter.from) params.set('date_from', filter.from);
    if (filter.to) params.set('date_to', filter.to);
  }
  return params.toString();
}

export function syncSummary(total: number, platform: number | null | undefined): string {
  return t('已同步 {count} 則', { count: total.toLocaleString(locale()) }) + (platform == null ? '' :
    t('／平台顯示 {count} 則', { count: platform.toLocaleString(locale()) }) +
    (platform > total ? t('（較舊的留言尚未同步）') : ''));
}

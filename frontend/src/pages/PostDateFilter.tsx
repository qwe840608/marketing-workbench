import { dateOptions } from '../postDateFilters';
import type { DateFilter } from '../postDateFilters';
import { SegmentedControl } from './SegmentedControl';
import { t } from '../i18n.ts';

export function PostDateFilter({ label, value, onChange }: { label: string; value: DateFilter; onChange: (value: DateFilter) => void }) {
  const invalid = value.period === 'custom' && value.from && value.to && value.from > value.to;
  return <div className="post-date-filter" role="group" aria-label={label} title={t('台北時間 · 自訂日期包含起訖日')}>
    <div className="filter-choice"><span className="filter-label">{label}</span>
      <SegmentedControl compact label={label} options={Object.entries(dateOptions).map(([period, name]) => ({ value: period as DateFilter['period'], label: name }))}
        value={value.period} onChange={period => onChange({ period, from: '', to: '' })} />
    </div>
    <div className="post-date-inputs">
      <label><span className="date-input-name">{t('起日')}</span><input type="date" aria-label={t('{label}起日', { label })} value={value.from} max={value.to || undefined}
        onChange={event => onChange({ ...value, period: 'custom', from: event.target.value })} /></label>
      <span aria-hidden="true">～</span>
      <label><span className="date-input-name">{t('迄日')}</span><input type="date" aria-label={t('{label}迄日', { label })} value={value.to} min={value.from || undefined}
        onChange={event => onChange({ ...value, period: 'custom', to: event.target.value })} /></label>
    </div>
    {invalid && <p className="error" role="alert">{t('起日不可晚於迄日')}</p>}
    <small className="metric-note">{t('台北時間 · 自訂日期包含起訖日')}</small>
  </div>;
}

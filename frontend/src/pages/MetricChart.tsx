import { useEffect, useRef, useState } from 'react';
import type { Metric } from '../api';
import { defaultMetric, metricFields, metricValue } from '../metricFields';
import type { MetricField } from '../metricFields';
import { t, locale } from '../i18n.ts';

const time = (date: string) => new Intl.DateTimeFormat(locale(), { timeZone: 'Asia/Taipei', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(date));

export function MetricChart({ metrics, platform }: { metrics: Metric[]; platform?: string | null }) {
  const chart = useRef<SVGSVGElement>(null);
  const options = metricFields(platform);
  const fields = Object.fromEntries(options) as Record<MetricField, string>;
  useEffect(() => {
    const element = chart.current;
    if (!element) return;
    // SVG viewBox scaling must not shrink labels below the shared minimum.
    const observer = new ResizeObserver(([entry]) => {
      if (entry.contentRect.width > 0) element.style.setProperty('--chart-text-scale', String(620 / entry.contentRect.width));
    });
    observer.observe(element);
    return () => observer.disconnect();
  });
  const [field, setField] = useState<MetricField>(defaultMetric(platform));
  const valid = (row: Metric) => metricValue(row, field) !== null && Number.isFinite(new Date(row.captured_at).getTime());
  const available = metrics.filter(valid);
  const highest = Math.max(0, ...available.map(row => metricValue(row, field)!));
  const max = Math.max(1, highest);
  const times = metrics.map(row => new Date(row.captured_at).getTime()).filter(Number.isFinite);
  const first = times.length ? Math.min(...times) : 0;
  const last = times.length ? Math.max(...times) : 0;
  const x = (row: Metric) => last === first ? 310 : 55 + (new Date(row.captured_at).getTime() - first) / (last - first) * 510;
  const y = (row: Metric) => 180 - metricValue(row, field)! / max * 135;
  const segments: string[][] = [[]];
  metrics.forEach(row => { if (!valid(row)) { if (segments.at(-1)!.length) segments.push([]); } else segments.at(-1)!.push(`${x(row)},${y(row)}`); });
  return <section className="metric-chart" aria-label={t('數據快照曲線')}><div className="card-title"><h3>{t('數據變化')}</h3><label><span className="sr-only">{t('曲線指標')}</span><select value={field} onChange={e => setField(e.target.value as MetricField)}>{options.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label></div>
    {available.length ? <><svg ref={chart} viewBox="0 0 620 220" role="img" aria-label={t('{metric}變化，{count}筆有效快照，最高{highest}', { metric: fields[field], count: available.length, highest })}>
      {[0, 0.5, 1].map(r => <g key={r}><line x1="55" x2="565" y1={180 - r * 135} y2={180 - r * 135} className="chart-grid" /><text x="0" y={184 - r * 135} textAnchor="start">{(max * r).toLocaleString(locale(), { maximumFractionDigits: 1 })}</text></g>)}
      {segments.filter(s => s.length).map((s, i) => <polyline key={i} points={s.join(' ')} className="chart-line" />)}
      {available.map(row => <circle key={row.id} cx={x(row)} cy={y(row)} r="4" className="chart-point"><title>{time(row.captured_at)} · {fields[field]} {metricValue(row, field)?.toLocaleString(locale())}</title></circle>)}
      <text x="55" y="207">{time(new Date(first).toISOString())}</text>{last !== first && <text x="565" y="207" textAnchor="end">{time(new Date(last).toISOString())}</text>}
    </svg><p className="metric-note">{available.length === 1 ? t('目前只有一筆有效快照，累積後會顯示曲線。') : t('按快照時間排列；平台未提供的區段不連線。')} {t('台北時間')}</p></> : <p className="empty-data">{t('尚無「{metric}」的有效快照，累積後會顯示曲線。', { metric: fields[field] })}</p>}
  </section>;
}

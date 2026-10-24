import { useEffect, useRef, useState } from 'react';
import type { Metric } from '../api';
import { formatMetric, metricValue } from '../metricFields';
import type { MetricDefinition, MetricField } from '../metricFields';
import { t, locale } from '../i18n.ts';
import { formatTaipei } from '../time.ts';

const time = (date: string) => formatTaipei(date, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });

// 快照曲線卡片：上方分頁籤切換指標。互動指標（數據變化）與影片觀看指標（觀看變化）各用一張。
export function MetricChart({ metrics, fields, title, initial, className = 'metric-chart' }: {
  metrics: Metric[]; fields: readonly MetricDefinition[]; title: string; initial: MetricField; className?: string;
}) {
  const chart = useRef<SVGSVGElement>(null);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  const labels = Object.fromEntries(fields) as Record<MetricField, string>;
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
  const [chosen, setField] = useState<MetricField>(initial);
  const field = labels[chosen] ? chosen : fields[0][0];
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
  const choose = (index: number) => { setField(fields[index][0]); tabs.current[index]?.focus(); };
  return <section className={className} aria-label={title}><div className="card-title"><h3>{title}</h3></div>
    <div className="tabs chart-tabs" role="tablist" aria-label={t('曲線指標')}>{fields.map(([key, label], index) =>
      <button key={key} ref={el => { tabs.current[index] = el; }} type="button" role="tab" aria-selected={field === key} tabIndex={field === key ? 0 : -1} onClick={() => setField(key)} onKeyDown={event => {
        const next = event.key === 'ArrowRight' ? (index + 1) % fields.length : event.key === 'ArrowLeft' ? (index + fields.length - 1) % fields.length : event.key === 'Home' ? 0 : event.key === 'End' ? fields.length - 1 : null;
        if (next === null) return;
        event.preventDefault(); choose(next);
      }}>{label}</button>)}</div>
    <div role="tabpanel" aria-label={labels[field]}>
    {available.length ? <><svg ref={chart} viewBox="0 0 620 220" role="img" aria-label={t('{metric}變化，{count}筆有效快照，最高{highest}', { metric: labels[field], count: available.length, highest: formatMetric(highest, field) })}>
      {[0, 0.5, 1].map(r => <g key={r}><line x1="55" x2="565" y1={180 - r * 135} y2={180 - r * 135} className="chart-grid" /><text x="0" y={184 - r * 135} textAnchor="start">{(max * r).toLocaleString(locale(), { maximumFractionDigits: 1 })}</text></g>)}
      {segments.filter(s => s.length).map((s, i) => <polyline key={i} points={s.join(' ')} className="chart-line" />)}
      {available.map(row => <circle key={row.id} cx={x(row)} cy={y(row)} r="4" className="chart-point"><title>{time(row.captured_at)} · {labels[field]} {formatMetric(metricValue(row, field), field)}</title></circle>)}
      <text x="55" y="207">{time(new Date(first).toISOString())}</text>{last !== first && <text x="565" y="207" textAnchor="end">{time(new Date(last).toISOString())}</text>}
    </svg><p className="metric-note">{available.length === 1 ? t('目前只有一筆有效快照，累積後會顯示曲線。') : t('按快照時間排列；平台未提供的區段不連線。')} {t('台北時間')}</p></> : <p className="empty-data">{t('尚無「{metric}」的有效快照，累積後會顯示曲線。', { metric: labels[field] })}</p>}
    </div>
  </section>;
}

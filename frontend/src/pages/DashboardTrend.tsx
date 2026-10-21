import { useEffect, useRef, useState } from 'react';
import { SegmentedControl } from './SegmentedControl';
import { api } from '../api';
import { trendDescription, trendGeometry, type Trends } from '../dashboardTrend';
import { growthText } from '../growth';
import { t, locale } from '../i18n.ts';

export function DashboardTrend({ brand, revision }: { brand: string; revision: number }) {
  const [days, setDays] = useState(() => new URLSearchParams(location.search).get('trend_days') === '7' ? 7 : 30);
  const [data, setData] = useState<Trends | null>(null), [error, setError] = useState('');
  const [active, setActive] = useState<number | null>(null), [focusDay, setFocusDay] = useState(0);
  const chart = useRef<SVGSVGElement>(null);
  useEffect(() => {
    const onPopState = () => setDays(new URLSearchParams(location.search).get('trend_days') === '7' ? 7 : 30);
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);
  useEffect(() => {
    const controller = new AbortController(); let running = false;
    setData(null); setError(''); setActive(null); setFocusDay(0);
    async function refresh() {
      if (running) return; running = true;
      try {
        const value = await api<Trends>(`/dashboard/trends?days=${days}${brand ? `&brand_id=${brand}` : ''}`, { signal: controller.signal });
        if (!controller.signal.aborted) { setData(value); setError(''); }
      } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : t('每日趨勢暫時無法讀取')); }
      finally { running = false; }
    }
    void refresh(); const timer = window.setInterval(refresh, 15000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [brand, days, revision]);
  useEffect(() => {
    const element = chart.current;
    if (!element) return;
    // 與快照曲線一致，抵銷 viewBox 縮放以維持最低字級。
    const observer = new ResizeObserver(([entry]) => {
      if (entry.contentRect.width > 0) element.style.setProperty('--chart-text-scale', String(620 / entry.contentRect.width));
    });
    observer.observe(element);
    return () => observer.disconnect();
  });
  function selectDays(value: number) {
    const url = new URL(location.href); url.searchParams.set('trend_days', String(value));
    history.replaceState(history.state, '', url); setDays(value);
  }
  const geometry = data ? trendGeometry(data.series) : null;
  const total = data ? data.series.reduce((sum, row) => sum + row.new_messages, 0) : 0;
  const format = (value: number) => value.toLocaleString(locale(), { maximumFractionDigits: 1 });
  return <section className="dashboard-card dashboard-trend section-card" aria-label={t('每日趨勢')}>
    <div className="card-title"><h2>{t('每日趨勢')}</h2><div className="trend-days"><SegmentedControl compact label={t('趨勢天數')} options={[{ value: '7', label: t('7 天') }, { value: '30', label: t('30 天') }]} value={String(days)} onChange={value => selectDays(Number(value))} /></div></div>
    {error ? <p className="error" role="alert">{error}</p> : !geometry ? <p className="empty-data">{t('正在讀取每日趨勢…')}</p> : geometry.empty ? <p className="empty-data">{t('累積留言後會顯示每日趨勢')}</p> : <>
      <div className="trend-plot"><svg ref={chart} viewBox="0 0 620 220" role="group" aria-label={t('每日新留言')}>
        <text x="0" y="22">{t('留言')}</text>
        {[0, 0.5, 1].map(ratio => <g key={ratio}><line x1="55" x2="565" y1={180 - ratio * 135} y2={180 - ratio * 135} className="chart-grid" /><text x="0" y={184 - ratio * 135}>{format(geometry.maxMessages * ratio)}</text></g>)}
        {geometry.points.map(point => <rect key={point.date} className="trend-bar" x={point.x - geometry.step * 0.28} y={point.barY} width={geometry.step * 0.56} height={180 - point.barY} />)}
        {geometry.points.map((point, index) => <g key={point.date}>
          {point.label && <text x={point.x} y="210" textAnchor="middle">{point.label}</text>}
          <rect className={'trend-day' + (active === index ? ' is-active' : '')} x={point.x - geometry.step / 2} y="38" width={geometry.step} height="150" tabIndex={focusDay === index ? 0 : -1} role="img" aria-label={trendDescription(point)}
            onMouseEnter={() => setActive(index)} onMouseLeave={() => setActive(null)} onFocus={() => { setFocusDay(index); setActive(index); }} onBlur={() => setActive(null)}
            onKeyDown={event => {
              if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
              event.preventDefault();
              const next = event.key === 'Home' ? 0 : event.key === 'End' ? geometry.points.length - 1 : Math.max(0, Math.min(geometry.points.length - 1, index + (event.key === 'ArrowRight' ? 1 : -1)));
              chart.current?.querySelectorAll<SVGRectElement>('.trend-day')[next]?.focus();
            }}><title>{trendDescription(point)}</title></rect>
        </g>)}
      </svg>{active !== null && geometry.points[active] && <div className="trend-tooltip" role="tooltip">{trendDescription(geometry.points[active])}</div>}</div>
      <p className="trend-legend">{t('長條＝新留言 · 台北時間')}</p>
      {data?.previous_total !== undefined && <p className="trend-compare">{t('近 {days} 天共 {total} 則 · {comparison}（前 {days} 天 {previous} 則）', { days: data.days, total: total.toLocaleString(locale()), comparison: growthText(total, data.previous_total, t('前 {days} 天', { days: data.days })), previous: data.previous_total.toLocaleString(locale()) })}</p>}
    </>}
  </section>;
}

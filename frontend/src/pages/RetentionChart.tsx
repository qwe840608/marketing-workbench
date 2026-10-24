import { useEffect, useRef } from 'react';
import { locale, t } from '../i18n.ts';

const percent = (value: number) => value.toLocaleString(locale(), { maximumFractionDigits: 1 }) + '%';

// 觀眾留存曲線：平台把影片長度切成等分，每點是仍在觀看的比例（FB 為 40 等分）。
export function RetentionChart({ points }: { points: number[] }) {
  const chart = useRef<SVGSVGElement>(null);
  useEffect(() => {
    const element = chart.current;
    if (!element) return;
    // 與數據變化曲線相同：viewBox 縮放時字級不低於全站最小字級。
    const observer = new ResizeObserver(([entry]) => {
      if (entry.contentRect.width > 0) element.style.setProperty('--chart-text-scale', String(600 / entry.contentRect.width));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const top = Math.max(100, ...points);
  const x = (index: number) => 40 + index / (points.length - 1) * 540;
  const y = (value: number) => 150 - value / top * 130;
  const middle = points[Math.round((points.length - 1) / 2)];
  const end = points[points.length - 1];
  return <section className="metric-chart retention-chart" aria-label={t('觀眾留存')}>
    <div className="card-title"><h3>{t('觀眾留存')}</h3></div>
    <svg ref={chart} viewBox="0 0 600 180" role="img" aria-label={t('觀眾留存曲線，影片中段仍有 {middle}，結尾仍有 {end}', { middle: percent(middle), end: percent(end) })}>
      {[0, 50, 100].map(r => <g key={r}><line x1="40" x2="580" y1={y(r)} y2={y(r)} className="chart-grid" /><text x="0" y={y(r) + 4}>{r}%</text></g>)}
      <polyline points={points.map((value, index) => `${x(index)},${y(value)}`).join(' ')} className="retention-line" />
      <text x="40" y="174">{t('開頭')}</text><text x="580" y="174" textAnchor="end">{t('結尾')}</text>
    </svg>
    <p className="metric-note">{t('影片中段仍在看：{middle} · 看到結尾：{end}', { middle: percent(middle), end: percent(end) })}</p>
  </section>;
}

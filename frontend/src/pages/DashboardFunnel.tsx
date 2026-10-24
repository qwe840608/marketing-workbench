import { useEffect, useState } from 'react';
import { SegmentedControl } from './SegmentedControl';
import { api, errorMessage } from '../api';
import { barWidth, conversion, funnelLabels, type Funnel } from '../growth';
import { t, locale } from '../i18n.ts';

const readDays = () => new URLSearchParams(location.search).get('funnel_days') === '7' ? 7 : 30;

export function DashboardFunnel({ brand, revision }: { brand: string; revision: number }) {
  const [days, setDays] = useState(readDays);
  const [data, setData] = useState<Funnel | null>(null), [error, setError] = useState('');
  useEffect(() => {
    const onPopState = () => setDays(readDays());
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);
  useEffect(() => {
    const controller = new AbortController(); let running = false;
    setData(null); setError('');
    async function refresh() {
      if (running) return; running = true;
      try {
        const value = await api<Funnel>(`/dashboard/funnel?days=${days}${brand ? `&brand_id=${brand}` : ''}`, { signal: controller.signal });
        if (!controller.signal.aborted) { setData(value); setError(''); }
      } catch (e) { if (!controller.signal.aborted) setError(errorMessage(e, t('轉換漏斗暫時無法讀取'))); }
      finally { running = false; }
    }
    void refresh(); const timer = window.setInterval(refresh, 15000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [brand, days, revision]);
  function selectDays(value: number) {
    const url = new URL(location.href); url.searchParams.set('funnel_days', String(value));
    history.replaceState(history.state, '', url); setDays(value);
  }
  const top = data?.stages[0]?.value ?? 0;
  const number = (value: number) => value.toLocaleString(locale());
  return <section className="dashboard-card dashboard-funnel section-card" aria-label={t('轉換漏斗')}>
    <div className="card-title"><h2>{t('轉換漏斗')}</h2><div className="trend-days"><SegmentedControl compact label={t('漏斗天數')} options={[{ value: '7', label: t('7 天') }, { value: '30', label: t('30 天') }]} value={String(days)} onChange={value => selectDays(Number(value))} /></div></div>
    {error ? <p className="error" role="alert">{error}</p> : !data ? <p className="empty-data">{t('正在讀取轉換漏斗…')}</p> : !data.posts ? <p className="empty-data">{t('近 {days} 天沒有提供觸及數據的貼文', { days: data.days })}</p> : <>
      <p className="muted">{t('近 {days} 天發佈、有觸及數據的 {count} 篇貼文', { days: data.days, count: number(data.posts) })}</p>
      <ol className="funnel-stages">{data.stages.map((stage, index) => {
        const rate = index ? conversion(stage.value, data.stages[index - 1].value) : null;
        return <li key={stage.key} className="funnel-stage" data-stage={stage.key}>
          <div className="funnel-row"><span>{funnelLabels[stage.key]}</span><strong>{number(stage.value)}</strong></div>
          <span className="funnel-track" aria-hidden="true"><span style={{ width: `${barWidth(stage.value, top)}%` }} /></span>
          {index > 0 && <small className="funnel-rate">{rate === null ? t('上一階為 0，無轉換率') : t('上一階的 {rate}%', { rate: number(rate) })}</small>}
        </li>;
      })}</ol>
      <p className="funnel-note">{t('互動＝按讚、留言、分享、收藏的次數，同一人可能多次，所以可能多於觸及。消費詢問＝分類為價格詢問、預約、服務內容的客人留言。')}</p>
    </>}
  </section>;
}

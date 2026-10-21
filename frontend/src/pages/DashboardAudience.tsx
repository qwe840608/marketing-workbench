import { useEffect, useState } from 'react';
import { SegmentedControl } from './SegmentedControl';
import { api } from '../api';
import {
  audiencePlatformNames, audiencePlatforms, audienceSections, findInsight, itemLabel, peakHours, periodLabel,
  platformNotes, sectionTitle, shares, unavailableText,
  type AudienceAccount, type AudienceInsight, type AudiencePlatform, type AudienceReport, type AudienceSection,
} from '../audience';
import { t, locale } from '../i18n.ts';

const readPlatform = (): AudiencePlatform => {
  const value = new URLSearchParams(location.search).get('audience_platform');
  return (audiencePlatforms as readonly string[]).includes(value || '') ? value as AudiencePlatform : 'instagram';
};
const day = (value: string) => new Date(value).toLocaleDateString(locale(), { timeZone: 'Asia/Taipei', month: 'numeric', day: 'numeric' });

function Bars({ section, insight }: { section: AudienceSection; insight: AudienceInsight }) {
  const rows = shares(insight.items, insight.unit);
  const top = Math.max(...rows.map(row => row.share), 0);
  const number = (value: number) => value.toLocaleString(locale(), { maximumFractionDigits: 1 });
  return <ul className="audience-bars">{rows.map(row => <li key={row.key}>
    <div className="audience-row"><span>{itemLabel(section.breakdown, row.key)}</span>
      <strong>{number(row.share)}%{insight.unit === 'count' && <small>{section.metric === 'viewers' ? t('{count} 次觀看', { count: number(row.value) }) : t('{count} 人', { count: number(row.value) })}</small>}</strong></div>
    <span className="audience-track" aria-hidden="true"><span style={{ width: `${top ? row.share / top * 100 : 0}%` }} /></span>
  </li>)}</ul>;
}

function Hours({ insight }: { insight: AudienceInsight }) {
  const top = Math.max(...insight.items.map(item => item.value), 0);
  const peaks = peakHours(insight.items);
  return <>
    <div className="audience-hours" role="img" aria-label={t('各時段平均上線人數')}>{insight.items.map(item =>
      <span key={item.key} title={t('{hour} 時 · 平均 {count} 人', { hour: item.key, count: item.value.toLocaleString(locale()) })}>
        <span style={{ height: `${top ? item.value / top * 100 : 0}%` }} className={peaks.includes(Number(item.key)) ? 'is-peak' : ''} /></span>)}</div>
    <div className="audience-hour-axis" aria-hidden="true"><span>0</span><span>6</span><span>12</span><span>18</span><span>23</span></div>
    {peaks.length > 0 && <p className="audience-peak">{t('最多人上線：{hours}（台北時間）', { hours: peaks.map(hour => t('{hour} 時', { hour })).join('、') })}</p>}
  </>;
}

function Section({ account, section }: { account: AudienceAccount; section: AudienceSection }) {
  const insight = findInsight(account, section);
  return <section className="audience-section">
    <h3>{sectionTitle(section)}</h3>
    {!insight ? <p className="empty-data">{t('尚未取得，系統每天更新一次。')}</p>
      : insight.status !== 'ready' ? <p className="audience-hint">{unavailableText(insight.error)}</p>
      : <>{section.breakdown === 'hour' ? <Hours insight={insight} /> : <Bars section={section} insight={insight} />}
        <small className="audience-meta">{section.metric === 'viewers' && section.breakdown === 'country' ? t('依觀看次數 · {period} · 更新於 {date}', { period: periodLabel(insight.period), date: day(insight.fetched_at) }) : t('{period} · 更新於 {date}', { period: periodLabel(insight.period), date: day(insight.fetched_at) })}</small></>}
  </section>;
}

export function DashboardAudience({ brand, revision }: { brand: string; revision: number }) {
  const [platform, setPlatform] = useState(readPlatform);
  const [data, setData] = useState<AudienceReport | null>(null), [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    setData(null); setError('');
    api<AudienceReport>(`/dashboard/audience${brand ? `?brand_id=${brand}` : ''}`, { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) setData(value); })
      .catch(e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : t('受眾分析暫時無法讀取')); });
    return () => controller.abort();
  }, [brand, revision]);
  function select(value: AudiencePlatform) {
    const url = new URL(location.href); url.searchParams.set('audience_platform', value);
    history.replaceState(history.state, '', url); setPlatform(value);
  }
  const accounts = data?.accounts.filter(account => account.platform === platform) ?? [];
  const sections = audienceSections[platform];
  return <section className="dashboard-card dashboard-audience section-card" aria-label={t('受眾分析')}>
    <div className="card-title"><h2>{t('受眾分析')}</h2></div>
    <SegmentedControl label={t('受眾分析平台')} options={audiencePlatforms.map(value => ({ value, label: audiencePlatformNames[value] }))} value={platform} onChange={select} />
    {error ? <p className="error" role="alert">{error}</p> : !data ? <p className="empty-data">{t('正在讀取受眾分析…')}</p> : <>
      {sections.length > 0 && !accounts.length && <p className="empty-data">{t('這個品牌還沒有連結 {platform} 帳號。', { platform: audiencePlatformNames[platform] })}</p>}
      {sections.length > 0 && accounts.map(account => <div key={account.id} className="audience-account">
        {accounts.length > 1 && <h3 className="audience-account-name">{account.name}</h3>}
        <div className="audience-grid">{sections.map(section => <Section key={section.metric + section.breakdown} account={account} section={section} />)}</div>
      </div>)}
      {platformNotes(platform).map(note => <p key={note} className={sections.length ? 'audience-note' : 'audience-hint'}>{note}</p>)}
    </>}
  </section>;
}

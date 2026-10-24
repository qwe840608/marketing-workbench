import { PageHeader } from './PageHeader';
import { useEffect, useState } from 'react';
import { api, errorMessage } from '../api';
import { intents } from '../labels';
import { ReportExport } from './Exports';
import { DashboardTrend } from './DashboardTrend';
import { DashboardFunnel } from './DashboardFunnel';
import { DashboardAudience } from './DashboardAudience';
import { growthDirection, growthText } from '../growth';
import { pollWhileVisible } from '../visiblePolling';
import { t, locale } from '../i18n.ts';
import { formatTaipei } from '../time.ts';

type RankedPost = { id: number; caption: string; platform: string; reach: number; captured_at: string; thumbnail_url?: string | null };
type Summary = { week_start: string; as_of: string; new_messages: number; new_comments: number;
  previous?: { start: string; end: string; new_comments: number };
  top_intent: { intent: string; count: number } | null;
  intents: { intent: string; count: number }[]; highest_reach: RankedPost[]; lowest_reach: RankedPost[] };
const date = (value: string) => formatTaipei(value, { month: 'long', day: 'numeric' });
const number = (value: number) => value.toLocaleString(locale());

export function Dashboard({ brand, canExport, onPost }: { brand: string; canExport: boolean; onPost: (id: number) => void }) {
  const [data, setData] = useState<Summary | null>(null), [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    setData(null); setError('');
    // 分頁隱藏時暫停輪詢，回到前景立即重抓。
    return pollWhileVisible(async signal => {
      try {
        const value = await api<Summary>(`/dashboard${brand ? `?brand_id=${brand}` : ''}`, { signal });
        if (!signal.aborted) { setData(value); setError(''); }
      } catch (e) { if (!signal.aborted) setError(errorMessage(e, t('儀表板暫時無法讀取'))); }
    }, 15000);
  }, [brand, revision]);
  const most = Math.max(1, ...(data?.intents.map(x => x.count) ?? []));
  function ranking(title: string, rows: RankedPost[], className: string) {
    return <section className={'dashboard-card section-card ranking-card ' + className}><h2>{title}</h2><p className="muted">{t('本週發佈貼文 · 依最新觸及人數排序')}</p>
      {rows.length ? rows.map((post, i) => <button className="ranked-post" key={post.id} onClick={() => onPost(post.id)}>
        <span className="rank-number">0{i + 1}</span>{post.thumbnail_url && <img className="rank-thumb" src={post.thumbnail_url} alt="" loading="lazy" onError={e => { e.currentTarget.hidden = true; }} />}<span className="rank-text"><strong>{post.caption || t('無文字貼文')}</strong><small>{t('{platform} · 快照 {date}', { platform: post.platform === 'instagram' ? 'Instagram' : post.platform === 'facebook' ? 'Facebook' : t('其他平台'), date: date(post.captured_at) })}</small></span><span className="rank-reach">{number(post.reach)}<small>{t('觸及')}</small></span>
      </button>) : <p className="empty-data">{t('尚無提供觸及數據的本週貼文')}</p>}
    </section>;
  }
  return <section className="dashboard-page"><PageHeader title={t('儀表板')}>{canExport && <ReportExport brand={brand} />}<button className="secondary" onClick={() => setRevision(x => x + 1)}>{t('重新整理 ↻')}</button>
      </PageHeader>
    <p className="muted dashboard-period">{data ? t('{start}起 · 截至 {end} · 台北時間', { start: date(data.week_start), end: date(data.as_of) }) : t('本週品牌營運概況')}</p>
    {error && <p className="error" role="alert">{error}</p>}
    {!data ? !error && <p className="empty-small">{t('正在整理品牌數據…')}</p> : <>
      <div className="dashboard-kpis">
        <section className="kpi stat-tile"><span>{t('本週新留言')}</span><strong>{number(data.new_comments)}</strong>{data.previous && <small className={'kpi-compare is-' + growthDirection(data.new_comments, data.previous.new_comments)}>{t('{comparison} · 上週同期 {count} 則', { comparison: growthText(data.new_comments, data.previous.new_comments, t('上週同期')), count: number(data.previous.new_comments) })}</small>}</section>
        <section className="kpi stat-tile"><span>{t('最多人問的類別')}</span><strong className="category-kpi">{data.top_intent ? t('{intent} · {count} 則', { intent: intents[data.top_intent.intent] || t('其他'), count: number(data.top_intent.count) }) : t('尚無資料')}</strong></section></div>
      <DashboardTrend brand={brand} revision={revision} />
      <DashboardFunnel brand={brand} revision={revision} />
      <DashboardAudience brand={brand} revision={revision} />
        <section className="dashboard-card section-card"><h2>{t('客人正在問什麼')}</h2><p className="muted">{t('本週新留言的最近分流結果')}</p><div className="intent-bars list-box">{data.intents.length ? data.intents.map(row => <div key={row.intent}><div><span>{intents[row.intent] || t('其他')}</span><strong>{number(row.count)}</strong></div><span className="intent-track"><span style={{ width: `${row.count / most * 100}%` }} /></span></div>) : <p className="empty-data">{t('本週尚無新留言')}</p>}</div></section>
      <div className="dashboard-pair">{ranking(t('觸及最高的貼文'), data.highest_reach, 'highest')}{ranking(t('觸及最低的貼文'), data.lowest_reach, 'lowest')}</div>
      <p className="dashboard-definition">{t('未提供觸及的貼文不參與排名。觸及呈現內容被看見的範圍，並非成交或廣告成效。')}</p>
    </>}
  </section>;
}

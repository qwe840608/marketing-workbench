import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { api, ApiError, errorMessage } from '../api';
import { defaultFollowerSelection, followerLabels, followerWeeks, followerWeekLabel, formatDelta } from '../followers';
import type { FollowerReport } from '../followers';
import { t, locale } from '../i18n.ts';

// 粉絲數直接取自平台官方統計，可能比 App 晚更新。
const FOLLOWER_SOURCE_HINT = t('平台官方統計，可能比 App 晚更新或略有差異');

// children 放在期間與統計之間，讓頁面把自己的篩選器併入同一列，不另占一塊版面。
export function Followers({ brand, platform, revision, onLogout, children }: { brand: string; platform: string; revision: number; onLogout: () => void; children?: ReactNode }) {
  const [selection, setSelection] = useState(defaultFollowerSelection);
  const [report, setReport] = useState<FollowerReport | null>(null), [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [hintOpen, setHintOpen] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setReport(null); setLoading(true); setError('');
    const query = new URLSearchParams({ platform, year: String(selection.year), month: String(selection.month), week: String(selection.week), ...(brand ? { brand_id: brand } : {}) });
    api<FollowerReport>('/posts/followers?' + query, { signal: controller.signal }).then(value => {
      if (!controller.signal.aborted) setReport(value);
    }).catch(e => {
      if (controller.signal.aborted) return;
      if (e instanceof ApiError && e.status === 401) onLogout();
      else setError(errorMessage(e, t('粉絲數讀取失敗')));
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [brand, platform, selection, revision]);
  const weeks = followerWeeks(selection.year, selection.month);
  const years = [...new Set([defaultFollowerSelection().year, selection.year, ...(report?.years || [])])].sort((a, b) => b - a);
  const labels = report ? [report.is_current_week ? t('本週') : t('該週'), report.is_current_month ? t('本月') : t('該月')] : followerLabels(selection);
  const noun = platform === 'youtube' ? t('訂閱數') : t('粉絲數');
  const stats = [[noun, report?.current_count ?? null], [labels[0], report?.week_delta ?? null], [labels[1], report?.month_delta ?? null]] as const;
  // 增減以語意色呈現：成長綠、減少紅、無資料灰；粉絲數本身用一般文字色。
  const tone = (index: number, value: number | null) => value === null ? 'stat-empty' : index === 0 ? '' : value < 0 ? 'follower-decrease' : value > 0 ? 'follower-increase' : '';
  return <>
    {error && <div className="error" role="alert">{error}</div>}
    <section className="follower-panel section-card" aria-label={noun} aria-busy={loading}>
      {report && !report.connected ? <><p className="follower-unconnected">{t('尚未串接，串接後開始記錄{noun}', { noun })}</p>{children}</> : <>
        <div className="follower-period"><span className="follower-period-label">{t('{noun}期間', { noun })}</span><div className="follower-filter">
          <select aria-label={t('年份')} value={selection.year} onChange={e => setSelection({ ...selection, year: Number(e.target.value), week: 1 })}>
            {years.map(year => <option key={year} value={year}>{t('{year}年', { year })}</option>)}
          </select>
          <select aria-label={t('月份')} value={selection.month} onChange={e => setSelection({ ...selection, month: Number(e.target.value), week: 1 })}>
            {Array.from({ length: 12 }, (_, i) => <option key={i + 1} value={i + 1}>{t('{month}月', { month: i + 1 })}</option>)}
          </select>
          <select aria-label={t('週次')} value={selection.week} onChange={e => setSelection({ ...selection, week: Number(e.target.value) })}>
            {weeks.map(week => <option key={week.week} value={week.week} title={followerWeekLabel(week)}>{t('第{week}週', { week: week.week })}</option>)}
          </select>
        </div></div>
        {children}
        <dl className="follower-stats">{stats.map(([label, value], index) => <div key={index}><dt>{label}</dt>
          <dd className={tone(index, value)}>{index === 0 ? value === null ? '—' : value.toLocaleString(locale()) : formatDelta(value)}</dd>
          {index === 0 && <span className={'follower-hint' + (hintOpen ? ' open' : '')}>
            <button type="button" aria-label={t('{noun}說明', { noun })} aria-expanded={hintOpen} onClick={() => setHintOpen(!hintOpen)} onBlur={() => setHintOpen(false)}><span className="follower-hint-mark" aria-hidden="true" /></button>
            <span role="tooltip">{platform === 'youtube' && report?.subscriber_hidden ? t('頻道隱藏訂閱數，無法取得統計') : FOLLOWER_SOURCE_HINT}</span>
          </span>}
        </div>)}</dl>
      </>}
    </section>
  </>;
}

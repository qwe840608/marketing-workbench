import { t, locale } from './i18n.ts';

export type AudienceItem = { key: string; value: number };
export type AudienceInsight = {
  metric: 'followers' | 'viewers' | 'online'; breakdown: 'age' | 'gender' | 'country' | 'city' | 'hour';
  status: 'ready' | 'unavailable'; error: string | null; period: string; unit: 'count' | 'percent';
  items: AudienceItem[]; fetched_at: string;
};
export type AudienceAccount = { id: number; brand_id: number; platform: string; name: string; status: string; insights: AudienceInsight[] };
export type AudienceReport = { timezone: string; accounts: AudienceAccount[] };
export type AudienceSection = { metric: AudienceInsight['metric']; breakdown: AudienceInsight['breakdown'] };

export const audiencePlatforms = ['instagram', 'facebook', 'threads', 'youtube', 'tiktok', 'line'] as const;
export type AudiencePlatform = typeof audiencePlatforms[number];
export const audiencePlatformNames: Record<AudiencePlatform, string> = {
  instagram: 'Instagram', facebook: 'Facebook', threads: 'Threads', youtube: 'YouTube', tiktok: 'TikTok', line: 'LINE',
};

const followers = (...breakdowns: AudienceSection['breakdown'][]) => breakdowns.map(breakdown => ({ metric: 'followers' as const, breakdown }));
// 每個平台官方 API 能給的項目；不在清單內的由 platformNotes 說明原因。
export const audienceSections: Record<AudiencePlatform, AudienceSection[]> = {
  instagram: [...followers('age', 'gender', 'country', 'city'), { metric: 'online', breakdown: 'hour' }],
  facebook: followers('country', 'city'),
  threads: followers('age', 'gender', 'country', 'city'),
  youtube: (['age', 'gender', 'country'] as const).map(breakdown => ({ metric: 'viewers' as const, breakdown })),
  tiktok: [],
  line: [],
};

export function platformNotes(platform: AudiencePlatform): string[] {
  return {
    instagram: [t('追蹤者未滿 100 人時，Instagram 不提供受眾分布與上線時段。')],
    facebook: [t('Meta 已在 2024 年 3 月停止提供粉絲專頁追蹤者的年齡與性別，也沒有提供上線時段，所以這裡只有地區。')],
    threads: [t('追蹤者未滿 100 人時，Threads 不提供受眾分布。Threads 沒有提供追蹤者上線時段。')],
    youtube: [t('年齡與性別只計入已登入的觀眾。YouTube API 沒有提供 Studio 裡的「觀眾上線時間」。')],
    tiktok: [t('目前連結 TikTok 使用的 Display API 不提供受眾資料。官方只有 Business API 提供年齡、性別、地區與活躍時段，需要企業帳號並另外申請、通過 TikTok 審核。')],
    line: [t('工作檯的 LINE 只用來發送通知，沒有連接品牌的官方帳號，所以沒有受眾資料。')],
  }[platform];
}

export function sectionTitle(section: AudienceSection) {
  if (section.metric === 'online') return t('追蹤者上線時段');
  if (section.metric === 'viewers') return { age: t('觀眾年齡'), gender: t('觀眾性別'), country: t('觀眾國家／地區'), city: '', hour: '' }[section.breakdown];
  return { age: t('追蹤者年齡'), gender: t('追蹤者性別'), country: t('追蹤者國家／地區'), city: t('追蹤者城市'), hour: '' }[section.breakdown];
}

export function periodLabel(period: string) {
  return ({
    this_month: t('本月'), last_28_days: t('近 28 天'), last_7_days: t('近 7 天平均'), lifetime: t('目前'), day: t('最新一天'),
  } as Record<string, string>)[period] ?? period;
}

// 缺資料的原因；平台的錯誤代碼轉成可以採取行動的提示。
export function unavailableText(error: string | null) {
  if (error === 'permission_missing') return t('缺少讀取權限，請到「設定 → 平台連線」重新連結這個帳號。');
  if (error === 'not_available') return t('平台沒有提供這項資料（帳號未達門檻，例如追蹤者少於 100 人）。');
  return t('平台目前沒有回傳資料（追蹤者少於 100 人，或這段期間沒有資料）。');
}

let regions: Intl.DisplayNames | null | undefined;
function regionName(code: string) {
  if (regions === undefined) {
    try { regions = new Intl.DisplayNames([locale()], { type: 'region' }); } catch { regions = null; }
  }
  try { return (/^[A-Z]{2}$/.test(code) && regions?.of(code)) || code; } catch { return code; }
}

export function itemLabel(breakdown: AudienceSection['breakdown'], key: string) {
  if (breakdown === 'gender') return ({ F: t('女性'), female: t('女性'), M: t('男性'), male: t('男性'), U: t('未指定'), user_specified: t('未指定') } as Record<string, string>)[key] ?? key;
  if (breakdown === 'age') return key.replace(/-$/, '+');
  if (breakdown === 'country') return regionName(key);
  if (breakdown === 'hour') return t('{hour} 時', { hour: key });
  return key;
}

// 人數轉成占比；百分比資料直接用平台的數字。地區只列前幾名，所以占比以列出的合計為分母。
export function shares(items: AudienceItem[], unit: AudienceInsight['unit']) {
  const total = items.reduce((sum, item) => sum + item.value, 0);
  return items.map(item => ({ ...item, share: unit === 'percent' ? item.value : total ? item.value / total * 100 : 0 }));
}

export function peakHours(items: AudienceItem[], count = 3) {
  return [...items].filter(item => item.value > 0).sort((a, b) => b.value - a.value || Number(a.key) - Number(b.key))
    .slice(0, count).map(item => Number(item.key)).sort((a, b) => a - b);
}

export function findInsight(account: AudienceAccount, section: AudienceSection) {
  return account.insights.find(row => row.metric === section.metric && row.breakdown === section.breakdown) ?? null;
}

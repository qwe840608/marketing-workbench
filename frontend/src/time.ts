import { locale } from './i18n.ts';

// 介面一律以台北時間顯示：日期與數字格式跟著介面語言，時區固定。
export const TAIPEI = 'Asia/Taipei';

// 自訂欄位的台北時間（Intl 沒給日期／時間欄位時只顯示日期，所以呼叫端要明確指定）。
export const formatTaipei = (value: string | number | Date, options: Intl.DateTimeFormatOptions) =>
  new Intl.DateTimeFormat(locale(), { timeZone: TAIPEI, ...options }).format(new Date(value));

// 瀏覽器預設的日期＋時間寫法；hour12 省略時依語言決定 12／24 小時制。
export const taipeiDateTime = (value: string | number | Date, options: Intl.DateTimeFormatOptions = {}) =>
  new Date(value).toLocaleString(locale(), { timeZone: TAIPEI, ...options });

// 只有日期（例如 10/19）。
export const taipeiDate = (value: string | number | Date, options: Intl.DateTimeFormatOptions = {}) =>
  new Date(value).toLocaleDateString(locale(), { timeZone: TAIPEI, ...options });

// 台北日期鍵 yyyy-mm-dd，給檔名與日期篩選用，與語言無關。
export const taipeiDateKey = (value: Date = new Date()) =>
  new Intl.DateTimeFormat('en-CA', { timeZone: TAIPEI, year: 'numeric', month: '2-digit', day: '2-digit' }).format(value);

// 把 UTC 時間轉成 <input type="datetime-local"> 的值；台北沒有夏令時間，固定 +8 即可。
export const toLocalInput = (value: string) => new Date(new Date(value).getTime() + 8 * 3600000).toISOString().slice(0, 16);

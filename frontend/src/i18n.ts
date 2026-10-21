// 介面字串以繁體中文原文當鍵：繁中不查表，瀏覽器驗收的中文 locator 因此不受影響；
// 其他語言缺翻譯時退回繁中，不會出現空白或鍵名。
export type Language = 'zh-TW' | 'zh-CN' | 'en' | 'ja';
export const DEFAULT_LANGUAGE: Language = 'zh-TW';
// 選單永遠以各語言自己的寫法顯示，看不懂目前語言的人也找得到。
export const LANGUAGES: { code: Language; label: string }[] = [
  { code: 'zh-TW', label: '繁體中文' },
  { code: 'zh-CN', label: '简体中文' },
  { code: 'en', label: 'English' },
  { code: 'ja', label: '日本語' },
];
const STORAGE_KEY = 'mwb.language';
const loaders: Record<Exclude<Language, 'zh-TW'>, () => Promise<{ default: Record<string, string> }>> = {
  'zh-CN': () => import('./locales/zh-CN/index.ts'),
  en: () => import('./locales/en/index.ts'),
  ja: () => import('./locales/ja/index.ts'),
};

let current: Language = DEFAULT_LANGUAGE;
let table: Record<string, string> = {};

export const isLanguage = (value: unknown): value is Language => LANGUAGES.some(item => item.code === value);
export const language = () => current;
// 日期與數字格式跟著介面語言；時區仍由各呼叫端固定為 Asia/Taipei。
export const locale = () => current;

export function t(text: string, values?: Record<string, string | number>): string {
  const translated = table[text] ?? text;
  return values ? translated.replace(/\{(\w+)\}/g, (match, key: string) => key in values ? String(values[key]) : match) : translated;
}

// 同一段繁中在不同位置需要不同譯法時（例如英文的 Settings 與按鈕 Set）用 tx 加上情境；
// 沒有情境譯文的語言退回一般譯文，繁中仍直接顯示原文。
export function tx(context: string, text: string, values?: Record<string, string | number>): string {
  const key = `${context}|${text}`;
  return key in table ? t(key, values) : t(text, values);
}

export function storedLanguage(): Language {
  try { const value = localStorage.getItem(STORAGE_KEY); return isLanguage(value) ? value : DEFAULT_LANGUAGE; } catch { return DEFAULT_LANGUAGE; }
}

// 必須在載入任何頁面模組之前完成，模組層級的常數字串才會是正確語言。
export async function initLanguage(): Promise<void> {
  current = storedLanguage();
  if (current !== 'zh-TW') {
    try { table = (await loaders[current]()).default; } catch { current = DEFAULT_LANGUAGE; table = {}; }
  }
  document.documentElement.lang = current === 'zh-TW' ? 'zh-Hant' : current === 'zh-CN' ? 'zh-Hans' : current;
}

// 切換語言時重新載入頁面：許多標籤是模組層級常數，重新整理比逐一改成響應式簡單可靠。
export function applyLanguage(next: Language) {
  try { localStorage.setItem(STORAGE_KEY, next); } catch { /* 無法保存時只影響這一次 */ }
  if (next !== current) location.reload();
}

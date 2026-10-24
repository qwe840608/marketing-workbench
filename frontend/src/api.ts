import { t } from './i18n.ts';

// 後端錯誤訊息是固定的繁中字串，在這裡統一查翻譯表；比對特定訊息時仍用原文。
export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

// 各頁面把例外轉成可顯示的訊息：Error 取 message，其他一律用該頁的預設文字。
export const errorMessage = (error: unknown, fallback: string) => error instanceof Error ? error.message : fallback;

let csrf = '';
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  if (options.method && options.method !== 'GET') {
    if (!csrf) await refreshCsrf();
    headers.set('X-CSRF-Token', csrf);
  }
  const response = await fetch('/api' + path, { ...options, headers, credentials: 'same-origin' });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    if (response.status === 401) { csrf = ''; window.dispatchEvent(new Event('auth-expired')); }
    if (response.status === 403 && error.detail === '請先變更密碼') window.dispatchEvent(new Event('password-required'));
    throw new ApiError(response.status, typeof error.detail === 'string' ? t(error.detail) : t('連線失敗，請稍後再試'));
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}
export async function refreshCsrf() {
  csrf = (await api<{ csrf_token: string }>('/auth/csrf')).csrf_token;
}
export function setCsrf(value: string) { csrf = value; }

export async function download(path: string, filename: string, body?: unknown) {
  if (!csrf) await refreshCsrf();
  const response = await fetch('/api' + path, { method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
    body: JSON.stringify(body || {}) });
  if (!response.ok) {
    const value = await response.json().catch(() => ({}));
    if (response.status === 401) { csrf = ''; window.dispatchEvent(new Event('auth-expired')); }
    if (response.status === 403 && value.detail === '請先變更密碼') window.dispatchEvent(new Event('password-required'));
    throw new ApiError(response.status, typeof value.detail === 'string' ? t(value.detail) : t('匯出失敗，請稍後再試'));
  }
  const url = URL.createObjectURL(await response.blob()), anchor = document.createElement('a');
  anchor.href = url; anchor.download = filename; anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 60000);
}

export type User = { id: number; username: string; display_name: string; role: string; role_name?: string | null; permissions?: string[]; must_change_password: boolean; language?: string | null; brand_ids: number[] };
export type Brand = { id: number; name: string; slug: string };
export type Post = { id: number; account_id: number; external_id: string; caption: string;
  permalink: string | null; media_type: string; visibility?: string | null; published_at: string; schedule_tier: string; thumbnail_url?: string | null };
export type Metric = { id: number; captured_at: string; views: number | null; reach: number | null;
  likes: number | null; comments: number | null; shares: number | null; saves: number | null;
  avg_watch_time?: number | string | null;
  extra_json: { watch_hours?: number | null; subscribers_gained?: number | null; unavailable?: Record<string, string | number>; reposts?: number | null; quotes?: number | null;
    skip_rate?: number | null; avg_view_percentage?: number | null; retention?: number[] | null; metric_units?: Record<string, string> } };
export type Message = {
  has_text: boolean;
  id: number; text: string; direction: string; contact_name: string; sent_at: string;
  edited_at: string | null; received_at: string;
  attachments_json: { type?: string; fileName?: string }[];
  sources_json: ('webhook' | 'poll')[];
};
export type CommentSync = { state: 'idle' | 'pending' | 'running' | 'error' | 'throttled' | 'waiting' | 'stopped';
  last_completed_at: string | null; next_poll_at: string; last_error: string | null;
  last_auto_completed_at: string | null; auto_sync_enabled: boolean; window_days: number | null;
  manual_requested: boolean; progress: { comments_done: boolean; pending_replies: number; pages: number; saved_comments: number };
  wait_reason?: string | null; retry_at: string | null; usage_percent?: number | null; calls_per_hour?: number | null;
  interval_minutes: number | null; webhook_live: boolean };

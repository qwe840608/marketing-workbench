import { t } from './i18n.ts';
import { formatTaipei } from './time.ts';

const names: Record<string, string> = { gemini_api: 'Gemini', openai_api: 'OpenAI', anthropic_api: 'Anthropic' };

export function aiErrorMessage(raw: string, provider = '', retryAt: string | null = null): string {
  const autostartCode = raw.match(/autostart_unsupported|autostart_conflict|autostart_timeout|autostart_failed/)?.[0];
  if (autostartCode) return ({
    autostart_unsupported: t('僅支援 Windows'),
    autostart_conflict: t('同名排程的設定不同，請在工作排程器確認 MWB-AutoStart'),
    autostart_timeout: t('設定逾時，請確認工作排程器狀態後再試'),
    autostart_failed: t('無法更新或取得自動啟動狀態，請確認 Windows 工作排程器與帳號權限'),
  } as Record<string, string>)[autostartCode];
  // 本機 CLI 已移除；舊報告與用量紀錄裡還可能留有 cli_ 開頭的錯誤代碼，統一顯示為舊紀錄說明。
  if (/\bcli_[a-z_]+/.test(raw)) return t('本機 CLI 已不再支援（舊紀錄），請改用 API 或交給 Agent 撰寫');
  const code = raw.match(/provider_quota_free_tier|provider_quota_exhausted|provider_rate_limited|provider_time_exhausted|provider_http_\d{3}|provider_invalid_key|provider_timeout|provider_connection_error|provider_failed|generation_failed|provider_unavailable|provider_unpaid_tier|configuration_missing|monthly_budget_exceeded|incomplete_output|empty_output|input_too_large|output_too_large/)?.[0];
  if (!code) return raw;
  const name = names[provider] || t('AI 供應商');
  const status = Number(code.replace('provider_http_', ''));
  let message = '';
  if (code === 'provider_quota_free_tier') return t('Gemini 免費方案額度已用完，請到 Google AI Studio 開啟付費方案，或稍後再試');
  if (code === 'provider_quota_exhausted') return t('{name} 額度不足，請檢查供應商帳務與用量上限', { name });
  if (code === 'provider_time_exhausted') return t('模型回應逾時，請稍後再試');
  if (code === 'provider_rate_limited') {
    const value = raw.match(/provider_rate_limited;retry_after_seconds=(\d+(?:\.\d+)?(?:e[+-]?\d+)?)/i)?.[1];
    const seconds = value === undefined ? null : Number(value);
    if (!retryAt && seconds !== null && Number.isFinite(seconds)) return t('{name} 請求過於頻繁或配額已達上限，約 {seconds} 秒後可再試', { name, seconds: Math.ceil(seconds) });
    message = t('{name} 請求過於頻繁或配額已達上限', { name });
  }
  if (status === 401 || code === 'provider_invalid_key') return t('API 金鑰無效，請到 AI 設定更新');
  if (status === 403) return t('API 權限不足，請檢查金鑰與模型存取權限');
  if (status === 402) return t('API 額度不足，請檢查供應商帳務');
  if (status === 429) message = t('{name} 目前請求過多或配額已達上限', { name });
  else if (status === 503 && provider === 'gemini_api') message = t('Gemini 目前流量過高（Google 端問題）');
  else if (status === 408 || code === 'provider_timeout') message = t('{name} 回應逾時', { name });
  else if (code === 'provider_connection_error') message = t('暫時無法連線至 {name}', { name });
  else if (status >= 500) message = t('{name} 服務暫時無法使用', { name });
  if (message) {
    const date = retryAt ? new Date(retryAt) : null;
    const time = date && !Number.isNaN(date.valueOf()) ? formatTaipei(date, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }) : null;
    return time ? t('{message}，將於 {time} 自動重試', { message, time }) : t('{message}，請稍後再試', { message });
  }
  const messages: Record<string, string> = {
    configuration_missing: t('尚未設定 API 金鑰或模型，請到 AI 設定更新'),
    provider_unavailable: t('此 AI 供應商尚未開放使用，請到 AI 設定更新'),
    provider_unpaid_tier: t('Gemini 免費方案不能處理平台資料，請改用其他供應商或啟用付費方案'),
    monthly_budget_exceeded: t('本月 AI 預算已達上限，請到 AI 設定確認'),
    incomplete_output: t('模型未完成回應或內容遭拒，請調整內容後重試'),
    empty_output: t('模型未回傳文字，請稍後再試'),
    input_too_large: t('輸入文字過長，請縮短內容後重試'),
    output_too_large: t('模型回應過長，請調整需求後重試'),
    provider_failed: t('AI 執行失敗，請確認供應商設定或稍後再試'),
    generation_failed: t('AI 內容產生失敗，請確認供應商設定或稍後再試'),
  };
  return messages[code] || t('API 請求無法完成，請確認模型與輸入內容');
}

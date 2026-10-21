import test from 'node:test';
import assert from 'node:assert/strict';
import { aiErrorMessage } from '../src/aiErrors.ts';

test('自動啟動錯誤使用繁體中文，隱藏原始錯誤內容', () => {
  const cases = {
    autostart_unsupported: '僅支援 Windows',
    autostart_conflict: '同名排程的設定不同，請在工作排程器確認 MWB-AutoStart',
    autostart_timeout: '設定逾時，請確認工作排程器狀態後再試',
    autostart_failed: '無法更新或取得自動啟動狀態，請確認 Windows 工作排程器與帳號權限',
  };
  for (const [code, message] of Object.entries(cases)) {
    assert.equal(aiErrorMessage(`${code}: private-output`), message);
  }
});

test('Gemini 503 顯示 Google 問題與台北重試時間', () => {
  assert.equal(aiErrorMessage('provider_http_503', 'gemini_api'), 'Gemini 目前流量過高（Google 端問題），請稍後再試');
  assert.equal(aiErrorMessage('provider_http_503', 'gemini_api', '2026-10-01T03:05:00Z'), 'Gemini 目前流量過高（Google 端問題），將於 11:05 自動重試');
  assert.equal(aiErrorMessage('provider_http_503', 'gemini_api', 'invalid'), 'Gemini 目前流量過高（Google 端問題），請稍後再試');
});

test('暫時與永久錯誤中文化，保留無關文字', () => {
  const cases = {
    provider_http_401: 'API 金鑰無效，請到 AI 設定更新',
    provider_invalid_key: 'API 金鑰無效，請到 AI 設定更新',
    provider_http_403: 'API 權限不足，請檢查金鑰與模型存取權限',
    provider_http_402: 'API 額度不足，請檢查供應商帳務',
    provider_http_429: 'OpenAI 目前請求過多或配額已達上限，請稍後再試',
    provider_http_500: 'OpenAI 服務暫時無法使用，請稍後再試',
    provider_http_502: 'OpenAI 服務暫時無法使用，請稍後再試',
    provider_http_503: 'OpenAI 服務暫時無法使用，請稍後再試',
    provider_http_504: 'OpenAI 服務暫時無法使用，請稍後再試',
    provider_http_408: 'OpenAI 回應逾時，請稍後再試',
    provider_timeout: 'OpenAI 回應逾時，請稍後再試',
    provider_connection_error: '暫時無法連線至 OpenAI，請稍後再試',
    configuration_missing: '尚未設定 API 金鑰或模型，請到 AI 設定更新',
    monthly_budget_exceeded: '本月 AI 預算已達上限，請到 AI 設定確認',
    incomplete_output: '模型未完成回應或內容遭拒，請調整內容後重試',
  };
  for (const [code, message] of Object.entries(cases)) assert.equal(aiErrorMessage(`草稿未完成（${code}）`, 'openai_api'), message);
  assert.equal(aiErrorMessage('請重新整理'), '請重新整理');
});

test('免費額度、一般限速、帳務額度與剩餘時間不足中文化', () => {
  assert.equal(aiErrorMessage('provider_quota_free_tier;retry_after_seconds=12.08', 'gemini_api', '2026-10-01T03:05:00Z'), 'Gemini 免費方案額度已用完，請到 Google AI Studio 開啟付費方案，或稍後再試');
  assert.equal(aiErrorMessage('文字模型未完成（provider_rate_limited;retry_after_seconds=12.08）', 'gemini_api'), 'Gemini 請求過於頻繁或配額已達上限，約 13 秒後可再試');
  assert.equal(aiErrorMessage('provider_rate_limited;retry_after_seconds=50.5', 'anthropic_api'), 'Anthropic 請求過於頻繁或配額已達上限，約 51 秒後可再試');
  assert.equal(aiErrorMessage('provider_rate_limited', 'openai_api'), 'OpenAI 請求過於頻繁或配額已達上限，請稍後再試');
  assert.equal(aiErrorMessage('provider_rate_limited;retry_after_seconds=90', 'gemini_api', '2026-10-01T03:05:00Z'), 'Gemini 請求過於頻繁或配額已達上限，將於 11:05 自動重試');
  assert.equal(aiErrorMessage('provider_quota_exhausted', 'openai_api'), 'OpenAI 額度不足，請檢查供應商帳務與用量上限');
  assert.equal(aiErrorMessage('provider_time_exhausted'), '模型回應逾時，請稍後再試');
});

test('舊紀錄裡的本機 CLI 錯誤代碼顯示為已不再支援，不外露代碼', () => {
  const codes = ['cli_not_installed', 'cli_not_logged_in', 'cli_login_unknown', 'cli_disabled', 'cli_task_forbidden', 'cli_busy', 'cli_timeout', 'cli_invalid_output', 'cli_quota_exhausted', 'cli_model_unavailable', 'cli_failed', 'cli_update_failed'];
  for (const code of codes) for (const provider of ['codex_cli', 'claude_cli', 'agy_cli', '']) {
    const text = aiErrorMessage(`文字模型未完成（${code}）`, provider);
    assert.equal(text, '本機 CLI 已不再支援（舊紀錄），請改用 API 或交給 Agent 撰寫', code);
  }
  assert.equal(aiErrorMessage('請重新整理'), '請重新整理');
});

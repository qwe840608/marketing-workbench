import { t } from './i18n.ts';

// 本機 CLI 已移除。舊報告與 AI 用量紀錄的 provider 仍可能是 CLI 識別字，只用來顯示名稱。
export const agentProvider = 'agent';
const apiNames: Record<string, string> = { gemini_api: 'Gemini API', openai_api: 'OpenAI API', anthropic_api: 'Anthropic API', jev: 'jev API' };
const retiredNames: Record<string, string> = { codex_cli: 'Codex CLI', claude_cli: 'Claude Code', agy_cli: 'Antigravity' };

export function isRetiredProvider(provider: string): boolean {
  return provider in retiredNames;
}
export function executionLabel(provider: string): string {
  if (provider === agentProvider) return t('交給 Agent 撰寫');
  if (apiNames[provider]) return apiNames[provider];
  return retiredNames[provider] ? t('{name}（已停用）', { name: retiredNames[provider] }) : t('已停用的執行方式');
}

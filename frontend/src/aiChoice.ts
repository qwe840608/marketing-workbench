import { agentProvider } from './providers.ts';

type Option = { provider: string; model: string; available: boolean };

export function ideationChoiceKey(brandId: string) { return 'ideation-choice:' + brandId; }

// 順序：瀏覽器記憶 → 品牌預設 AI → 第一個可用 API → 交給 Agent 撰寫。
// 記憶或預設若是已移除的本機 CLI 或目前不可用的 API，一律略過。
export function selectIdeationChoice(options: Option[], saved: unknown, defaultProvider: string): string {
  const available = options.filter(option => option.available);
  if (saved === agentProvider) return agentProvider;
  if (typeof saved === 'string' && available.some(option => option.provider === saved)) return saved;
  const selected = available.find(option => option.provider === defaultProvider) || available[0];
  return selected?.provider || agentProvider;
}

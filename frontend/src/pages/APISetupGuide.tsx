import { t } from '../i18n.ts';

export function APISetupGuide({ canConfigure = true }: { canConfigure?: boolean }) {
  if (!canConfigure) return <p role="status" className="muted">{t('尚無可用的 AI API，請聯絡管理員。')}</p>;
  return <p role="status" className="muted">{t('尚無可用的 AI API。請由管理員前往 ')}<a href="/?view=ai">{t('AI 設定')}</a>{t(' 輸入並驗證 Gemini、OpenAI 或 Anthropic API 金鑰，再設定模型與品牌預設供應商。')}</p>;
}

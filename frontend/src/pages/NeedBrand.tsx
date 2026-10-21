import { t } from '../i18n.ts';

// 需要單一品牌的頁面在「全部可見品牌」下顯示提示；用 CSS 依寬度切換桌機（左側）與手機（上方）文字。
export function NeedBrand() {
  return <p className="notice need-brand" role="status"><span className="need-brand-wide">{t('請先在左側選擇品牌')}</span><span className="need-brand-narrow">{t('請先在上方選擇品牌')}</span></p>;
}

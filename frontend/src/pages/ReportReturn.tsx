import { reportReturn } from '../ideationNavigation';
import { t } from '../i18n.ts';
export function ReportReturn() {
  const target = reportReturn(location.search);
  return target && <a className="report-return" href={target.href}>{t('← 回到報告 #{id}', { id: target.id })}</a>;
}

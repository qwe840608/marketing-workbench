import { t } from './i18n.ts';

export const intents: Record<string, string> = { price: t('價格詢問'), booking: t('預約'), model_question: t('服務內容'), complaint: t('客訴'), cooperation: t('合作'), spam: t('垃圾訊息'), other: t('其他'), reschedule: t('改期／取消'), job: t('求職'), unclassified: t('尚未分流') };

export const platforms: Record<string, string> = { line: 'LINE', facebook: 'Facebook', instagram: 'Instagram' };

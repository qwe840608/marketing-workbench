import { t } from './i18n.ts';
import { formatTaipei } from './time.ts';

export type BackfillWait = {
  state: string;
  wait_reason?: string | null;
  retry_at: string | null;
  usage_percent?: number | null;
  calls_per_hour?: number | null;
};

export function backfillWaitText(job: BackfillWait, now = Date.now()): string | null {
  if (!['waiting', 'throttled'].includes(job.state)) return null;
  const retry = job.retry_at ? new Date(job.retry_at) : null;
  const time = retry && formatTaipei(retry, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
  const action = job.wait_reason === 'meta_unstable' || job.wait_reason === 'threads_unstable' || job.wait_reason === 'youtube_unstable' ? t('重試') : t('繼續');
  const continuation = retry && retry.getTime() > now
    ? t('將於 {time} 自動{action}', { time: time as string, action })
    : retry ? t('已到重試時間，等待排程自動{action}', { action }) : t('等待排程自動{action}', { action });
  const usage = job.usage_percent == null ? t('Meta 未提供用量') : t('Meta 實際用量 {percent}%', { percent: job.usage_percent });
  switch (job.wait_reason || 'meta_usage') {
    case 'system_budget':
      return job.calls_per_hour == null
        ? t('已達本系統每小時 Meta 呼叫上限（{usage}），{continuation}', { usage, continuation })
        : t('已達本系統每小時 {calls} 次的 Meta 呼叫上限（{usage}），{continuation}', { calls: job.calls_per_hour, usage, continuation });
    case 'meta_usage':
      return t('Meta 暫時限制呼叫（{usage}），{continuation}', { usage: job.usage_percent == null ? t('未提供用量') : t('用量 {percent}%', { percent: job.usage_percent }), continuation });
    case 'meta_unstable':
      return t('Meta 回應逾時或暫時錯誤，{continuation}', { continuation });
    case 'youtube_usage':
      return t('YouTube 暫時限制呼叫或已達每日配額，{continuation}', { continuation });
    case 'youtube_unstable':
      return t('YouTube 回應逾時或暫時錯誤，{continuation}', { continuation });
    case 'threads_usage':
      return t('Threads 暫時限制呼叫，{continuation}', { continuation });
    case 'threads_unstable':
      return t('Threads 回應逾時或暫時錯誤，{continuation}', { continuation });
    case 'work_budget':
      return t('本輪讀取已達工作預算，{continuation}', { continuation });
    case 'meta_auth':
      return t('Meta 憑證錯誤造成呼叫暫停，{continuation}', { continuation });
    default:
      return t('補抓暫時等待，{continuation}', { continuation });
  }
}

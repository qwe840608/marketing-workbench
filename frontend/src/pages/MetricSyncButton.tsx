import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../api';
import { pollWhileVisible } from '../visiblePolling';
import { t } from '../i18n.ts';

type MetricSync = { state: 'idle' | 'pending' | 'running'; finished_at: string | null; retry_after: number };

/** 排一輪貼文與成效同步。冷卻秒數由後端決定，這裡只顯示倒數；自己按的那輪跑完才通知頁面重讀。 */
export function MetricSyncButton({ onNotice, onFinished, onError }: {
  onNotice: (message: string) => void; onFinished: () => void; onError: (error: unknown) => void;
}) {
  const [sync, setSync] = useState<MetricSync | null>(null), [busy, setBusy] = useState(false);
  const [until, setUntil] = useState(0), [now, setNow] = useState(() => Date.now());
  // 只有使用者按過才在完成時重讀；每小時的排程跑完不打斷正在看的畫面。
  const waiting = useRef(false), finished = useRef<string | null>(null);
  const done = useRef(onFinished); done.current = onFinished;
  function apply(value: MetricSync) {
    setSync(value); setNow(Date.now()); setUntil(Date.now() + value.retry_after * 1000);
    if (waiting.current && value.state === 'idle' && value.finished_at !== finished.current) {
      waiting.current = false; done.current();
    }
    if (value.state === 'idle') finished.current = value.finished_at;
  }
  useEffect(() => pollWhileVisible(async signal => {
    try { apply(await api<MetricSync>('/scheduler/metrics-sync', { signal })); }
    catch { /* 狀態讀不到只是按鈕暫時停用，不蓋掉頁面上的錯誤訊息。 */ }
  }, 5000), []);
  const remaining = Math.max(0, Math.ceil((until - now) / 1000));
  useEffect(() => {
    if (!remaining) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [remaining > 0]);
  async function request() {
    setBusy(true);
    try {
      const result = await api<MetricSync & { queued: boolean }>('/scheduler/metrics-sync', { method: 'POST' });
      waiting.current = true; apply(result);
      onNotice(result.queued ? t('已排入貼文與成效同步，完成後會自動重新整理。') : t('貼文與成效正在同步，完成後會自動重新整理。'));
    } catch (error) {
      if (error instanceof ApiError && error.status === 429) {
        onNotice(error.message);
        try { apply(await api<MetricSync>('/scheduler/metrics-sync')); } catch { /* 下一輪輪詢會補上 */ }
      } else onError(error);
    } finally { setBusy(false); }
  }
  const label = sync?.state === 'running' ? t('同步中…') : sync?.state === 'pending' ? t('已排入同步…')
    : remaining ? t('立即同步（{seconds} 秒）', { seconds: remaining }) : t('立即同步');
  return <button className="secondary" disabled={busy || !sync || sync.state !== 'idle' || remaining > 0}
    title={t('向各平台抓取最新貼文與成效，每分鐘最多一次。')} onClick={() => void request()}>{label}</button>;
}

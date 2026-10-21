/** 每次重新可見都建立新請求生命週期，隱藏時舊回應不能覆寫畫面。 */
export function pollWhileVisible(refresh: (signal: AbortSignal) => Promise<void>, milliseconds: number) {
  let controller: AbortController | null = null;
  let timer: ReturnType<typeof window.setInterval> | undefined;
  function stop() {
    controller?.abort(); controller = null;
    window.clearInterval(timer); timer = undefined;
  }
  function start() {
    stop();
    if (document.visibilityState !== 'visible') return;
    const current = new AbortController(); controller = current;
    let running = false;
    async function tick() {
      if (running || current.signal.aborted || document.visibilityState !== 'visible') return;
      running = true;
      try { await refresh(current.signal); }
      finally { running = false; }
    }
    void tick(); timer = window.setInterval(tick, milliseconds);
  }
  document.addEventListener('visibilitychange', start);
  start();
  return () => { stop(); document.removeEventListener('visibilitychange', start); };
}

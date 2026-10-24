import { useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { download, errorMessage } from '../api';
import { t } from '../i18n.ts';
import { taipeiDateKey } from '../time.ts';

const today = () => taipeiDateKey();
export function ReportExport({ brand }: { brand: string }) {
  const dialog = useRef<HTMLDialogElement>(null), trigger = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [start, setStart] = useState(today().slice(0, 7) + '-01'), [end, setEnd] = useState(today());
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  async function save() {
    setBusy(true); setError('');
    try { await download('/exports/report/docx', t('營運報表_{start}_{end}.docx', { start, end }), { brand_id: Number(brand), start, end }); }
    catch (e) { setError(errorMessage(e, t('匯出失敗'))); }
    finally { setBusy(false); }
  }
  return <><button className="secondary" ref={trigger} aria-haspopup="dialog" aria-expanded={open} onClick={() => { dialog.current?.showModal(); setOpen(true); }}>{t('匯出報表')}</button>
    {createPortal(<dialog className="app-dialog report-export" ref={dialog} aria-labelledby="report-export-title" onClose={() => { setOpen(false); trigger.current?.focus(); }} onClick={e => {
      const bounds = e.currentTarget.getBoundingClientRect();
      if (e.target === e.currentTarget && (e.clientX < bounds.left || e.clientX > bounds.right || e.clientY < bounds.top || e.clientY > bounds.bottom)) e.currentTarget.close();
    }} onKeyDown={e => {
      if (e.key !== 'Tab') return;
      const controls = e.currentTarget.querySelectorAll<HTMLButtonElement | HTMLInputElement>('button:not(:disabled), input:not(:disabled)');
      const first = controls[0], last = controls[controls.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
    }}>
    <div className="sheet-heading"><h2 id="report-export-title">{t('匯出報表')}</h2><button className="secondary" onClick={() => dialog.current?.close()}>{t('關閉')}</button></div>
    <div className="sheet-content"><p className="muted">{t('先選擇單一品牌。統計包含起訖日，依台北時間計算。')}</p>
    <form onSubmit={e => { e.preventDefault(); void save(); }}><label>{t('開始日期')}<input type="date" required value={start} max={end} onChange={e => setStart(e.target.value)} /></label><label>{t('結束日期')}<input type="date" required min={start} value={end} onChange={e => setEnd(e.target.value)} /></label><button className="primary" disabled={!brand || busy}>{busy ? t('正在匯出…') : t('下載 Word 報表 ↓')}</button></form>
    {error && <p className="error" role="alert">{error}</p>}
    </div></dialog>, document.body)}</>;
}

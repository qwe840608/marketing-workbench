import { type ReactNode, useEffect, useId, useRef } from 'react';
import { t } from '../i18n.ts';

// heading＋children 供需要結構化內容的確認（例如發佈前逐平台列出）；一般確認只用 message。
export function ConfirmDialog({ message, heading, children, confirmLabel, onConfirm, onClose, danger = false }: {
  message?: string; heading?: string; children?: ReactNode; confirmLabel: string; onConfirm: () => void; onClose: () => void; danger?: boolean;
}) {
  const dialog = useRef<HTMLDivElement>(null);
  const title = useId();
  useEffect(() => {
    const trigger = document.activeElement as HTMLElement | null;
    dialog.current?.querySelector<HTMLButtonElement>('[data-cancel]')?.focus();
    return () => { if (trigger?.isConnected) trigger.focus(); };
  }, []);
  return <div className="ideation-modal-backdrop" onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div ref={dialog} className="ideation-delete-dialog" role="dialog" aria-modal="true" aria-labelledby={title} onKeyDown={event => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); onClose(); }
      if (event.key !== 'Tab') return;
      event.stopPropagation();
      const buttons = dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex="0"]');
      if (!buttons?.length) return;
      if (event.shiftKey && document.activeElement === buttons[0]) { event.preventDefault(); buttons[buttons.length - 1].focus(); }
      else if (!event.shiftKey && document.activeElement === buttons[buttons.length - 1]) { event.preventDefault(); buttons[0].focus(); }
    }}>
      {heading ? <h2 id={title} className="confirm-heading">{heading}</h2> : <p id={title}>{message}</p>}
      {children}
      <div className="action-row"><button className="secondary" data-cancel onClick={onClose}>{t('取消')}</button><button className={danger ? 'primary danger' : 'primary'} onClick={onConfirm}>{confirmLabel}</button></div>
    </div>
  </div>;
}

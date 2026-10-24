import { useEffect, useId, useRef } from 'react';
import { createPortal } from 'react-dom';
import { t } from '../i18n.ts';
import './guide-dialog.css';

// 完整貼文視窗：沿用設定教學視窗的版面、焦點進出與 Tab 循環。
export function PostDialog({ eyebrow, timing, caption, thumbnail, permalink, onClose }: {
  eyebrow: string; timing: string; caption: string; thumbnail: string | null; permalink: string | null; onClose: () => void;
}) {
  const dialog = useRef<HTMLDivElement>(null);
  const title = useId();
  useEffect(() => {
    const trigger = document.activeElement as HTMLElement | null;
    dialog.current?.querySelector<HTMLButtonElement>('[data-close]')?.focus();
    return () => { if (trigger?.isConnected) trigger.focus(); };
  }, []);
  return createPortal(<div className="ideation-modal-backdrop" onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div ref={dialog} className="guide-dialog post-full-dialog" role="dialog" aria-modal="true" aria-labelledby={title} onKeyDown={event => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); onClose(); }
      if (event.key !== 'Tab') return;
      event.stopPropagation();
      const focusable = dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], [tabindex="0"]');
      if (!focusable?.length) return;
      if (event.shiftKey && document.activeElement === focusable[0]) { event.preventDefault(); focusable[focusable.length - 1].focus(); }
      else if (!event.shiftKey && document.activeElement === focusable[focusable.length - 1]) { event.preventDefault(); focusable[0].focus(); }
    }}>
      <div className="guide-heading"><h2 id={title}>{t('完整貼文')}</h2><button className="secondary" type="button" data-close onClick={onClose}>{t('關閉')}</button></div>
      <div className="guide-body" tabIndex={0}>
        <p className="eyebrow">{eyebrow}</p>
        {thumbnail && <img className="post-full-image" src={thumbnail} alt={t('貼文圖片預覽')} onError={e => { e.currentTarget.hidden = true; }} />}
        <p className="post-full-caption">{caption || t('無文字貼文')}</p>
        <p className="post-timing">{timing}</p>
        {permalink && <a className="post-link" href={permalink} target="_blank" rel="noreferrer">{t('開啟原始貼文 ↗')}</a>}
      </div>
    </div>
  </div>, document.body);
}

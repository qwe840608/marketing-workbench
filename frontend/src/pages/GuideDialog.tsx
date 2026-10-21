import { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { t } from '../i18n.ts';
import { type GuideContext, type PlatformGuide, resolveGuideValue } from '../platformGuides';
import './guide-dialog.css';

function CopyBlock({ value }: { value: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  // 非安全來源沒有 navigator.clipboard，存取時會同步拋錯，所以整段放進 try。
  async function copy() {
    window.clearTimeout(timer.current);
    try { await navigator.clipboard.writeText(value); setState('copied'); }
    catch { setState('failed'); return; }
    timer.current = window.setTimeout(() => setState('idle'), 2000);
  }
  return <><div className="oauth-callback guide-copy"><code>{value || t('尚未設定')}</code><button className="secondary" type="button" disabled={!value} onClick={() => void copy()}>{state === 'copied' ? t('已複製') : t('複製')}</button></div>
    {state === 'failed' && <p className="notice danger" role="alert">{t('無法複製，請手動選取內容')}</p>}</>;
}

// 站內彈出的設定教學；沿用 ConfirmDialog 的 backdrop、焦點進出與 Tab 循環慣例。
export function GuideDialog({ guide, context, onClose }: { guide: PlatformGuide; context: GuideContext; onClose: () => void }) {
  const dialog = useRef<HTMLDivElement>(null);
  const title = useId();
  useEffect(() => {
    const trigger = document.activeElement as HTMLElement | null;
    dialog.current?.querySelector<HTMLButtonElement>('[data-close]')?.focus();
    return () => { if (trigger?.isConnected) trigger.focus(); };
  }, []);
  // 掛在 body 上，避免繼承設定卡片內的標題與按鈕樣式。
  return createPortal(<div className="ideation-modal-backdrop" onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div ref={dialog} className="guide-dialog" role="dialog" aria-modal="true" aria-labelledby={title} onKeyDown={event => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); onClose(); }
      if (event.key !== 'Tab') return;
      event.stopPropagation();
      const focusable = dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], summary, [tabindex="0"]');
      if (!focusable?.length) return;
      if (event.shiftKey && document.activeElement === focusable[0]) { event.preventDefault(); focusable[focusable.length - 1].focus(); }
      else if (!event.shiftKey && document.activeElement === focusable[focusable.length - 1]) { event.preventDefault(); focusable[0].focus(); }
    }}>
      <div className="guide-heading"><h2 id={title}>{guide.title}</h2><button className="secondary" type="button" data-close onClick={onClose}>{t('關閉')}</button></div>
      <div className="guide-body" tabIndex={0}>
        <div className="guide-intro">
          <p className="guide-time">{t('大約需要 {minutes} 分鐘', { minutes: guide.minutes })}</p>
          <h3>{t('開始前你需要')}</h3>
          <ul>{guide.needs.map((need, index) => <li key={index}>{need}</li>)}</ul>
        </div>
        {guide.sections.map((section, index) => <section key={index}>
          {section.heading && <h3>{section.heading}</h3>}
          <ol className="guide-steps">{section.steps.map((step, number) => <li key={number}><div className="guide-step">
            <p>{step.text}</p>
            {step.links && <p className="guide-links">{step.links.map(item => <a key={item.url} href={item.url} target="_blank" rel="noopener noreferrer">{item.label} ↗</a>)}</p>}
            {step.values?.map((value, position) => <CopyBlock key={position} value={resolveGuideValue(value, context)} />)}
            {step.check && <p className="notice success guide-note"><strong>{t('✅ 完成後會看到')}</strong> {step.check}</p>}
          </div></li>)}</ol>
        </section>)}
        {guide.faq.length > 0 && <details className="guide-faq"><summary>{t('⚠️ 卡關了？常見問題')}</summary>
          <ul>{guide.faq.map((item, index) => <li key={index}>{item}</li>)}</ul>
        </details>}
      </div>
    </div>
  </div>, document.body);
}

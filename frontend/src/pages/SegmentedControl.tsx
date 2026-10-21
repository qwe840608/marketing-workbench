import { useRef } from 'react';
import './segmented-control.css';

type Option<T extends string> = { value: T; label: string };

export function SegmentedControl<T extends string>({ label, options, value, disabled, compact = false, onChange }: {
  label: string; options: readonly Option<T>[]; value: T; disabled?: boolean; compact?: boolean; onChange: (value: T) => void;
}) {
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  // 值不在選項內（例如日期篩選的自訂期間）時，仍讓第一個選項可用 Tab 進入。
  const focusable = options.some(option => option.value === value) ? value : options[0]?.value;
  return <div className={'segmented-control' + (compact ? ' compact' : '')} role="radiogroup" aria-label={label}>
    {options.map((option, index) => <button key={option.value} ref={el => { buttons.current[index] = el; }}
      type="button" role="radio" aria-checked={value === option.value} tabIndex={focusable === option.value ? 0 : -1}
      disabled={disabled} onClick={() => onChange(option.value)} onKeyDown={event => {
        const offset = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 0;
        if (!offset && event.key !== 'Home' && event.key !== 'End') return;
        event.preventDefault();
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1 : (index + offset + options.length) % options.length;
        onChange(options[next].value); buttons.current[next]?.focus();
      }}>{option.label}</button>)}
  </div>;
}

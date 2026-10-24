import { useState } from 'react';
import { api, errorMessage } from '../api';
import type { User } from '../api';
import { applyLanguage, isLanguage, language, LANGUAGES, t } from '../i18n.ts';

// 登入前只記在這台瀏覽器；登入後同時存到帳號，換裝置也維持同一種語言。
export function LanguagePicker({ className = '', account = false }: { className?: string; account?: boolean }) {
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  async function change(value: string) {
    if (!isLanguage(value)) return;
    setError('');
    if (account) {
      setBusy(true);
      try { await api<User>('/auth/language', { method: 'PUT', body: JSON.stringify({ language: value }) }); }
      catch (e) { setError(errorMessage(e, t('語言儲存失敗'))); setBusy(false); return; }
    }
    applyLanguage(value);
  }
  return <div className={'language-picker ' + className}>
    <label><span>{t('介面語言')}</span><select value={language()} disabled={busy} onChange={event => void change(event.target.value)}>
      {LANGUAGES.map(item => <option key={item.code} value={item.code} lang={item.code}>{item.label}</option>)}
    </select></label>
    {error && <p className="notice danger" role="alert">{error}</p>}
  </div>;
}

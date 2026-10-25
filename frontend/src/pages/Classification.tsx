import { useEffect, useState, useRef } from 'react';
import { api, errorMessage } from '../api';
import type { Brand } from '../api';
import { intents } from '../labels';
import { t } from '../i18n.ts';

export function ClassificationSettings({ brands, brand, canEdit }: { brands: Brand[]; brand: string; canEdit: boolean }) {
  const brandId = brand || String(brands[0]?.id || '');
  return <section className="settings-page classification-settings">
    {brandId && <IntentNotesEditor key={brandId} brandId={brandId} canEdit={canEdit} />}
  </section>;
}

const intentFields = [
  ['price', t('服務價格、報價、費用與折扣')], ['booking', t('新預約、接案與可安排時段')],
  ['reschedule', t('變更、延期或取消既有預約與訂單')], ['model_question', t('服務內容、方案、流程、交付物與規格')],
  ['complaint', t('服務不滿、未履行承諾與問題處理')], ['cooperation', t('商業合作、聯合推廣與轉介')],
  ['job', t('職缺、招募與應徵')], ['spam', t('垃圾廣告、詐騙與無關推銷')],
  ['other', t('問候、致謝或無法歸類的需求')],
] as const;
type IntentNotes = Record<typeof intentFields[number][0], string> & { version: number };

function IntentNotesEditor({ brandId, canEdit }: { brandId: string; canEdit: boolean }) {
  const [data, setData] = useState<IntentNotes | null>(null);
  const [error, setError] = useState(''), [notice, setNotice] = useState(''), [busy, setBusy] = useState(false);
  const mounted = useRef(true);
  useEffect(() => {
    const controller = new AbortController(); mounted.current = true;
    api<IntentNotes>('/classifications/intents?brand_id=' + brandId, { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) setData(value); })
      .catch(e => { if (!controller.signal.aborted) setError(e.message); });
    return () => { mounted.current = false; controller.abort(); };
  }, [brandId]);
  async function save(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError(''); setNotice('');
    try {
      const value = await api<IntentNotes>('/classifications/intents?brand_id=' + brandId, { method: 'PUT', body: JSON.stringify(data) });
      if (mounted.current) { setData(value); setNotice(t('類別說明已儲存')); }
    } catch (e) { if (mounted.current) setError(errorMessage(e, t('儲存失敗'))); }
    finally { if (mounted.current) setBusy(false); }
  }
  return <section className="settings-section section-card intent-notes" aria-labelledby="intent-notes-title" aria-busy={busy}>
    <h2 id="intent-notes-title">{t('類別說明')}</h2>
    <p className="muted">{t('AI 會自動判斷粉絲在各平台貼文下的留言（含留言回覆）屬於哪一類；私訊、品牌自己的回覆和 CSV 匯入的留言不分類。分類結果用在儀表板的「客人正在問什麼」、Agent 查詢熱門問題，以及客訴與緊急留言的 LINE 通知。')}</p>
    <p className="muted">{t('每個類別可以補充這個品牌常見的說法或例子，AI 判斷時會一併參考；留空就照預設定義判斷。')}</p>
    {data && <form onSubmit={event => void save(event)}>
      <div className="intent-notes-fields">{intentFields.map(([key, placeholder]) => <label key={key}>
        <span>{intents[key]}</span><input value={data[key]} placeholder={placeholder} maxLength={200} disabled={!canEdit || busy} onChange={event => { setData({ ...data, [key]: event.target.value }); setNotice(''); }} />
      </label>)}</div>
      {canEdit && <button className="primary" disabled={busy}>{busy ? t('儲存中…') : t('儲存')}</button>}
    </form>}
    {error && <p className="error" role="alert">{error}</p>}{notice && <p className="notice success" role="status">{notice}</p>}
  </section>;
}

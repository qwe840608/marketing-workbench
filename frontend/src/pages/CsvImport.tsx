import { useEffect, useState } from 'react';
import { api } from '../api';
import { platforms } from '../labels';
import './csv-import.css';
import { locale, t } from '../i18n.ts';

type Account = { id: number; platform: string; name: string };
type Column = { column: string; header: string; field: string | null; suggested?: string; confidence: number | null; method: string; samples: string[] };
type Preview = { token: string; columns: Column[]; fields: Record<string, string>; total: number; fallback: string | null };
type RowError = { row: number; reason: string };
type Validation = { revision: string; valid: number; total: number; errors: RowError[]; samples: { row: number; text: string; kind: string; sent_at: string; source_ref: string }[] };
type Result = { created: number; duplicates: number; total: number; errors: RowError[] };

export function CsvImport({ brandId, canEdit }: { brandId: string; canEdit: boolean }) {
  const [accounts, setAccounts] = useState<Account[]>([]), [selected, setSelected] = useState<Record<string, number>>({});
  const [file, setFile] = useState<File | null>(null), [preview, setPreview] = useState<Preview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({}), [validated, setValidated] = useState<Validation | null>(null);
  const [result, setResult] = useState<Result | null>(null), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    if (brandId && canEdit) api<Account[]>('/csv/accounts?brand_id=' + brandId, { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) setAccounts(value); })
      .catch(e => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [brandId, canEdit]);
  function invalidate() { setValidated(null); setConfirmed(false); setResult(null); setError(''); }
  async function upload() {
    if (!file) return;
    setBusy(true); setError(''); setPreview(null); invalidate();
    try {
      if (file.size > 2 * 1024 * 1024) throw new Error(t('檔案上限為 2 MB'));
      const bytes = new Uint8Array(await file.arrayBuffer());
      try { new TextDecoder('utf-8', { fatal: true }).decode(bytes); }
      catch { throw new Error(t('請使用 UTF-8，Excel 請另存 CSV UTF-8')); }
      let binary = '';
      for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
      const value = await api<Preview>('/csv/preview', { method: 'POST', body: JSON.stringify({ brand_id: Number(brandId), filename: file.name, content_base64: btoa(binary) }) });
      setPreview(value); setMapping(Object.fromEntries(value.columns.map(c => [c.column, c.field || ''])));
    } catch (e) { setError(e instanceof Error ? e.message : t('上傳失敗')); }
    finally { setBusy(false); }
  }
  async function validate() {
    if (!preview) return;
    setBusy(true); invalidate();
    try { setValidated(await api<Validation>('/csv/validate', { method: 'POST', body: JSON.stringify({ token: preview.token, columns: mapping, accounts: selected }) })); }
    catch (e) { setError(e instanceof Error ? e.message : t('預覽失敗')); }
    finally { setBusy(false); }
  }
  async function commit() {
    if (!preview || !validated || !confirmed) return;
    setBusy(true); setError('');
    try { setResult(await api<Result>('/csv/confirm', { method: 'POST', body: JSON.stringify({ token: preview.token, revision: validated.revision }) })); }
    catch (e) { setError(e instanceof Error ? e.message : t('匯入失敗，請重試')); }
    finally { setBusy(false); }
  }
  const errors = result?.errors || validated?.errors || [];
  return <section className="settings-section workspace-subsection csv-import" aria-label={t('匯入歷史資料')}>
    <h3>{t('匯入歷史資料')}</h3>
    <p className="muted">{t('CSV UTF-8 · 最多 2 MB／5000 列。無時區的時間視為台北時間。匯入後不產生通知。')}</p>
    {!canEdit ? <p>{t('此帳號僅能檢視資料，請由管理員或行銷人員匯入。')}</p> : <>
      <p>{t('1. 上傳檔案 → 2. 確認欄位與帳號 → 3. 預覽並匯入')}</p>
      <label>{t('歷史資料檔案')}<input type="file" accept=".csv,text/csv" disabled={busy || !brandId} onChange={e => { setFile(e.target.files?.[0] || null); setPreview(null); invalidate(); }} /></label>
      <p className="muted">{t('Excel 請選「CSV UTF-8」。只匯入粉絲入站留言；必填平台、類型、外部 ID、時間、內文。若沒有對話 ID，將各列建立為獨立匯入紀錄。')}</p>
      <button className="primary" disabled={!file || busy || !brandId} onClick={() => void upload()}>{busy ? t('處理中…') : t('讀取 CSV 欄位')}</button>
      {preview && !result && <>
        <h3>{t('欄位對應 · 共 {total} 列', { total: preview.total })}</h3>
        {preview.fallback && <p className="warning">{preview.fallback}</p>}
        <p className="muted">{t('預覽保留十五分鐘。信心低於 80% 不自動採用，請選擇用途或明確忽略。更改對應後需重新預覽。')}</p>
        <div className="csv-columns">{preview.columns.map(column => <div className="csv-column" key={column.column}>
          <label>{t('第 {index} 欄：{header}', { index: Number(column.column) + 1, header: column.header })}<select aria-label={t('欄位用途 {header}', { header: column.header })} value={mapping[column.column] || ''} disabled={busy} onChange={e => { setMapping({ ...mapping, [column.column]: e.target.value }); invalidate(); }}>
            <option value="">{t('請人工選擇')}</option>{Object.entries(preview.fields).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select></label>
          <p className="muted">{column.method === 'jev' ? t('AI 建議') : column.method} · {column.confidence === null ? t('尚無信心分數') : t('信心 {percent}%', { percent: Math.round(column.confidence * 100) })}{column.suggested && t(' · 建議：{field}', { field: preview.fields[column.suggested] })}</p>
          {column.samples.map((sample, index) => <p className="csv-sample" key={index}>{sample || t('（空白）')}</p>)}
        </div>)}</div>
        <h3>{t('匯入帳號')}</h3>
        <p className="muted">{t('依 CSV 內的平台選擇此品牌的既有帳號，未出現的平台可不選。來源網址不會用來自動猜測貼文；如有貼文 ID 請對應該欄。')}</p>
        <div className="policy-grid">{Object.entries(platforms).filter(([key]) => accounts.some(a => a.platform === key)).map(([key, label]) => <label key={key}>{t('{platform} 匯入帳號', { platform: label })}<select aria-label={t('{platform} 匯入帳號', { platform: label })} disabled={busy} value={selected[key] || ''} onChange={e => { const next = { ...selected }; if (e.target.value) next[key] = Number(e.target.value); else delete next[key]; setSelected(next); invalidate(); }}>
          <option value="">{t('請選擇')}</option>{accounts.filter(a => a.platform === key).map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select></label>)}</div>
        {!accounts.length && <p>{t('此品牌尚無可匯入的帳號，請先由管理員建立。')}</p>}
        <button className="primary" disabled={busy || Object.values(mapping).some(v => !v) || !Object.keys(selected).length} onClick={() => void validate()}>{t('驗證並預覽資料')}</button>
      </>}
      {validated && !result && <div className="csv-validation">
        <h3>{t('匯入前預覽')}</h3><p>{t('格式有效 {valid} 列／共 {total} 列。重複與來源衝突於確認時比對現存資料。', { valid: validated.valid, total: validated.total })}</p>
        {validated.samples.map(sample => <article className="csv-sample" key={sample.row}><strong>{t('第 {row} 列 · {kind}', { row: sample.row, kind: sample.kind })}</strong><p>{t('{time}（台北）', { time: new Date(sample.sent_at).toLocaleString(locale(), { timeZone: 'Asia/Taipei' }) })}</p><p>{sample.text}</p><p className="muted">{sample.source_ref}</p></article>)}
        <label><input type="checkbox" checked={confirmed} disabled={busy} onChange={e => setConfirmed(e.target.checked)} />{t('我已核對品牌、帳號與資料，僅匯入有效列')}</label>
        <button className="primary" disabled={busy || !confirmed || !validated.valid} onClick={() => void commit()}>{t('確認匯入歷史資料')}</button>
      </div>}
      {result && <div role="status" className="success-note notice success"><h3>{t('匯入完成')}</h3><p>{t('新增 {created} 列、重複略過 {duplicates} 列、錯誤 {errors} 列。', { created: result.created, duplicates: result.duplicates, errors: result.errors.length })}</p></div>}
      {!!errors.length && <details open className="csv-errors"><summary>{t('錯誤列與原因（{count} 列）', { count: errors.length })}</summary><ul>{errors.map((item, index) => <li key={index}>{t('第 {row} 列：{reason}', { row: item.row, reason: item.reason })}</li>)}</ul></details>}
    </>}
    {error && <p className="error" role="alert">{error}</p>}
  </section>;
}

import { useEffect, useId, useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { api, errorMessage } from '../api';
import type { Brand, User } from '../api';
import { ConfirmDialog } from './ConfirmDialog';
import './members.css';
import { t } from '../i18n.ts';
import { taipeiDateTime } from '../time.ts';
import { permissionLabel, roleLabel } from '../permissions';

type Member = User & { active: boolean; last_login_at: string | null; connection_count: number };
export type Role = { id: number | null; key: string; name: string | null; builtin: boolean; permissions: string[]; member_count: number };
type RoleCatalog = { permissions: string[]; roles: Role[] };
// 送出發佈一定要能編輯草稿（後端 roles.REQUIRES 同一規則）。
const REQUIRES: Record<string, string> = { 'publish.submit': 'publish.edit' };

export const roleSummary = (role: Role) => role.key === 'admin' ? t('全部功能與全部品牌，並可管理成員與角色')
  : role.permissions.length ? role.permissions.map(permissionLabel).join(t('、')) : t('只能檢視資料');
type PasswordResult = { member: Member; temporary_password: string };

export function MemberDialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null), id = useId();
  useEffect(() => {
    const trigger = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>('input,button,[tabindex="0"]')?.focus();
    return () => { if (trigger?.isConnected) trigger.focus(); };
  }, []);
  return <div className="ideation-modal-backdrop" onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
    <div className="ideation-delete-dialog member-dialog" ref={ref} role="dialog" aria-modal="true" aria-labelledby={id} onKeyDown={e => {
      if (e.key === 'Escape') { e.preventDefault(); onClose(); }
      if (e.key !== 'Tab') return;
      const controls = ref.current?.querySelectorAll<HTMLElement>('input:not(:disabled),button:not(:disabled):not([tabindex="-1"]),select:not(:disabled),[tabindex="0"]');
      if (!controls?.length) return;
      const first = controls[0], last = controls[controls.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }}><h2 id={id}>{title}</h2>{children}</div>
  </div>;
}

export function TemporaryPasswordDialog({ password, onClose }: { password: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false), [error, setError] = useState('');
  return <MemberDialog title={t('臨時密碼')} onClose={onClose}>
    <div className="temporary-password-row"><code className="temporary-password">{password}</code><button className="secondary" onClick={async () => { try { await navigator.clipboard.writeText(password); setCopied(true); } catch { setError(t('無法複製，請手動選取密碼')); } }}>{copied ? t('已複製') : t('複製')}</button></div>
    <p className="muted">{t('只會顯示這一次，請轉交給對方；對方第一次登入時需改密碼')}</p>
    {error && <p className="notice danger" role="alert">{error}</p>}
    <div className="action-row"><button className="secondary" onClick={onClose}>{t('關閉')}</button></div>
  </MemberDialog>;
}

export function Members({ brands, currentUserId, onUserChanged, onSelfReset }: { brands: Brand[]; currentUserId: number; onUserChanged: () => void; onSelfReset: (password: string) => void }) {
  const [revoking, setRevoking] = useState<Member | null>(null), [revokingBusy, setRevokingBusy] = useState(false);
  const [rows, setRows] = useState<Member[]>([]), [loading, setLoading] = useState(true), [error, setError] = useState('');
  const [catalog, setCatalog] = useState<RoleCatalog>({ permissions: [], roles: [] });
  const [editing, setEditing] = useState<Member | 'new' | null>(null), [temporary, setTemporary] = useState<string | null>(null);
  async function load() {
    try { const [members, roles] = await Promise.all([api<Member[]>('/members'), api<RoleCatalog>('/roles')]); setRows(members); setCatalog(roles); }
    catch (e) { setError(errorMessage(e, t('載入失敗'))); } finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, []);
  function saved(result?: PasswordResult) {
    setEditing(null);
    if (result?.member.id === currentUserId) { onSelfReset(result.temporary_password); return; }
    if (result) setTemporary(result.temporary_password);
    void load(); onUserChanged();
  }
  return <section className="section-card members-card" aria-busy={loading}>
    <div className="member-card-heading"><h2>{t('成員')}</h2><button className="primary" onClick={() => setEditing('new')}>{t('新增成員')}</button></div>
    {error && <p className="notice danger" role="alert">{error}</p>}
    <div className="list-box member-list">{rows.map(member => <div className="list-row member-row" key={member.id}>
      <div className="member-name"><strong>{member.display_name}</strong><span>{member.username}</span></div>
      <span className="status-badge neutral">{roleLabel(member.role, member.role_name)}</span>
      <span className="member-brands" title={member.role === 'admin' ? t('全部品牌') : brands.filter(b => member.brand_ids.includes(b.id)).map(b => b.name).join(t('、'))}>{member.role === 'admin' ? t('全部品牌') : brands.filter(b => member.brand_ids.includes(b.id)).map(b => b.name).join(t('、')) || t('未指派品牌')}</span>
      <div className="member-status"><span className={'status-badge ' + (member.active ? 'ready' : 'neutral')}>{member.active ? t('啟用') : t('停用')}</span>{member.must_change_password && <span className="status-badge pending">{t('須改密碼')}</span>}</div>
      <div className="member-connections"><span>{t('Agent 連線 {count} 個', { count: member.connection_count })}</span><button className="secondary" disabled={!member.connection_count || revokingBusy} onClick={() => setRevoking(member)}>{t('撤銷全部 Agent 連線')}</button></div>
      <button className="secondary" onClick={() => setEditing(member)}>{t('編輯')}</button>
    </div>)}{!rows.length && <p className="muted">{loading ? t('載入中…') : t('尚無成員')}</p>}</div>
    {editing && <MemberEditor key={editing === 'new' ? 'new' : editing.id} member={editing === 'new' ? null : editing} brands={brands} roles={catalog.roles} onClose={() => setEditing(null)} onSaved={saved} />}
    {temporary !== null && <TemporaryPasswordDialog password={temporary} onClose={() => setTemporary(null)} />}
    {revoking && <ConfirmDialog message={t('撤銷 {name} 的全部 Agent 連線？', { name: revoking.display_name })} confirmLabel={t('撤銷全部 Agent 連線')} onClose={() => setRevoking(null)} onConfirm={() => { const identity = revoking.id; setRevoking(null); setRevokingBusy(true); void api(`/members/${identity}/revoke-connections`, { method: 'POST' }).then(() => load()).catch(e => setError(errorMessage(e, t('撤銷失敗')))).finally(() => setRevokingBusy(false)); }} />}
    <Roles catalog={catalog} onChanged={() => { void load(); onUserChanged(); }} />
  </section>;
}

function Roles({ catalog, onChanged }: { catalog: RoleCatalog; onChanged: () => void }) {
  const [editing, setEditing] = useState<Role | 'new' | null>(null), [deleting, setDeleting] = useState<Role | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  return <div className="member-roles">
    <div className="member-card-heading"><div><h2>{t('角色')}</h2><p className="muted">{t('勾選每個角色能使用的功能；內建角色不能修改。成員管理只限管理員。')}</p></div><button className="secondary" onClick={() => setEditing('new')}>{t('新增角色')}</button></div>
    {error && <p className="notice danger" role="alert">{error}</p>}
    <div className="list-box role-list">{catalog.roles.map(role => <div className="list-row role-row" key={role.key}>
      <div className="role-name"><strong>{roleLabel(role.key, role.name)}</strong>{role.builtin && <span className="status-badge neutral">{t('內建')}</span>}</div>
      <span className="role-permissions">{roleSummary(role)}</span>
      <span className="role-count">{t('{count} 位成員', { count: role.member_count })}</span>
      <div className="action-row">{!role.builtin && <><button className="secondary" disabled={busy} onClick={() => setEditing(role)}>{t('編輯')}</button><button className="secondary" disabled={busy || role.member_count > 0} title={role.member_count > 0 ? t('仍有成員使用此角色，請先改成其他角色') : undefined} onClick={() => setDeleting(role)}>{t('刪除')}</button></>}</div>
    </div>)}</div>
    {editing && <RoleEditor role={editing === 'new' ? null : editing} permissions={catalog.permissions} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); onChanged(); }} />}
    {deleting && <ConfirmDialog message={t('刪除角色「{name}」？', { name: deleting.name || '' })} confirmLabel={t('確認刪除')} danger onClose={() => setDeleting(null)} onConfirm={() => {
      const role = deleting; setDeleting(null); setBusy(true); setError('');
      void api(`/roles/${role.id}`, { method: 'DELETE' }).then(onChanged).catch(e => setError(errorMessage(e, t('刪除失敗')))).finally(() => setBusy(false));
    }} />}
  </div>;
}

function RoleEditor({ role, permissions, onClose, onSaved }: { role: Role | null; permissions: string[]; onClose: () => void; onSaved: () => void }) {
  const [chosen, setChosen] = useState<string[]>(role?.permissions || []), [busy, setBusy] = useState(false), [error, setError] = useState('');
  function toggle(permission: string, checked: boolean) {
    setChosen(current => {
      const next = new Set(current);
      if (checked) { next.add(permission); if (REQUIRES[permission]) next.add(REQUIRES[permission]); }
      else { next.delete(permission); Object.entries(REQUIRES).forEach(([key, needed]) => { if (needed === permission) next.delete(key); }); }
      return permissions.filter(p => next.has(p));
    });
  }
  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); const name = new FormData(e.currentTarget).get('name');
    setBusy(true); setError('');
    void api(role ? `/roles/${role.id}` : '/roles', { method: role ? 'PUT' : 'POST', body: JSON.stringify({ name, permissions: chosen }) })
      .then(onSaved).catch(err => setError(errorMessage(err, t('操作失敗')))).finally(() => setBusy(false));
  }
  return <MemberDialog title={role ? t('編輯角色') : t('新增角色')} onClose={() => { if (!busy) onClose(); }}>
    <form className="member-form" onSubmit={submit}>
      <label>{t('角色名稱')}<input name="name" defaultValue={role?.name || ''} required maxLength={80} disabled={busy} autoComplete="off" /></label>
      <fieldset className="member-brand-options role-permission-options"><legend>{t('可使用的功能')}</legend>
        {permissions.map(permission => <label key={permission}><input type="checkbox" checked={chosen.includes(permission)} disabled={busy} onChange={e => toggle(permission, e.target.checked)} />{permissionLabel(permission)}</label>)}
      </fieldset>
      <p className="muted">{t('沒有勾選任何功能時，此角色只能檢視被指派品牌的資料。勾選「送出、重試與取消發佈」會一併勾選「編輯發佈草稿」。')}</p>
      {error && <p className="notice danger" role="alert">{error}</p>}
      <div className="action-row"><button type="button" className="secondary" disabled={busy} onClick={onClose}>{t('取消')}</button><button className="primary" disabled={busy}>{role ? t('儲存') : t('新增')}</button></div>
    </form>
  </MemberDialog>;
}

function MemberEditor({ member, brands, roles, onClose, onSaved }: { member: Member | null; brands: Brand[]; roles: Role[]; onClose: () => void; onSaved: (result?: PasswordResult) => void }) {
  const [role, setRole] = useState(member?.role || 'marketing'), [brandIds, setBrandIds] = useState(member?.brand_ids || (brands.length === 1 ? [brands[0].id] : []));
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [confirming, setConfirming] = useState(false);
  async function perform(action: () => Promise<unknown>) { setBusy(true); setError(''); try { await action(); } catch (e) { setError(errorMessage(e, t('操作失敗'))); } finally { setBusy(false); } }
  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); const data = new FormData(e.currentTarget);
    void perform(async () => {
      const body = { display_name: data.get('display_name'), role, brand_ids: role === 'admin' ? [] : brandIds, ...(!member ? { username: data.get('username') } : {}) };
      if (member) { await api('/members/' + member.id, { method: 'PUT', body: JSON.stringify(body) }); onSaved(); }
      else onSaved(await api<PasswordResult>('/members', { method: 'POST', body: JSON.stringify(body) }));
    });
  }
  return <MemberDialog title={member ? t('編輯成員') : t('新增成員')} onClose={() => { if (!busy) onClose(); }}>
    <form className="member-form" onSubmit={submit}>
      {!member && <label>{t('帳號')}<input name="username" required minLength={1} maxLength={80} autoComplete="off" disabled={busy} /></label>}
      <label>{t('顯示名稱')}<input name="display_name" defaultValue={member?.display_name || ''} required maxLength={200} disabled={busy} /></label>
      <fieldset className="member-role-options"><legend>{t('角色')}</legend>{roles.map(option => <label key={option.key}>
        <input type="radio" name="role" value={option.key} checked={role === option.key} disabled={busy} aria-labelledby={'role-name-' + option.key} aria-describedby={'role-summary-' + option.key} onChange={() => setRole(option.key)} />
        <span><strong id={'role-name-' + option.key}>{roleLabel(option.key, option.name)}</strong><small id={'role-summary-' + option.key}>{roleSummary(option)}</small></span>
      </label>)}</fieldset>
      {role === 'admin' ? <p className="muted">{t('管理員可存取全部品牌')}</p> : <fieldset className="member-brand-options"><legend>{t('可存取品牌')}</legend>{brands.map(b => <label key={b.id}><input type="checkbox" checked={brandIds.includes(b.id)} disabled={busy} onChange={e => setBrandIds(ids => e.target.checked ? [...ids, b.id] : ids.filter(id => id !== b.id))} />{b.name}</label>)}</fieldset>}
      {member && <p className="muted">{t('最後登入：{time}', { time: member.last_login_at ? taipeiDateTime(member.last_login_at) : t('尚未登入') })}</p>}
      {error && <p className="notice danger" role="alert">{error}</p>}
      <div className="action-row"><button type="button" className="secondary" disabled={busy} onClick={onClose}>{t('取消')}</button><button className="primary" disabled={busy}>{member ? t('儲存') : t('新增')}</button></div>
    </form>
    {member && <div className="member-maintenance"><button className="secondary" disabled={busy} onClick={() => void perform(async () => onSaved(await api<PasswordResult>(`/members/${member.id}/reset-password`, { method: 'POST' })))}>{t('重設密碼')}</button>
      <button className={member.active ? 'primary danger' : 'secondary'} disabled={busy} onClick={() => { if (member.active) setConfirming(true); else void perform(async () => { await api(`/members/${member.id}/state`, { method: 'PUT', body: JSON.stringify({ active: true }) }); onSaved(); }); }}>{member.active ? t('停用帳號') : t('啟用帳號')}</button></div>}
    {confirming && member && <ConfirmDialog message={t('停用 {name}？此成員將立即登出。', { name: member.display_name })} confirmLabel={t('停用帳號')} danger onClose={() => setConfirming(false)} onConfirm={() => { setConfirming(false); void perform(async () => { await api(`/members/${member.id}/state`, { method: 'PUT', body: JSON.stringify({ active: false }) }); onSaved(); }); }} />}
  </MemberDialog>;
}

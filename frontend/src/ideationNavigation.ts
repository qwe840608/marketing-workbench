export type Evidence = { id: number; kind?: string | null; post_id?: number | null };
export function positiveId(value: string | null): number | null {
  const id = Number(value); return /^[1-9]\d*$/.test(value || '') && Number.isSafeInteger(id) ? id : null;
}
export const views = ['dashboard', 'posts', 'ideation', 'publish', 'settings'] as const;
export type View = typeof views[number];
export type SettingsTab = 'ai' | 'connections' | 'policy' | 'workspace' | 'members' | 'account';
export function readSettingsTab(search: string): SettingsTab {
  const params = new URLSearchParams(search), view = params.get('view');
  if (view === 'ai' || view === 'policy') return view;
  const tab = params.get('settings_tab');
  if (tab === 'ai' || tab === 'connections' || tab === 'policy' || tab === 'workspace' || tab === 'members' || tab === 'account') return tab;
  // A pre-tabs workspace bookmark used view=settings without a tab parameter.
  return view === 'settings' && tab === null ? 'workspace' : 'connections';
}
export function readView(search: string): View {
  const value = new URLSearchParams(search).get('view');
  if (value === 'policy' || value === 'ai') return 'settings';
  return views.find(view => view === value) ?? 'dashboard';
}
export function viewQuery(search: string, view: View): string {
  const p = new URLSearchParams(search);
  p.set('view', view);
  return p.size ? '?' + p : '';
}
export function quoteHref(q: Evidence, brandId: number, reportId: number, scriptId?: number): string | null {
  const p = new URLSearchParams({ brand_id: String(brandId), return_report_id: String(reportId) });
  if (scriptId) p.set('return_script_id', String(scriptId));
  if (q.kind === 'comment_thread' && q.post_id) { p.set('view', 'posts'); p.set('post_id', String(q.post_id)); p.set('comment_id', String(q.id)); }
  else return null;
  return '/?' + p;
}
export function reportReturn(search: string): { id: number; href: string } | null {
  const p = new URLSearchParams(search), id = positiveId(p.get('return_report_id'));
  if (!id) return null;
  const result = new URLSearchParams({ view: 'ideation', report_id: String(id) });
  for (const [from, to] of [['brand_id', 'brand_id'], ['return_script_id', 'script_id']]) {
    const value = positiveId(p.get(from)); if (value) result.set(to, String(value));
  }
  return { id, href: '/?' + result };
}
export function selectionQuery(search: string, brandId: string, reportId: number | null, scriptId: number | null): string {
  const p = new URLSearchParams(search); p.set('view', 'ideation');
  if (brandId) p.set('brand_id', brandId);
  for (const [key, value] of [['report_id', reportId], ['script_id', scriptId]] as const) {
    if (value) p.set(key, String(value)); else p.delete(key);
  }
  for (const key of ['post_id', 'comment_id', 'return_report_id', 'return_script_id']) p.delete(key);
  return '?' + p;
}

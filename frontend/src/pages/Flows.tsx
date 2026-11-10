import { Fragment, useCallback, useEffect, useRef, useState } from 'react';
import type { DragEvent, RefObject } from 'react';
import { Background, Controls, Handle, Position, ReactFlow, ReactFlowProvider, addEdge, useEdgesState, useNodesState, useReactFlow } from '@xyflow/react';
import type { Connection, Edge as FlowEdge, Node as FlowNode, NodeProps } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { api, errorMessage } from '../api';
import type { Brand, User } from '../api';
import { ConfirmDialog } from './ConfirmDialog';
import { SegmentedControl } from './SegmentedControl';
import { platformLabels } from '../publishComposer';
import { PageHeader } from './PageHeader';
import { Publish } from './Publish';
import { t } from '../i18n.ts';
import { formatTaipei } from '../time.ts';
import { can } from '../permissions';
import './flows.css';

type Platform = 'facebook' | 'instagram' | 'threads' | 'youtube' | 'tiktok' | 'x';
type Kind = 'trigger' | 'draft' | 'approval' | 'publish' | 'delay' | 'notify';
type Config = Record<string, unknown>;
type GraphNode = { id: string; type: Kind; position: { x: number; y: number }; config: Config };
type Graph = { nodes: GraphNode[]; edges: { source: string; target: string }[] };
type Validation = { ok: boolean; errors: string[]; nodes: Record<string, string[]>; order: string[] };
type Flow = { id: number; brand_id: number; name: string; enabled: boolean; graph: Graph; validation: Validation; next_run_at: string | null; last_run: { id: number; status: string; trigger_at: string } | null; version: number };
type Run = { id: number; flow_id: number; flow_name: string; status: string; trigger_at: string; graph: Graph; draft_post_id: number | null; approval_deadline: string | null; approved_at: string | null; steps: Record<string, { status: string; post_id?: number; at?: string; error?: string }>; posts: Record<string, { status: string; scheduled_at: string | null }>; plan: { node: string; platforms: Platform[]; at: string }[]; error: string | null; finished_at: string | null };
type DraftPost = { id: number; version: number; caption: string; status: string; source?: string };
// 畫布上看到的方塊種類：「選取草稿」在後端仍是 draft 方塊（source=post），只是介面上分開。
type Look = Kind | 'pick';
type PaletteItem = { key: string; type: Kind; look: Look; label: string; hint: string; config: Config };
const DRAG_TYPE = 'application/x-mwb-flow-block';
// 左邊多留出方塊選單的寬度，縮放後的方塊不會被選單蓋住。
const FIT_PADDING = { top: 0.15, right: 0.15, bottom: 0.15, left: '180px' } as const;

const kindLabels: Record<Kind, string> = { trigger: t('時間觸發'), draft: t('建立草稿'), approval: t('等待核准'), publish: t('發佈'), delay: t('延遲'), notify: t('通知') };
const kindHints: Record<Kind, string> = { trigger: t('每天、每週或指定日期的時間開始'), draft: t('用固定範本或主題發想的下一題建立草稿'), approval: t('通知 LINE 群組，等人核准'), publish: t('核准後排程到選定平台'), delay: t('等一段時間或到指定時刻'), notify: t('送 LINE 通知；放在發佈後會附上結果') };
const defaults: Record<Kind, Config> = { trigger: { mode: 'weekly', weekdays: [0], time: '20:00' }, draft: { source: 'template', format: 'text', caption: '' }, approval: { hours: 24 }, publish: { platforms: [] }, delay: { amount: 1, unit: 'hours' }, notify: { message: '' } };
const weekdayLabels = [t('一'), t('二'), t('三'), t('四'), t('五'), t('六'), t('日')];
const runStates: Record<string, string> = { running: t('執行中'), awaiting_approval: t('待核准'), scheduled: t('已排程'), done: t('完成'), partial: t('部分成功'), failed: t('失敗'), expired: t('逾期未核准'), cancelled: t('已取消'), missed: t('已錯過') };
const runTone = (status: string) => status === 'done' ? 'ready' : ['failed', 'partial', 'expired', 'missed'].includes(status) ? 'failed' : status === 'cancelled' ? 'neutral' : 'pending';
const postStates: Record<string, string> = { draft: t('草稿'), scheduled: t('排程中'), publishing: t('發佈中'), done: t('成功'), partial: t('部分成功'), failed: t('失敗'), missed: t('已錯過'), paused: t('已暫停'), cancelled: t('已取消') };
// 流程時間以分鐘為單位，不顯示秒。
const taipei = (value: string) => formatTaipei(value, { year: 'numeric', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
const reason = (e: unknown) => errorMessage(e, t('操作失敗，請重試'));
const platforms = Object.keys(platformLabels) as Platform[];
const look = (node: GraphNode): Look => node.type === 'draft' && node.config.source === 'post' ? 'pick' : node.type;
const pickLabel = t('選取草稿'), pickHint = t('從現有草稿挑一篇，每次執行複製一份；雙擊方塊可以直接編輯這篇草稿');
// 發佈方塊一個平台一塊，標題直接寫平台；舊流程一塊多平台的仍顯示「發佈」。
function title(node: GraphNode): string {
  if (look(node) === 'pick') return pickLabel;
  const list = (node.config.platforms as Platform[]) || [];
  if (node.type === 'publish' && list.length === 1) return t('發佈到 {platform}', { platform: platformLabels[list[0]] });
  return kindLabels[node.type];
}
const basic = (type: Kind): PaletteItem => ({ key: type, type, look: type, label: kindLabels[type], hint: kindHints[type], config: defaults[type] });
const palette: PaletteItem[] = [
  basic('trigger'), basic('draft'),
  { key: 'pick', type: 'draft', look: 'pick', label: pickLabel, hint: pickHint, config: { source: 'post', post_id: null } },
  basic('approval'), basic('delay'), basic('notify'),
  ...platforms.map((p): PaletteItem => ({ key: 'publish-' + p, type: 'publish', look: 'publish', label: platformLabels[p], hint: t('核准後排程到 {platform}', { platform: platformLabels[p] }), config: { platforms: [p] } })),
];

// 驗證錯誤是後端的固定繁中訊息，顯示時查翻譯表（與 api.ts 的錯誤訊息相同）。
// 方塊上的一行摘要，畫布與窄螢幕清單共用。
function summary(node: GraphNode): string {
  const c = node.config;
  if (node.type === 'trigger') {
    const time = String(c.time || '20:00');
    if (c.mode === 'daily') return t('每天 {time}', { time });
    if (c.mode === 'once') return t('{date} {time}', { date: String(c.date || '—'), time });
    const days = ((c.weekdays as number[]) || []).map(d => weekdayLabels[d]).join(t('、'));
    return t('每週{days} {time}', { days: days || '—', time });
  }
  if (node.type === 'draft') return c.source === 'idea' ? t('主題發想的下一題') : c.source === 'post' ? (c.post_id ? t('複製草稿 #{id}', { id: Number(c.post_id) }) : t('（尚未選草稿）')) : String(c.caption || '').slice(0, 24) || t('（尚未輸入範本）');
  if (node.type === 'approval') return t('{hours} 小時內核准', { hours: Number(c.hours || 24) });
  if (node.type === 'publish') { const list = (c.platforms as Platform[]) || []; return list.length === 1 ? t('核准後排程') : list.map(p => platformLabels[p]).join(t('、')) || t('（尚未選平台）'); }
  if (node.type === 'delay') return c.at ? t('等到 {time}', { time: String(c.at) }) : t('等 {amount} {unit}', { amount: Number(c.amount || 1), unit: { minutes: t('分鐘'), hours: t('小時'), days: t('天') }[String(c.unit || 'hours')] || '' });
  return String(c.message || '') || t('（只送流程名稱）');
}

type NodeData = { node: GraphNode; errors: string[] };
// 每種方塊一個線條圖示（24×24），選單與畫布共用，顏色跟方塊色條一致。
const kindIcons: Record<Look, string> = {
  pick: 'M8 8h12v12H8zM16 8V4H4v12h4',
  trigger: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2',
  draft: 'M14 3H6v18h12V7zM14 3v4h4M9 12h6M9 16h4',
  approval: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM8 12l3 3 5-6',
  delay: 'M7 3h10M7 21h10M8 3v3l4 6 4-6V3M8 21v-3l4-6 4 6v3',
  publish: 'M21 3 3 10l7 3 3 7 8-17zM10 13l11-10',
  notify: 'M6 16v-5a6 6 0 0 1 12 0v5l2 2H4zM10 21h4',
};
function KindIcon({ kind }: { kind: Look }) {
  return <span className="flow-kind-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d={kindIcons[kind]} /></svg></span>;
}
function BlockNode({ data, selected }: NodeProps<FlowNode<NodeData>>) {
  const { node, errors } = data;
  return <div className={'flow-block is-' + look(node) + (selected ? ' selected' : '') + (errors.length ? ' has-error' : '')} title={errors.map(text => t(text)).join(t('；'))}>
    {node.type !== 'trigger' && <Handle type="target" position={Position.Left} />}
    <strong className="flow-block-title"><KindIcon kind={look(node)} />{title(node)}</strong><span>{summary(node)}</span>
    {errors.length > 0 && <small>{t(errors[0])}</small>}
    <Handle type="source" position={Position.Right} />
  </div>;
}
const nodeTypes = { block: BlockNode };

const toFlowNodes = (graph: Graph, validation?: Validation): FlowNode<NodeData>[] => graph.nodes.map(node => ({ id: node.id, type: 'block', position: node.position, data: { node, errors: validation?.nodes[node.id] || [] } }));
const toFlowEdges = (graph: Graph): FlowEdge[] => graph.edges.map(edge => ({ id: edge.source + '>' + edge.target, source: edge.source, target: edge.target }));
const starter = (): Graph => {
  const order: Kind[] = ['trigger', 'draft', 'approval', 'publish'];
  const nodes = order.map((type, index) => ({ id: type + '-1', type, position: { x: index * 220, y: 80 }, config: { ...defaults[type] } }));
  return { nodes, edges: nodes.slice(1).map((node, index) => ({ source: nodes[index].id, target: node.id })) };
};
const ordered = (graph: Graph, validation: Validation) => {
  const byId = new Map(graph.nodes.map(node => [node.id, node]));
  const chain = validation.order.map(id => byId.get(id)).filter((node): node is GraphNode => !!node);
  return [...chain, ...graph.nodes.filter(node => !validation.order.includes(node.id))];
};

function ConfigFields({ node, drafts, onEditDraft, onChange }: { node: GraphNode; drafts: DraftPost[]; onEditDraft: (id: number) => void; onChange: (config: Config) => void }) {
  const c = node.config, set = (patch: Config) => onChange({ ...c, ...patch });
  if (node.type === 'trigger') return <>
    <SegmentedControl compact label={t('觸發方式')} options={[{ value: 'daily', label: t('每天') }, { value: 'weekly', label: t('每週') }, { value: 'once', label: t('指定日期') }]} value={String(c.mode || 'weekly') as 'daily' | 'weekly' | 'once'} onChange={mode => set({ mode })} />
    {c.mode === 'weekly' && <fieldset className="flow-weekdays"><legend>{t('星期')}</legend>{weekdayLabels.map((label, day) => { const days = (c.weekdays as number[]) || []; return <label key={day}><input type="checkbox" checked={days.includes(day)} onChange={e => set({ weekdays: e.target.checked ? [...days, day].sort() : days.filter(d => d !== day) })} />{label}</label>; })}</fieldset>}
    {c.mode === 'once' && <label>{t('日期')}<input type="date" value={String(c.date || '')} onChange={e => set({ date: e.target.value || null })} /></label>}
    <label>{t('時間（台北）')}<input type="time" value={String(c.time || '20:00')} onChange={e => set({ time: e.target.value })} /></label>
  </>;
  if (node.type === 'draft') return <>
    {c.source === 'post' ? <>
      <label>{t('草稿')}<select aria-label={t('草稿')} value={String(c.post_id || '')} onChange={e => set({ post_id: e.target.value ? Number(e.target.value) : null })}><option value="">{t('請選擇草稿')}</option>{drafts.map(d => <option key={d.id} value={d.id}>{'#' + d.id + ' ' + (d.caption.replace(/\s+/g, ' ').slice(0, 40) || t('（沒有文案）'))}</option>)}</select></label>
      {!!c.post_id && <button className="secondary" onClick={() => onEditDraft(Number(c.post_id))}>{t('編輯這篇草稿')}</button>}
      <p className="notice">{t('每次執行會複製這篇草稿（含文案、素材與平台選項），原稿留著可以重複使用。格式跟著原稿。')}</p>
    </> : <>
    <SegmentedControl compact label={t('草稿來源')} options={[{ value: 'template', label: t('固定範本') }, { value: 'idea', label: t('主題發想') }]} value={String(c.source || 'template') as 'template' | 'idea'} onChange={source => set({ source })} />
    <SegmentedControl compact label={t('貼文格式')} options={[{ value: 'text', label: t('純文字') }, { value: 'image', label: t('圖片') }, { value: 'carousel', label: t('輪播') }, { value: 'video', label: t('影片') }]} value={String(c.format || 'text') as 'text' | 'image' | 'carousel' | 'video'} onChange={format => set({ format })} />
    {c.source === 'idea' ? <p className="notice">{t('取最新主題發想報告中還沒建立過貼文的下一題，用標題、開場和 hashtag 當初稿，不呼叫 AI。')}</p> : <label>{t('範本文案')}<textarea rows={5} maxLength={5000} value={String(c.caption || '')} onChange={e => set({ caption: e.target.value })} /></label>}
    {c.format !== 'text' && <p className="notice warning">{t('圖片與影片要在核准前到草稿上傳，否則會檢查不過。')}</p>}
    </>}
  </>;
  if (node.type === 'approval') return <label>{t('核准期限（小時）')}<input type="number" min={1} max={168} value={Number(c.hours || 24)} onChange={e => set({ hours: Math.min(168, Math.max(1, Number(e.target.value) || 1)) })} /></label>;
  // 一個發佈方塊只發一個平台；要發多個平台就接多個方塊。
  if (node.type === 'publish') return <fieldset className="flow-platforms"><legend>{t('發佈平台')}</legend>{platforms.map(p => { const list = (c.platforms as Platform[]) || []; return <label key={p}><input type="radio" name={'platform-' + node.id} checked={list.includes(p)} onChange={() => set({ platforms: [p] })} />{platformLabels[p]}</label>; })}</fieldset>;
  if (node.type === 'delay') return <>
    <SegmentedControl compact label={t('延遲方式')} options={[{ value: 'span', label: t('等一段時間') }, { value: 'clock', label: t('等到指定時刻') }]} value={c.at ? 'clock' : 'span'} onChange={mode => set(mode === 'clock' ? { at: '20:00' } : { at: null })} />
    {c.at ? <label>{t('時刻（台北）')}<input type="time" value={String(c.at)} onChange={e => set({ at: e.target.value })} /></label> : <div className="flow-delay-span"><label>{t('數量')}<input type="number" min={1} max={720} value={Number(c.amount || 1)} onChange={e => set({ amount: Math.min(720, Math.max(1, Number(e.target.value) || 1)) })} /></label><label>{t('單位')}<select value={String(c.unit || 'hours')} onChange={e => set({ unit: e.target.value })}><option value="minutes">{t('分鐘')}</option><option value="hours">{t('小時')}</option><option value="days">{t('天')}</option></select></label></div>}
  </>;
  return <label>{t('通知內容（可留空）')}<textarea rows={3} maxLength={500} value={String(c.message || '')} onChange={e => set({ message: e.target.value })} /></label>;
}

// 草稿彈窗：直接用發佈頁的編輯器（隱藏發佈按鈕），修改自動存回同一篇草稿，不離開流程頁。
function DraftDialog({ id, brandId, brands, user, leave, onClose }: { id: number; brandId: string; brands: Brand[]; user: User; leave: Leave; onClose: () => void }) {
  const [closing, setClosing] = useState(false);
  async function close() {
    setClosing(true);
    const ok = !leave.current || await leave.current();
    setClosing(false); if (ok) onClose();
  }
  return <div className="ideation-modal-backdrop flow-draft-backdrop">
    <div className="flow-draft-dialog" role="dialog" aria-modal="true" aria-label={t('編輯草稿 #{id}', { id })} onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); void close(); } }}>
      <div className="flow-draft-top"><h2>{t('編輯草稿 #{id}', { id })}</h2><span className="flow-hint">{t('修改會自動存回這篇草稿')}</span><button className="primary" disabled={closing} aria-busy={closing} onClick={() => void close()}>{t('完成')}</button></div>
      <div className="flow-draft-body"><Publish embedded brand={brandId} brands={brands} user={user} draftId={id} fromIdea={false} onDraftId={() => undefined} beforeLeave={leave} onConnections={() => window.open('/?' + new URLSearchParams({ view: 'settings', settings_tab: 'connections', brand_id: brandId }), '_blank', 'noopener')} /></div>
    </div>
  </div>;
}

type Leave = RefObject<(() => Promise<boolean>) | null>;
type Snapshot = { name: string; graph: Graph };
// 沒存到伺服器的變更（存檔失敗、存檔途中關掉分頁）留在這台電腦，下次打開同一個流程時還原。
const backupKey = (brand: string, id: number | 'new') => 'mwb.flow-unsaved.' + brand + '.' + id;
const openKey = (brand: string) => 'mwb.flow-open.' + brand;
function readStore<T>(key: string): T | null {
  try { const raw = localStorage.getItem(key); return raw ? JSON.parse(raw) as T : null; } catch { return null; }
}
function writeStore(key: string, value: unknown) {
  // 無痕視窗或停用網站資料時寫不進去，只靠伺服器自動儲存。
  try { if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, JSON.stringify(value)); } catch { /* 略過 */ }
}
// 只比內容：React Flow 會在方塊上加選取、尺寸等欄位，不能拿來判斷有沒有改。
const fingerprint = (value: Snapshot) => JSON.stringify([value.name, value.graph.nodes.map(n => [n.id, n.type, Math.round(n.position.x), Math.round(n.position.y), n.config]), value.graph.edges.map(e => [e.source, e.target])]);

function Editor({ flow, brandId, brands, user, wide, leave, draftLeave, onClose }: { flow: Flow | null; brandId: string; brands: Brand[]; user: User; wide: boolean; leave: Leave; draftLeave: Leave; onClose: () => void }) {
  const brand = String(flow?.brand_id || brandId);
  const [start] = useState(() => {
    const base: Snapshot = { name: flow?.name || t('新流程'), graph: flow?.graph.nodes.length ? flow.graph : starter() };
    const key = backupKey(brand, flow?.id ?? 'new'), backup = readStore<Snapshot & { version: number }>(key);
    // 伺服器上的版本比備份新（別的分頁改過）就不還原，免得蓋掉。
    const restored = backup && backup.version === (flow?.version || 0) && fingerprint(backup) !== fingerprint(base) ? backup : null;
    if (backup && !restored) writeStore(key, null);
    return { base, current: restored ? { name: restored.name, graph: restored.graph } : base, restored: !!restored };
  });
  const [name, setName] = useState(start.current.name);
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode<NodeData>>(toFlowNodes(start.current.graph, flow?.validation));
  const [edges, setEdges, onEdgesChange] = useEdgesState<FlowEdge>(toFlowEdges(start.current.graph));
  const [selected, setSelected] = useState<string | null>(null);
  const [saved, setSaved] = useState<Flow | null>(flow), [error, setError] = useState('');
  const [status, setStatus] = useState<'idle' | 'pending' | 'saving' | 'saved' | 'failed'>(start.restored ? 'pending' : flow ? 'saved' : 'idle');
  const [editing, setEditing] = useState<number | null>(null), [draftTick, setDraftTick] = useState(0);
  const view = useReactFlow();
  const [drafts, setDrafts] = useState<DraftPost[]>([]);
  useEffect(() => {
    if (!brand) return;
    const controller = new AbortController();
    // 只列人工建立的草稿；流程自己複製出來的不再當範本。
    const load = () => void api<DraftPost[]>('/publish/posts?brand_id=' + brand, { signal: controller.signal }).then(rows => setDrafts(rows.filter(row => row.status === 'draft' && row.source !== 'flow'))).catch(() => undefined);
    // 草稿可能在別的分頁改過，回到這裡時重新讀，下拉選單的文案才會是新的。
    load(); window.addEventListener('focus', load);
    return () => { controller.abort(); window.removeEventListener('focus', load); };
  }, [brand, draftTick]);
  const graph = (): Graph => ({ nodes: nodes.map(n => ({ ...n.data.node, position: { x: Math.round(n.position.x), y: Math.round(n.position.y) } })), edges: edges.map(e => ({ source: e.source, target: e.target })) });
  const latest = useRef<Snapshot>(start.current); latest.current = { name, graph: graph() };
  const savedRef = useRef(flow), lastSaved = useRef(fingerprint(start.base)), mounted = useRef(true);
  const queue = useRef<Promise<void>>(Promise.resolve());
  // 自動儲存：一次只送一個請求；送出時取最新內容，跟上次存的一樣就不送。
  function flush(): Promise<void> {
    const run = async () => {
      const value = latest.current, mark = fingerprint(value), current = savedRef.current;
      if (mark === lastSaved.current || !value.name.trim()) return;
      if (mounted.current) setStatus('saving');
      try {
        // keepalive：關分頁、重新整理時請求仍會送完。
        const result = await api<Flow>(current ? '/flows/' + current.id : '/flows', { method: current ? 'PUT' : 'POST', keepalive: true, body: JSON.stringify({ brand_id: Number(brand), name: value.name, graph: value.graph, version: current?.version || 1 }) });
        savedRef.current = result; lastSaved.current = mark;
        writeStore(backupKey(brand, 'new'), null); writeStore(backupKey(brand, result.id), null); writeStore(openKey(brand), result.id);
        if (!mounted.current) return;
        setSaved(result); setError(''); setStatus(fingerprint(latest.current) === mark ? 'saved' : 'pending');
        setNodes(list => list.map(n => ({ ...n, data: { ...n.data, errors: result.validation.nodes[n.id] || [] } })));
      } catch (e) {
        if (mounted.current) { setError(reason(e)); setStatus('failed'); }
        throw e;
      }
    };
    const next = queue.current.catch(() => undefined).then(run); queue.current = next; return next;
  }
  const flushRef = useRef(flush); flushRef.current = flush;
  useEffect(() => {
    const key = backupKey(brand, savedRef.current?.id ?? 'new');
    if (fingerprint(latest.current) === lastSaved.current) { writeStore(key, null); return; }
    writeStore(key, { ...latest.current, version: savedRef.current?.version || 0 });
    setStatus(value => value === 'saving' ? value : 'pending');
    const timer = window.setTimeout(() => void flushRef.current().catch(() => undefined), 800);
    return () => window.clearTimeout(timer);
  }, [nodes, edges, name]);
  useEffect(() => {
    mounted.current = true;
    const unload = () => void flushRef.current().catch(() => undefined);
    window.addEventListener('pagehide', unload);
    // 切到別的頁面前先把草稿彈窗和畫布存完；存不了也放行，變更已留在本機備份。
    leave.current = async () => {
      if (draftLeave.current && !await draftLeave.current()) return false;
      await flushRef.current().catch(() => undefined); return true;
    };
    return () => { mounted.current = false; window.removeEventListener('pagehide', unload); leave.current = null; void flushRef.current().catch(() => undefined); };
  }, []);
  const onConnect = useCallback((connection: Connection) => setEdges(list => addEdge(connection, list)), [setEdges]);
  const current = nodes.find(n => n.id === selected)?.data.node || null;
  function add(item: PaletteItem, at?: { x: number; y: number }) {
    const { type } = item;
    const count = nodes.filter(n => n.data.node.type === type).length + 1;
    let id = type + '-' + count; while (nodes.some(n => n.id === id)) id += 'x';
    const last = nodes.reduce((max, n) => Math.max(max, n.position.x), -220);
    const node: GraphNode = { id, type, position: at || { x: last + 220, y: 80 }, config: structuredClone(item.config) };
    setNodes(list => [...list, { id, type: 'block', position: node.position, data: { node, errors: [] } }]); setSelected(id);
    // 用點的會放在最右邊，重新縮放讓它出現在畫面內；拖進來的放在放開的位置，不動畫面。
    if (!at) window.setTimeout(() => void view.fitView({ padding: FIT_PADDING }), 50);
  }
  function drop(event: DragEvent<HTMLDivElement>) {
    const item = palette.find(entry => entry.key === event.dataTransfer.getData(DRAG_TYPE));
    if (!item) return;
    event.preventDefault();
    // 以滑鼠位置當方塊中心（方塊寬 180、約高 60）。
    const point = view.screenToFlowPosition({ x: event.clientX, y: event.clientY });
    add(item, { x: Math.round(point.x - 90), y: Math.round(point.y - 30) });
  }
  function update(config: Config) {
    setNodes(list => list.map(n => n.id === selected ? { ...n, data: { ...n.data, node: { ...n.data.node, config } } } : n));
  }
  function remove() {
    setNodes(list => list.filter(n => n.id !== selected)); setEdges(list => list.filter(e => e.source !== selected && e.target !== selected)); setSelected(null);
  }
  async function close() { await flush().catch(() => undefined); onClose(); }
  // 剛改完、自動儲存的 effect 還沒跑時，畫面不能還寫「已自動儲存」。
  const shown = (status === 'saved' || status === 'idle') && fingerprint(latest.current) !== lastSaved.current ? 'pending' : status;
  const stateText = !name.trim() ? t('輸入流程名稱後才會儲存') : shown === 'saving' ? t('儲存中…') : shown === 'pending' ? t('有變更，稍後自動儲存') : shown === 'failed' ? t('沒存到，變更先留在這台電腦') : saved ? (saved.validation.ok ? t('已自動儲存') : t('已儲存，但流程還有錯誤，修正後才能啟用')) : t('修改後會自動儲存');
  return <div className="section-card flow-editor">
    <div className="flow-editor-top"><label>{t('流程名稱')}<input value={name} maxLength={80} onChange={e => setName(e.target.value)} /></label><div className="action-row"><span className={'flow-save-state' + (status === 'failed' ? ' is-failed' : '')} role="status" aria-live="polite">{stateText}</span><button className="secondary" onClick={() => void close()}>{t('返回流程清單')}</button></div></div>
    {start.restored && <p className="notice">{t('已還原上次還沒存到的變更')}</p>}
    {error && <p className="notice danger" role="alert">{error}</p>}
    {saved?.enabled && <p className="notice warning">{t('流程啟用中：有錯誤時不會存，修正後才會自動儲存；已觸發的執行不受影響。')}</p>}
    {wide ? <>
      <div className="flow-workspace">
        <div className="flow-canvas" aria-label={t('流程畫布')} onDragOver={e => { if (e.dataTransfer.types.includes(DRAG_TYPE)) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; } }} onDrop={drop}>
          {/* 方塊選單浮在畫布左側，拖出來就放進畫布；點一下則加在最右邊。 */}
          <div className="flow-palette" role="toolbar" aria-label={t('新增方塊')} aria-orientation="vertical">{palette.map(item => <Fragment key={item.key}>
            {item.key === 'publish-' + platforms[0] && <span className="flow-palette-heading">{t('發佈到')}</span>}
            <button type="button" className={'flow-palette-item is-' + item.look} draggable title={item.hint} onDragStart={e => { e.dataTransfer.setData(DRAG_TYPE, item.key); e.dataTransfer.effectAllowed = 'copy'; }} onClick={() => add(item)}><KindIcon kind={item.look} />{item.label}</button>
          </Fragment>)}</div>
          <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect} onNodeClick={(_, node) => setSelected(node.id)} onNodeDoubleClick={(_, node) => { const picked = node.data.node; if (look(picked) === 'pick' && picked.config.post_id) setEditing(Number(picked.config.post_id)); }} zoomOnDoubleClick={false} onPaneClick={() => setSelected(null)} deleteKeyCode={['Delete', 'Backspace']} connectionRadius={40} fitView fitViewOptions={{ padding: FIT_PADDING }} proOptions={{ hideAttribution: true }}>
            <Background /><Controls position="bottom-right" showInteractive={false} />
          </ReactFlow>
        </div>
        <aside className="flow-inspector">{current ? <>
          <h3>{title(current)}</h3><p className="flow-hint">{look(current) === 'pick' ? pickHint : kindHints[current.type]}</p>
          <ConfigFields node={current} drafts={drafts} onEditDraft={setEditing} onChange={update} />
          <button className="primary danger" onClick={remove}>{t('刪除方塊')}</button>
        </> : <p className="flow-hint">{t('把左側選單的方塊拖到畫布上（點一下則加在最右邊）；點方塊編輯設定；從方塊右側圓點拉線到下一個方塊左側。選取連線後按 Delete 可刪除。')}</p>}</aside>
      </div>
    </> : <p className="notice">{t('流程畫布需要較寬的螢幕（768px 以上）才能編輯，這裡只能改名稱。')}</p>}
    {saved && !saved.validation.ok && <ul className="flow-errors">{[...saved.validation.errors, ...Object.values(saved.validation.nodes).flat()].map((text, i) => <li key={i}>{t(text)}</li>)}</ul>}
    {editing !== null && <DraftDialog id={editing} brandId={brand} brands={brands} user={user} leave={draftLeave} onClose={() => { setEditing(null); setDraftTick(n => n + 1); }} />}
  </div>;
}

function Steps({ graph, validation }: { graph: Graph; validation: Validation }) {
  return <ol className="flow-steps">{ordered(graph, validation).map(node => <li key={node.id} className={validation.nodes[node.id] ? 'has-error' : ''}><strong>{title(node)}</strong><span>{summary(node)}</span>{validation.nodes[node.id] && <small>{t(validation.nodes[node.id][0])}</small>}</li>)}</ol>;
}

export function Flows({ brandId, brands, user, beforeLeave, onOpenDraft }: { brandId: string; brands: Brand[]; user: User; beforeLeave: Leave; onOpenDraft: (id: number) => void }) {
  const editorLeave = useRef<(() => Promise<boolean>) | null>(null), draftLeave = useRef<(() => Promise<boolean>) | null>(null);
  const [draft, setDraft] = useState<number | null>(null);
  useEffect(() => {
    beforeLeave.current = async () => (!draftLeave.current || await draftLeave.current()) && (!editorLeave.current || await editorLeave.current());
    return () => { beforeLeave.current = null; };
  }, []);
  const [publishEnabled, setPublishEnabled] = useState(false);
  const canSubmit = can(user, 'publish.submit');
  const [flows, setFlows] = useState<Flow[]>([]), [runs, setRuns] = useState<Run[]>([]);
  const [editing, setEditing] = useState<Flow | null | 'new'>(null), [expanded, setExpanded] = useState<number | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [approveRun, setApproveRun] = useState<{ run: Run; draft: DraftPost } | null>(null);
  const [cancelRun, setCancelRun] = useState<Run | null>(null), [deleteFlow, setDeleteFlow] = useState<Flow | null>(null);
  const [wide, setWide] = useState(() => window.matchMedia('(min-width: 768px)').matches);
  useEffect(() => { const query = window.matchMedia('(min-width: 768px)'), change = () => setWide(query.matches); query.addEventListener('change', change); return () => query.removeEventListener('change', change); }, []);
  async function reload(): Promise<Flow[]> {
    if (!brandId) return [];
    try {
      const [list, history, options] = await Promise.all([api<Flow[]>('/flows?brand_id=' + brandId), api<Run[]>('/flow-runs?brand_id=' + brandId), api<{ enabled: boolean }>('/publish/options?brand_id=' + brandId)]);
      setFlows(list); setRuns(history); setPublishEnabled(options.enabled); return list;
    } catch (e) { setError(reason(e)); return []; }
  }
  function open(flow: Flow | 'new' | null) {
    setEditing(flow); writeStore(openKey(brandId), flow === null ? null : flow === 'new' ? 'new' : flow.id);
  }
  useEffect(() => {
    setEditing(null);
    // 離開前正在編輯的流程，回到這頁時直接打開。
    const last = readStore<number | 'new'>(openKey(brandId));
    void reload().then(list => { if (last === 'new') setEditing('new'); else if (last !== null) setEditing(list.find(flow => flow.id === last) || null); });
  }, [brandId]);
  async function perform(task: () => Promise<void>, done?: string) {
    setBusy(true); setError(''); setNotice('');
    try { await task(); if (done) setNotice(done); await reload(); } catch (e) { setError(reason(e)); } finally { setBusy(false); }
  }
  const toggle = (flow: Flow) => perform(async () => { await api('/flows/' + flow.id + '/enabled', { method: 'POST', body: JSON.stringify({ enabled: !flow.enabled, version: flow.version }) }); }, flow.enabled ? t('已停用流程') : t('已啟用流程'));
  async function openApproval(run: Run) {
    setError('');
    try { setApproveRun({ run, draft: await api<DraftPost>('/publish/posts/' + run.draft_post_id) }); } catch (e) { setError(reason(e)); }
  }
  if (editing) return <section className="settings-page flow-page"><PageHeader title={t('流程')} /><ReactFlowProvider><Editor key={editing === 'new' ? 'new' : editing.id} flow={editing === 'new' ? null : editing} brandId={brandId} brands={brands} user={user} wide={wide} leave={editorLeave} draftLeave={draftLeave} onClose={() => { open(null); void reload(); }} /></ReactFlowProvider></section>;
  const waiting = runs.filter(run => run.status === 'awaiting_approval');
  return <section className="settings-page flow-page"><PageHeader title={t('流程')} />
    <p className="flow-intro">{t('用方塊和連線安排固定的發文節奏：到時間自動建立草稿、通知你核准，核准後才排程到各平台。電腦需要開著，送出仍經過發佈總開關與規則檢查。')}</p>
    {error && <p className="notice danger" role="alert">{error}</p>}{notice && <p className="notice success" role="status">{notice}</p>}
    {waiting.length > 0 && <section className="section-card flow-waiting"><h2>{t('待核准')}</h2>{waiting.map(run => <div key={run.id} className="list-row flow-run">
      <div className="publish-record-heading"><strong>{run.flow_name}</strong><span>{t('期限 {time}', { time: run.approval_deadline ? taipei(run.approval_deadline) : '—' })}</span></div>
      <ul className="flow-plan">{run.plan.map(item => <li key={item.node}>{taipei(item.at)} · {item.platforms.map(p => platformLabels[p]).join(t('、'))}</li>)}</ul>
      <div className="action-row">{run.draft_post_id && <button className="secondary" onClick={() => setDraft(run.draft_post_id)}>{t('編輯草稿')}</button>}{canSubmit && <><button className="primary" disabled={busy || !publishEnabled} onClick={() => void openApproval(run)}>{t('核准並排程')}</button><button className="secondary" disabled={busy} onClick={() => setCancelRun(run)}>{t('不發佈這次')}</button></>}</div>
    </div>)}</section>}
    <section className="section-card"><div className="flow-list-heading"><h2>{t('流程')}</h2><button className="primary" disabled={!brandId} onClick={() => open('new')}>{t('新增流程')}</button></div>
      <div className="list-box">{flows.length ? flows.map(flow => <div key={flow.id} className="list-row flow-row">
        <div className="publish-record-heading"><strong>{flow.name}</strong><span className={'status-badge ' + (flow.enabled ? 'ready' : 'neutral')}>{flow.enabled ? t('啟用中') : t('已停用')}</span>{!flow.validation.ok && <span className="status-badge failed">{t('有錯誤')}</span>}<span>{flow.next_run_at ? t('下次 {time}', { time: taipei(flow.next_run_at) }) : t('沒有下次觸發')}</span>{flow.last_run && <span className={'status-badge ' + runTone(flow.last_run.status)}>{t('上次：{status}', { status: runStates[flow.last_run.status] })}</span>}</div>
        {!wide && <Steps graph={flow.graph} validation={flow.validation} />}
        <div className="action-row"><button className="secondary" onClick={() => open(flow)}>{t('編輯')}</button>{canSubmit && <button className="secondary" disabled={busy || (!flow.enabled && !flow.validation.ok)} onClick={() => void toggle(flow)}>{flow.enabled ? t('停用') : t('啟用')}</button>}<button className="primary danger" disabled={busy} onClick={() => setDeleteFlow(flow)}>{t('刪除')}</button></div>
      </div>) : <p className="empty-data">{t('還沒有流程')}</p>}</div>
    </section>
    <section className="section-card"><h2>{t('執行紀錄')}</h2><div className="list-box">{runs.length ? runs.map(run => <div key={run.id} className="list-row flow-run">
      <div className="publish-record-heading"><span className="publish-record-id">#{run.id}</span><time>{taipei(run.trigger_at)}</time><strong>{run.flow_name}</strong><span className={'status-badge ' + runTone(run.status)}>{runStates[run.status] || run.status}</span>{run.error && <span className="publish-reasons">{t(run.error)}</span>}</div>
      <div className="action-row"><button className="secondary" aria-expanded={expanded === run.id} onClick={() => setExpanded(expanded === run.id ? null : run.id)}>{t('各步驟')}</button>{canSubmit && run.status === 'scheduled' && <button className="secondary" disabled={busy} onClick={() => setCancelRun(run)}>{t('取消這次')}</button>}</div>
      {expanded === run.id && <ol className="flow-steps">{run.graph.nodes.filter(node => run.steps[node.id]).map(node => { const step = run.steps[node.id], post = step.post_id ? run.posts[String(step.post_id)] : null; return <li key={node.id}><strong>{kindLabels[node.type]}</strong><span>{summary(node)}</span><span>{post ? postStates[post.status] || post.status : step.status === 'done' ? t('完成') : step.status === 'waiting' ? t('等待中') : step.status === 'failed' ? t('失敗') : step.status}</span>{post?.scheduled_at && <time>{taipei(post.scheduled_at)}</time>}{step.post_id && <button className="secondary" onClick={() => onOpenDraft(step.post_id!)}>{t('查看貼文 #{id}', { id: step.post_id })}</button>}</li>; })}</ol>}
    </div>) : <p className="empty-data">{t('還沒有執行紀錄')}</p>}</div></section>
    {approveRun && <ConfirmDialog heading={t('核准「{name}」', { name: approveRun.run.flow_name })} confirmLabel={t('確認核准')} onClose={() => setApproveRun(null)} onConfirm={() => { const { run, draft } = approveRun; setApproveRun(null); void perform(async () => { await api('/flow-runs/' + run.id + '/approve', { method: 'POST', body: JSON.stringify({ confirmed: true, post_version: draft.version }) }); }, t('已核准，貼文已排程')); }}>
      <p className="flow-confirm-caption">{approveRun.draft.caption || t('（無文案）')}</p>
      <ul className="flow-plan">{approveRun.run.plan.map(item => <li key={item.node}>{taipei(item.at)} · {item.platforms.map(p => platformLabels[p]).join(t('、'))}</li>)}</ul>
      <p className="flow-hint">{t('時間依核准當下重新計算；一次核准涵蓋這次流程的所有發佈。排程後仍可在「排程中」取消，送出前一分鐘會鎖定。')}</p>
    </ConfirmDialog>}
    {cancelRun && <ConfirmDialog message={cancelRun.status === 'scheduled' ? t('取消這次執行？還沒送出的貼文會回到草稿，一分鐘內要送出的已鎖定、不能取消。') : t('這次不發佈？草稿會留在發佈頁。')} confirmLabel={t('確認取消')} danger onClose={() => setCancelRun(null)} onConfirm={() => { const run = cancelRun; setCancelRun(null); void perform(async () => { await api('/flow-runs/' + run.id + '/cancel', { method: 'POST' }); }, t('已取消這次執行')); }} />}
    {draft !== null && <DraftDialog id={draft} brandId={brandId} brands={brands} user={user} leave={draftLeave} onClose={() => { setDraft(null); void reload(); }} />}
    {deleteFlow && <ConfirmDialog message={t('刪除流程「{name}」？之後不會再觸發；已建立的草稿與排程不受影響。', { name: deleteFlow.name })} confirmLabel={t('刪除')} danger onClose={() => setDeleteFlow(null)} onConfirm={() => { const flow = deleteFlow; setDeleteFlow(null); void perform(async () => { await api('/flows/' + flow.id, { method: 'DELETE' }); }, t('已刪除流程')); }} />}
  </section>;
}

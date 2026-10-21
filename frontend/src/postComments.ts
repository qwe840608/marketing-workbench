import type { Message } from './api';
import { t } from './i18n.ts';

export type PostComment = Message & {
  thread_id: number; external_id: string; author_type: string;
  comment_parent_known: boolean; comment_parent_id: string | null; comment_root_id: string | null;
};
export type Retention = { comment_retention_days: number; youtube_fresh_days: number; retention_enabled: boolean };

// 平台條款限制觀眾資料能保存多久；在留言區照實告訴使用者規則，以及每日刪除是否已啟用。
export function retentionNotice(platform: string | null, retention: Retention | null): string {
  if (!retention || !platform) return '';
  if (platform === 'tiktok') return t('TikTok 留言不會讀取或保存。');
  const rule = platform === 'youtube'
    ? t('觀眾留言依 YouTube 規定，{days} 天內未重新抓取就刪除；YouTube 上已刪除的影片，相關資料 {days} 天後刪除。', { days: retention.youtube_fresh_days })
    : t('觀眾留言自工作檯取得起保留 {days} 天，到期刪除。', { days: retention.comment_retention_days });
  return rule + (retention.retention_enabled ? '' : t('每日刪除尚未啟用，請管理員依部署文件啟用。'));
}

export type CommentRow = { message: PostComment; depth: number; relation: 'known' | 'unknown' | 'missing' | 'cycle'; parent: PostComment | null };

export function commentRows(messages: PostComment[], newestFirst = false, rootIds: number[] = []): CommentRow[] {
  const sorted = [...messages].sort((a, b) => Date.parse(a.sent_at) - Date.parse(b.sent_at) || a.id - b.id);
  const byExternal = new Map<string, PostComment[]>();
  for (const message of sorted) byExternal.set(message.external_id, [...(byExternal.get(message.external_id) || []), message]);
  const explicitRoots = new Set(rootIds);
  const parentById = new Map<number, PostComment>();
  const relations = new Map<number, CommentRow['relation']>();
  for (const message of sorted) {
    const parents = message.comment_parent_id ? byExternal.get(message.comment_parent_id) : null;
    if (!message.comment_parent_known) relations.set(message.id, 'unknown');
    else if (message.comment_parent_id && parents?.length !== 1) relations.set(message.id, 'missing');
    else if (parents?.length === 1) {
      if (explicitRoots.has(message.id)) relations.set(message.id, 'missing');
      else parentById.set(message.id, parents[0]);
    }
  }
  // Corrupt/cyclic relationships remain visible without inventing a root.
  for (const message of sorted) {
    const visited = new Set<number>([message.id]);
    let current = parentById.get(message.id);
    while (current) {
      if (visited.has(current.id)) { parentById.delete(message.id); relations.set(message.id, 'cycle'); break; }
      visited.add(current.id); current = parentById.get(current.id);
    }
  }
  const children = new Map<number, PostComment[]>();
  const roots: PostComment[] = [];
  for (const message of sorted) {
    const parent = parentById.get(message.id);
    if (parent) children.set(parent.id, [...(children.get(parent.id) || []), message]);
    else roots.push(message);
  }
  if (newestFirst) roots.reverse();
  const result: CommentRow[] = [];
  const stack = [...roots].reverse().map(message => ({ message, depth: 0 }));
  while (stack.length) {
    const { message, depth } = stack.pop()!;
    result.push({ message, depth, relation: relations.get(message.id) || 'known', parent: parentById.get(message.id) || null });
    for (const child of [...(children.get(message.id) || [])].reverse()) stack.push({ message: child, depth: depth + 1 });
  }
  return result;
}

export function readPostPlatform(search: string): string | null {
  const value = new URLSearchParams(search).getAll('post_platform').at(-1);
  return value && ['facebook', 'instagram', 'youtube', 'tiktok', 'threads'].includes(value) ? value : null;
}

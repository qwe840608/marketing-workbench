import type { User } from './api';
import { t } from './i18n.ts';

// 與 backend/app/services/roles.py 的 PERMISSIONS／BUILTIN 一致；後端仍會逐一重驗。
export const PERMISSIONS = ['posts.sync', 'reports.export', 'ideation.edit', 'publish.edit', 'publish.submit', 'connections.manage', 'ai.manage', 'settings.manage'] as const;
export type Permission = typeof PERMISSIONS[number];

const BUILTIN: Record<string, readonly Permission[]> = {
  admin: PERMISSIONS,
  marketing: ['posts.sync', 'reports.export', 'ideation.edit', 'publish.edit', 'publish.submit'],
  viewer: [],
};
export const BUILTIN_ROLES = Object.keys(BUILTIN);

export const permissionLabel = (permission: string) => ({
  'posts.sync': t('同步貼文數據與留言'),
  'reports.export': t('匯出報告'),
  'ideation.edit': t('主題發想與腳本'),
  'publish.edit': t('編輯發佈草稿'),
  'publish.submit': t('送出、重試與取消發佈'),
  'connections.manage': t('平台連線與憑證'),
  'ai.manage': t('AI 設定'),
  'settings.manage': t('工作區與系統設定'),
} as Record<string, string>)[permission] || permission;

// 內建角色以角色鍵判斷（權限固定），自訂角色才看後端回傳的權限清單。
export function can(user: Pick<User, 'role' | 'permissions'>, permission: Permission) {
  return (BUILTIN[user.role] ?? user.permissions ?? []).includes(permission);
}

export const builtinPermissions = (role: string) => BUILTIN[role] ?? [];

export const roleLabel = (role: string, name?: string | null) =>
  role === 'admin' ? t('管理員') : role === 'marketing' ? t('行銷') : role === 'viewer' ? t('檢視者') : name || t('自訂角色');

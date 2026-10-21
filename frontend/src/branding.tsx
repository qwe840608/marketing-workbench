import { createContext, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { api } from './api';
import { t } from './i18n.ts';

type Identity = { name: string; version: number };
// 只有內建備援名稱跟著介面語言；伺服器設定的工作檯名稱是使用者資料，原樣顯示。
const fallback = { name: t('行銷管理工作檯'), version: 0 };
const Workspace = createContext({ identity: fallback, update: (_value: Identity) => {} });
export const useWorkspace = () => useContext(Workspace);
export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [identity, update] = useState<Identity>(fallback);
  useEffect(() => { const c = new AbortController(); api<Identity>('/workspace/identity', { signal: c.signal }).then(update).catch(() => {}); return () => c.abort(); }, []);
  useEffect(() => { document.title = identity.name; }, [identity.name]);
  return <Workspace.Provider value={{ identity, update }}>{children}</Workspace.Provider>;
}

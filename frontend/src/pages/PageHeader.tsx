import type { ReactNode } from 'react';

export function PageHeader({ title, count, children }: { title: string; count?: number; children?: ReactNode }) {
  return <header className="page-header">
    <h1>{title}{count !== undefined && <span className="page-count">{count}</span>}</h1>
    <div className="page-actions">{children}</div>
  </header>;
}

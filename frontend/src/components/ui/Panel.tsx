import type { ReactNode } from 'react';

export function Panel({
  title,
  actions,
  children,
}: {
  title: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="panel">
      <header className="panel-header flex items-center justify-between">
        <span>{title}</span>
        {actions}
      </header>
      <div className="p-4">{children}</div>
    </section>
  );
}

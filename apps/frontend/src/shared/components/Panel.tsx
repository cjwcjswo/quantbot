import type { ReactNode } from "react";

type Props = {
  title?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
};

export function Panel({ title, actions, children, className }: Props) {
  return (
    <section className={`rounded-lg border border-panelBorder bg-panel ${className ?? ""}`}>
      {(title || actions) && (
        <header className="flex items-center justify-between border-b border-panelBorder px-4 py-2.5">
          {title && <h2 className="text-sm font-semibold text-slate-200">{title}</h2>}
          {actions}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

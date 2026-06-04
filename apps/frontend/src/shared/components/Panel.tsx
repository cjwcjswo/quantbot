import type { ReactNode } from "react";
import { cn } from "@/shared/utils/cn";

type Props = {
  title?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
};

export function Panel({ title, actions, children, className }: Props) {
  return (
    <section
      className={cn(
        "rounded-xl border border-panelBorder/80 bg-panel/70 shadow-panel backdrop-blur-sm",
        className,
      )}
    >
      {(title || actions) && (
        <header className="flex items-center justify-between gap-2 border-b border-panelBorder/70 px-4 py-3">
          {title && (
            <h2 className="flex items-center gap-2 text-sm font-semibold tracking-tight text-slate-100">
              <span className="h-3.5 w-1 rounded-full bg-accent/70" />
              {title}
            </h2>
          )}
          {actions}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

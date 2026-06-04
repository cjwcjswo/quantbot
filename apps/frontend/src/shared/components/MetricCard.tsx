import type { ReactNode } from "react";
import { cn } from "@/shared/utils/cn";

type Props = {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  valueClassName?: string;
};

export function MetricCard({ label, value, hint, valueClassName }: Props) {
  return (
    <div className="group relative overflow-hidden rounded-xl border border-panelBorder/80 bg-panel/60 px-4 py-3 shadow-panel transition-colors hover:border-accent/30">
      <div className="pointer-events-none absolute inset-x-0 -top-px h-px bg-gradient-to-r from-transparent via-accent/40 to-transparent opacity-0 transition-opacity group-hover:opacity-100" />
      <div className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
        {label}
      </div>
      <div className={cn("mt-1 text-xl font-semibold tabular-nums text-slate-100", valueClassName)}>
        {value}
      </div>
      {hint !== undefined && <div className="mt-0.5 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

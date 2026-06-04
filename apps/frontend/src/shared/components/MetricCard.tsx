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
    <div className="rounded-lg border border-panelBorder bg-panel px-4 py-3 shadow-sm">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className={cn("mt-1 text-xl font-semibold tabular-nums", valueClassName)}>{value}</div>
      {hint !== undefined && <div className="mt-0.5 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

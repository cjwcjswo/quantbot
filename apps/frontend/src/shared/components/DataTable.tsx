import type { ReactNode } from "react";
import { cn } from "@/shared/utils/cn";
import { EmptyState } from "./States";

export type Column<T> = {
  key: string;
  header: string;
  align?: "left" | "right" | "center";
  render: (row: T) => ReactNode;
};

type Props<T> = {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  onRowClick?: (row: T) => void;
  empty?: string;
};

const ALIGN: Record<string, string> = {
  left: "text-left",
  right: "text-right",
  center: "text-center",
};

export function DataTable<T>({ columns, rows, rowKey, onRowClick, empty }: Props<T>) {
  if (rows.length === 0) return <EmptyState label={empty ?? "데이터 없음"} />;
  return (
    <div className="-mx-1 overflow-x-auto">
      <table className="w-full min-w-max text-sm">
        <thead>
          <tr className="border-b border-panelBorder/80 text-[11px] uppercase tracking-wider text-slate-500">
            {columns.map((c) => (
              <th
                key={c.key}
                className={cn(
                  "whitespace-nowrap px-3 py-2.5 font-semibold",
                  ALIGN[c.align ?? "left"],
                )}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={rowKey(row)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              className={cn(
                "border-b border-panelBorder/40 transition-colors",
                onRowClick
                  ? "cursor-pointer hover:bg-accent/[0.06]"
                  : "hover:bg-white/[0.02]",
              )}
            >
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={cn(
                    "whitespace-nowrap px-3 py-2.5 tabular-nums",
                    ALIGN[c.align ?? "left"],
                  )}
                >
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

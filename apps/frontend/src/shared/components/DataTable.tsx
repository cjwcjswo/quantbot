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
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-panelBorder text-xs uppercase tracking-wide text-slate-400">
            {columns.map((c) => (
              <th key={c.key} className={cn("px-3 py-2 font-medium", ALIGN[c.align ?? "left"])}>
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
                "border-b border-panelBorder/60",
                onRowClick && "cursor-pointer hover:bg-slate-800/40",
              )}
            >
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={cn("px-3 py-2 tabular-nums", ALIGN[c.align ?? "left"])}
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

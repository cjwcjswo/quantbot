import { useState } from "react";
import type { BotEvent, Order } from "@/shared/api/types";
import { DataTable, type Column } from "@/shared/components/DataTable";
import { DirectionBadge, SeverityBadge } from "@/shared/components/Badges";
import { formatDateTime } from "@/shared/utils/format";
import {
  directionFromEventData,
  directionFromRelatedOrders,
} from "@/shared/utils/tradingDirection";

const DANGEROUS = new Set([
  "EMERGENCY_STOP",
  "EMERGENCY_CLOSE",
  "EMERGENCY_TPSL_FAILED",
  "TPSL_FAILED",
  "ORDER_LOCKED",
  "RISK_LOCKED",
  "MANUAL_INTERVENTION_DETECTED",
  "EXTERNAL_POSITION_DETECTED",
  "KILL_SWITCH_TRIPPED",
]);

export function EventsTable({ events, orders = [] }: { events: BotEvent[]; orders?: Order[] }) {
  const [expanded, setExpanded] = useState<number | null>(null);
  const columns: Column<BotEvent>[] = [
    { key: "ts", header: "시각", render: (e) => formatDateTime(e.ts) },
    { key: "sev", header: "심각도", render: (e) => <SeverityBadge severity={e.severity} /> },
    {
      key: "type",
      header: "이벤트",
      render: (e) => (
        <span className={DANGEROUS.has(e.type) ? "font-semibold text-red-400" : ""}>{e.type}</span>
      ),
    },
    { key: "symbol", header: "종목", render: (e) => e.symbol ?? "-" },
    {
      key: "direction",
      header: "방향",
      render: (e) => {
        const direction = directionFromEventData(e.data) ?? directionFromRelatedOrders(e, orders);
        if (direction) return <DirectionBadge direction={direction} />;
        return e.symbol ? (
          <span className="text-xs text-slate-500">방향 미기록</span>
        ) : (
          <span className="text-slate-600">—</span>
        );
      },
    },
    { key: "message", header: "메시지", render: (e) => e.message },
    {
      key: "details",
      header: "상세",
      render: (e) =>
        Object.keys(e.data ?? {}).length > 0 ? (
          <button
            className="text-xs text-accent hover:underline"
            onClick={() => setExpanded(expanded === e.id ? null : e.id)}
          >
            {expanded === e.id ? "숨기기" : "보기"}
          </button>
        ) : (
          <span className="text-slate-600">—</span>
        ),
    },
  ];

  return (
    <div>
      <DataTable columns={columns} rows={events} rowKey={(e) => e.id} empty="이벤트 없음" />
      {expanded !== null && (
        <pre className="mt-2 max-h-48 overflow-auto rounded border border-panelBorder bg-bg p-3 text-xs text-slate-300">
          {JSON.stringify(events.find((e) => e.id === expanded)?.data ?? {}, null, 2)}
        </pre>
      )}
    </div>
  );
}

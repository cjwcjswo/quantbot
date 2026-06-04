import type { Position } from "@/shared/api/types";
import { DataTable, type Column } from "@/shared/components/DataTable";
import { ProtectionBadge, TextBadge } from "@/shared/components/Badges";
import { Button } from "@/shared/components/Button";
import { formatDateTime, formatPrice, formatNumber, pnlClass } from "@/shared/utils/format";

function SourceCell({ p }: { p: Position }) {
  const manual = Number(p.manual_added_qty ?? "0") > 0;
  return (
    <span className="flex items-center gap-1">
      {p.source === "EXTERNAL" ? (
        <TextBadge text="⚠ EXTERNAL" tone="amber" />
      ) : (
        <TextBadge text={p.source} tone="slate" />
      )}
      {manual && <TextBadge text="Manual Added" tone="sky" />}
    </span>
  );
}

export function PositionsTable({
  positions,
  onClose,
}: {
  positions: Position[];
  onClose?: (symbol: string) => void;
}) {
  const columns: Column<Position>[] = [
    { key: "symbol", header: "Symbol", render: (p) => p.symbol },
    {
      key: "side",
      header: "Side",
      render: (p) => (
        <span className={p.side === "LONG" ? "text-emerald-400" : "text-rose-400"}>{p.side}</span>
      ),
    },
    { key: "source", header: "Source", render: (p) => <SourceCell p={p} /> },
    { key: "mode", header: "Mode", render: (p) => p.mode ?? "-" },
    { key: "qty", header: "Qty", align: "right", render: (p) => formatNumber(p.qty, 4) },
    {
      key: "manualQty",
      header: "Manual Added Qty",
      align: "right",
      render: (p) => formatNumber(p.manual_added_qty, 4),
    },
    {
      key: "entry",
      header: "Avg Entry",
      align: "right",
      render: (p) => formatPrice(p.avg_entry_price),
    },
    { key: "mark", header: "Mark", align: "right", render: (p) => formatPrice(p.mark_price) },
    {
      key: "upnl",
      header: "uPnL",
      align: "right",
      render: (p) => (
        <span className={pnlClass(p.unrealized_pnl)}>{formatNumber(p.unrealized_pnl)}</span>
      ),
    },
    {
      key: "upnlPct",
      header: "uPnL %",
      align: "right",
      render: (p) => (
        <span className={pnlClass(p.unrealized_pnl_percent)}>
          {p.unrealized_pnl_percent == null ? "-" : `${formatNumber(p.unrealized_pnl_percent)}%`}
        </span>
      ),
    },
    { key: "lev", header: "Lev", align: "right", render: (p) => p.leverage ?? "-" },
    { key: "entryMode", header: "Entry Mode", render: (p) => p.entry_mode ?? "-" },
    { key: "strategy", header: "Strategy", render: (p) => p.strategy_id ?? "-" },
    {
      key: "protection",
      header: "Protection",
      render: (p) => (
        <span className="flex items-center gap-1">
          <ProtectionBadge status={p.protection_status} />
          {p.mode === "LIVE" && p.protection_status !== "TPSL_OK" && (
            <TextBadge text="Check" tone="red" />
          )}
        </span>
      ),
    },
    { key: "sl", header: "SL", align: "right", render: (p) => formatPrice(p.stop_loss_price) },
    { key: "tp", header: "TP", align: "right", render: (p) => formatPrice(p.take_profit_price) },
    { key: "opened", header: "Opened At", render: (p) => formatDateTime(p.opened_at) },
  ];

  if (onClose) {
    columns.push({
      key: "actions",
      header: "Actions",
      render: (p) => (
        <Button variant="danger-outline" onClick={() => onClose(p.symbol)}>
          Close
        </Button>
      ),
    });
  }

  return (
    <DataTable
      columns={columns}
      rows={positions}
      rowKey={(p) => p.symbol}
      empty="No open positions."
    />
  );
}

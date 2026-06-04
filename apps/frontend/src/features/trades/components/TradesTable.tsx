import type { Trade } from "@/shared/api/types";
import { DataTable, type Column } from "@/shared/components/DataTable";
import { formatDateTime, formatNumber, formatPrice, pnlClass } from "@/shared/utils/format";

export function TradesTable({
  trades,
  onRowClick,
}: {
  trades: Trade[];
  onRowClick?: (t: Trade) => void;
}) {
  const columns: Column<Trade>[] = [
    { key: "tradeId", header: "Trade ID", render: (t) => t.trade_id ?? `#${t.id}` },
    { key: "symbol", header: "Symbol", render: (t) => t.symbol },
    {
      key: "side",
      header: "Side",
      render: (t) => (
        <span className={t.side === "LONG" ? "text-emerald-400" : "text-rose-400"}>{t.side}</span>
      ),
    },
    { key: "strategy", header: "Strategy", render: (t) => t.strategy_id ?? "-" },
    { key: "entryMode", header: "Entry Mode", render: (t) => t.entry_mode ?? "-" },
    { key: "mode", header: "Mode", render: (t) => t.mode ?? "-" },
    { key: "entry", header: "Entry", align: "right", render: (t) => formatPrice(t.entry_price) },
    { key: "exit", header: "Exit", align: "right", render: (t) => formatPrice(t.exit_price) },
    { key: "qty", header: "Qty", align: "right", render: (t) => formatNumber(t.qty, 4) },
    {
      key: "gross",
      header: "Gross PnL",
      align: "right",
      render: (t) => (
        <span className={pnlClass(t.gross_pnl)}>{formatNumber(t.gross_pnl)}</span>
      ),
    },
    { key: "fees", header: "Fees", align: "right", render: (t) => formatNumber(t.fees) },
    {
      key: "funding",
      header: "Funding",
      align: "right",
      render: (t) => formatNumber(t.funding_fees),
    },
    {
      key: "net",
      header: "Net PnL",
      align: "right",
      render: (t) => (
        <span className={pnlClass(t.net_pnl ?? t.realized_pnl)}>
          {formatNumber(t.net_pnl ?? t.realized_pnl)}
        </span>
      ),
    },
    { key: "r", header: "R", align: "right", render: (t) => formatNumber(t.r_multiple, 2) },
    { key: "reason", header: "Exit Reason", render: (t) => t.exit_reason ?? "-" },
    { key: "opened", header: "Opened At", render: (t) => formatDateTime(t.opened_at) },
    { key: "closed", header: "Closed At", render: (t) => formatDateTime(t.closed_at) },
  ];
  return (
    <DataTable
      columns={columns}
      rows={trades}
      rowKey={(t) => t.id}
      onRowClick={onRowClick}
      empty="No trades."
    />
  );
}

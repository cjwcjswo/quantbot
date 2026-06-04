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
    { key: "tradeId", header: "체결 ID", render: (t) => t.trade_id ?? `#${t.id}` },
    { key: "symbol", header: "종목", render: (t) => t.symbol },
    {
      key: "side",
      header: "방향",
      render: (t) => (
        <span className={t.side === "LONG" ? "text-emerald-400" : "text-rose-400"}>{t.side}</span>
      ),
    },
    { key: "strategy", header: "전략", render: (t) => t.strategy_id ?? "-" },
    { key: "entryMode", header: "진입 모드", render: (t) => t.entry_mode ?? "-" },
    { key: "mode", header: "모드", render: (t) => t.mode ?? "-" },
    { key: "entry", header: "진입가", align: "right", render: (t) => formatPrice(t.entry_price) },
    { key: "exit", header: "청산가", align: "right", render: (t) => formatPrice(t.exit_price) },
    { key: "qty", header: "수량", align: "right", render: (t) => formatNumber(t.qty, 4) },
    {
      key: "gross",
      header: "총손익",
      align: "right",
      render: (t) => (
        <span className={pnlClass(t.gross_pnl)}>{formatNumber(t.gross_pnl)}</span>
      ),
    },
    { key: "fees", header: "수수료", align: "right", render: (t) => formatNumber(t.fees) },
    {
      key: "funding",
      header: "펀딩비",
      align: "right",
      render: (t) => formatNumber(t.funding_fees),
    },
    {
      key: "net",
      header: "순손익",
      align: "right",
      render: (t) => (
        <span className={pnlClass(t.net_pnl ?? t.realized_pnl)}>
          {formatNumber(t.net_pnl ?? t.realized_pnl)}
        </span>
      ),
    },
    { key: "r", header: "R", align: "right", render: (t) => formatNumber(t.r_multiple, 2) },
    { key: "reason", header: "청산 사유", render: (t) => t.exit_reason ?? "-" },
    { key: "opened", header: "진입 시각", render: (t) => formatDateTime(t.opened_at) },
    { key: "closed", header: "청산 시각", render: (t) => formatDateTime(t.closed_at) },
  ];
  return (
    <DataTable
      columns={columns}
      rows={trades}
      rowKey={(t) => t.id}
      onRowClick={onRowClick}
      empty="체결 내역 없음"
    />
  );
}

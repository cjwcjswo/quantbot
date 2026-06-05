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
        <TextBadge text="⚠ 외부" tone="amber" />
      ) : (
        <TextBadge text={p.source} tone="slate" />
      )}
      {manual && <TextBadge text="수동 추가" tone="sky" />}
    </span>
  );
}

function leverageText(value: string | null): string {
  if (!value) return "-";
  const n = Number(value);
  if (Number.isNaN(n)) return value.endsWith("x") ? value : `${value}x`;
  return `${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}x`;
}

export function PositionsTable({
  positions,
  onClose,
}: {
  positions: Position[];
  onClose?: (symbol: string) => void;
}) {
  const columns: Column<Position>[] = [
    { key: "symbol", header: "종목", render: (p) => p.symbol },
    {
      key: "side",
      header: "방향",
      render: (p) => (
        <span className={p.side === "LONG" ? "text-emerald-400" : "text-rose-400"}>{p.side}</span>
      ),
    },
    { key: "source", header: "출처", render: (p) => <SourceCell p={p} /> },
    { key: "mode", header: "모드", render: (p) => p.mode ?? "-" },
    { key: "qty", header: "수량", align: "right", render: (p) => formatNumber(p.qty, 4) },
    {
      key: "manualQty",
      header: "수동 추가 수량",
      align: "right",
      render: (p) => formatNumber(p.manual_added_qty, 4),
    },
    {
      key: "entry",
      header: "평균 진입가",
      align: "right",
      render: (p) => formatPrice(p.avg_entry_price),
    },
    { key: "mark", header: "마크가", align: "right", render: (p) => formatPrice(p.mark_price) },
    {
      key: "upnl",
      header: "평가손익",
      align: "right",
      render: (p) => (
        <span className={pnlClass(p.unrealized_pnl)}>{formatNumber(p.unrealized_pnl)}</span>
      ),
    },
    {
      key: "upnlPct",
      header: "평가손익 %",
      align: "right",
      render: (p) => (
        <span className={pnlClass(p.unrealized_pnl_percent)}>
          {p.unrealized_pnl_percent == null ? "-" : `${formatNumber(p.unrealized_pnl_percent)}%`}
        </span>
      ),
    },
    { key: "lev", header: "레버리지", align: "right", render: (p) => leverageText(p.leverage) },
    { key: "entryMode", header: "진입 모드", render: (p) => p.entry_mode ?? "-" },
    { key: "strategy", header: "전략", render: (p) => p.strategy_id ?? "-" },
    {
      key: "protection",
      header: "보호",
      render: (p) => (
        <span className="flex items-center gap-1">
          <ProtectionBadge status={p.protection_status} />
          {p.mode === "LIVE" && p.protection_status !== "TPSL_OK" && (
            <TextBadge text="확인 필요" tone="red" />
          )}
        </span>
      ),
    },
    { key: "sl", header: "손절가", align: "right", render: (p) => formatPrice(p.stop_loss_price) },
    { key: "tp", header: "익절가", align: "right", render: (p) => formatPrice(p.take_profit_price) },
    { key: "opened", header: "진입 시각", render: (p) => formatDateTime(p.opened_at) },
  ];

  if (onClose) {
    columns.push({
      key: "actions",
      header: "작업",
      render: (p) => (
        <Button variant="danger-outline" onClick={() => onClose(p.symbol)}>
          청산
        </Button>
      ),
    });
  }

  return (
    <DataTable
      columns={columns}
      rows={positions}
      rowKey={(p) => p.symbol}
      empty="보유 중인 포지션이 없습니다."
    />
  );
}

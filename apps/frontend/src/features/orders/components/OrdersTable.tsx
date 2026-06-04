import type { Order } from "@/shared/api/types";
import { DataTable, type Column } from "@/shared/components/DataTable";
import { TextBadge } from "@/shared/components/Badges";
import { Button } from "@/shared/components/Button";
import { formatDateTime, formatNumber, formatPrice } from "@/shared/utils/format";

const STATUS_TONE: Record<string, string> = {
  NEW: "sky",
  PARTIALLY_FILLED: "sky",
  FILLED: "emerald",
  CANCELED: "slate",
  CANCELLED: "slate",
  REJECTED: "red",
  EXPIRED: "amber",
  FAILED: "red",
  UNKNOWN: "amber",
};

const CANCELABLE = new Set(["NEW", "PARTIALLY_FILLED", "UNKNOWN"]);

export function OrdersTable({
  orders,
  onCancel,
}: {
  orders: Order[];
  onCancel?: (order: Order) => void;
}) {
  const columns: Column<Order>[] = [
    { key: "order_id", header: "주문 ID", render: (o) => o.order_id ?? `#${o.id}` },
    { key: "symbol", header: "종목", render: (o) => o.symbol },
    { key: "side", header: "방향", render: (o) => o.side },
    { key: "type", header: "유형", render: (o) => o.order_type },
    {
      key: "status",
      header: "상태",
      render: (o) => <TextBadge text={o.status} tone={STATUS_TONE[o.status] ?? "slate"} />,
    },
    { key: "source", header: "출처", render: (o) => o.source ?? "-" },
    { key: "mode", header: "모드", render: (o) => o.mode ?? "-" },
    { key: "qty", header: "수량", align: "right", render: (o) => formatNumber(o.qty, 4) },
    {
      key: "filled",
      header: "체결량",
      align: "right",
      render: (o) => formatNumber(o.filled_qty, 4),
    },
    { key: "price", header: "가격", align: "right", render: (o) => formatPrice(o.price) },
    {
      key: "avg",
      header: "평균 체결가",
      align: "right",
      render: (o) => formatPrice(o.avg_fill_price),
    },
    { key: "reduce", header: "리듀스", render: (o) => (o.reduce_only ? "예" : "-") },
    { key: "created", header: "생성", render: (o) => formatDateTime(o.created_at) },
    { key: "updated", header: "수정", render: (o) => formatDateTime(o.updated_at) },
  ];

  if (onCancel) {
    columns.push({
      key: "actions",
      header: "작업",
      render: (o) =>
        CANCELABLE.has(o.status) && o.order_id ? (
          <Button variant="danger-outline" onClick={() => onCancel(o)}>
            취소
          </Button>
        ) : (
          <span className="text-slate-600">—</span>
        ),
    });
  }

  return <DataTable columns={columns} rows={orders} rowKey={(o) => o.id} empty="주문 없음" />;
}

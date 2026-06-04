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
    { key: "order_id", header: "Order ID", render: (o) => o.order_id ?? `#${o.id}` },
    { key: "symbol", header: "Symbol", render: (o) => o.symbol },
    { key: "side", header: "Side", render: (o) => o.side },
    { key: "type", header: "Type", render: (o) => o.order_type },
    {
      key: "status",
      header: "Status",
      render: (o) => <TextBadge text={o.status} tone={STATUS_TONE[o.status] ?? "slate"} />,
    },
    { key: "source", header: "Source", render: (o) => o.source ?? "-" },
    { key: "mode", header: "Mode", render: (o) => o.mode ?? "-" },
    { key: "qty", header: "Qty", align: "right", render: (o) => formatNumber(o.qty, 4) },
    {
      key: "filled",
      header: "Filled",
      align: "right",
      render: (o) => formatNumber(o.filled_qty, 4),
    },
    { key: "price", header: "Price", align: "right", render: (o) => formatPrice(o.price) },
    {
      key: "avg",
      header: "Avg Fill",
      align: "right",
      render: (o) => formatPrice(o.avg_fill_price),
    },
    { key: "reduce", header: "Reduce", render: (o) => (o.reduce_only ? "yes" : "-") },
    { key: "created", header: "Created", render: (o) => formatDateTime(o.created_at) },
    { key: "updated", header: "Updated", render: (o) => formatDateTime(o.updated_at) },
  ];

  if (onCancel) {
    columns.push({
      key: "actions",
      header: "Actions",
      render: (o) =>
        CANCELABLE.has(o.status) && o.order_id ? (
          <Button variant="danger-outline" onClick={() => onCancel(o)}>
            Cancel
          </Button>
        ) : (
          <span className="text-slate-600">—</span>
        ),
    });
  }

  return <DataTable columns={columns} rows={orders} rowKey={(o) => o.id} empty="No orders." />;
}

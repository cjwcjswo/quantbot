import { useState } from "react";
import { useOrders, useCancelOrder } from "@/features/orders/hooks";
import { OrdersTable } from "@/features/orders/components/OrdersTable";
import { Panel } from "@/shared/components/Panel";
import { SelectInput, TextInput } from "@/shared/components/Field";
import { ConfirmDialog } from "@/shared/components/ConfirmDialog";
import { ErrorState, LoadingState } from "@/shared/components/States";
import { ApiClientError } from "@/shared/api/client";
import type { Order } from "@/shared/api/types";

const STATUSES = ["NEW", "PARTIALLY_FILLED", "FILLED", "CANCELED", "REJECTED", "EXPIRED", "FAILED"];
const SOURCES = ["BOT", "EXTERNAL", "PAPER"];
const MODES = ["PAPER", "LIVE"];

export function OrdersPage() {
  const [symbol, setSymbol] = useState("");
  const [status, setStatus] = useState("");
  const [source, setSource] = useState("");
  const [mode, setMode] = useState("");
  const [cancelTarget, setCancelTarget] = useState<Order | null>(null);

  const { data, isLoading, error, refetch } = useOrders({
    symbol: symbol || undefined,
    status: status || undefined,
    source: source || undefined,
    mode: mode || undefined,
  });
  const cancel = useCancelOrder();

  return (
    <Panel title="Orders">
      <div className="mb-3 flex flex-wrap gap-3">
        <TextInput label="Symbol" value={symbol} onChange={setSymbol} placeholder="BTCUSDT" />
        <SelectInput label="Status" value={status} onChange={setStatus} options={STATUSES} />
        <SelectInput label="Source" value={source} onChange={setSource} options={SOURCES} />
        <SelectInput label="Mode" value={mode} onChange={setMode} options={MODES} />
      </div>

      {isLoading && <LoadingState />}
      {error && (
        <ErrorState
          message={error instanceof ApiClientError ? error.message : "Failed to load orders"}
          onRetry={() => refetch()}
        />
      )}
      {data && <OrdersTable orders={data.orders} onCancel={(o) => setCancelTarget(o)} />}

      <ConfirmDialog
        open={cancelTarget !== null}
        title="Cancel order"
        message={`Cancel order ${cancelTarget?.order_id ?? ""} (${cancelTarget?.symbol ?? ""})?`}
        confirmLabel="Cancel order"
        danger
        onCancel={() => setCancelTarget(null)}
        onConfirm={() => {
          if (cancelTarget?.order_id) cancel.mutate(cancelTarget.order_id);
          setCancelTarget(null);
        }}
      />
    </Panel>
  );
}

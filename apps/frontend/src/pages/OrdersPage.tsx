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
    <Panel title="주문">
      <div className="mb-3 flex flex-wrap gap-3">
        <TextInput label="종목" value={symbol} onChange={setSymbol} placeholder="BTCUSDT" />
        <SelectInput label="상태" value={status} onChange={setStatus} options={STATUSES} />
        <SelectInput label="출처" value={source} onChange={setSource} options={SOURCES} />
        <SelectInput label="모드" value={mode} onChange={setMode} options={MODES} />
      </div>

      {isLoading && <LoadingState />}
      {error && (
        <ErrorState
          message={error instanceof ApiClientError ? error.message : "주문을 불러오지 못했습니다"}
          onRetry={() => refetch()}
        />
      )}
      {data && <OrdersTable orders={data.orders} onCancel={(o) => setCancelTarget(o)} />}

      <ConfirmDialog
        open={cancelTarget !== null}
        title="주문 취소"
        message={`주문 ${cancelTarget?.order_id ?? ""} (${cancelTarget?.symbol ?? ""}) 을(를) 취소할까요?`}
        confirmLabel="주문 취소"
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

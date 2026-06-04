import { useState } from "react";
import { useTradeDetail } from "@/features/trades/hooks";
import { OrdersTable } from "@/features/orders/components/OrdersTable";
import { Drawer } from "@/shared/components/Drawer";
import { SeverityBadge } from "@/shared/components/Badges";
import { DataTable, type Column } from "@/shared/components/DataTable";
import { ErrorState, LoadingSkeleton } from "@/shared/components/States";
import { ApiClientError } from "@/shared/api/client";
import { formatDateTime, formatNumber, formatPrice, pnlClass } from "@/shared/utils/format";
import type { Fill, TimelineEvent } from "@/shared/api/types";

const FILL_COLUMNS: Column<Fill>[] = [
  { key: "side", header: "Side", render: (f) => f.side },
  { key: "price", header: "Price", align: "right", render: (f) => formatPrice(f.price) },
  { key: "qty", header: "Qty", align: "right", render: (f) => formatNumber(f.qty, 4) },
  { key: "fee", header: "Fee", align: "right", render: (f) => formatNumber(f.fee, 4) },
  { key: "slippage", header: "Slippage", align: "right", render: (f) => f.slippage ?? "-" },
];

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 py-0.5 text-sm">
      <span className="text-slate-400">{label}</span>
      <span className="tabular-nums text-slate-200">{value}</span>
    </div>
  );
}

function Timeline({ events }: { events: TimelineEvent[] }) {
  const [expanded, setExpanded] = useState<number | null>(null);
  if (events.length === 0) return <p className="text-sm text-slate-500">No timeline events.</p>;
  return (
    <ol className="space-y-2">
      {events.map((e, i) => (
        <li key={i} className="flex items-start gap-2 text-sm">
          <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-sky-500" />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="font-medium text-slate-200">{e.type}</span>
              {e.severity && <SeverityBadge severity={e.severity} />}
              {e.data && Object.keys(e.data).length > 0 && (
                <button
                  className="text-xs text-sky-400 hover:underline"
                  onClick={() => setExpanded(expanded === i ? null : i)}
                >
                  details
                </button>
              )}
            </div>
            <div className="text-xs text-slate-500">
              {formatDateTime(e.ts)} {e.message}
            </div>
            {expanded === i && (
              <pre className="mt-1 max-h-40 overflow-auto rounded border border-panelBorder bg-bg p-2 text-xs text-slate-300">
                {JSON.stringify(e.data ?? {}, null, 2)}
              </pre>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

export function TradeDetailDrawer({
  tradeId,
  onClose,
}: {
  tradeId: string | null;
  onClose: () => void;
}) {
  const { data, isLoading, error, refetch } = useTradeDetail(tradeId);

  return (
    <Drawer open={tradeId !== null} title={`Trade ${tradeId ?? ""}`} onClose={onClose}>
      {isLoading && <LoadingSkeleton />}
      {error && (
        <ErrorState
          message={error instanceof ApiClientError ? error.message : "Failed to load trade"}
          onRetry={() => refetch()}
        />
      )}
      {data && (
        <div className="space-y-5">
          <section>
            <h3 className="mb-1 text-xs uppercase tracking-wide text-slate-500">Trade</h3>
            <Field label="Symbol" value={data.trade.symbol} />
            <Field label="Side" value={data.trade.side} />
            <Field label="Strategy" value={data.trade.strategy_id ?? "-"} />
            <Field label="Entry Mode" value={data.trade.entry_mode ?? "-"} />
            <Field label="Mode" value={data.trade.mode ?? "-"} />
            <Field label="Entry" value={formatPrice(data.trade.entry_price)} />
            <Field label="Exit" value={formatPrice(data.trade.exit_price)} />
            <Field label="Qty" value={formatNumber(data.trade.qty, 4)} />
            <Field label="Leverage" value={data.trade.leverage ?? "-"} />
            <Field label="Fees" value={formatNumber(data.trade.fees)} />
            <Field
              label="Net PnL"
              value={
                <span className={pnlClass(data.trade.net_pnl ?? data.trade.realized_pnl)}>
                  {formatNumber(data.trade.net_pnl ?? data.trade.realized_pnl)}
                </span>
              }
            />
            <Field label="R Multiple" value={formatNumber(data.trade.r_multiple, 2)} />
            <Field label="Exit Reason" value={data.trade.exit_reason ?? "-"} />
            <Field label="Opened" value={formatDateTime(data.trade.opened_at)} />
            <Field label="Closed" value={formatDateTime(data.trade.closed_at)} />
          </section>

          <section>
            <h3 className="mb-2 text-xs uppercase tracking-wide text-slate-500">Timeline</h3>
            <Timeline events={data.timeline} />
          </section>

          <section>
            <h3 className="mb-1 text-xs uppercase tracking-wide text-slate-500">
              Orders ({data.orders.length})
            </h3>
            <OrdersTable orders={data.orders} />
          </section>

          <section>
            <h3 className="mb-1 text-xs uppercase tracking-wide text-slate-500">
              Fills ({data.fills.length})
            </h3>
            <DataTable
              columns={FILL_COLUMNS}
              rows={data.fills}
              rowKey={(f) => f.id}
              empty="No fills."
            />
            <p className="mt-1 text-xs text-slate-500">
              {data.protection_events.length} protection events ·{" "}
              {data.manual_interventions.length} manual interventions ·{" "}
              {data.risk_events.length} risk events.
            </p>
          </section>

          <section>
            <h3 className="mb-1 text-xs uppercase tracking-wide text-slate-500">Raw</h3>
            <pre className="max-h-60 overflow-auto rounded border border-panelBorder bg-bg p-3 text-xs text-slate-400">
              {JSON.stringify(data.trade, null, 2)}
            </pre>
          </section>
        </div>
      )}
    </Drawer>
  );
}

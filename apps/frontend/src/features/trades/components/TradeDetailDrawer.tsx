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
  { key: "side", header: "방향", render: (f) => f.side },
  { key: "price", header: "가격", align: "right", render: (f) => formatPrice(f.price) },
  { key: "qty", header: "수량", align: "right", render: (f) => formatNumber(f.qty, 4) },
  { key: "fee", header: "수수료", align: "right", render: (f) => formatNumber(f.fee, 4) },
  { key: "slippage", header: "슬리피지", align: "right", render: (f) => f.slippage ?? "-" },
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
  if (events.length === 0) return <p className="text-sm text-slate-500">타임라인 이벤트 없음</p>;
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
                  상세
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
    <Drawer open={tradeId !== null} title={`체결 ${tradeId ?? ""}`} onClose={onClose}>
      {isLoading && <LoadingSkeleton />}
      {error && (
        <ErrorState
          message={error instanceof ApiClientError ? error.message : "체결 정보를 불러오지 못했습니다"}
          onRetry={() => refetch()}
        />
      )}
      {data && (
        <div className="space-y-5">
          <section>
            <h3 className="mb-1 text-xs uppercase tracking-wide text-slate-500">체결</h3>
            <Field label="종목" value={data.trade.symbol} />
            <Field label="방향" value={data.trade.side} />
            <Field label="전략" value={data.trade.strategy_id ?? "-"} />
            <Field label="진입 모드" value={data.trade.entry_mode ?? "-"} />
            <Field label="모드" value={data.trade.mode ?? "-"} />
            <Field label="진입가" value={formatPrice(data.trade.entry_price)} />
            <Field label="청산가" value={formatPrice(data.trade.exit_price)} />
            <Field label="수량" value={formatNumber(data.trade.qty, 4)} />
            <Field label="레버리지" value={data.trade.leverage ?? "-"} />
            <Field label="수수료" value={formatNumber(data.trade.fees)} />
            <Field
              label="순손익"
              value={
                <span className={pnlClass(data.trade.net_pnl ?? data.trade.realized_pnl)}>
                  {formatNumber(data.trade.net_pnl ?? data.trade.realized_pnl)}
                </span>
              }
            />
            <Field label="R 배수" value={formatNumber(data.trade.r_multiple, 2)} />
            <Field label="청산 사유" value={data.trade.exit_reason ?? "-"} />
            <Field label="진입 시각" value={formatDateTime(data.trade.opened_at)} />
            <Field label="청산 시각" value={formatDateTime(data.trade.closed_at)} />
          </section>

          <section>
            <h3 className="mb-2 text-xs uppercase tracking-wide text-slate-500">타임라인</h3>
            <Timeline events={data.timeline} />
          </section>

          <section>
            <h3 className="mb-1 text-xs uppercase tracking-wide text-slate-500">
              주문 ({data.orders.length})
            </h3>
            <OrdersTable orders={data.orders} />
          </section>

          <section>
            <h3 className="mb-1 text-xs uppercase tracking-wide text-slate-500">
              체결 ({data.fills.length})
            </h3>
            <DataTable
              columns={FILL_COLUMNS}
              rows={data.fills}
              rowKey={(f) => f.id}
              empty="체결 없음"
            />
            <p className="mt-1 text-xs text-slate-500">
              보호 이벤트 {data.protection_events.length} ·{" "}
              수동개입 {data.manual_interventions.length} ·{" "}
              리스크 이벤트 {data.risk_events.length}
            </p>
          </section>

          <section>
            <h3 className="mb-1 text-xs uppercase tracking-wide text-slate-500">원본</h3>
            <pre className="max-h-60 overflow-auto rounded border border-panelBorder bg-bg p-3 text-xs text-slate-400">
              {JSON.stringify(data.trade, null, 2)}
            </pre>
          </section>
        </div>
      )}
    </Drawer>
  );
}

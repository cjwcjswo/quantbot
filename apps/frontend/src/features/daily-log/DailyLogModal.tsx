import { useMemo, useState } from "react";
import type { BotMode, Severity, Trade } from "@/shared/api/types";
import { useDailyLog } from "./hooks";
import { Modal } from "@/shared/components/Modal";
import { MetricCard } from "@/shared/components/MetricCard";
import { ErrorState, LoadingSkeleton } from "@/shared/components/States";
import { TradesTable } from "@/features/trades/components/TradesTable";
import { TradeDetailDrawer } from "@/features/trades/components/TradeDetailDrawer";
import { EventsTable } from "@/features/events/components/EventsTable";
import { ApiClientError } from "@/shared/api/client";
import { pnlClass } from "@/shared/utils/format";

const TABS = ["Summary", "Trades", "Events", "Manual", "Risk", "Protection", "Raw"] as const;
type Tab = (typeof TABS)[number];
const SEVERITIES: Severity[] = ["INFO", "WARNING", "ERROR", "CRITICAL"];
type SummaryRow = { key: string; trades: number; net: number };

function num(value: string | null | undefined): number {
  const n = Number(value ?? 0);
  return Number.isFinite(n) ? n : 0;
}

function summarizeTrades(trades: Trade[], field: "symbol" | "strategy_id" | "entry_mode") {
  const map = new Map<string, SummaryRow>();
  for (const trade of trades) {
    const key = trade[field] ?? "-";
    const row = map.get(key) ?? { key, trades: 0, net: 0 };
    row.trades += 1;
    row.net += num(trade.net_pnl ?? trade.realized_pnl);
    map.set(key, row);
  }
  return [...map.values()].sort((a, b) => Math.abs(b.net) - Math.abs(a.net));
}

function JsonList({ rows }: { rows: Record<string, unknown>[] }) {
  if (rows.length === 0) return <p className="text-sm text-slate-500">None.</p>;
  return (
    <pre className="max-h-80 overflow-auto rounded border border-panelBorder bg-bg p-3 text-xs text-slate-300">
      {JSON.stringify(rows, null, 2)}
    </pre>
  );
}

function SummaryTable({ title, rows }: { title: string; rows: SummaryRow[] }) {
  if (rows.length === 0) return null;
  return (
    <section>
      <h3 className="mb-1 text-xs uppercase tracking-wide text-slate-500">{title}</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="border-b border-panelBorder text-xs uppercase text-slate-500">
            <tr>
              <th className="px-2 py-1 text-left">Key</th>
              <th className="px-2 py-1 text-right">Trades</th>
              <th className="px-2 py-1 text-right">Net PnL</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key} className="border-b border-panelBorder/60">
                <td className="px-2 py-1">{row.key}</td>
                <td className="px-2 py-1 text-right tabular-nums">{row.trades}</td>
                <td className={`px-2 py-1 text-right tabular-nums ${pnlClass(row.net)}`}>
                  {row.net.toFixed(2)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function DailyLogModal({
  date,
  mode,
  onClose,
}: {
  date: string | null;
  mode?: BotMode;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<Tab>("Summary");
  const [tradeId, setTradeId] = useState<string | null>(null);
  const [severity, setSeverity] = useState<Severity | "">("");
  const { data, isLoading, error, refetch } = useDailyLog(date, mode);
  const summaryRows = useMemo(() => {
    const trades = data?.sections.trades ?? [];
    return {
      byStrategy: summarizeTrades(trades, "strategy_id"),
      bySymbol: summarizeTrades(trades, "symbol"),
      byEntryMode: summarizeTrades(trades, "entry_mode"),
    };
  }, [data]);
  const filteredEvents = useMemo(() => {
    const events = data?.sections.events ?? [];
    return severity ? events.filter((event) => event.severity === severity) : events;
  }, [data, severity]);

  return (
    <Modal
      open={date !== null}
      title={`Daily Log — ${date ?? ""} / ${mode ?? "ALL"}`}
      onClose={onClose}
      wide
    >
      {isLoading && <LoadingSkeleton rows={6} />}
      {error && (
        <ErrorState
          message={error instanceof ApiClientError ? error.message : "Failed to load daily log"}
          onRetry={() => refetch()}
        />
      )}
      {data && (
        <div>
          <div className="mb-3 flex flex-wrap gap-1 border-b border-panelBorder pb-2">
            {TABS.map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`rounded px-3 py-1 text-sm ${
                  tab === t ? "bg-sky-600/20 text-sky-300" : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {t}
              </button>
            ))}
          </div>

          {tab === "Summary" && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <MetricCard label="Trades" value={data.summary.trade_count} />
                <MetricCard label="Win / Loss" value={`${data.summary.win_count} / ${data.summary.loss_count}`} />
                <MetricCard
                  label="Win Rate"
                  value={
                    data.summary.trade_count === 0
                      ? "-"
                      : `${((data.summary.win_count / data.summary.trade_count) * 100).toFixed(1)}%`
                  }
                />
                <MetricCard
                  label="Net PnL"
                  value={data.summary.net_pnl}
                  valueClassName={pnlClass(data.summary.net_pnl)}
                />
                <MetricCard label="Realized" value={data.summary.realized_pnl} />
                <MetricCard label="Unrealized" value={data.summary.unrealized_pnl} />
                <MetricCard label="Fees" value={data.summary.fees} />
                <MetricCard label="Max Drawdown" value={data.summary.max_drawdown} />
                <MetricCard label="Manual Interv." value={data.summary.manual_intervention_count} />
                <MetricCard label="TP/SL Failed" value={data.summary.tpsl_failed_count} />
                <MetricCard label="Emergency" value={data.summary.emergency_count} />
              </div>
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
                <SummaryTable title="Strategy PnL" rows={summaryRows.byStrategy} />
                <SummaryTable title="Symbol PnL" rows={summaryRows.bySymbol} />
                <SummaryTable title="Entry Mode PnL" rows={summaryRows.byEntryMode} />
              </div>
            </div>
          )}
          {tab === "Trades" && (
            <TradesTable
              trades={data.sections.trades}
              onRowClick={(t) => t.trade_id && setTradeId(t.trade_id)}
            />
          )}
          {tab === "Events" && (
            <div className="space-y-3">
              <div className="flex flex-wrap gap-1">
                <button
                  onClick={() => setSeverity("")}
                  className={`rounded px-3 py-1 text-sm ${
                    severity === "" ? "bg-sky-600/20 text-sky-300" : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  All
                </button>
                {SEVERITIES.map((s) => (
                  <button
                    key={s}
                    onClick={() => setSeverity(s)}
                    className={`rounded px-3 py-1 text-sm ${
                      severity === s ? "bg-sky-600/20 text-sky-300" : "text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    {s}
                  </button>
                ))}
              </div>
              <EventsTable events={filteredEvents} />
            </div>
          )}
          {tab === "Manual" && <JsonList rows={data.sections.manual_interventions} />}
          {tab === "Risk" && <JsonList rows={data.sections.risk_events} />}
          {tab === "Protection" && <JsonList rows={data.sections.protection_events} />}
          {tab === "Raw" && (
            <pre className="max-h-96 overflow-auto rounded border border-panelBorder bg-bg p-3 text-xs text-slate-400">
              {JSON.stringify(data, null, 2)}
            </pre>
          )}

          <TradeDetailDrawer tradeId={tradeId} onClose={() => setTradeId(null)} />
        </div>
      )}
    </Modal>
  );
}

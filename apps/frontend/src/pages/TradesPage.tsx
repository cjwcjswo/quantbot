import { useState } from "react";
import { useTrades } from "@/features/trades/hooks";
import { TradesTable } from "@/features/trades/components/TradesTable";
import { TradeDetailDrawer } from "@/features/trades/components/TradeDetailDrawer";
import { Panel } from "@/shared/components/Panel";
import { SelectInput, TextInput } from "@/shared/components/Field";
import { ErrorState, LoadingState } from "@/shared/components/States";
import { ApiClientError } from "@/shared/api/client";

const ENTRY_MODES = ["PRE_BREAKOUT_SCOUT", "BREAKOUT_CONFIRM", "RETEST_CONFIRM"];
const MODES = ["PAPER", "LIVE"];
const PNL = ["positive", "negative"];

export function TradesPage() {
  const [symbol, setSymbol] = useState("");
  const [strategy, setStrategy] = useState("");
  const [entryMode, setEntryMode] = useState("");
  const [mode, setMode] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [pnl, setPnl] = useState("");
  const [exitReason, setExitReason] = useState("");
  const [tradeId, setTradeId] = useState<string | null>(null);

  const { data, isLoading, error, refetch } = useTrades({
    symbol: symbol || undefined,
    strategy_id: strategy || undefined,
    entry_mode: entryMode || undefined,
    mode: mode || undefined,
    from: from || undefined,
    to: to || undefined,
    pnl: pnl || undefined,
    exit_reason: exitReason || undefined,
  });

  return (
    <Panel title="Trades">
      <div className="mb-3 flex flex-wrap gap-3">
        <TextInput label="Symbol" value={symbol} onChange={setSymbol} placeholder="BTCUSDT" />
        <TextInput
          label="Strategy"
          value={strategy}
          onChange={setStrategy}
          placeholder="trend_following"
        />
        <SelectInput
          label="Entry Mode"
          value={entryMode}
          onChange={setEntryMode}
          options={ENTRY_MODES}
        />
        <SelectInput label="Mode" value={mode} onChange={setMode} options={MODES} />
        <TextInput label="From" value={from} onChange={setFrom} placeholder="2026-06-01" />
        <TextInput label="To" value={to} onChange={setTo} placeholder="2026-06-30" />
        <SelectInput label="PnL" value={pnl} onChange={setPnl} options={PNL} />
        <TextInput
          label="Exit Reason"
          value={exitReason}
          onChange={setExitReason}
          placeholder="STOP_LOSS"
        />
      </div>

      {isLoading && <LoadingState />}
      {error && (
        <ErrorState
          message={error instanceof ApiClientError ? error.message : "Failed to load trades"}
          onRetry={() => refetch()}
        />
      )}
      {data && (
        <TradesTable
          trades={data.trades}
          onRowClick={(t) => t.trade_id && setTradeId(t.trade_id)}
        />
      )}

      <TradeDetailDrawer tradeId={tradeId} onClose={() => setTradeId(null)} />
    </Panel>
  );
}

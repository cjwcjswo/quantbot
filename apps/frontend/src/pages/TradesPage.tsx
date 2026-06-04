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
    <Panel title="체결내역">
      <div className="mb-3 flex flex-wrap gap-3">
        <TextInput label="종목" value={symbol} onChange={setSymbol} placeholder="BTCUSDT" />
        <TextInput
          label="전략"
          value={strategy}
          onChange={setStrategy}
          placeholder="trend_following"
        />
        <SelectInput
          label="진입 모드"
          value={entryMode}
          onChange={setEntryMode}
          options={ENTRY_MODES}
        />
        <SelectInput label="모드" value={mode} onChange={setMode} options={MODES} />
        <TextInput label="시작일" value={from} onChange={setFrom} placeholder="2026-06-01" />
        <TextInput label="종료일" value={to} onChange={setTo} placeholder="2026-06-30" />
        <SelectInput label="손익" value={pnl} onChange={setPnl} options={PNL} />
        <TextInput
          label="청산 사유"
          value={exitReason}
          onChange={setExitReason}
          placeholder="STOP_LOSS"
        />
      </div>

      {isLoading && <LoadingState />}
      {error && (
        <ErrorState
          message={error instanceof ApiClientError ? error.message : "체결 내역을 불러오지 못했습니다"}
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

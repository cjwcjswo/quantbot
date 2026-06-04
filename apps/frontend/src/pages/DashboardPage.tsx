import { useState } from "react";
import { useBotStatus } from "@/features/bot-status/hooks";
import { usePnlSummary, usePnlDaily } from "@/features/pnl/hooks";
import { usePositions } from "@/features/positions/hooks";
import { useOrders } from "@/features/orders/hooks";
import { useTrades } from "@/features/trades/hooks";
import { useEvents } from "@/features/events/hooks";
import { CommandBar } from "@/features/commands/components/CommandBar";
import { PnlChart } from "@/features/pnl/components/PnlChart";
import { PositionsTable } from "@/features/positions/components/PositionsTable";
import { OrdersTable } from "@/features/orders/components/OrdersTable";
import { TradesTable } from "@/features/trades/components/TradesTable";
import { EventsTable } from "@/features/events/components/EventsTable";
import { TradeDetailDrawer } from "@/features/trades/components/TradeDetailDrawer";
import { Calendar } from "@/features/daily-log/Calendar";
import { DailyLogModal } from "@/features/daily-log/DailyLogModal";
import { MetricCard } from "@/shared/components/MetricCard";
import { Panel } from "@/shared/components/Panel";
import { Button } from "@/shared/components/Button";
import { ModeBadge, StatusBadge } from "@/shared/components/Badges";
import { formatNumber, pnlClass, statusText, timeAgo } from "@/shared/utils/format";

export function DashboardPage() {
  const status = useBotStatus();
  const pnl = usePnlSummary();
  const daily = usePnlDaily();
  const positions = usePositions();
  const orders = useOrders();
  const trades = useTrades();
  const events = useEvents();
  const [tradeId, setTradeId] = useState<string | null>(null);
  const [logDate, setLogDate] = useState<string | null>(null);

  const s = status.data;
  const p = pnl.data;
  const openPositions = positions.data?.positions ?? [];

  return (
    <div className="space-y-4">
      <Panel title="Controls">
        <CommandBar />
      </Panel>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <MetricCard label="Bot State" value={s ? <StatusBadge state={s.state} /> : "—"} />
        <MetricCard label="Mode" value={<ModeBadge mode={s?.mode ?? null} />} />
        <MetricCard label="Equity" value={formatNumber(p?.equity)} />
        <MetricCard
          label="Daily Net PnL"
          value={formatNumber(p?.daily_net_pnl)}
          valueClassName={pnlClass(p?.daily_net_pnl)}
        />
        <MetricCard label="Open Positions" value={openPositions.length} />
        <MetricCard label="Open Risk" value={statusText(s?.risk_status, "—")} />
        <MetricCard
          label="Realized"
          value={formatNumber(p?.realized_pnl)}
          valueClassName={pnlClass(p?.realized_pnl)}
        />
        <MetricCard
          label="Unrealized"
          value={formatNumber(p?.unrealized_pnl)}
          valueClassName={pnlClass(p?.unrealized_pnl)}
        />
        <MetricCard label="Fees" value={formatNumber(p?.fees)} />
        <MetricCard label="Funding" value={formatNumber(p?.funding_fees)} />
        <MetricCard label="Heartbeat" value={timeAgo(s?.heartbeat_at)} />
        <MetricCard label="TP/SL Protection" value={statusText(s?.protection_status, "—")} />
        <MetricCard label="Reconciliation" value={statusText(s?.reconciliation_status, "—")} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Panel title="PnL (daily net)" className="lg:col-span-2">
          <PnlChart daily={daily.data?.daily ?? []} />
        </Panel>
        <Panel
          title="Daily Log"
          actions={
            <Button variant="secondary" onClick={() => setLogDate(new Date().toISOString().slice(0, 10))}>
              Today
            </Button>
          }
        >
          <Calendar mode={s?.mode ?? undefined} onSelectDate={setLogDate} />
        </Panel>
      </div>

      <Panel title="Current Positions">
        <PositionsTable positions={openPositions} />
      </Panel>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel title="Recent Orders">
          <OrdersTable orders={(orders.data?.orders ?? []).slice(0, 8)} />
        </Panel>
        <Panel title="Recent Trades">
          <TradesTable
            trades={(trades.data?.trades ?? []).slice(0, 8)}
            onRowClick={(t) => t.trade_id && setTradeId(t.trade_id)}
          />
        </Panel>
      </div>

      <Panel title="Recent Events">
        <EventsTable events={(events.data?.events ?? []).slice(0, 12)} />
      </Panel>

      <TradeDetailDrawer tradeId={tradeId} onClose={() => setTradeId(null)} />
      <DailyLogModal date={logDate} mode={s?.mode ?? undefined} onClose={() => setLogDate(null)} />
    </div>
  );
}

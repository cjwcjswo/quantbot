import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useBotStatus } from "@/features/bot-status/hooks";
import { usePnlSummary, usePnlDaily } from "@/features/pnl/hooks";
import { usePositions } from "@/features/positions/hooks";
import { useWatchlist } from "@/features/watchlist/hooks";
import { useOrders } from "@/features/orders/hooks";
import { useTrades } from "@/features/trades/hooks";
import { useEvents } from "@/features/events/hooks";
import { CommandBar } from "@/features/commands/components/CommandBar";
import { PnlChart } from "@/features/pnl/components/PnlChart";
import { PositionsTable } from "@/features/positions/components/PositionsTable";
import { WatchlistTable } from "@/features/watchlist/components/WatchlistTable";
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
  const navigate = useNavigate();
  const status = useBotStatus();
  const pnl = usePnlSummary();
  const daily = usePnlDaily();
  const positions = usePositions();
  const watchlist = useWatchlist();
  const orders = useOrders();
  const trades = useTrades();
  const events = useEvents();
  const [tradeId, setTradeId] = useState<string | null>(null);
  const [logDate, setLogDate] = useState<string | null>(null);

  const s = status.data;
  const p = pnl.data;
  const openPositions = positions.data?.positions ?? [];
  const watchEntries = watchlist.data?.watchlist ?? [];

  return (
    <div className="space-y-4">
      <Panel title="제어">
        <CommandBar />
      </Panel>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <MetricCard label="봇 상태" value={s ? <StatusBadge state={s.state} /> : "—"} />
        <MetricCard label="모드" value={<ModeBadge mode={s?.mode ?? null} />} />
        <MetricCard label="자산" value={formatNumber(p?.equity)} />
        <MetricCard
          label="일일 순손익"
          value={formatNumber(p?.daily_net_pnl)}
          valueClassName={pnlClass(p?.daily_net_pnl)}
        />
        <MetricCard label="보유 포지션" value={openPositions.length} />
        <MetricCard label="리스크" value={statusText(s?.risk_status, "—")} />
        <MetricCard
          label="실현손익"
          value={formatNumber(p?.realized_pnl)}
          valueClassName={pnlClass(p?.realized_pnl)}
        />
        <MetricCard
          label="미실현손익"
          value={formatNumber(p?.unrealized_pnl)}
          valueClassName={pnlClass(p?.unrealized_pnl)}
        />
        <MetricCard label="수수료" value={formatNumber(p?.fees)} />
        <MetricCard label="펀딩비" value={formatNumber(p?.funding_fees)} />
        <MetricCard label="하트비트" value={timeAgo(s?.heartbeat_at)} />
        <MetricCard label="TP/SL 보호" value={statusText(s?.protection_status, "—")} />
        <MetricCard label="동기화" value={statusText(s?.reconciliation_status, "—")} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Panel title="손익 (일일 순손익)" className="lg:col-span-2">
          <PnlChart daily={daily.data?.daily ?? []} />
        </Panel>
        <Panel
          title="일일 로그"
          actions={
            <Button variant="secondary" onClick={() => setLogDate(new Date().toISOString().slice(0, 10))}>
              오늘
            </Button>
          }
        >
          <Calendar mode={s?.mode ?? undefined} onSelectDate={setLogDate} />
        </Panel>
      </div>

      <Panel title="현재 포지션">
        <PositionsTable positions={openPositions} />
      </Panel>

      <Panel
        title="감시 종목 (진입 후보)"
        actions={
          <Button variant="secondary" onClick={() => navigate("/watchlist")}>
            전체 보기
          </Button>
        }
      >
        <WatchlistTable entries={watchEntries.slice(0, 8)} />
      </Panel>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel title="최근 주문">
          <OrdersTable orders={(orders.data?.orders ?? []).slice(0, 8)} />
        </Panel>
        <Panel title="최근 체결">
          <TradesTable
            trades={(trades.data?.trades ?? []).slice(0, 8)}
            onRowClick={(t) => t.trade_id && setTradeId(t.trade_id)}
          />
        </Panel>
      </div>

      <Panel title="최근 이벤트">
        <EventsTable
          events={(events.data?.events ?? []).slice(0, 12)}
          orders={orders.data?.orders ?? []}
        />
      </Panel>

      <TradeDetailDrawer tradeId={tradeId} onClose={() => setTradeId(null)} />
      <DailyLogModal date={logDate} mode={s?.mode ?? undefined} onClose={() => setLogDate(null)} />
    </div>
  );
}

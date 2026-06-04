import type { WatchEntry, WatchReadiness, WatchTrend } from "@/shared/api/types";
import { DataTable, type Column } from "@/shared/components/DataTable";
import { TextBadge } from "@/shared/components/Badges";
import { formatNumber, formatPrice } from "@/shared/utils/format";

const READINESS_TONE: Record<WatchReadiness, string> = {
  BREAKOUT: "emerald",
  NEAR: "sky",
  SCOUT_ZONE: "amber",
  WATCHING: "slate",
  NO_SIGNAL: "slate",
};

const READINESS_LABEL: Record<WatchReadiness, string> = {
  BREAKOUT: "Breakout",
  NEAR: "Near",
  SCOUT_ZONE: "Scout zone",
  WATCHING: "Watching",
  NO_SIGNAL: "No signal",
};

export function ReadinessBadge({ readiness }: { readiness: WatchReadiness }) {
  return <TextBadge text={READINESS_LABEL[readiness] ?? readiness} tone={READINESS_TONE[readiness] ?? "slate"} />;
}

function DirectionCell({ e }: { e: WatchEntry }) {
  if (e.direction === "LONG") return <span className="font-medium text-emerald-400">LONG</span>;
  if (e.direction === "SHORT") return <span className="font-medium text-rose-400">SHORT</span>;
  return <span className="text-slate-500">—</span>;
}

const TREND_GLYPH: Record<WatchTrend, string> = { UP: "▲", DOWN: "▼", FLAT: "—" };
const TREND_CLASS: Record<WatchTrend, string> = {
  UP: "text-emerald-400",
  DOWN: "text-rose-400",
  FLAT: "text-slate-500",
};

function TrendCell({ trend }: { trend: WatchTrend }) {
  return (
    <span className={TREND_CLASS[trend] ?? "text-slate-500"}>
      {TREND_GLYPH[trend] ?? "—"} {trend}
    </span>
  );
}

// Percent that price must still move to reach the breakout boundary (signed: a
// negative value means price is already beyond it).
function distancePct(e: WatchEntry): string {
  if (e.distance_to_breakout_pct == null) return "—";
  const n = Number(e.distance_to_breakout_pct);
  if (Number.isNaN(n)) return "—";
  return `${n >= 0 ? "" : "+"}${formatNumber(-n, 2)}%`;
}

export function WatchlistTable({ entries }: { entries: WatchEntry[] }) {
  const columns: Column<WatchEntry>[] = [
    { key: "symbol", header: "Symbol", render: (e) => e.symbol },
    { key: "direction", header: "Lean", render: (e) => <DirectionCell e={e} /> },
    { key: "readiness", header: "Readiness", render: (e) => <ReadinessBadge readiness={e.readiness} /> },
    {
      key: "toBreakout",
      header: "To Breakout",
      align: "right",
      render: (e) => distancePct(e),
    },
    {
      key: "score",
      header: "Score",
      align: "right",
      render: (e) => (e.signal_score == null ? "—" : formatNumber(e.signal_score, 1)),
    },
    { key: "trend", header: "15m Trend", render: (e) => <TrendCell trend={e.trend} /> },
    { key: "price", header: "Price", align: "right", render: (e) => formatPrice(e.last_price) },
    { key: "rsi", header: "RSI(1m)", align: "right", render: (e) => formatNumber(e.rsi, 1) },
    {
      key: "atr",
      header: "ATR%",
      align: "right",
      render: (e) => (e.atr_percent == null ? "—" : `${formatNumber(e.atr_percent, 2)}%`),
    },
    { key: "vol", header: "Vol×", align: "right", render: (e) => formatNumber(e.volume_ratio, 2) },
    {
      key: "reason",
      header: "Signal",
      render: (e) => (
        <span className="text-slate-400" title={e.signal_reason ?? undefined}>
          {e.signal_reason ?? "—"}
        </span>
      ),
    },
  ];

  return (
    <DataTable
      columns={columns}
      rows={entries}
      rowKey={(e) => e.symbol}
      empty="No symbols being watched. The bot scans the universe only while RUNNING."
    />
  );
}

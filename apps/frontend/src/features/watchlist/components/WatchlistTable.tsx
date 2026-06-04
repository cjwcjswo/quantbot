import type { WatchEntry, WatchReadiness, WatchTrend } from "@/shared/api/types";
import { DataTable, type Column } from "@/shared/components/DataTable";
import { TextBadge } from "@/shared/components/Badges";
import { cn } from "@/shared/utils/cn";
import { formatNumber, formatPrice } from "@/shared/utils/format";

const READINESS_TONE: Record<WatchReadiness, string> = {
  BREAKOUT: "emerald",
  NEAR: "sky",
  SCOUT_ZONE: "amber",
  WATCHING: "slate",
  NO_SIGNAL: "slate",
};

const READINESS_LABEL: Record<WatchReadiness, string> = {
  BREAKOUT: "돌파",
  NEAR: "임박",
  SCOUT_ZONE: "관망권",
  WATCHING: "감시중",
  NO_SIGNAL: "신호없음",
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
const TREND_LABEL: Record<WatchTrend, string> = { UP: "상승", DOWN: "하락", FLAT: "횡보" };
const TREND_CLASS: Record<WatchTrend, string> = {
  UP: "text-emerald-400",
  DOWN: "text-rose-400",
  FLAT: "text-slate-500",
};

function TrendCell({ trend }: { trend: WatchTrend }) {
  return (
    <span className={TREND_CLASS[trend] ?? "text-slate-500"}>
      {TREND_GLYPH[trend] ?? "—"} {TREND_LABEL[trend] ?? trend}
    </span>
  );
}

// 0~100: 진입(돌파) 트리거까지 얼마나 가까운지. 돌파 박스 경계까지 남은 ATR 거리로 환산
// (남은 거리 0 → 100%, 1.2 ATR 이상 → 0%). 신호가 없으면 0%.
function entryProgress(e: WatchEntry): number {
  if (e.direction === "NONE" || e.readiness === "NO_SIGNAL") return 0;
  if (e.readiness === "BREAKOUT") return 100;
  const d = e.distance_atr == null ? NaN : Number(e.distance_atr);
  if (Number.isNaN(d)) {
    return e.readiness === "NEAR" ? 85 : e.readiness === "SCOUT_ZONE" ? 60 : 30;
  }
  const CAP = 1.2; // ATR
  return Math.max(0, Math.min(100, Math.round((1 - d / CAP) * 100)));
}

const BAR_TONE: Record<WatchReadiness, string> = {
  BREAKOUT: "bg-emerald-500",
  NEAR: "bg-sky-500",
  SCOUT_ZONE: "bg-amber-500",
  WATCHING: "bg-slate-500",
  NO_SIGNAL: "bg-slate-700",
};

function EntryProgressBar({ e }: { e: WatchEntry }) {
  const pct = entryProgress(e);
  const tone = e.direction === "NONE" ? "bg-slate-700" : BAR_TONE[e.readiness] ?? "bg-slate-500";
  const title =
    e.distance_atr != null ? `돌파까지 ${formatNumber(e.distance_atr, 2)} ATR` : "신호 없음";
  return (
    <div className="flex items-center gap-2" title={title}>
      <div className="h-2 w-24 overflow-hidden rounded-full bg-slate-800">
        <div className={cn("h-full rounded-full transition-all", tone)} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-9 text-right tabular-nums text-xs text-slate-400">{pct}%</span>
    </div>
  );
}

export function WatchlistTable({ entries }: { entries: WatchEntry[] }) {
  const columns: Column<WatchEntry>[] = [
    { key: "symbol", header: "종목", render: (e) => e.symbol },
    { key: "direction", header: "방향", render: (e) => <DirectionCell e={e} /> },
    { key: "progress", header: "진입 임박도", render: (e) => <EntryProgressBar e={e} /> },
    { key: "readiness", header: "상태", render: (e) => <ReadinessBadge readiness={e.readiness} /> },
    {
      key: "score",
      header: "점수",
      align: "right",
      render: (e) => (e.signal_score == null ? "—" : formatNumber(e.signal_score, 1)),
    },
    { key: "trend", header: "15m 추세", render: (e) => <TrendCell trend={e.trend} /> },
    { key: "price", header: "가격", align: "right", render: (e) => formatPrice(e.last_price) },
    { key: "rsi", header: "RSI(1m)", align: "right", render: (e) => formatNumber(e.rsi, 1) },
    {
      key: "atr",
      header: "ATR%",
      align: "right",
      render: (e) => (e.atr_percent == null ? "—" : `${formatNumber(e.atr_percent, 2)}%`),
    },
    { key: "vol", header: "거래량배수", align: "right", render: (e) => formatNumber(e.volume_ratio, 2) },
    {
      key: "reason",
      header: "신호",
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
      empty="감시 중인 종목이 없습니다. 봇은 RUNNING 상태에서만 종목을 탐색합니다."
    />
  );
}

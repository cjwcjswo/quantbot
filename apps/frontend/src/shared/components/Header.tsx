import { useBotStatus } from "@/features/bot-status/hooks";
import { useWebsocketStore } from "@/features/websocket/websocketStore";
import { useUiStore } from "@/shared/store/uiStore";
import { useNow } from "@/shared/hooks/useNow";
import { statusText, timeAgo } from "@/shared/utils/format";
import { ModeBadge, StatusBadge, TextBadge } from "./Badges";

function Dot({ ok, pulse }: { ok: boolean; pulse?: boolean }) {
  return (
    <span
      className={`h-2 w-2 rounded-full ${ok ? "bg-emerald-400" : "bg-rose-500"} ${
        ok && pulse ? "animate-pulse-dot" : ""
      }`}
    />
  );
}

export function Header() {
  const { data } = useBotStatus();
  const connected = useWebsocketStore((s) => s.connected);
  const setMobileNav = useUiStore((s) => s.setMobileNav);
  const now = useNow();

  return (
    <header className="sticky top-0 z-30 flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-panelBorder/70 bg-surface/80 px-3 py-2.5 backdrop-blur-md sm:px-4">
      <button
        onClick={() => setMobileNav(true)}
        className="grid h-8 w-8 place-items-center rounded-lg text-slate-300 ring-1 ring-inset ring-white/10 transition-colors hover:bg-white/5 lg:hidden"
        aria-label="메뉴 열기"
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path d="M2 4h12M2 8h12M2 12h12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      </button>

      <span className="flex items-center gap-2 text-sm font-bold tracking-tight">
        <span className="h-2 w-2 rounded-full bg-accent shadow-glow" />
        <span className="bg-gradient-to-r from-accent to-indigo-400 bg-clip-text text-transparent">
          QuantBot
        </span>
      </span>

      {data && <StatusBadge state={data.state} />}
      <ModeBadge mode={data?.mode ?? null} />

      <div className="hidden items-center gap-1 text-xs text-slate-400 sm:flex">
        <Dot ok={!!data?.is_alive} pulse />
        하트비트 {timeAgo(data?.heartbeat_at)}
      </div>

      <span className="hidden items-center gap-1 text-xs text-slate-500 lg:inline-flex">
        리스크 <TextBadge text={statusText(data?.risk_status, "—")} />
      </span>
      <span className="hidden items-center gap-1 text-xs text-slate-500 lg:inline-flex">
        보호 <TextBadge text={statusText(data?.protection_status, "—")} />
      </span>
      <span className="hidden items-center gap-1 text-xs text-slate-500 lg:inline-flex">
        동기화 <TextBadge text={statusText(data?.reconciliation_status, "—")} />
      </span>

      <div className="ml-auto flex items-center gap-3 text-xs text-slate-400">
        <span className="flex items-center gap-1.5">
          <Dot ok={connected} pulse />
          {connected ? "WS 연결됨" : "WS 끊김"}
        </span>
        <span className="hidden tabular-nums sm:inline">{now.toLocaleTimeString()}</span>
      </div>
    </header>
  );
}

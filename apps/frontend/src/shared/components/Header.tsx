import { useBotStatus } from "@/features/bot-status/hooks";
import { useWebsocketStore } from "@/features/websocket/websocketStore";
import { useNow } from "@/shared/hooks/useNow";
import { statusText, timeAgo } from "@/shared/utils/format";
import { ModeBadge, StatusBadge, TextBadge } from "./Badges";

export function Header() {
  const { data } = useBotStatus();
  const connected = useWebsocketStore((s) => s.connected);
  const now = useNow();

  return (
    <header className="flex flex-wrap items-center gap-3 border-b border-panelBorder bg-panel px-4 py-2.5">
      <span className="text-sm font-semibold text-slate-100">QuantBot</span>
      {data && <StatusBadge state={data.state} />}
      <ModeBadge mode={data?.mode ?? null} />

      <div className="flex items-center gap-1 text-xs text-slate-400">
        <span
          className={`h-2 w-2 rounded-full ${data?.is_alive ? "bg-emerald-500" : "bg-red-500"}`}
        />
        heartbeat {timeAgo(data?.heartbeat_at)}
      </div>

      <span className="text-xs text-slate-500">
        risk <TextBadge text={statusText(data?.risk_status, "—")} />
      </span>
      <span className="text-xs text-slate-500">
        protection <TextBadge text={statusText(data?.protection_status, "—")} />
      </span>
      <span className="text-xs text-slate-500">
        recon <TextBadge text={statusText(data?.reconciliation_status, "—")} />
      </span>

      <div className="ml-auto flex items-center gap-3 text-xs text-slate-400">
        <span className="flex items-center gap-1">
          <span className={`h-2 w-2 rounded-full ${connected ? "bg-emerald-500" : "bg-red-500"}`} />
          {connected ? "WS live" : "WS disconnected"}
        </span>
        <span className="tabular-nums">{now.toLocaleTimeString()}</span>
      </div>
    </header>
  );
}

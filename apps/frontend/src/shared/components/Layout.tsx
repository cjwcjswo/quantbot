import { Outlet } from "react-router-dom";
import { useBotStatus } from "@/features/bot-status/hooks";
import { usePositions } from "@/features/positions/hooks";
import { useDashboardSocket } from "@/features/websocket/useDashboardSocket";
import { useWebsocketStore } from "@/features/websocket/websocketStore";
import { useUiStore } from "@/shared/store/uiStore";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";
import { Toaster } from "./Toaster";

function AlertBar({ tone, children }: { tone: "red" | "amber"; children: React.ReactNode }) {
  const cls =
    tone === "red"
      ? "bg-red-600/90 text-white"
      : "bg-amber-500/90 text-slate-900";
  return <div className={`px-4 py-1.5 text-center text-sm font-semibold ${cls}`}>{children}</div>;
}

export function Layout() {
  useDashboardSocket();
  const { data: status } = useBotStatus();
  const { data: positions } = usePositions();
  const connected = useWebsocketStore((s) => s.connected);
  const sidebarOpen = useUiStore((s) => s.sidebarOpen);

  const tpslFailed = (positions?.positions ?? []).some(
    (p) => p.mode === "LIVE" && p.protection_status === "TPSL_FAILED",
  );

  return (
    <div className="flex h-full flex-col">
      <Header />
      {status?.mode === "LIVE" && (
        <AlertBar tone="red">LIVE MODE — Real orders are enabled</AlertBar>
      )}
      {status?.state === "EMERGENCY_STOP" && (
        <AlertBar tone="red">EMERGENCY STOP — trading halted</AlertBar>
      )}
      {tpslFailed && (
        <AlertBar tone="red">TP/SL protection FAILED on a LIVE position — check Positions</AlertBar>
      )}
      {!connected && (
        <AlertBar tone="amber">DISCONNECTED — reconnecting to live updates…</AlertBar>
      )}
      <div className="flex flex-1 overflow-hidden">
        <Sidebar open={sidebarOpen} />
        <main className="flex-1 overflow-y-auto p-4">
          <Outlet />
        </main>
      </div>
      <Toaster />
    </div>
  );
}

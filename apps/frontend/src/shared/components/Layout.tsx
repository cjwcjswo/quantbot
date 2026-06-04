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
      ? "bg-gradient-to-r from-rose-600/25 via-rose-500/15 to-rose-600/25 text-rose-200 border-rose-500/30"
      : "bg-gradient-to-r from-amber-500/20 via-amber-400/10 to-amber-500/20 text-amber-200 border-amber-500/30";
  return (
    <div
      className={`border-b px-4 py-1.5 text-center text-xs font-semibold tracking-wide backdrop-blur-sm ${cls}`}
    >
      {children}
    </div>
  );
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
        <AlertBar tone="red">LIVE 모드 — 실제 주문이 활성화되어 있습니다</AlertBar>
      )}
      {status?.state === "EMERGENCY_STOP" && (
        <AlertBar tone="red">비상 정지 — 매매가 중단되었습니다</AlertBar>
      )}
      {tpslFailed && (
        <AlertBar tone="red">LIVE 포지션의 TP/SL 보호 실패 — 포지션 탭을 확인하세요</AlertBar>
      )}
      {!connected && (
        <AlertBar tone="amber">연결 끊김 — 실시간 업데이트에 재연결 중…</AlertBar>
      )}
      <div className="flex flex-1 overflow-hidden">
        <Sidebar open={sidebarOpen} />
        <main className="flex-1 overflow-y-auto p-3 sm:p-4 lg:p-6">
          <div className="mx-auto w-full max-w-[1700px] animate-fade-in">
            <Outlet />
          </div>
        </main>
      </div>
      <Toaster />
    </div>
  );
}

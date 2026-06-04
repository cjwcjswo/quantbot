import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useWebsocketStore } from "./websocketStore";
import { useUiStore } from "@/shared/store/uiStore";
import type { WsEventType, WsMessage } from "./types";

function wsUrl(): string {
  const explicit = import.meta.env.VITE_WS_URL;
  if (explicit) return explicit;
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/ws/dashboard`;
}

// which react-query keys to refetch for each ws event (§13.4: WS is immediate,
// REST snapshot is source of truth, so we invalidate and let queries refetch).
const INVALIDATE: Record<WsEventType, string[]> = {
  snapshot: ["botStatus", "positions", "pnl", "watchlist"],
  bot_status: ["botStatus"],
  pnl_update: ["pnl"],
  position_update: ["positions", "trades"],
  watchlist_update: ["watchlist"],
  order_update: ["orders"],
  trade_update: ["trades"],
  risk_update: ["botStatus"],
  protection_update: ["positions", "botStatus"],
  reconciliation_update: ["botStatus"],
  manual_intervention_event: ["positions", "events"],
  bot_event: ["events"],
};

export function useDashboardSocket(): void {
  const queryClient = useQueryClient();
  const setConnected = useWebsocketStore((s) => s.setConnected);
  const setError = useWebsocketStore((s) => s.setError);
  const pushEvent = useWebsocketStore((s) => s.pushEvent);
  const pushToast = useUiStore((s) => s.pushToast);
  const retryRef = useRef(0);
  const stopRef = useRef(false);

  useEffect(() => {
    stopRef.current = false;
    let socket: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      if (stopRef.current) return;
      socket = new WebSocket(wsUrl());

      socket.onopen = () => {
        retryRef.current = 0;
        setConnected(true);
        setError(null);
        // §13.3 reconnect policy: refetch REST snapshot after (re)connect
        queryClient.invalidateQueries();
      };

      socket.onmessage = (ev) => {
        let msg: WsMessage;
        try {
          msg = JSON.parse(ev.data) as WsMessage;
        } catch {
          return;
        }
        pushEvent(msg.type, msg.timestamp ?? new Date().toISOString(), msg.data);
        const keys = INVALIDATE[msg.type] ?? [];
        for (const key of keys) {
          queryClient.invalidateQueries({ queryKey: [key] });
        }
        if (msg.type === "manual_intervention_event") {
          pushToast("warning", "Manual intervention detected");
        }
      };

      socket.onerror = () => setError("websocket error");

      socket.onclose = () => {
        setConnected(false);
        if (stopRef.current) return;
        // backoff 3s..30s (§13.3)
        const delay = Math.min(3000 * 2 ** retryRef.current, 30000);
        retryRef.current += 1;
        timer = setTimeout(connect, delay);
      };
    };

    connect();

    return () => {
      stopRef.current = true;
      if (timer) clearTimeout(timer);
      socket?.close();
    };
  }, [queryClient, setConnected, setError, pushEvent, pushToast]);
}

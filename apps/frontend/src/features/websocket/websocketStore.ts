import { create } from "zustand";
import type { WsEventType } from "./types";

export type RealtimeEvent = {
  id: number;
  type: WsEventType;
  timestamp: string;
  data: unknown;
};

type WsState = {
  connected: boolean;
  lastError: string | null;
  recent: RealtimeEvent[];
  setConnected: (c: boolean) => void;
  setError: (e: string | null) => void;
  pushEvent: (type: WsEventType, timestamp: string, data: unknown) => void;
};

let seq = 1;
const MAX_RECENT = 50;

export const useWebsocketStore = create<WsState>((set) => ({
  connected: false,
  lastError: null,
  recent: [],
  setConnected: (connected) => set({ connected }),
  setError: (lastError) => set({ lastError }),
  pushEvent: (type, timestamp, data) =>
    set((s) => ({
      recent: [{ id: seq++, type, timestamp, data }, ...s.recent].slice(0, MAX_RECENT),
    })),
}));

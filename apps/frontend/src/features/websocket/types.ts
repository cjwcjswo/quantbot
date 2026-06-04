export type WsEventType =
  | "snapshot"
  | "bot_status"
  | "pnl_update"
  | "position_update"
  | "watchlist_update"
  | "order_update"
  | "trade_update"
  | "risk_update"
  | "protection_update"
  | "reconciliation_update"
  | "manual_intervention_event"
  | "bot_event";

export type WsMessage = {
  type: WsEventType;
  timestamp?: string;
  data: unknown;
};

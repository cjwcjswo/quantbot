import { apiGet, apiSend } from "./client";
import type {
  BotMode,
  BotStatus,
  CalendarResponse,
  CommandAccepted,
  DailyLog,
  DailyPnl,
  MonthlyPnl,
  BotEvent,
  Fill,
  Order,
  PnlSummary,
  PositionsResponse,
  StorageInfo,
  StrategyConfig,
  Trade,
  TradeDetail,
  WatchlistResponse,
} from "./types";

export type ListQuery = Record<string, string | number | undefined>;

export const api = {
  health: () => apiGet<Record<string, string>>("/health"),

  botStatus: () => apiGet<BotStatus>("/bot/status"),
  start: (liveConfirm = false) =>
    apiSend<CommandAccepted>("POST", "/bot/start", { live_confirm: liveConfirm }),
  stop: (closePositions: boolean, cancelOpenOrders: boolean) =>
    apiSend<CommandAccepted>("POST", "/bot/stop", {
      close_positions: closePositions,
      cancel_open_orders: cancelOpenOrders,
    }),
  pause: (reason = "manual pause") =>
    apiSend<CommandAccepted>("POST", "/bot/pause", { reason }),
  resume: () => apiSend<CommandAccepted>("POST", "/bot/resume", {}),
  sync: () => apiSend<CommandAccepted>("POST", "/bot/sync"),

  positions: () => apiGet<PositionsResponse>("/positions"),
  watchlist: () => apiGet<WatchlistResponse>("/watchlist"),
  closePosition: (symbol: string, closePercent: number, reason = "manual dashboard close") =>
    apiSend<CommandAccepted>("POST", `/positions/${symbol}/close`, {
      close_percent: closePercent,
      reason,
    }),

  orders: (q?: ListQuery) => apiGet<{ orders: Order[] }>("/orders", q),
  cancelOrder: (orderId: string, reason = "manual dashboard cancel") =>
    apiSend<CommandAccepted>("POST", `/orders/${orderId}/cancel`, { reason }),

  trades: (q?: ListQuery) => apiGet<{ trades: Trade[] }>("/trades", q),
  tradeDetail: (tradeId: string) => apiGet<TradeDetail>(`/trades/${tradeId}`),
  fills: (q?: ListQuery) => apiGet<{ fills: Fill[] }>("/fills", q),

  pnlSummary: () => apiGet<PnlSummary>("/pnl/summary"),
  pnlDaily: () => apiGet<{ daily: DailyPnl[] }>("/pnl/daily"),
  pnlMonthly: () => apiGet<{ monthly: MonthlyPnl[] }>("/pnl/monthly"),

  events: (q?: ListQuery) => apiGet<{ events: BotEvent[] }>("/events", q),

  strategyConfig: () => apiGet<StrategyConfig>("/strategy/config"),
  patchConfig: (configVersion: number, patch: Record<string, unknown>, reason: string) =>
    apiSend<{ config_version: number; command_id: string }>("PUT", "/strategy/config", {
      config_version: configVersion,
      patch,
      reason,
    }),

  dailyLog: (date: string, mode?: BotMode) =>
    apiGet<DailyLog>("/logs/daily", { date, mode }),
  dailyCalendar: (year: number, month: number, mode?: BotMode) =>
    apiGet<CalendarResponse>("/logs/daily/calendar", { year, month, mode }),

  systemStorage: () => apiGet<StorageInfo>("/system/storage"),
};

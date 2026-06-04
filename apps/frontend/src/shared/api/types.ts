// Typed API contracts (frontend doc §14). `any` is never used.

export type ApiError = {
  code: string;
  message: string;
  details: Record<string, unknown>;
};

export type ApiResponse<T> = {
  ok: boolean;
  data: T | null;
  error: ApiError | null;
};

export type BotState =
  | "BOOTING"
  | "STANDBY"
  | "START_REQUESTED"
  | "SYNCING"
  | "READY"
  | "RUNNING"
  | "PAUSED"
  | "RISK_LOCKED"
  | "RECONCILING"
  | "ORDER_LOCKED"
  | "EMERGENCY_STOP"
  | "STOPPING"
  | "STOPPED"
  | "UNKNOWN"
  | "DISCONNECTED";

export type BotMode = "PAPER" | "LIVE";

export type LastEvent = { event_type: string; message: string } | null;

export type BotStatus = {
  state: BotState;
  mode: BotMode | null;
  heartbeat_at: string | null;
  is_alive: boolean;
  is_trading_enabled: boolean;
  risk_status: unknown;
  protection_status: unknown;
  reconciliation_status: unknown;
  last_event: LastEvent;
  degraded?: boolean;
};

export type PositionSource = "BOT" | "EXTERNAL" | "MANUAL_ADDED";
export type PositionSide = "LONG" | "SHORT";
export type ProtectionStatus =
  | "TPSL_OK"
  | "TPSL_PENDING"
  | "TPSL_FAILED"
  | "NOT_REQUIRED"
  | "UNKNOWN";

export type Position = {
  symbol: string;
  side: PositionSide;
  source: PositionSource;
  mode: BotMode | null;
  qty: string | null;
  manual_added_qty: string | null;
  avg_entry_price: string | null;
  mark_price: string | null;
  unrealized_pnl: string | null;
  unrealized_pnl_percent?: string | null;
  leverage: string | null;
  entry_mode: string | null;
  strategy_id: string | null;
  protection_status: ProtectionStatus;
  stop_loss_price: string | null;
  take_profit_price: string | null;
  opened_at: string | null;
};

export type PositionsResponse = {
  positions: Position[];
  source: string;
  degraded?: boolean;
};

export type OrderStatus =
  | "NEW"
  | "PARTIALLY_FILLED"
  | "FILLED"
  | "CANCELED"
  | "CANCELLED"
  | "REJECTED"
  | "EXPIRED"
  | "FAILED"
  | "UNKNOWN";

export type Order = {
  id: number;
  symbol: string;
  side: string;
  order_type: string;
  status: OrderStatus;
  source: string | null;
  mode: BotMode | null;
  qty: string;
  filled_qty: string | null;
  price: string | null;
  avg_fill_price: string | null;
  reduce_only: boolean;
  order_id: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type Trade = {
  id: number;
  trade_id: string | null;
  symbol: string;
  side: string;
  strategy_id: string | null;
  entry_mode: string | null;
  mode: BotMode | null;
  leverage: string | null;
  entry_price: string;
  exit_price: string | null;
  qty: string;
  gross_pnl: string | null;
  fees: string | null;
  funding_fees: string | null;
  net_pnl: string | null;
  realized_pnl: string;
  r_multiple: string | null;
  exit_reason: string | null;
  opened_at: string | null;
  closed_at: string | null;
};

export type Fill = {
  id: number;
  symbol: string;
  order_id: string | null;
  side: string;
  price: string;
  qty: string;
  fee: string;
  realized_pnl: string;
  mode: BotMode | null;
  slippage: string | null;
  ts: string;
};

export type PnlSummary = {
  mode: BotMode | null;
  equity: string | null;
  daily_net_pnl: string;
  daily_net_pnl_percent: string | null;
  realized_pnl: string;
  unrealized_pnl: string;
  fees: string;
  funding_fees: string;
  max_drawdown_today: string | null;
  updated_at: string | null;
  degraded?: boolean;
};

export type DailyPnl = {
  day: string;
  realized: string;
  unrealized: string;
  fees: string;
  net: string;
};

export type Severity = "INFO" | "WARNING" | "ERROR" | "CRITICAL";

export type BotEvent = {
  id: number;
  type: string;
  symbol: string | null;
  message: string;
  data: Record<string, unknown>;
  severity: Severity;
  ts: string;
};

export type StrategyConfig = {
  config_version: number;
  mode: BotMode | null;
  strategy: { active_strategies: string[] } & Record<string, unknown>;
  bot: Record<string, unknown>;
  paper: Record<string, unknown>;
  universe: Record<string, unknown>;
  scanner: Record<string, unknown>;
  trend_quality: Record<string, unknown>;
  volume: Record<string, unknown>;
  candle_quality: Record<string, unknown>;
  risk: Record<string, unknown>;
  entry: Record<string, unknown>;
  orders: Record<string, unknown>;
  liquidation_guard: Record<string, unknown>;
  tpsl: Record<string, unknown>;
  position_protection: Record<string, unknown>;
  position: Record<string, unknown>;
  stagnation_exit: Record<string, unknown>;
  cooldown: Record<string, unknown>;
  global_kill_switch: Record<string, unknown>;
  reconciliation: Record<string, unknown>;
  manual_intervention: Record<string, unknown>;
  data_quality: Record<string, unknown>;
  funding_guard: Record<string, unknown>;
};

export type CommandAccepted = { command_id: string; status: string };

export type TimelineEvent = {
  type: string;
  ts: string | null;
  severity: Severity | null;
  message: string;
  data?: Record<string, unknown>;
};

export type TradeDetail = {
  trade: Trade;
  orders: Order[];
  fills: Fill[];
  events: BotEvent[];
  manual_interventions: Record<string, unknown>[];
  protection_events: Record<string, unknown>[];
  risk_events: Record<string, unknown>[];
  timeline: TimelineEvent[];
};

export type DailyLogSummary = {
  trade_count: number;
  win_count: number;
  loss_count: number;
  net_pnl: string;
  realized_pnl: string;
  unrealized_pnl: string;
  fees: string;
  max_drawdown: string;
  manual_intervention_count: number;
  tpsl_failed_count: number;
  emergency_count: number;
};

export type DailyLog = {
  date: string;
  mode: BotMode | null;
  summary: DailyLogSummary;
  sections: {
    trades: Trade[];
    events: BotEvent[];
    manual_interventions: Record<string, unknown>[];
    risk_events: Record<string, unknown>[];
    protection_events: Record<string, unknown>[];
  };
};

export type CalendarItem = {
  date: string;
  trade_count: number;
  net_pnl: string;
  has_warning: boolean;
  has_error: boolean;
  manual_intervention_count: number;
};

export type CalendarResponse = {
  year: number;
  month: number;
  items: CalendarItem[];
};

export type StorageTable = {
  name: string;
  rows: number;
  size_mb: number | null;
  oldest_created_at: string | null;
};

export type StorageInfo = {
  database_size_mb: number | null;
  tables: StorageTable[];
  retention_status: Record<string, string | null>;
};

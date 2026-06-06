export type PositionDirection = "LONG" | "SHORT";

type DirectionEvent = {
  symbol: string | null;
  ts: string | null;
  data: Record<string, unknown>;
};

type DirectionOrder = {
  symbol: string;
  side: string;
  reduce_only: boolean;
  order_id: string | null;
  created_at: string | null;
  updated_at?: string | null;
};

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim().toUpperCase() : null;
}

export function directionFromOrderSide(
  side: unknown,
  reduceOnly = false,
): PositionDirection | null {
  const value = stringValue(side);
  if (value === "LONG" || value === "SHORT") return value;
  if (value === "BUY") return reduceOnly ? "SHORT" : "LONG";
  if (value === "SELL") return reduceOnly ? "LONG" : "SHORT";
  return null;
}

function booleanValue(value: unknown): boolean {
  if (typeof value === "boolean") return value;
  const text = stringValue(value);
  return text === "TRUE" || text === "1" || text === "YES";
}

const EVENT_DIRECTION_KEYS = [
  "side",
  "position_side",
  "positionSide",
  "direction",
  "strategy_signal_side",
  "signal_side",
  "signalSide",
];

const EVENT_ORDER_SIDE_KEYS = ["order_side", "orderSide", "exchange_side", "exchangeSide"];

export function directionFromEventData(
  data: Record<string, unknown> | null | undefined,
): PositionDirection | null {
  if (!data) return null;

  const reduceOnly = booleanValue(data.reduce_only ?? data.reduceOnly);
  for (const key of EVENT_DIRECTION_KEYS) {
    const direction = directionFromOrderSide(data[key], reduceOnly);
    if (direction) return direction;
  }
  for (const key of EVENT_ORDER_SIDE_KEYS) {
    const direction = directionFromOrderSide(data[key], reduceOnly);
    if (direction) return direction;
  }
  return null;
}

function timeMs(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

export function directionFromRelatedOrders(
  event: DirectionEvent,
  orders: DirectionOrder[] = [],
): PositionDirection | null {
  const orderId = typeof event.data.order_id === "string" ? event.data.order_id : null;
  if (orderId) {
    const matched = orders.find((order) => order.order_id === orderId);
    const direction = matched
      ? directionFromOrderSide(matched.side, matched.reduce_only)
      : null;
    if (direction) return direction;
  }

  if (!event.symbol) return null;
  const eventTime = timeMs(event.ts);
  if (eventTime === null) return null;

  const nearest = orders
    .filter((order) => order.symbol === event.symbol)
    .map((order) => ({
      order,
      time: timeMs(order.updated_at ?? order.created_at),
    }))
    .filter((item): item is { order: DirectionOrder; time: number } => item.time !== null)
    .filter((item) => item.time <= eventTime + 30_000)
    .sort((a, b) => b.time - a.time)[0]?.order;

  return nearest ? directionFromOrderSide(nearest.side, nearest.reduce_only) : null;
}

export function directionLabel(direction: PositionDirection): string {
  return direction === "LONG" ? "롱 LONG" : "숏 SHORT";
}

export function orderIntentLabel(reduceOnly: boolean): string {
  return reduceOnly ? "청산" : "진입";
}

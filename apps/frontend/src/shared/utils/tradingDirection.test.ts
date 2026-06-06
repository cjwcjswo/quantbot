import { describe, expect, it } from "vitest";
import {
  directionFromEventData,
  directionFromRelatedOrders,
  directionFromOrderSide,
  orderIntentLabel,
} from "./tradingDirection";

describe("trading direction helpers", () => {
  it("derives entry direction from exchange order side", () => {
    expect(directionFromOrderSide("Buy", false)).toBe("LONG");
    expect(directionFromOrderSide("Sell", false)).toBe("SHORT");
  });

  it("derives closed position direction from reduce-only order side", () => {
    expect(directionFromOrderSide("Buy", true)).toBe("SHORT");
    expect(directionFromOrderSide("Sell", true)).toBe("LONG");
  });

  it("uses explicit event position side first", () => {
    expect(directionFromEventData({ side: "LONG" })).toBe("LONG");
    expect(directionFromEventData({ strategy_signal_side: "SHORT" })).toBe("SHORT");
  });

  it("derives event direction from order side and reduce-only flag", () => {
    expect(directionFromEventData({ order_side: "Buy", reduce_only: true })).toBe("SHORT");
    expect(directionFromEventData({ exchangeSide: "Sell", reduceOnly: false })).toBe("SHORT");
  });

  it("restores event direction from matching recent orders", () => {
    const orders = [
      {
        symbol: "HOMEUSDT",
        side: "Buy",
        reduce_only: false,
        order_id: "entry-1",
        created_at: "2026-06-06T00:01:01.000Z",
        updated_at: "2026-06-06T00:01:01.000Z",
      },
      {
        symbol: "HOMEUSDT",
        side: "Sell",
        reduce_only: true,
        order_id: "exit-1",
        created_at: "2026-06-06T00:01:37.000Z",
        updated_at: "2026-06-06T00:01:37.000Z",
      },
    ];

    expect(
      directionFromRelatedOrders(
        { symbol: "HOMEUSDT", ts: "2026-06-06T00:02:02.000Z", data: {} },
        orders,
      ),
    ).toBe("LONG");
  });

  it("labels order intent", () => {
    expect(orderIntentLabel(false)).toBe("진입");
    expect(orderIntentLabel(true)).toBe("청산");
  });
});

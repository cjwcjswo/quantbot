import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { WatchlistTable } from "./WatchlistTable";
import type { WatchEntry } from "@/shared/api/types";

function entry(overrides: Partial<WatchEntry> = {}): WatchEntry {
  return {
    symbol: "BTCUSDT",
    strategy: "trend_following",
    direction: "LONG",
    signal_score: "7.5",
    signal_reason: "trend long gap=0.40%",
    readiness: "NEAR",
    trend: "UP",
    last_price: "65000",
    box_high: "65100",
    box_low: "64000",
    distance_to_breakout_pct: "0.15",
    distance_atr: "0.18",
    atr_percent: "2.1",
    rsi: "56",
    volume_ratio: "1.8",
    updated_ms: 1_000,
    ...overrides,
  };
}

describe("WatchlistTable", () => {
  it("renders a candidate with its lean and readiness", () => {
    render(<WatchlistTable entries={[entry()]} />);
    expect(screen.getByText("BTCUSDT")).toBeInTheDocument();
    expect(screen.getByText("LONG")).toBeInTheDocument();
    expect(screen.getByText("Near")).toBeInTheDocument();
  });

  it("shows a dash lean and No signal for symbols without a signal", () => {
    render(
      <WatchlistTable
        entries={[entry({ direction: "NONE", readiness: "NO_SIGNAL", signal_score: null })]}
      />,
    );
    expect(screen.getByText("No signal")).toBeInTheDocument();
  });

  it("renders an explanatory empty state", () => {
    render(<WatchlistTable entries={[]} />);
    expect(screen.getByText(/scans the universe only while RUNNING/i)).toBeInTheDocument();
  });
});

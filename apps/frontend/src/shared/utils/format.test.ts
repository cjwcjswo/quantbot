import { describe, expect, it } from "vitest";
import { formatNumber, pnlClass, pnlSign } from "./format";

describe("format", () => {
  it("formats numbers with 2dp", () => {
    expect(formatNumber("1234.5")).toBe("1,234.50");
    expect(formatNumber(null)).toBe("-");
    expect(formatNumber(undefined)).toBe("-");
  });

  it("computes pnl sign", () => {
    expect(pnlSign("10")).toBe(1);
    expect(pnlSign("-5")).toBe(-1);
    expect(pnlSign("0")).toBe(0);
    expect(pnlSign(null)).toBe(0);
  });

  it("maps pnl color class", () => {
    expect(pnlClass("10")).toContain("emerald");
    expect(pnlClass("-1")).toContain("rose");
    expect(pnlClass("0")).toContain("slate");
  });
});

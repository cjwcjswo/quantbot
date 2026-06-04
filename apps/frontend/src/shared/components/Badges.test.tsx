import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ModeBadge, StatusBadge } from "./Badges";

describe("badges", () => {
  it("renders bot state", () => {
    render(<StatusBadge state="RUNNING" />);
    expect(screen.getByText("RUNNING")).toBeInTheDocument();
  });

  it("renders LIVE mode with red emphasis", () => {
    render(<ModeBadge mode="LIVE" />);
    const el = screen.getByText("LIVE");
    expect(el.className).toContain("red");
  });

  it("renders PAPER mode", () => {
    render(<ModeBadge mode="PAPER" />);
    expect(screen.getByText("PAPER")).toBeInTheDocument();
  });
});

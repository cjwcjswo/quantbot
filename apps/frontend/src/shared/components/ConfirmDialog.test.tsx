import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ConfirmDialog } from "./ConfirmDialog";

describe("ConfirmDialog", () => {
  it("requires the exact text before enabling confirm (LIVE)", () => {
    const onConfirm = vi.fn();
    render(
      <ConfirmDialog
        open
        title="Start LIVE"
        message="type LIVE"
        requireText="LIVE"
        onConfirm={onConfirm}
        onCancel={() => {}}
      />,
    );
    const confirmBtn = screen.getByRole("button", { name: "Confirm" });
    expect(confirmBtn).toBeDisabled();

    fireEvent.change(screen.getByPlaceholderText("Type LIVE to confirm"), {
      target: { value: "LIVE" },
    });
    expect(confirmBtn).toBeEnabled();
    fireEvent.click(confirmBtn);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("calls onCancel", () => {
    const onCancel = vi.fn();
    render(
      <ConfirmDialog open title="x" message="y" onConfirm={() => {}} onCancel={onCancel} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalled();
  });
});

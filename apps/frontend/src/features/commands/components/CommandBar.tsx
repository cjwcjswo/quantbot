import { useState } from "react";
import { useBotStatus } from "@/features/bot-status/hooks";
import { useCommand } from "@/features/commands/useCommands";
import { Button } from "@/shared/components/Button";
import { ConfirmDialog } from "@/shared/components/ConfirmDialog";
import { Modal } from "@/shared/components/Modal";

type Dialog = "none" | "startLive" | "stop";

export function CommandBar() {
  const { data } = useBotStatus();
  const cmd = useCommand();
  const [dialog, setDialog] = useState<Dialog>("none");
  const [closePositions, setClosePositions] = useState(false);
  const [cancelOrders, setCancelOrders] = useState(true);
  const [stopConfirmText, setStopConfirmText] = useState("");

  const state = data?.state;
  const isRunning = state === "RUNNING";
  const isPaused = state === "PAUSED";
  const locked = state === "EMERGENCY_STOP" || state === "RISK_LOCKED" || state === "ORDER_LOCKED";
  const disconnected = !data || state === "DISCONNECTED" || state === "UNKNOWN";
  const canStart = !isRunning && !locked;
  const closeStopDialog = () => {
    setDialog("none");
    setStopConfirmText("");
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        variant="primary"
        disabled={!canStart || cmd.isPending}
        onClick={() => cmd.mutate({ kind: "start", mode: "PAPER", liveConfirm: false })}
      >
        START PAPER
      </Button>
      <Button
        variant="danger"
        disabled={!canStart || cmd.isPending}
        onClick={() => setDialog("startLive")}
      >
        START LIVE
      </Button>
      <Button variant="danger-outline" disabled={cmd.isPending} onClick={() => setDialog("stop")}>
        STOP
      </Button>
      <Button
        variant="warning"
        disabled={!isRunning || cmd.isPending}
        onClick={() => cmd.mutate({ kind: "pause" })}
      >
        PAUSE
      </Button>
      <Button
        variant="primary"
        disabled={!isPaused || locked || cmd.isPending}
        onClick={() => cmd.mutate({ kind: "resume" })}
      >
        RESUME
      </Button>
      <Button
        variant="secondary"
        disabled={disconnected || cmd.isPending}
        onClick={() => cmd.mutate({ kind: "sync" })}
      >
        SYNC NOW
      </Button>

      <ConfirmDialog
        open={dialog === "startLive"}
        title="Start in LIVE mode"
        message="LIVE 모드로 실제 주문이 실행됩니다. 계속하려면 LIVE를 입력하세요."
        confirmLabel="Start LIVE"
        danger
        requireText="LIVE"
        onCancel={() => setDialog("none")}
        onConfirm={() => {
          cmd.mutate({ kind: "start", mode: "LIVE", liveConfirm: true });
          setDialog("none");
        }}
      />

      <Modal open={dialog === "stop"} title="Stop bot" onClose={closeStopDialog}>
        <p className="text-sm text-slate-300">The bot will stop accepting new entries.</p>
        <label className="mt-3 flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={cancelOrders}
            onChange={(e) => setCancelOrders(e.target.checked)}
          />
          Cancel open orders
        </label>
        <label className="mt-2 flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={closePositions}
            onChange={(e) => {
              setClosePositions(e.target.checked);
              setStopConfirmText("");
            }}
          />
          Close all positions
        </label>
        {closePositions && (
          <div className="mt-2 rounded border border-red-500/40 bg-red-500/10 px-3 py-2">
            <p className="text-sm text-red-300">This will request closing ALL open positions.</p>
            <input
              autoFocus
              value={stopConfirmText}
              onChange={(e) => setStopConfirmText(e.target.value)}
              placeholder="Type CLOSE to confirm"
              className="mt-2 w-full rounded border border-red-500/40 bg-bg px-3 py-2 text-sm outline-none focus:border-red-400"
            />
          </div>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={closeStopDialog}>
            Cancel
          </Button>
          <Button
            variant="danger"
            disabled={closePositions && stopConfirmText !== "CLOSE"}
            onClick={() => {
              cmd.mutate({
                kind: "stop",
                closePositions,
                cancelOpenOrders: cancelOrders,
              });
              closeStopDialog();
            }}
          >
            Stop
          </Button>
        </div>
      </Modal>
    </div>
  );
}

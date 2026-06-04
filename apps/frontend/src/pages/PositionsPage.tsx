import { useState } from "react";
import { usePositions, useClosePosition } from "@/features/positions/hooks";
import { PositionsTable } from "@/features/positions/components/PositionsTable";
import { Panel } from "@/shared/components/Panel";
import { Button } from "@/shared/components/Button";
import { Modal } from "@/shared/components/Modal";
import { ErrorState, LoadingState } from "@/shared/components/States";
import { ApiClientError } from "@/shared/api/client";

export function PositionsPage() {
  const { data, isLoading, error, refetch } = usePositions();
  const close = useClosePosition();
  const [target, setTarget] = useState<string | null>(null);
  const [percent, setPercent] = useState(100);
  const closePercent = Math.min(100, Math.max(1, Number.isFinite(percent) ? percent : 100));

  return (
    <Panel title="Positions">
      {isLoading && <LoadingState />}
      {error && (
        <ErrorState
          message={error instanceof ApiClientError ? error.message : "Failed to load positions"}
          onRetry={() => refetch()}
        />
      )}
      {data && (
        <PositionsTable positions={data.positions} onClose={(symbol) => setTarget(symbol)} />
      )}

      <Modal open={target !== null} title={`Close ${target ?? ""}`} onClose={() => setTarget(null)}>
        <p className="text-sm text-slate-300">Select how much of the position to close.</p>
        <div className="mt-3 flex gap-2">
          {[25, 50, 100].map((v) => (
            <Button
              key={v}
              variant={percent === v ? "primary" : "secondary"}
              onClick={() => setPercent(v)}
            >
              {v}%
            </Button>
          ))}
          <input
            type="number"
            min={1}
            max={100}
            value={percent}
            onChange={(e) => {
              const next = Number(e.target.value);
              setPercent(Number.isFinite(next) ? next : 100);
            }}
            onBlur={() => setPercent(closePercent)}
            className="w-20 rounded border border-panelBorder bg-bg px-2 py-1 text-sm"
          />
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setTarget(null)}>
            Cancel
          </Button>
          <Button
            variant="danger"
            onClick={() => {
              if (target) close.mutate({ symbol: target, percent: closePercent });
              setTarget(null);
            }}
          >
            Close {closePercent}%
          </Button>
        </div>
      </Modal>
    </Panel>
  );
}

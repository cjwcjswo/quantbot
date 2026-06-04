import { useState } from "react";
import { useStrategyConfig, usePatchConfig } from "@/features/strategy-config/hooks";
import { Panel } from "@/shared/components/Panel";
import { Button } from "@/shared/components/Button";
import { ConfirmDialog } from "@/shared/components/ConfirmDialog";
import { ErrorState, LoadingState } from "@/shared/components/States";
import { ApiClientError } from "@/shared/api/client";
import { useUiStore } from "@/shared/store/uiStore";
import type { StrategyConfig } from "@/shared/api/types";

const RISKY = ["risk", "leverage", "stop_loss", "tpsl", "position_protection", "orders", "global_kill_switch"];
const SECTIONS = [
  "bot",
  "paper",
  "universe",
  "scanner",
  "trend_quality",
  "volume",
  "candle_quality",
  "entry",
  "orders",
  "risk",
  "liquidation_guard",
  "tpsl",
  "position_protection",
  "position",
  "stagnation_exit",
  "cooldown",
  "global_kill_switch",
  "reconciliation",
  "manual_intervention",
  "data_quality",
  "funding_guard",
] as const satisfies readonly (keyof StrategyConfig)[];

export function StrategyConfigPage() {
  const { data, isLoading, error, refetch } = useStrategyConfig();
  const patch = usePatchConfig();
  const pushToast = useUiStore((s) => s.pushToast);
  const [json, setJson] = useState("{\n  \n}");
  const [reason, setReason] = useState("");
  const [confirmRisky, setConfirmRisky] = useState<Record<string, unknown> | null>(null);

  const submit = () => {
    if (!data) return;
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(json) as Record<string, unknown>;
    } catch {
      pushToast("error", "패치가 올바른 JSON 형식이 아닙니다");
      return;
    }
    const risky = Object.keys(parsed).some((k) => RISKY.includes(k));
    if (risky) {
      setConfirmRisky(parsed);
      return;
    }
    patch.mutate({ version: data.config_version, patch: parsed, reason });
  };

  return (
    <div className="space-y-4">
      <Panel title="전략 설정">
        {isLoading && <LoadingState />}
        {error && (
          <ErrorState
            message={error instanceof ApiClientError ? error.message : "설정을 불러오지 못했습니다"}
            onRetry={() => refetch()}
          />
        )}
        {data && (
          <div className="space-y-3">
            <div className="text-sm text-slate-400">
              버전 <span className="text-slate-200">{data.config_version}</span> · 모드{" "}
              <span className="text-slate-200">{data.mode ?? "—"}</span> · 전략{" "}
              <span className="text-slate-200">
                {data.strategy.active_strategies.join(", ")}
              </span>
            </div>
            {SECTIONS.map((section) => (
              <div key={section}>
                <h3 className="text-xs uppercase tracking-wide text-slate-500">{section}</h3>
                <pre className="mt-1 max-h-48 overflow-auto rounded border border-panelBorder bg-bg p-3 text-xs text-slate-300">
                  {JSON.stringify(data[section], null, 2)}
                </pre>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <Panel title="설정 변경 요청">
        <textarea
          value={json}
          onChange={(e) => setJson(e.target.value)}
          rows={6}
          className="w-full rounded border border-panelBorder bg-bg p-3 font-mono text-xs text-slate-100 outline-none focus:border-sky-500"
        />
        <input
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="사유"
          className="mt-2 w-full rounded border border-panelBorder bg-bg px-3 py-2 text-sm outline-none focus:border-sky-500"
        />
        <div className="mt-2">
          <Button variant="primary" disabled={!data || patch.isPending} onClick={submit}>
            변경 적용
          </Button>
        </div>
      </Panel>

      <ConfirmDialog
        open={confirmRisky !== null}
        title="위험 설정 변경"
        message="리스크 관련 설정을 변경합니다. 계속할까요?"
        confirmLabel="적용"
        danger
        requireText="APPLY"
        onCancel={() => setConfirmRisky(null)}
        onConfirm={() => {
          if (data && confirmRisky) {
            patch.mutate({ version: data.config_version, patch: confirmRisky, reason });
          }
          setConfirmRisky(null);
        }}
      />
    </div>
  );
}

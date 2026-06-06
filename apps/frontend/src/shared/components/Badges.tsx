import type { BotMode, BotState, ProtectionStatus, Severity } from "@/shared/api/types";
import type { PositionDirection } from "@/shared/utils/tradingDirection";
import { directionLabel } from "@/shared/utils/tradingDirection";
import { cn } from "@/shared/utils/cn";

function Pill({ text, className }: { text: string; className: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-semibold tracking-wide whitespace-nowrap",
        className,
      )}
    >
      {text}
    </span>
  );
}

// §5.2 bot state colors
const STATE_COLORS: Record<string, string> = {
  RUNNING: "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30",
  STANDBY: "bg-slate-500/15 text-slate-300 border border-slate-500/30",
  READY: "bg-slate-500/15 text-slate-300 border border-slate-500/30",
  BOOTING: "bg-slate-500/15 text-slate-300 border border-slate-500/30",
  STOPPED: "bg-slate-500/15 text-slate-300 border border-slate-500/30",
  STOPPING: "bg-slate-500/15 text-slate-300 border border-slate-500/30",
  PAUSED: "bg-amber-500/15 text-amber-400 border border-amber-500/30",
  SYNCING: "bg-sky-500/15 text-sky-400 border border-sky-500/30",
  START_REQUESTED: "bg-sky-500/15 text-sky-400 border border-sky-500/30",
  RECONCILING: "bg-sky-500/15 text-sky-400 border border-sky-500/30",
  RISK_LOCKED: "bg-orange-500/15 text-orange-400 border border-orange-500/30",
  ORDER_LOCKED: "bg-orange-500/15 text-orange-400 border border-orange-500/30",
  EMERGENCY_STOP: "bg-red-500/20 text-red-400 border border-red-500/40",
  DISCONNECTED: "bg-red-500/20 text-red-400 border border-red-500/40",
  UNKNOWN: "bg-red-500/20 text-red-400 border border-red-500/40",
};

export function StatusBadge({ state }: { state: BotState }) {
  return <Pill text={state} className={STATE_COLORS[state] ?? STATE_COLORS.UNKNOWN} />;
}

export function ModeBadge({ mode }: { mode: BotMode | null }) {
  if (mode === "LIVE") {
    return <Pill text="LIVE" className="bg-red-500/20 text-red-400 border border-red-500/40" />;
  }
  return <Pill text={mode ?? "—"} className="bg-sky-500/15 text-sky-400 border border-sky-500/30" />;
}

const PROTECTION_COLORS: Record<ProtectionStatus, string> = {
  TPSL_OK: "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30",
  TPSL_PENDING: "bg-sky-500/15 text-sky-400 border border-sky-500/30",
  TPSL_FAILED: "bg-red-500/20 text-red-400 border border-red-500/40",
  NOT_REQUIRED: "bg-slate-500/15 text-slate-400 border border-slate-500/30",
  UNKNOWN: "bg-amber-500/15 text-amber-400 border border-amber-500/30",
};

export function ProtectionBadge({ status }: { status: ProtectionStatus }) {
  return <Pill text={status} className={PROTECTION_COLORS[status] ?? PROTECTION_COLORS.UNKNOWN} />;
}

const SEVERITY_COLORS: Record<Severity, string> = {
  INFO: "bg-slate-500/15 text-slate-300 border border-slate-500/30",
  WARNING: "bg-amber-500/15 text-amber-400 border border-amber-500/30",
  ERROR: "bg-orange-500/15 text-orange-400 border border-orange-500/30",
  CRITICAL: "bg-red-500/20 text-red-400 border border-red-500/40",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <Pill text={severity} className={SEVERITY_COLORS[severity] ?? SEVERITY_COLORS.INFO} />;
}

export function TextBadge({ text, tone = "slate" }: { text: string; tone?: string }) {
  const map: Record<string, string> = {
    slate: "bg-slate-500/15 text-slate-300 border border-slate-500/30",
    emerald: "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30",
    amber: "bg-amber-500/15 text-amber-400 border border-amber-500/30",
    red: "bg-red-500/20 text-red-400 border border-red-500/40",
    sky: "bg-sky-500/15 text-sky-400 border border-sky-500/30",
  };
  return <Pill text={text} className={map[tone] ?? map.slate} />;
}

export function DirectionBadge({ direction }: { direction: PositionDirection }) {
  const className =
    direction === "LONG"
      ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
      : "bg-red-500/20 text-red-400 border border-red-500/40";
  return <Pill text={directionLabel(direction)} className={className} />;
}

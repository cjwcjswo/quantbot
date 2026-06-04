// Formatting helpers (frontend doc §20.2: right-align numbers, color PnL).

export function formatNumber(value: string | number | null | undefined, dp = 2): string {
  if (value === null || value === undefined || value === "") return "-";
  const n = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(n)) return String(value);
  return n.toLocaleString(undefined, {
    minimumFractionDigits: dp,
    maximumFractionDigits: dp,
  });
}

export function formatPrice(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "-";
  const n = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(n)) return String(value);
  // adaptive precision for crypto prices
  const dp = Math.abs(n) >= 100 ? 2 : Math.abs(n) >= 1 ? 4 : 6;
  return n.toLocaleString(undefined, { maximumFractionDigits: dp });
}

export function pnlSign(value: string | number | null | undefined): number {
  if (value === null || value === undefined || value === "") return 0;
  const n = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(n)) return 0;
  return n > 0 ? 1 : n < 0 ? -1 : 0;
}

export function pnlClass(value: string | number | null | undefined): string {
  const s = pnlSign(value);
  if (s > 0) return "text-emerald-400";
  if (s < 0) return "text-rose-400";
  return "text-slate-300";
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return "-";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleTimeString();
}

// risk/protection/reconciliation status come from Redis as a string or a {status} object.
export function statusText(value: unknown, fallback: string): string {
  if (value == null) return fallback;
  if (typeof value === "string") return value;
  if (typeof value === "object" && "status" in (value as Record<string, unknown>)) {
    return String((value as Record<string, unknown>).status);
  }
  return fallback;
}

export function timeAgo(value: string | null | undefined): string {
  if (!value) return "-";
  const ms = Date.now() - new Date(value).getTime();
  if (Number.isNaN(ms)) return "-";
  const sec = Math.round(ms / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  return `${Math.round(min / 60)}h ago`;
}

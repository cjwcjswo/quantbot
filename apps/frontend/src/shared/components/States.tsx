import { Button } from "./Button";

export function LoadingState({ label = "불러오는 중…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-8 text-sm text-slate-400">
      <span className="h-3 w-3 animate-pulse rounded-full bg-sky-500" />
      {label}
    </div>
  );
}

export function LoadingSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2 py-2">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-6 animate-pulse rounded bg-slate-800/60" />
      ))}
    </div>
  );
}

export function EmptyState({ label = "데이터 없음" }: { label?: string }) {
  return <div className="py-8 text-center text-sm text-slate-500">{label}</div>;
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="flex flex-col items-start gap-2 rounded border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
      <span>{message}</span>
      {onRetry && (
        <Button variant="secondary" onClick={onRetry}>
          다시 시도
        </Button>
      )}
    </div>
  );
}

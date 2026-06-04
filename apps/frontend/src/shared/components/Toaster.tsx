import { useEffect } from "react";
import { useUiStore } from "@/shared/store/uiStore";
import { cn } from "@/shared/utils/cn";

const TONES: Record<string, string> = {
  info: "border-sky-500/40 bg-sky-500/10 text-sky-200",
  success: "border-emerald-500/40 bg-emerald-500/10 text-emerald-200",
  warning: "border-amber-500/40 bg-amber-500/10 text-amber-200",
  error: "border-red-500/40 bg-red-500/10 text-red-200",
};

function ToastItem({ id, kind, message }: { id: number; kind: string; message: string }) {
  const dismiss = useUiStore((s) => s.dismissToast);
  useEffect(() => {
    const t = setTimeout(() => dismiss(id), 5000);
    return () => clearTimeout(t);
  }, [id, dismiss]);
  return (
    <div
      className={cn(
        "animate-fade-in cursor-pointer rounded-xl border px-3.5 py-2.5 text-sm shadow-lg backdrop-blur-md",
        TONES[kind],
      )}
      onClick={() => dismiss(id)}
    >
      {message}
    </div>
  );
}

export function Toaster() {
  const toasts = useUiStore((s) => s.toasts);
  return (
    <div className="fixed bottom-4 right-3 z-[60] flex w-[min(20rem,calc(100vw-1.5rem))] flex-col gap-2 sm:right-4">
      {toasts.map((t) => (
        <ToastItem key={t.id} id={t.id} kind={t.kind} message={t.message} />
      ))}
    </div>
  );
}

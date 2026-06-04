import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/shared/utils/cn";

type Variant = "primary" | "secondary" | "warning" | "danger" | "danger-outline";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-accent/15 text-accent ring-1 ring-inset ring-accent/30 hover:bg-accent/25 hover:ring-accent/50",
  secondary:
    "bg-white/[0.04] text-slate-200 ring-1 ring-inset ring-white/10 hover:bg-white/[0.08] hover:text-white",
  warning:
    "bg-amber-500/15 text-amber-300 ring-1 ring-inset ring-amber-500/30 hover:bg-amber-500/25",
  danger:
    "bg-rose-500/15 text-rose-300 ring-1 ring-inset ring-rose-500/40 hover:bg-rose-500/25 hover:text-rose-200",
  "danger-outline":
    "text-rose-300 ring-1 ring-inset ring-rose-500/40 hover:bg-rose-500/10",
};

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant };

export function Button({ variant = "secondary", className, ...rest }: Props) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-medium",
        "transition-all duration-150 active:scale-[0.98]",
        "disabled:opacity-40 disabled:cursor-not-allowed disabled:active:scale-100",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60",
        VARIANTS[variant],
        className,
      )}
      {...rest}
    />
  );
}

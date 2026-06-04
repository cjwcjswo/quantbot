import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/shared/utils/cn";

type Variant = "primary" | "secondary" | "warning" | "danger" | "danger-outline";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-sky-600 hover:bg-sky-500 text-white",
  secondary: "bg-slate-700 hover:bg-slate-600 text-slate-100",
  warning: "bg-amber-600 hover:bg-amber-500 text-white",
  danger: "bg-red-600 hover:bg-red-500 text-white",
  "danger-outline": "border border-red-500/60 text-red-400 hover:bg-red-500/10",
};

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant };

export function Button({ variant = "secondary", className, ...rest }: Props) {
  return (
    <button
      className={cn(
        "rounded px-3 py-1.5 text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed",
        VARIANTS[variant],
        className,
      )}
      {...rest}
    />
  );
}

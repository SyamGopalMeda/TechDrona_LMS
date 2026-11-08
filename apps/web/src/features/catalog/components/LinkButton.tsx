import Link from "next/link";
import type { ComponentProps } from "react";
import { cn } from "@/lib/ui/cn";

type Variant = "primary" | "secondary" | "ghost";

const variants: Record<Variant, string> = {
  primary: "bg-brand text-brand-on hover:bg-brand-hover active:bg-brand-active",
  secondary: "border border-line-control bg-surface text-fg hover:bg-surface-hover",
  ghost: "text-fg hover:bg-surface-hover",
};

/** A navigation link styled like the design-system Button (links stay links for a11y). */
export function LinkButton({
  variant = "primary",
  size = "md",
  className,
  ...props
}: ComponentProps<typeof Link> & { variant?: Variant; size?: "sm" | "md" }) {
  return (
    <Link
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors focus-visible:shadow-focus focus-visible:outline-none",
        size === "sm" ? "h-8 px-3 text-sm" : "h-10 px-4 text-sm",
        variants[variant],
        className,
      )}
      {...props}
    />
  );
}

/** Accessible progress bar; the value is always server-reported (never computed client-side). */
export function ProgressBar({ value, label }: { value: number | null | undefined; label: string }) {
  const pct = typeof value === "number" && Number.isFinite(value) ? Math.round(Math.max(0, Math.min(100, value))) : null;
  return (
    <div className="flex items-center gap-2">
      <div
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct ?? undefined}
        aria-valuetext={pct === null ? "Not started" : `${pct}% complete`}
        className="h-2 flex-1 overflow-hidden rounded-full bg-surface-sunken"
      >
        <div className="h-full rounded-full bg-brand" style={{ width: `${pct ?? 0}%` }} />
      </div>
      <span className="w-10 text-right text-xs tabular-nums text-fg-secondary">{pct === null ? "—" : `${pct}%`}</span>
    </div>
  );
}

import { cn } from "@/lib/ui/cn";

/* Server-safe (no hooks, no handlers): usable from server and client components. */

type ProgressTone = "brand" | "success" | "warning" | "danger";

const fillTones: Record<ProgressTone, string> = {
  brand: "bg-brand",
  success: "bg-success-solid",
  warning: "bg-warning-solid",
  danger: "bg-danger-solid",
};

const strokeTones: Record<ProgressTone, string> = {
  brand: "stroke-brand",
  success: "stroke-success-solid",
  warning: "stroke-warning-solid",
  danger: "stroke-danger-solid",
};

function clampPct(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? Math.round(Math.max(0, Math.min(100, value))) : null;
}

export interface ProgressBarProps {
  /** 0–100; server-reported (never computed client-side). null = not started / unknown. */
  value: number | null | undefined;
  /** Accessible name, e.g. "DSA course progress". */
  label: string;
  /** Show the "42%" text beside the bar (default true). */
  showValue?: boolean;
  size?: "sm" | "md";
  tone?: ProgressTone;
  className?: string;
}

/** Accessible progress bar; the value is always server-reported (never computed client-side). */
export function ProgressBar({ value, label, showValue = true, size = "sm", tone = "brand", className }: ProgressBarProps) {
  const pct = clampPct(value);
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct ?? undefined}
        aria-valuetext={pct === null ? "Not started" : `${pct}% complete`}
        className={cn("flex-1 overflow-hidden rounded-full bg-surface-sunken", size === "md" ? "h-3" : "h-2")}
      >
        <div className={cn("h-full rounded-full", fillTones[tone])} style={{ width: `${pct ?? 0}%` }} />
      </div>
      {showValue ? <span className="w-10 text-right text-xs tabular-nums text-fg-secondary">{pct === null ? "—" : `${pct}%`}</span> : null}
    </div>
  );
}

export interface ProgressRingProps {
  /** 0–100 (rounded and clamped). */
  value: number | null | undefined;
  /** Accessible name (default "Progress"). */
  label?: string;
  /** Diameter in px (default 56). */
  size?: number;
  tone?: ProgressTone;
  className?: string;
}

/** Circular % indicator with the value printed in the middle (never colour/length alone). */
export function ProgressRing({ value, label = "Progress", size = 56, tone = "brand", className }: ProgressRingProps) {
  const pct = clampPct(value);
  const v = pct ?? 0;
  const stroke = size >= 48 ? 6 : 4;
  const r = (size - stroke - 2) / 2;
  const c = 2 * Math.PI * r;
  return (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct ?? undefined}
      aria-valuetext={pct === null ? "Not started" : `${pct}% complete`}
      aria-label={label}
      className={cn("relative inline-flex shrink-0 items-center justify-center", className)}
      style={{ width: size, height: size }}
    >
      <svg width={size} height={size} aria-hidden="true" className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke} className="stroke-surface-sunken" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - v / 100)}
          className={strokeTones[tone]}
        />
      </svg>
      <span aria-hidden="true" className="absolute text-xs font-semibold tabular-nums text-fg">
        {pct === null ? "—" : `${pct}%`}
      </span>
    </div>
  );
}

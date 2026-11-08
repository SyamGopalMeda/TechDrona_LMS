import type { ReactNode } from "react";
import { cn } from "@/lib/ui/cn";

/**
 * Staff risk-level visuals (design-system §3.3, §5.13): every level ships with a label, an
 * icon and a 4-pip meter, so meaning never depends on hue. No level uses red.
 */

export type RiskLevelNumber = 0 | 1 | 2 | 3 | 4;

export const STAFF_LEVEL_LABEL: Record<RiskLevelNumber, string> = {
  0: "L0 · None",
  1: "L1 · Notice",
  2: "L2 · Verify",
  3: "L3 · Temporary restriction",
  4: "L4 · Suspended",
};

const TOKENS: Record<RiskLevelNumber, { pill: string; pip: string }> = {
  0: { pill: "bg-risk-l0-subtle text-risk-l0-fg border-risk-l0-border", pip: "bg-risk-l0-border" },
  1: { pill: "bg-risk-l1-subtle text-risk-l1-fg border-risk-l1-border", pip: "bg-risk-l1-border" },
  2: { pill: "bg-risk-l2-subtle text-risk-l2-fg border-risk-l2-border", pip: "bg-risk-l2-border" },
  3: { pill: "bg-risk-l3-subtle text-risk-l3-fg border-risk-l3-border", pip: "bg-risk-l3-border" },
  4: { pill: "bg-risk-l4-subtle text-risk-l4-fg border-risk-l4-border", pip: "bg-risk-l4-border" },
};

export function toLevel(n: unknown): RiskLevelNumber | null {
  const v = typeof n === "string" ? Number(n.replace(/^L/i, "")) : n;
  return v === 0 || v === 1 || v === 2 || v === 3 || v === 4 ? v : null;
}

/** Lucide-equivalent outlines: shield-check, info, smartphone, pause-circle, lock. */
function LevelIcon({ level }: { level: RiskLevelNumber }) {
  const common = { width: 14, height: 14, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true, focusable: false };
  const paths: Record<RiskLevelNumber, ReactNode> = {
    0: (
      <>
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
        <path d="m9 12 2 2 4-4" />
      </>
    ),
    1: (
      <>
        <circle cx="12" cy="12" r="10" />
        <path d="M12 16v-4M12 8h.01" />
      </>
    ),
    2: (
      <>
        <rect x="5" y="2" width="14" height="20" rx="2" />
        <path d="M12 18h.01" />
      </>
    ),
    3: (
      <>
        <circle cx="12" cy="12" r="10" />
        <path d="M10 15V9M14 15V9" />
      </>
    ),
    4: (
      <>
        <rect x="3" y="11" width="18" height="11" rx="2" />
        <path d="M7 11V7a5 5 0 0 1 10 0v4" />
      </>
    ),
  };
  return <svg {...common}>{paths[level]}</svg>;
}

/** 4 pips 8×8 px, gap 4 px; filled = level. */
export function LevelMeter({ level }: { level: RiskLevelNumber }) {
  return (
    <span role="img" aria-label={`Level ${level} of 4`} className="inline-flex items-center gap-1">
      {[1, 2, 3, 4].map((i) => (
        <span key={i} aria-hidden="true" data-filled={i <= level || undefined} className={cn("h-2 w-2 rounded-full", i <= level ? TOKENS[level].pip : "bg-line-strong")} />
      ))}
    </span>
  );
}

/** Staff risk badge: pill + icon + "L3 · Temporary restriction" + pips. Unknown level renders "—". */
export function RiskBadge({ level, compact = false }: { level: unknown; compact?: boolean }) {
  const lv = toLevel(level);
  if (lv === null) return <span className="text-fg-muted">—</span>;
  const label = STAFF_LEVEL_LABEL[lv];
  return (
    <span className={cn("inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium", TOKENS[lv].pill)}>
      <LevelIcon level={lv} />
      <span>{compact ? `L${lv}` : label}</span>
      {compact ? <span className="sr-only">{label.slice(5)}</span> : null}
      <LevelMeter level={lv} />
    </span>
  );
}

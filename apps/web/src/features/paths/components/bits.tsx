import { Badge, type BadgeTone } from "@/components/ui";
import type { Flow, StepState, StepType } from "../lib/types";

export const STEP_TYPE_LABEL: Record<StepType, string> = {
  reading: "Reading",
  video: "Video",
  article: "Article",
  assignment: "Assignment",
  assessment: "Assessment",
  super_step: "Super-step",
};

const STEP_GLYPH: Record<StepType, string> = {
  reading: "📄",
  video: "▶",
  article: "📖",
  assignment: "✎",
  assessment: "☑",
  super_step: "▤",
};

/** Step type icon with an accessible name. */
export function StepTypeIcon({ type, className }: { type: StepType; className?: string }) {
  return (
    <span role="img" aria-label={STEP_TYPE_LABEL[type]} title={STEP_TYPE_LABEL[type]} className={className}>
      {STEP_GLYPH[type]}
    </span>
  );
}

const STATE: Record<StepState, { tone: BadgeTone; label: string }> = {
  locked: { tone: "neutral", label: "Locked" },
  available: { tone: "info", label: "Available" },
  in_progress: { tone: "warning", label: "In progress" },
  completed: { tone: "success", label: "Completed" },
};

export function StepStateBadge({ state }: { state: StepState }) {
  const s = STATE[state];
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

export function FlowBadge({ flow }: { flow: Flow }) {
  return flow === "strict" ? <Badge tone="warning">On timeline</Badge> : <Badge tone="brand">Own pace</Badge>;
}

export function OrderBadge({ sequential }: { sequential: boolean }) {
  return <Badge>{sequential ? "Sequential" : "Any order"}</Badge>;
}

/** Circular % progress indicator. */
export function ProgressRing({ pct, size = 56 }: { pct: number; size?: number }) {
  const v = Math.max(0, Math.min(100, Math.round(pct)));
  const r = (size - 8) / 2;
  const c = 2 * Math.PI * r;
  return (
    <div role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={v} aria-label="Path progress" className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} aria-hidden="true" className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={6} className="stroke-surface-sunken" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          strokeWidth={6}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - v / 100)}
          className="stroke-brand"
        />
      </svg>
      <span className="absolute text-xs font-semibold tabular-nums text-fg">{v}%</span>
    </div>
  );
}

export function ProgressBar({ pct, label }: { pct: number; label: string }) {
  const v = Math.max(0, Math.min(100, Math.round(pct)));
  return (
    <div role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={v} aria-label={label} className="h-2 w-full overflow-hidden rounded-full bg-surface-sunken">
      <div className="h-full rounded-full bg-brand" style={{ width: `${v}%` }} />
    </div>
  );
}

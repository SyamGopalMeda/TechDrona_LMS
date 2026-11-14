import { Badge, ProgressBar as KitProgressBar, ProgressRing as KitProgressRing, StatusBadge } from "@/components/ui";
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

export function StepStateBadge({ state }: { state: StepState }) {
  return <StatusBadge status={state} />;
}

export function FlowBadge({ flow }: { flow: Flow }) {
  return flow === "strict" ? <Badge tone="warning">On timeline</Badge> : <Badge tone="brand">Own pace</Badge>;
}

export function OrderBadge({ sequential }: { sequential: boolean }) {
  return <Badge>{sequential ? "Sequential" : "Any order"}</Badge>;
}

/** Circular % progress indicator (kit ProgressRing). */
export function ProgressRing({ pct, size = 56 }: { pct: number; size?: number }) {
  return <KitProgressRing value={pct} size={size} label="Path progress" />;
}

/** Thin progress bar without the % text (kit ProgressBar). */
export function ProgressBar({ pct, label }: { pct: number; label: string }) {
  return <KitProgressBar value={pct} label={label} showValue={false} className="w-full" />;
}

"use client";

import type { ReactNode } from "react";
import {
  Badge,
  ErrorState,
  Skeleton,
  useToast,
  type BadgeTone,
} from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import type { ApiState } from "./use-api";

export {
  formatDate,
  formatDateTime,
  formatRelative,
} from "@/features/auth/lib/format";

/* ------------------------------------------------------------ k-anonymity floor */

/** `403 k_anonymity_floor` (api-spec §2.3): the whole report was suppressed. */
export function isKFloor(err: unknown): err is ApiError {
  return err instanceof ApiError && err.code === "k_anonymity_floor";
}

export function kMin(err: unknown, fallback = 10): number {
  if (err instanceof ApiError) {
    const v = err.problem?.k_min;
    if (typeof v === "number" && v > 0) return v;
  }
  return fallback;
}

/** Shown in place of a report/cell whose group is below the k-floor. Never shows a number. */
export function KFloorNotice({
  k = 10,
  compact = false,
}: {
  k?: number;
  compact?: boolean;
}) {
  if (compact)
    return (
      <span className="text-sm text-fg-muted">Too few students to show</span>
    );
  return (
    <div
      role="status"
      className="rounded-xl border border-dashed border-line-strong bg-surface p-6 text-center"
    >
      <p className="font-medium text-fg">Too few students to show</p>
      <p className="mx-auto mt-1 max-w-prose text-sm text-fg-muted">
        To protect student privacy, group results are only shown when at least{" "}
        {k} students are included. Widen the date range or choose a larger
        group.
      </p>
    </div>
  );
}

/** Suppressed aggregate cell (`{"suppressed": true}`). */
export function isSuppressed(v: unknown): v is { suppressed: true } {
  return (
    typeof v === "object" &&
    v !== null &&
    (v as { suppressed?: unknown }).suppressed === true
  );
}

/**
 * analytics `k_cell` (apps/api analytics/reports.py): a count/ratio below the k-floor arrives
 * as the string "<10" instead of a number. Returns the number, or null when suppressed.
 */
export function kValue(v: unknown): number | null {
  return typeof v === "number" ? v : null;
}

/** Honest placeholder for a screen/section whose backend endpoint doesn't exist yet. */
export function NotAvailable({
  title = "Not available yet",
  description,
  compact = false,
}: {
  title?: string;
  description?: string;
  compact?: boolean;
}) {
  if (compact) return <p className="text-sm text-fg-muted">{title}</p>;
  return (
    <div
      role="status"
      className="rounded-xl border border-dashed border-line-strong bg-surface p-6 text-center"
    >
      <p className="font-medium text-fg">{title}</p>
      {description ? (
        <p className="mx-auto mt-1 max-w-prose text-sm text-fg-muted">
          {description}
        </p>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------ boundaries */

export function LoadingBlock({
  rows = 3,
  label = "Loading",
}: {
  rows?: number;
  label?: string;
}) {
  return (
    <div aria-busy="true" aria-label={label} className="space-y-2">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-6 w-full" />
      ))}
    </div>
  );
}

/** L / X / k-floor states around one resource, then renders children with the data. */
export function Boundary<T>({
  state,
  children,
  rows,
}: {
  state: ApiState<T>;
  children: (data: T) => ReactNode;
  rows?: number;
}) {
  if (state.error) {
    if (isKFloor(state.error)) return <KFloorNotice k={kMin(state.error)} />;
    return (
      <ErrorState error={state.error} onRetry={() => void state.reload()} />
    );
  }
  if (state.loading && state.data === undefined)
    return <LoadingBlock rows={rows} />;
  if (state.data === undefined) return null;
  return <>{children(state.data)}</>;
}

/* ---------------------------------------------------------------------- toasts */

export function useFailToast() {
  const toast = useToast();
  return (err: unknown, fallback = "That didn't work") => {
    // Scoped grading (WS4 SEC-02, WS5 SEC-10): explain the two refusals graders actually meet.
    if (err instanceof ApiError && err.status === 403 && (err.code === "permission_denied" || err.code === "conflict_of_interest"))
      toast.show({
        tone: "danger",
        title: fallback,
        description:
          err.code === "conflict_of_interest"
            ? "You can't grade, extend or decide on your own work. Another grader has to do it."
            : "This is outside the batches or role you hold. Ask an Admin if you need access.",
        requestId: err.requestId,
      });
    else if (err instanceof ApiError)
      toast.show({
        tone: "danger",
        title: err.title,
        description: err.detail,
        requestId: err.requestId,
      });
    else
      toast.show({
        tone: "danger",
        title: fallback,
        description: "Please try again.",
      });
  };
}

/** problem+json `errors[]` → { field: message }. */
export function fieldErrorsOf(err: unknown): Record<string, string> {
  if (!(err instanceof ApiError)) return {};
  const out: Record<string, string> = {};
  for (const e of err.problem?.errors ?? [])
    if (!(e.field in out)) out[e.field] = e.message;
  return out;
}

/* ---------------------------------------------------------------------- badges */

const STATUS: Record<string, { tone: BadgeTone; label: string }> = {
  draft: { tone: "neutral", label: "Draft" },
  in_review: { tone: "info", label: "In review" },
  changes_requested: { tone: "warning", label: "Changes requested" },
  approved: { tone: "success", label: "Approved" },
  published: { tone: "success", label: "Published" },
  archived: { tone: "neutral", label: "Archived" },
  retired: { tone: "neutral", label: "Retired" },
  active: { tone: "success", label: "Active" },
  planned: { tone: "info", label: "Planned" },
  completed: { tone: "neutral", label: "Completed" },
  invited: { tone: "info", label: "Invited" },
  removed: { tone: "neutral", label: "Removed" },
  graduated: { tone: "neutral", label: "Graduated" },
  sent: { tone: "info", label: "Sent" },
  opened: { tone: "info", label: "Opened" },
  accepted: { tone: "success", label: "Accepted" },
  expired: { tone: "neutral", label: "Expired" },
  bounced: { tone: "warning", label: "Bounced" },
  revoked: { tone: "neutral", label: "Revoked" },
  proposed: { tone: "warning", label: "Pending verification" },
  verified: { tone: "success", label: "Verified" },
  rejected: { tone: "danger", label: "Rejected" },
  submitted: { tone: "info", label: "Submitted" },
  graded: { tone: "success", label: "Graded" },
  returned: { tone: "warning", label: "Returned" },
  late: { tone: "warning", label: "Late" },
  in_progress: { tone: "info", label: "In progress" },
  auto_submitted: { tone: "info", label: "Auto-submitted" },
  invalidated: { tone: "danger", label: "Invalidated" },
  scheduled: { tone: "info", label: "Scheduled" },
  confirmed: { tone: "info", label: "Confirmed" },
  no_show_student: { tone: "warning", label: "Student no-show" },
  no_show_mentor: { tone: "warning", label: "Mentor no-show" },
  cancelled: { tone: "neutral", label: "Cancelled" },
};

export function StatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return <Badge>Unknown</Badge>;
  const s = STATUS[status] ?? {
    tone: "neutral" as const,
    label: status.replace(/_/g, " "),
  };
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

/* -------------------------------------------------------------------- bar list */

export interface BarItem {
  label: string;
  /** null = suppressed (below k-floor) */
  value: number | null;
  display?: string;
}

/**
 * Horizontal labelled bars (ordinal bands use the indigo band ramp, design-system §charts).
 * Every bar carries its value as text, so meaning never depends on colour or length alone.
 */
export function BarList({
  items,
  label,
  max,
  ordinal = false,
}: {
  items: BarItem[];
  label: string;
  max?: number;
  ordinal?: boolean;
}) {
  const top = max ?? Math.max(1, ...items.map((i) => i.value ?? 0));
  const bands = [
    "bg-chart-band-1",
    "bg-chart-band-2",
    "bg-chart-band-3",
    "bg-chart-band-4",
  ];
  return (
    <ul aria-label={label} className="space-y-2">
      {items.map((it, idx) => (
        <li
          key={it.label}
          className="grid grid-cols-[minmax(5rem,9rem)_1fr_auto] items-center gap-3 text-sm"
        >
          <span className="truncate text-fg-secondary">{it.label}</span>
          <span className="h-3 rounded-sm bg-surface-sunken" aria-hidden="true">
            {it.value !== null ? (
              <span
                className={`block h-3 rounded-sm ${ordinal ? bands[Math.min(idx, 3)] : "bg-chart-1"}`}
                style={{
                  width: `${Math.max(2, Math.round((it.value / top) * 100))}%`,
                }}
              />
            ) : null}
          </span>
          <span className="tabular-nums text-fg">
            {it.value === null ? (
              <KFloorNotice compact />
            ) : (
              (it.display ?? String(it.value))
            )}
          </span>
        </li>
      ))}
    </ul>
  );
}

/* ------------------------------------------------------------------- helpers */

/** `<input type="datetime-local">` value (browser local time) → RFC 3339 UTC. */
export function localInputToIso(v: string): string | null {
  if (!v) return null;
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

export function pct(v: number | null | undefined): string {
  return typeof v === "number" ? `${Math.round(v)}%` : "—";
}

/** Only http(s) links are rendered as external links (meeting URLs, signed URLs). */
export function safeExternalUrl(u: string | null | undefined): string | null {
  if (!u) return null;
  try {
    const url = new URL(u);
    return url.protocol === "https:" || url.protocol === "http:"
      ? url.toString()
      : null;
  } catch {
    return null;
  }
}

/* -------------------------------------------------------------------- textarea */

export function TextArea(props: import("react").ComponentProps<"textarea">) {
  const { className, ...rest } = props;
  return (
    <textarea
      rows={4}
      {...rest}
      className={`w-full rounded-md border border-line-control bg-surface p-2 text-sm text-fg focus-visible:shadow-focus focus-visible:outline-none ${className ?? ""}`}
    />
  );
}

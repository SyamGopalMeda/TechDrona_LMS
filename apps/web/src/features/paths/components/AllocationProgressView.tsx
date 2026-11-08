"use client";

import Link from "next/link";
import { Badge, StatTile, Table } from "@/components/ui";
import { formatDateTime } from "@/features/trainer/shared/ui";
import { useApi } from "@/features/trainer/shared/use-api";
import { seg } from "../lib/api";
import { formatHours, formatPlanDate } from "../lib/pace";
import type { AllocationProgress, LearnerProgress } from "../lib/types";
import { FlowBadge, OrderBadge, ProgressBar } from "./bits";
import { usePathsBase } from "../lib/base";

/** Per-allocation progress dashboard (trainer). */
export function AllocationProgressView({ allocationId }: { allocationId: string }) {
  const base = usePathsBase();
  const state = useApi<AllocationProgress>(`path-allocations/${seg(allocationId)}/progress`);
  const d = state.data;
  const learners = d?.learners;
  const avg = learners && learners.length ? Math.round(learners.reduce((s, l) => s + l.pct, 0) / learners.length) : null;
  const done = learners ? learners.filter((l) => l.total_steps > 0 && l.completed_steps >= l.total_steps).length : null;
  const behind = learners ? learners.filter((l) => l.behind).length : null;

  return (
    <div className="space-y-6">
      {d ? (
        <div>
          <Link href={`${base}/${encodeURIComponent(d.path.id)}`} className="text-sm text-fg-link underline">
            ← {d.path.title}
          </Link>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-fg-muted">
            <FlowBadge flow={d.allocation.flow} />
            <OrderBadge sequential={d.allocation.sequential} />
            <span>
              {d.allocation.target_type === "batch" ? (d.allocation.batch_name ?? "Batch") : "Individual learners"} · v{d.allocation.version_no} · {formatHours(d.allocation.total_hours)} ·{" "}
              {formatPlanDate(d.allocation.start_date)} → {formatPlanDate(d.allocation.finish_date)}
            </span>
            {d.allocation.status === "revoked" ? <Badge tone="danger">Removed</Badge> : null}
          </div>
        </div>
      ) : null}
      <div className="grid gap-3 sm:grid-cols-4">
        <StatTile label="Learners" value={learners ? learners.length : null} />
        <StatTile label="Average progress" value={avg === null ? null : `${avg}%`} />
        <StatTile label="Completed" value={done} />
        <StatTile label="Behind plan" value={behind} hint={d?.allocation.flow === "strict" ? "Past a step's due date" : "Suggested plan only"} />
      </div>
      <Table<LearnerProgress>
        caption="Learner progress"
        rows={learners}
        loading={state.loading && !d}
        error={state.error}
        onRetry={() => void state.reload()}
        rowKey={(r) => r.user_id}
        empty={{ title: "No learners yet", description: "Learners appear here once they are in the allocated batch or chosen." }}
        columns={[
          { key: "name", header: "Learner", cell: (r) => (
            <div>
              <p className="font-medium">{r.full_name ?? "Learner"}</p>
              <p className="text-xs text-fg-muted">{r.email}</p>
            </div>
          ) },
          { key: "steps", header: "Steps", cell: (r) => `${r.completed_steps}/${r.total_steps}`, align: "right" },
          { key: "credits", header: "Credits", cell: (r) => `${r.credits_earned}/${r.total_credits}`, align: "right" },
          { key: "pct", header: "Progress", cell: (r) => (
            <div className="flex min-w-[8rem] items-center gap-2">
              <ProgressBar pct={r.pct} label={`${r.full_name ?? "Learner"} progress`} />
              <span className="w-10 text-right tabular-nums">{Math.round(r.pct)}%</span>
            </div>
          ) },
          { key: "last", header: "Last activity", cell: (r) => (r.last_activity_at ? formatDateTime(r.last_activity_at) : "—") },
          { key: "status", header: "Status", cell: (r) => (r.behind ? <Badge tone="warning">Behind</Badge> : <Badge tone="success">On track</Badge>) },
        ]}
      />
    </div>
  );
}

"use client";

import Link from "next/link";
import { Badge, EmptyState, ErrorState, PageHeader, Skeleton, Tabs, type BadgeTone } from "@/components/ui";
import { assessmentApi } from "../lib/api";
import { formatDuration, formatIstDateTime } from "../lib/format";
import type { TestRowData } from "../lib/types";
import { useLoader, type Resource } from "../lib/use-resource";

const STATUS: Record<string, { label: string; tone: BadgeTone }> = {
  available: { label: "Available", tone: "brand" },
  in_progress: { label: "In progress", tone: "warning" },
  scheduled: { label: "Scheduled", tone: "info" },
  completed: { label: "Completed", tone: "success" },
  closed: { label: "Closed", tone: "neutral" },
};

/** ASM-01 has no server-side filter: tabs group the row statuses client-side. */
const FILTERS = [
  { id: "available", label: "Available", statuses: ["in_progress", "available"] },
  { id: "scheduled", label: "Scheduled", statuses: ["scheduled"] },
  { id: "completed", label: "Completed", statuses: ["completed", "closed"] },
];

function TestRow({ t }: { t: TestRowData }) {
  const s = STATUS[t.status] ?? { label: t.status, tone: "neutral" as BadgeTone };
  const resumeHref = t.in_progress_attempt_id ? `/app/attempts/${encodeURIComponent(t.in_progress_attempt_id)}` : null;
  return (
    <li className="flex flex-col gap-3 rounded-xl border border-line bg-surface p-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <p className="font-semibold text-fg">{t.title}</p>
        <p className="mt-1 text-sm text-fg-muted">
          {t.duration_seconds ? `${formatDuration(t.duration_seconds)} · ` : ""}
          {t.status === "scheduled" && t.available_from ? `Opens ${formatIstDateTime(t.available_from)}` : t.available_until ? `Closes ${formatIstDateTime(t.available_until)}` : "No deadline"}
          {t.attempts_left !== undefined && t.attempts_left !== null ? ` · ${t.attempts_left} attempt${t.attempts_left === 1 ? "" : "s"} left` : ""}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <Badge tone={s.tone}>{s.label}</Badge>
        {resumeHref ? (
          <Link className="text-sm font-medium text-fg-link underline" href={resumeHref}>
            Resume test
          </Link>
        ) : t.last_attempt && (t.status === "completed" || t.status === "closed") ? (
          <Link className="text-sm font-medium text-fg-link underline" href={`/app/tests/${encodeURIComponent(t.test_id)}/results/${encodeURIComponent(t.last_attempt.attempt_id)}`}>
            View results
          </Link>
        ) : (
          <Link className="text-sm font-medium text-fg-link underline" href={`/app/tests/${encodeURIComponent(t.test_id)}`}>
            View instructions
          </Link>
        )}
      </div>
    </li>
  );
}

function TestsTab({ status, res }: { status: string; res: Resource<TestRowData[]> }) {
  if (res.error) return <ErrorState error={res.error} onRetry={() => void res.reload()} />;
  if (res.loading && !res.data)
    return (
      <div aria-busy="true" className="space-y-3">
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-20 w-full" />
      </div>
    );
  const statuses = FILTERS.find((f) => f.id === status)?.statuses ?? [status];
  const rows = (res.data ?? []).filter((t) => statuses.includes(t.status));
  if (rows.length === 0)
    return (
      <EmptyState
        title={status === "completed" ? "No completed tests yet" : "No tests here yet"}
        description="When your trainer assigns a test, it appears here. Meanwhile, practise a topic."
        action={<Link className="text-sm font-medium text-fg-link underline" href="/app/practice">Go to practice</Link>}
      />
    );
  return (
    <ul className="space-y-3">
      {rows.map((t) => (
        <TestRow key={t.test_id} t={t} />
      ))}
    </ul>
  );
}

/** STU-009 Tests list (ASM-01). */
export function TestsList() {
  const res = useLoader("me/tests", () => assessmentApi.listTests());
  return (
    <div>
      <PageHeader title="Tests" description="Mock tests and assigned tests. The timer runs on our server once you start." />
      <Tabs label="Filter tests" items={FILTERS.map((f) => ({ id: f.id, label: f.label, content: <TestsTab status={f.id} res={res} /> }))} />
    </div>
  );
}

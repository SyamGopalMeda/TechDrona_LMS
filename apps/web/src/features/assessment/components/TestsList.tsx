"use client";

import { StatusBadge, EmptyState, ErrorState, LinkButton, LoadingBlock, PageHeader, Tabs } from "@/components/ui";
import { assessmentApi } from "../lib/api";
import { formatDuration, formatIstDateTime } from "../lib/format";
import type { TestRowData } from "../lib/types";
import { useLoader, type Resource } from "../lib/use-resource";

/** ASM-01 has no server-side filter: tabs group the row statuses client-side. */
const FILTERS = [
  { id: "available", label: "Available", statuses: ["in_progress", "available"] },
  { id: "scheduled", label: "Scheduled", statuses: ["scheduled"] },
  { id: "completed", label: "Completed", statuses: ["completed", "closed"] },
];

/** The one action for a row: resume, see results, or open the instructions (where "Start" lives). */
export function testRowAction(t: TestRowData): { href: string; label: string } {
  const enc = encodeURIComponent;
  if (t.in_progress_attempt_id) return { href: `/app/attempts/${enc(t.in_progress_attempt_id)}`, label: "Resume test" };
  if (t.last_attempt && (t.status === "completed" || t.status === "closed")) return { href: `/app/tests/${enc(t.test_id)}/results/${enc(t.last_attempt.attempt_id)}`, label: "View results" };
  return { href: `/app/tests/${enc(t.test_id)}`, label: "Open test" };
}

/**
 * One test as a card that is clickable as a whole: the visible action button is the only link and
 * its ::after overlay stretches over the card (one tab stop, one accessible name). The status badge
 * is shown only when it adds something ("In progress", "Scheduled", "Completed"), not on every
 * "Available" row of the Available tab.
 */
function TestRow({ t }: { t: TestRowData }) {
  const action = testRowAction(t);
  return (
    <li className="relative flex flex-col gap-3 rounded-xl border border-line bg-surface p-4 shadow-xs transition-colors hover:border-brand/40 hover:bg-surface-hover sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <p className="break-words font-display font-bold text-fg-heading">{t.title}</p>
          {t.status !== "available" ? <StatusBadge status={t.status} /> : null}
        </div>
        <p className="mt-1 text-sm text-fg-muted">
          {t.duration_seconds ? `${formatDuration(t.duration_seconds)} · ` : ""}
          {t.status === "scheduled" && t.available_from ? `Opens ${formatIstDateTime(t.available_from)}` : t.available_until ? `Closes ${formatIstDateTime(t.available_until)}` : "No deadline"}
          {t.attempts_left !== undefined && t.attempts_left !== null ? ` · ${t.attempts_left} attempt${t.attempts_left === 1 ? "" : "s"} left` : ""}
        </p>
      </div>
      <LinkButton
        href={action.href}
        size="sm"
        variant={t.in_progress_attempt_id ? "primary" : "secondary"}
        aria-label={`${action.label}: ${t.title}`}
        className="shrink-0 self-start after:absolute after:inset-0 after:rounded-xl sm:self-auto"
      >
        {action.label}
      </LinkButton>
    </li>
  );
}

function TestsTab({ status, res }: { status: string; res: Resource<TestRowData[]> }) {
  if (res.error) return <ErrorState error={res.error} onRetry={() => void res.reload()} />;
  if (res.loading && !res.data) return <LoadingBlock label="Loading your tests" rows={2} size="card" />;
  const statuses = FILTERS.find((f) => f.id === status)?.statuses ?? [status];
  const rows = (res.data ?? []).filter((t) => statuses.includes(t.status));
  if (rows.length === 0)
    return (
      <EmptyState
        icon={status === "completed" ? "award" : "calendar"}
        title={status === "completed" ? "No completed tests yet" : status === "scheduled" ? "No tests scheduled" : "No tests open right now"}
        description="When your trainer assigns a test, it appears here. Meanwhile, practise a topic."
        action={
          <LinkButton href="/app/practice" variant="secondary" size="sm">
            Go to practice
          </LinkButton>
        }
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
      <PageHeader title="Tests" description="Timed mock tests and tests from your trainer." />
      <Tabs label="Filter tests" items={FILTERS.map((f) => ({ id: f.id, label: f.label, content: <TestsTab status={f.id} res={res} /> }))} />
    </div>
  );
}

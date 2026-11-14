"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, ErrorState, StatGrid, StatTile, Table } from "@/components/ui";
import { api, type Page } from "@/lib/api/client";
import { useMemberNames, useTeachingQuery } from "../lib/batches";
import type { AssignmentSummary, TestAssignment, TestSummary } from "../lib/types";
import { useApi, seg } from "../shared/use-api";
import { LoadingBlock, formatDateTime } from "../shared/ui";
import { LessonFunnelView, ProgressDistributionView, type LessonFunnelCourse, type ProgressDistribution } from "../shared/report-sections";

/* ---------------------------------------------------------------- grading backlog */

/** TRN-001 grading backlog: `GET /assignments?scope=mine` carries `pending_count` per assignment. */
export function GradingBacklog() {
  // verified: app/modules/learning/router.py list_assignments → pending_count (submitted + late)
  const list = useApi<Page<AssignmentSummary>>("assignments", { scope: "mine", limit: 100, ...useTeachingQuery() });
  if (list.error) return <ErrorState error={list.error} onRetry={() => void list.reload()} />;
  if (list.loading || !list.data) return <p className="text-sm text-fg-muted">Loading grading backlog…</p>;
  const pending = list.data.data.filter((a) => a.pending_count > 0).sort((a, b) => b.pending_count - a.pending_count);
  const total = pending.reduce((n, a) => n + a.pending_count, 0);
  if (total === 0) return <p className="text-sm text-fg-secondary">No submissions are waiting to be graded.</p>;
  return (
    <div className="space-y-2">
      <p className="text-sm text-fg-secondary">
        <span className="font-display text-2xl font-bold tabular-nums text-fg">
          {total}
          {list.data.page.has_more ? "+" : ""}
        </span>{" "}
        submission{total === 1 ? "" : "s"} waiting to be graded.
      </p>
      <ul className="space-y-1 text-sm">
        {pending.slice(0, 5).map((a) => (
          <li key={a.assignment_id} className="flex min-w-0 justify-between gap-2">
            <span className="min-w-0 truncate">
              {a.title}
              {a.batch_name ? <span className="text-fg-muted"> · {a.batch_name}</span> : null}
            </span>
            <span className="shrink-0 tabular-nums text-fg-secondary">{a.pending_count}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ---------------------------------------------------------------- live tests */

export interface LiveRow {
  test: TestSummary;
  assignment: TestAssignment;
  live: boolean;
}

/** Published tests whose assignment window for one of `batchIds` is open now or opens within 7 days. */
export function pickLive(tests: TestSummary[], assignments: TestAssignment[][], batchIds: string[], now = Date.now()): LiveRow[] {
  const soon = now + 7 * 24 * 3600 * 1000;
  const rows: LiveRow[] = [];
  tests.forEach((t, i) => {
    for (const a of assignments[i] ?? []) {
      if (!a.batch_id || !batchIds.includes(a.batch_id)) continue;
      const from = Date.parse(a.available_from);
      const until = Date.parse(a.available_until);
      if (until < now || from > soon) continue;
      rows.push({ test: t, assignment: a, live: from <= now });
    }
  });
  return rows.sort((x, y) => Number(y.live) - Number(x.live) || Date.parse(x.assignment.available_from) - Date.parse(y.assignment.available_from));
}

/** Max tests whose assignments are fetched (ASM-11 is per test; there is no batch-level list). */
const LIVE_SCAN = 25;

/** TRN-001 live and upcoming tests for the trainer's batches (ASM-03 + ASM-11 per published test). */
export function LiveTests({ batches }: { batches: { id: string; name: string }[] }) {
  const tests = useApi<{ items: TestSummary[] }>("studio/tests");
  const [rows, setRows] = useState<LiveRow[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const ids = batches.map((b) => b.id);
  const idKey = ids.join(",");
  const published = (tests.data?.items ?? []).filter((t) => t.status === "published");
  const scanned = published.slice(0, LIVE_SCAN);
  const scanKey = scanned.map((t) => t.id).join(",");

  useEffect(() => {
    if (!tests.data) return;
    let live = true;
    const list = scanKey ? scanKey.split(",") : [];
    setError(null);
    Promise.all(list.map((id) => api.get<{ items: TestAssignment[] }>(`tests/${seg(id)}/assignments`).then((r) => r.items)))
      .then((as) => {
        if (!live) return;
        const byId = new Map((tests.data?.items ?? []).map((t) => [t.id, t]));
        setRows(pickLive(list.map((id) => byId.get(id)!), as, idKey ? idKey.split(",") : []));
      })
      .catch((e) => live && setError(e));
    return () => {
      live = false;
    };
  }, [tests.data, scanKey, idKey]);

  const err = tests.error ?? error;
  if (err) return <ErrorState error={err} onRetry={() => void tests.reload()} />;
  if (tests.loading || rows === null) return <LoadingBlock rows={2} label="Loading live tests" />;
  const batchName = (id: string | null) => batches.find((b) => b.id === id)?.name ?? "Batch";
  return (
    <div className="space-y-2">
      <Table
        caption="Live and upcoming tests"
        columns={[
          {
            key: "t",
            header: "Test",
            cell: (r: LiveRow) => (
              <Link className="text-fg-link underline" href={`/trainer/tests/${seg(r.test.id)}/attempts`}>
                {r.test.title}
              </Link>
            ),
          },
          { key: "b", header: "Batch", cell: (r) => batchName(r.assignment.batch_id) },
          { key: "s", header: "State", cell: (r) => (r.live ? "Live now" : `Opens ${formatDateTime(r.assignment.available_from)}`) },
          { key: "c", header: "Closes", cell: (r) => formatDateTime(r.assignment.available_until) },
        ]}
        rows={rows}
        rowKey={(r) => r.assignment.id}
        empty={{ title: "No live tests", description: "Nothing is open for your batches now or in the next 7 days." }}
      />
      {published.length > LIVE_SCAN ? (
        <p className="text-xs text-fg-muted">Checked the {LIVE_SCAN} most recent published tests.</p>
      ) : null}
    </div>
  );
}

/* ---------------------------------------------------------------- batch progress */

/** verified: app/modules/analytics/reports.py batch_report */
export interface BatchReport {
  batch_id: string;
  week_start: string;
  learners_total: number;
  weekly_learning_time: { n: number | string; median_s: number | string; p90_s: number | string; suppressed: boolean };
  learners: { user_id: string; weekly_learning_s: number; weak_topics: number; needs_attention: boolean; reasons: string[] }[];
  progress_distribution: ProgressDistribution | null;
  lesson_funnel: LessonFunnelCourse[] | null;
}

const mins = (s: number | string) => (typeof s === "number" ? `${Math.round(s / 60)} min` : "—");

/** TRN-002 batch insights from AN `GET /analytics/reports/batches/{id}` (k-anonymity respected). */
export function BatchProgress({ batchId }: { batchId: string }) {
  const report = useApi<BatchReport>(`analytics/reports/batches/${seg(batchId)}`);
  const nameOf = useMemberNames([batchId]);
  if (report.error) return <ErrorState error={report.error} onRetry={() => void report.reload()} />;
  if (report.loading || !report.data) return <LoadingBlock rows={3} label="Loading batch progress" />;
  const r = report.data;
  const atRisk = r.learners.filter((l) => l.needs_attention);
  const weak = r.learners.filter((l) => l.weak_topics > 0).sort((a, b) => b.weak_topics - a.weak_topics);
  const wl = r.weekly_learning_time;
  return (
    <Card title="Batch progress">
      <div className="space-y-4">
        <StatGrid columns={3}>
          <StatTile label="Learners" value={String(r.learners_total)} />
          <StatTile label="Median learning time this week" value={wl.suppressed ? null : mins(wl.median_s)} hint={wl.suppressed ? "Hidden: too few active learners to report" : undefined} />
          <StatTile label="Need attention" value={String(atRisk.length)} />
        </StatGrid>
        <Table
          caption="Students needing attention"
          showCaption
          columns={[
            { key: "n", header: "Student", cell: (l: BatchReport["learners"][number]) => nameOf(l.user_id) },
            { key: "w", header: "Weak topics", cell: (l) => l.weak_topics },
            { key: "t", header: "Learning this week", cell: (l) => mins(l.weekly_learning_s) },
          ]}
          rows={atRisk.length ? atRisk : weak.slice(0, 10)}
          rowKey={(l) => l.user_id}
          empty={{ title: "No students flagged", description: "Students with two or more weak required topics appear here." }}
        />
        <section aria-labelledby="trn-dist-h" className="space-y-2">
          <h3 id="trn-dist-h" className="text-sm font-semibold text-fg">
            Course progress distribution
          </h3>
          <ProgressDistributionView data={r.progress_distribution} />
        </section>
        <section aria-labelledby="trn-funnel-h" className="space-y-2">
          <h3 id="trn-funnel-h" className="text-sm font-semibold text-fg">
            Lesson funnel
          </h3>
          <LessonFunnelView data={r.lesson_funnel} />
        </section>
      </div>
    </Card>
  );
}

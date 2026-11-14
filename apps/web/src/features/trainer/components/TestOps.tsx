"use client";

import { useState } from "react";
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  Dialog,
  EmptyState,
  FormField,
  Input,
  Select,
  StatGrid,
  StatTile,
  Table,
  useToast,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import type { Body } from "@/lib/api-types";
import type { BatchMember } from "@/features/batches/lib/types";
import { useMemberNames, useTrainerBatches } from "../lib/batches";
import type {
  AttemptRow,
  ItemStat,
  Override,
  ReleaseResult,
  TestAssignment,
  TestReport,
} from "../lib/types";
import { useApi, seg } from "../shared/use-api";
import {
  BarList,
  Boundary,
  KFloorNotice,
  StatusBadge,
  fieldErrorsOf,
  formatDateTime,
  pct,
  useFailToast,
} from "../shared/ui";

/* ------------------------------------------------------------------ overrides */

/** TRN-007 overrides: ASM-14 list, ASM-13 grant (reason required, audited). */
export function TestOverrides({ testId }: { testId: string }) {
  const toast = useToast();
  const fail = useFailToast();
  const list = useApi<{ items: Override[] }>(`tests/${seg(testId)}/overrides`);
  const { batches } = useTrainerBatches();
  const [batchId, setBatchId] = useState("");
  const members = useApi<{ data: BatchMember[] }>(
    batchId ? `batches/${seg(batchId)}/members` : null,
  );
  // ASM-11: a per-student override is anchored to the test's assignment for the student's
  // batch, so batch-scoped trainers are authorised at batch scope (ADM-42).
  const assignments = useApi<{ items: TestAssignment[] }>(
    `tests/${seg(testId)}/assignments`,
  );
  const batchAssignment = assignments.data?.items.find(
    (a) => a.batch_id === batchId,
  );
  const [f, setF] = useState({
    user_id: "",
    extra_minutes: "0",
    extra_attempts: "0",
    extension_hours: "0",
    reason: "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) =>
    setF((x) => ({ ...x, [k]: e.target.value }));

  const submit = async () => {
    const errs: Record<string, string> = {};
    const mins = Number(f.extra_minutes);
    const att = Number(f.extra_attempts);
    const hrs = Number(f.extension_hours);
    if (!batchId) errs.batch = "Choose a batch.";
    else if (f.user_id && assignments.data && !batchAssignment)
      errs.user_id =
        "Assign this test to the batch before granting a student override.";
    if (![mins, att, hrs].every((n) => Number.isFinite(n) && n >= 0))
      errs.extra_time_seconds = "Use zero or positive numbers.";
    else if (mins === 0 && att === 0 && hrs === 0)
      errs.extra_time_seconds =
        "Give extra time, an extra attempt or a window extension.";
    if (f.reason.trim().length < 3)
      errs.reason = "A reason is required; it is recorded in the audit log.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    try {
      await api.post(`tests/${seg(testId)}/overrides`, {
        ...(f.user_id
          ? {
              user_id: f.user_id,
              ...(batchAssignment
                ? { test_assignment_id: batchAssignment.id }
                : {}),
            }
          : { batch_id: batchId }),
        extra_time_seconds: Math.round(mins * 60),
        extra_attempts: att,
        window_extension_seconds: Math.round(hrs * 3600),
        reason: f.reason.trim(),
      } satisfies Body<"tests/{test_id}/overrides", "post">);
      toast.show({ tone: "success", title: "Override granted" });
      setF({
        user_id: "",
        extra_minutes: "0",
        extra_attempts: "0",
        extension_hours: "0",
        reason: "",
      });
      await list.reload();
    } catch (err) {
      const fe = fieldErrorsOf(err);
      if (Object.keys(fe).length) setErrors(fe);
      else fail(err, "Couldn't grant the override");
    } finally {
      setBusy(false);
    }
  };

  const students = (members.data?.data ?? []).filter(
    (m) => m.member_role === "student",
  );
  const nameOf = useMemberNames((batches ?? []).map((b) => b.id));
  const batchLabel = (id: string) =>
    batches?.find((b) => b.id === id)?.name ?? "Batch";

  return (
    <div className="space-y-6">
      <Card title="Grant an override">
        <div className="grid gap-4 md:grid-cols-2">
          <FormField label="Batch" required error={errors.batch}>
            {(p) => (
              <Select
                {...p}
                value={batchId}
                onChange={(e) => {
                  setBatchId(e.target.value);
                  setF((x) => ({ ...x, user_id: "" }));
                }}
                placeholder="Choose a batch"
                options={(batches ?? []).map((b) => ({
                  value: b.id,
                  label: b.name,
                }))}
              />
            )}
          </FormField>
          <FormField
            label="Student"
            hint="Leave as 'Whole batch' to apply to everyone"
            error={errors.user_id ?? errors.test_assignment_id}
          >
            {(p) => (
              <Select
                {...p}
                value={f.user_id}
                onChange={set("user_id")}
                disabled={!batchId}
                options={[
                  { value: "", label: "Whole batch" },
                  ...students.map((m) => ({
                    value: m.user_id,
                    label: m.full_name ?? "Student",
                  })),
                ]}
              />
            )}
          </FormField>
          <FormField
            label="Extra time (minutes)"
            error={errors.extra_time_seconds}
          >
            {(p) => (
              <Input
                {...p}
                type="number"
                min={0}
                inputMode="numeric"
                value={f.extra_minutes}
                onChange={set("extra_minutes")}
              />
            )}
          </FormField>
          <FormField label="Extra attempts" error={errors.extra_attempts}>
            {(p) => (
              <Input
                {...p}
                type="number"
                min={0}
                max={5}
                inputMode="numeric"
                value={f.extra_attempts}
                onChange={set("extra_attempts")}
              />
            )}
          </FormField>
          <FormField
            label="Window extension (hours)"
            error={errors.window_extension_seconds}
          >
            {(p) => (
              <Input
                {...p}
                type="number"
                min={0}
                inputMode="decimal"
                value={f.extension_hours}
                onChange={set("extension_hours")}
              />
            )}
          </FormField>
          <FormField label="Reason" required error={errors.reason}>
            {(p) => (
              <Input
                {...p}
                value={f.reason}
                onChange={set("reason")}
                placeholder="Power cut during the test"
              />
            )}
          </FormField>
        </div>
        <Button className="mt-4" onClick={() => void submit()} loading={busy}>
          Grant override
        </Button>
      </Card>
      <Table
        caption="Overrides on this test"
        showCaption
        columns={[
          {
            key: "w",
            header: "For",
            cell: (o: Override) =>
              o.user_id
                ? nameOf(o.user_id)
                : o.batch_id
                  ? batchLabel(o.batch_id)
                  : "Test",
          },
          {
            key: "t",
            header: "Extra time",
            cell: (o) =>
              o.extra_time_seconds
                ? `${Math.round(o.extra_time_seconds / 60)} min`
                : "—",
          },
          {
            key: "a",
            header: "Extra attempts",
            cell: (o) => o.extra_attempts || "—",
          },
          {
            key: "x",
            header: "Extension",
            cell: (o) =>
              o.window_extension_seconds
                ? `${Math.round(o.window_extension_seconds / 3600)} h`
                : "—",
          },
          { key: "r", header: "Reason", cell: (o) => o.reason },
          {
            key: "c",
            header: "Granted",
            cell: (o) => formatDateTime(o.created_at),
          },
        ]}
        rows={list.data?.items}
        rowKey={(o) => o.id}
        loading={list.loading}
        error={list.error}
        onRetry={() => void list.reload()}
        empty={{ title: "No overrides yet" }}
      />
    </div>
  );
}

/* --------------------------------------------------------------- attempt log */

const SUBMIT_REASON: Record<string, string> = {
  manual: "Submitted",
  deadline: "Auto-submitted at deadline",
};

function pctOf(v: string | null): string {
  if (v === null) return "—";
  const n = Number(v);
  return Number.isFinite(n) ? `${Math.round(n)}%` : "—";
}

/** Attempt log for a test: ASM-15 (status, score, integrity, rebinds) + ASM-21 rebind override. */
export function AttemptLog({ testId }: { testId: string }) {
  const toast = useToast();
  const fail = useFailToast();
  // verified: app/modules/assessments/router.py asm_15_attempts → {items} (no pagination, no names/events)
  const attempts = useApi<{ items: AttemptRow[] }>(
    `tests/${seg(testId)}/attempts`,
  );
  const { batches } = useTrainerBatches();
  const nameOf = useMemberNames((batches ?? []).map((b) => b.id));
  const [override, setOverride] = useState<AttemptRow | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const grant = async () => {
    if (!override) return;
    setBusy(true);
    try {
      await api.post(`attempts/${seg(override.attempt_id)}/rebind-override`, {
        reason: reason.trim(),
      } satisfies Body<"attempts/{attempt_id}/rebind-override", "post">);
      toast.show({
        tone: "success",
        title: `${nameOf(override.user_id)} can now move the attempt to another device`,
      });
      setOverride(null);
      setReason("");
      await attempts.reload();
    } catch (err) {
      fail(err, "Couldn't allow the device change");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <p className="max-w-prose text-sm text-fg-muted">
        A rebind is when a student moves an in-progress attempt to another
        device (at most 2 per attempt; proctored drives need your approval).
        Same-device reconnects don&apos;t count.
      </p>
      <Table
        caption="Attempts"
        columns={[
          {
            key: "n",
            header: "Student",
            cell: (a: AttemptRow) =>
              `${nameOf(a.user_id)}${a.attempt_no > 1 ? ` (attempt ${a.attempt_no})` : ""}`,
          },
          {
            key: "s",
            header: "Status",
            cell: (a) => (
              <span className="flex flex-wrap items-center gap-2">
                <StatusBadge status={a.status} />
                {a.submit_reason && a.submit_reason !== "manual" ? (
                  <span className="text-xs text-fg-muted">
                    {SUBMIT_REASON[a.submit_reason] ??
                      a.submit_reason.replace(/_/g, " ")}
                  </span>
                ) : null}
              </span>
            ),
          },
          {
            key: "t",
            header: "Started",
            cell: (a) => formatDateTime(a.started_at),
          },
          { key: "sc", header: "Score", cell: (a) => pctOf(a.percentage) },
          {
            key: "i",
            header: "Integrity",
            cell: (a) =>
              a.integrity_status === "review_recommended" ? (
                <Badge tone="warning">Review recommended</Badge>
              ) : a.integrity_status === "decided" ? (
                <Badge>Reviewed</Badge>
              ) : (
                "—"
              ),
          },
          {
            key: "r",
            header: "Rebinds",
            align: "right",
            cell: (a) => a.rebind_count,
          },
          {
            key: "a",
            header: <span className="sr-only">Actions</span>,
            align: "right",
            cell: (a) =>
              a.status === "in_progress" ? (
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => setOverride(a)}
                >
                  Allow device change
                </Button>
              ) : null,
          },
        ]}
        rows={attempts.data?.items}
        rowKey={(a) => a.attempt_id}
        loading={attempts.loading}
        error={attempts.error}
        onRetry={() => void attempts.reload()}
        empty={{ title: "No attempts yet" }}
      />
      <Dialog
        open={override !== null}
        onClose={() => setOverride(null)}
        dismissible={!busy}
        title="Allow a device change?"
        description="The student can move this attempt to another device even on a proctored drive or beyond the rebind limit. This is recorded."
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => setOverride(null)}
              disabled={busy}
            >
              Cancel
            </Button>
            <Button
              onClick={() => void grant()}
              loading={busy}
              disabled={reason.trim().length < 3}
            >
              Allow
            </Button>
          </>
        }
      >
        <FormField label="Reason" required>
          {(p) => (
            <Input
              {...p}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Laptop battery died; continuing on lab PC"
            />
          )}
        </FormField>
      </Dialog>
    </div>
  );
}

/* --------------------------------------------------------------------- report */

function fmtSecs(v: number | null): string {
  if (v === null) return "—";
  const m = Math.floor(v / 60);
  const sec = Math.round(v % 60);
  return m ? `${m} min ${sec} s` : `${sec} s`;
}

const fmt2 = (v: number | null) => (v === null ? "—" : v.toFixed(2));

/** ASM-22 report body: distribution, submit vs auto-submit, section times, item analysis (k-floored). */
export function TestReportPanel({
  testId,
  batchId,
}: {
  testId: string;
  batchId?: string;
}) {
  const report = useApi<TestReport>(`tests/${seg(testId)}/report`, {
    batch_id: batchId || undefined,
  });
  return (
    <Boundary state={report} rows={4}>
      {(r) =>
        r.attempts_count === 0 ? (
          // One empty state instead of a histogram of zeros, zero tiles and empty tables.
          <EmptyState
            icon="chart"
            title="No graded attempts yet"
            description="Score distribution and item analysis appear here once students submit and their attempts are graded."
          />
        ) : (
        <div className="space-y-6">
          {r.scope === "item_stats_only" ? (
            <p className="text-sm text-fg-muted">
              You can see item statistics only; scores stay with the batch
              staff.
            </p>
          ) : null}
          {r.distribution ? (
            <Card title="Score distribution">
              <p className="mb-3 text-sm text-fg-secondary">
                {r.attempts_count} graded attempt
                {r.attempts_count === 1 ? "" : "s"} · mean{" "}
                {pct(r.distribution.mean)} · median {pct(r.distribution.median)}
              </p>
              <BarList
                label="Attempts per score band"
                items={r.distribution.buckets.map((b) => ({
                  label: `${b.label}%`,
                  value: b.count,
                }))}
              />
            </Card>
          ) : null}
          {r.submissions ? (
            <StatGrid columns={3}>
              <StatTile
                label="Submitted by student"
                value={r.submissions.submitted}
              />
              <StatTile
                label="Auto-submitted"
                value={r.submissions.auto_submitted}
                hint="At the deadline or section end"
              />
              <StatTile
                label="Force-submitted"
                value={r.submissions.admin_force}
              />
            </StatGrid>
          ) : null}
          {r.sections ? (
            <Table
              caption="Average time per section"
              showCaption
              columns={[
                {
                  key: "t",
                  header: "Section",
                  cell: (x: NonNullable<TestReport["sections"]>[number]) =>
                    x.title,
                },
                {
                  key: "a",
                  header: "Average time",
                  align: "right",
                  cell: (x) => fmtSecs(x.avg_time_seconds),
                },
                {
                  key: "n",
                  header: "Attempts",
                  align: "right",
                  cell: (x) => x.attempts,
                },
              ]}
              rows={r.sections}
              rowKey={(x) => x.section_id}
              empty={{ title: "No sections" }}
            />
          ) : null}
          <Card title="Item analysis">
            {r.items.suppressed ? (
              <KFloorNotice k={r.k_min} />
            ) : (
              <Table
                caption="Item analysis"
                columns={[
                  {
                    key: "q",
                    header: "Question",
                    cell: (x: ItemStat) =>
                      `${x.section_title ? `${x.section_title} · ` : ""}Q${x.position}`,
                  },
                  {
                    key: "n",
                    header: "Responses",
                    align: "right",
                    cell: (x) => x.n,
                  },
                  {
                    key: "p",
                    header: "Difficulty (p)",
                    align: "right",
                    cell: (x) =>
                      x.suppressed ? (
                        <KFloorNotice compact />
                      ) : (
                        fmt2(x.difficulty_p)
                      ),
                  },
                  {
                    key: "d",
                    header: "Discrimination",
                    align: "right",
                    cell: (x) =>
                      x.suppressed ? (
                        <KFloorNotice compact />
                      ) : (
                        fmt2(x.discrimination)
                      ),
                  },
                ]}
                rows={r.items.data}
                rowKey={(x) => x.question_version_id}
                empty={{ title: "No responses yet" }}
              />
            )}
            <p className="mt-2 text-xs text-fg-muted">
              Difficulty is the share of students who answered correctly.
              Discrimination (point-biserial) shows how well the item separates
              stronger and weaker scores. Items with fewer than {r.k_min}{" "}
              responses are hidden.
            </p>
          </Card>
        </div>
        )
      }
    </Boundary>
  );
}

/** Results are visible once the assignment's release time has passed (ASM-16 sets it to now). */
export function isReleased(
  a: Pick<TestAssignment, "results_release_at">,
  now: number = Date.now(),
): boolean {
  if (!a.results_release_at) return false;
  const at = Date.parse(a.results_release_at);
  return Number.isFinite(at) && at <= now;
}

/** TRN-011 test report: ASM-22 analytics + result release (ASM-16, per assignment). */
export function TestReportView({ testId }: { testId: string }) {
  const toast = useToast();
  const fail = useFailToast();
  const assignments = useApi<{ items: TestAssignment[] }>(
    `tests/${seg(testId)}/assignments`,
  );
  const { batches } = useTrainerBatches();
  const [busy, setBusy] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<TestAssignment | null>(null);
  // Batch staff without batch.read (evaluators) can't look batch names up: show "—", never a
  // made-up label or a false empty state.
  const batchName = (id: string | null) => (id ? batches?.find((b) => b.id === id)?.name : undefined);
  const batchLabel = (id: string | null) => (id ? (batchName(id) ?? "—") : "No batch (older assignment)");

  const release = async (a: TestAssignment) => {
    setBusy(a.id);
    try {
      const res = await api.post<ReleaseResult>(
        `tests/${seg(testId)}/results/release`,
        { test_assignment_id: a.id } satisfies Body<
          "tests/{test_id}/results/release",
          "post"
        >,
      );
      toast.show({
        tone: "success",
        title: "Results released to students",
        description:
          res.kind === "ok"
            ? `${res.data.results_released} result${res.data.results_released === 1 ? "" : "s"} released`
            : undefined,
      });
      await assignments.reload();
    } catch (err) {
      fail(err, "Couldn't release results");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-6">
      <TestReportPanel testId={testId} />
      <Table
        caption="Release results"
        showCaption
        columns={[
          {
            key: "b",
            header: "Assigned to",
            cell: (a: TestAssignment) => batchLabel(a.batch_id),
          },
          {
            key: "w",
            header: "Window",
            cell: (a) =>
              `${formatDateTime(a.available_from)} – ${formatDateTime(a.available_until)}`,
          },
          {
            key: "r",
            header: "Released",
            cell: (a) =>
              a.results_release_at ? formatDateTime(a.results_release_at) : "—",
          },
          {
            key: "a",
            header: <span className="sr-only">Actions</span>,
            align: "right",
            cell: (a) => (
              <Button
                size="sm"
                variant="secondary"
                onClick={() => setConfirming(a)}
                loading={busy === a.id}
                disabled={isReleased(a)}
                aria-label={
                  a.batch_id && !batchName(a.batch_id)
                    ? `Release results for the assignment ${formatDateTime(a.available_from)} – ${formatDateTime(a.available_until)}`
                    : `Release results for ${batchLabel(a.batch_id)}`
                }
              >
                {isReleased(a) ? "Released" : "Release results"}
              </Button>
            ),
          },
        ]}
        rows={assignments.data?.items}
        rowKey={(a) => a.id}
        loading={assignments.loading}
        error={assignments.error}
        onRetry={() => void assignments.reload()}
        empty={{
          title: "No assignments to release",
          description: "This test isn't assigned to a batch you manage yet.",
        }}
      />
      <ConfirmDialog
        open={confirming !== null}
        onClose={() => setConfirming(null)}
        title="Release results?"
        description={`Students${confirming?.batch_id && batchName(confirming.batch_id) ? ` in ${batchName(confirming.batch_id)}` : ""} will see their scores for this test.`}
        confirmLabel="Release results"
        onConfirm={async () => {
          if (confirming) await release(confirming);
        }}
      />
    </div>
  );
}

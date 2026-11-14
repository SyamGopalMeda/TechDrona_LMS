"use client";

import { useState } from "react";
import { Badge, Button, Card, Checkbox, Dialog, ErrorState, FormField, LinkButton, PageHeader, StatGrid, StatTile, StatusBadge, Table, useToast } from "@/components/ui";
import { formatDateTime } from "@/features/catalog/lib/format";
import { useApi } from "@/features/trainer/shared/use-api";
import { useGradingBase } from "@/features/trainer/shared/portal-base";
import { LoadingBlock, TextArea, useFailToast } from "@/features/trainer/shared/ui";
import { fmtMarks, staffApi } from "./api";
import { ReviewModal } from "./ReviewModal";
import { AiNotIntegratedNotice } from "@/features/studio/components/NotIntegrated";
import type { EvaluationOut, EvaluationRow, RegradeOut } from "./types";

/** Flag badges for one learner row (late, extension, regrade, AI help). */
export function rowFlags(r: EvaluationRow): string[] {
  const out: string[] = [];
  const flags = new Set(r.flags ?? []);
  if (r.late || flags.has("late")) out.push("Late");
  if (flags.has("extension") || flags.has("extended")) out.push("Extension");
  if (r.regrade_open || flags.has("regrade_requested") || flags.has("regrade_open")) out.push("Regrade requested");
  if (r.ai_help_used > 0) out.push(`AI help used ${r.ai_help_used}`);
  if (r.needs_review > 0) out.push(`${r.needs_review} to check`);
  return out;
}

function RegradePanel({ assignmentId, onChanged }: { assignmentId: string; onChanged: () => Promise<void> }) {
  const toast = useToast();
  const fail = useFailToast();
  const list = useApi<{ data: RegradeOut[] }>(`assignments/${encodeURIComponent(assignmentId)}/regrade-requests`, { status: "open" });
  const [active, setActive] = useState<{ r: RegradeOut; action: "resolve" | "reject" } | null>(null);
  const [note, setNote] = useState("");
  const [reopen, setReopen] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!active) return;
    if (note.trim().length < 3) return setErr("Add a note for the learner.");
    setBusy(true);
    try {
      await staffApi.resolveRegrade(active.r.id, { action: active.action, note: note.trim(), ...(active.action === "resolve" ? { reopen } : {}) });
      toast.show({ tone: "success", title: active.action === "resolve" ? "Request resolved" : "Request rejected" });
      setActive(null);
      await Promise.all([list.reload(), onChanged()]);
    } catch (e) {
      fail(e, "Couldn't update the request");
    } finally {
      setBusy(false);
    }
  };

  const rows = list.data?.data ?? [];
  return (
    <Card title="Modification requests">
      {list.error ? (
        <ErrorState error={list.error} onRetry={() => void list.reload()} />
      ) : list.loading && !list.data ? (
        <LoadingBlock rows={1} />
      ) : rows.length === 0 ? (
        <p className="text-sm text-fg-muted">No open requests.</p>
      ) : (
        <ul className="space-y-3" aria-label="Open modification requests">
          {rows.map((r) => (
            <li key={r.id} className="rounded-lg border border-line p-3">
              <p className="text-sm font-medium text-fg">
                {r.learner_name ?? "Learner"} <span className="font-normal text-fg-muted">· {formatDateTime(r.created_at)}</span>
              </p>
              <p className="mt-1 whitespace-pre-wrap text-sm text-fg-secondary">{r.reason}</p>
              <div className="mt-2 flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => {
                    setActive({ r, action: "resolve" });
                    setNote("");
                    setReopen(false);
                    setErr(null);
                  }}
                >
                  Resolve
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => {
                    setActive({ r, action: "reject" });
                    setNote("");
                    setErr(null);
                  }}
                >
                  Reject
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <Dialog
        open={active !== null}
        onClose={() => setActive(null)}
        dismissible={!busy}
        title={active?.action === "reject" ? "Reject request" : "Resolve request"}
        description="The learner sees your note."
        footer={
          <>
            <Button variant="secondary" onClick={() => setActive(null)} disabled={busy}>
              Cancel
            </Button>
            <Button variant={active?.action === "reject" ? "danger" : "primary"} onClick={() => void submit()} loading={busy}>
              {active?.action === "reject" ? "Reject" : "Resolve"}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <FormField label="Note" required error={err ?? undefined}>
            {(p) => <TextArea {...p} rows={3} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} />}
          </FormField>
          {active?.action === "resolve" ? (
            <Checkbox
              label="Reopen the submission"
              description="Lets the learner change their answers and submit again."
              checked={reopen}
              onChange={(e) => setReopen(e.target.checked)}
            />
          ) : null}
        </div>
      </Dialog>
    </Card>
  );
}

/** Evaluation of one structured assignment: AI grading, review, publish, regrade requests. */
export function EvaluationView({ assignmentId }: { assignmentId: string }) {
  const { isEvaluator, gradingHome } = useGradingBase();
  const toast = useToast();
  const fail = useFailToast();
  const ev = useApi<EvaluationOut>(`assignments/${encodeURIComponent(assignmentId)}/evaluation`);
  const [busy, setBusy] = useState<"ai" | "publish" | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [review, setReview] = useState<string | null>(null);

  const crumbs = [{ label: "Grading", href: gradingHome }];
  if (ev.error)
    return (
      <>
        <PageHeader title="Evaluate assignment" breadcrumbs={[...crumbs, { label: "Evaluate assignment" }]} />
        <ErrorState error={ev.error} onRetry={() => void ev.reload()} />
      </>
    );
  if (!ev.data)
    return (
      <>
        <PageHeader title="Evaluate assignment" breadcrumbs={[...crumbs, { label: "Evaluate assignment" }]} />
        <LoadingBlock rows={4} />
      </>
    );
  const d = ev.data;
  const unfinalized = d.rows.filter((r) => !r.finalized).length;

  const runAI = async () => {
    setBusy("ai");
    try {
      const r = await staffApi.runAIGrading(assignmentId);
      toast.show({ tone: "info", title: "AI grading started", description: `${r.queued_items} answer(s) queued across ${r.submissions} submission(s); ${r.auto_scored_items} scored by rules.` });
      await ev.reload();
    } catch (err) {
      fail(err, "Couldn't start AI grading");
    } finally {
      setBusy(null);
    }
  };

  const publish = async () => {
    setBusy("publish");
    try {
      const r = await staffApi.releaseGrades(assignmentId);
      setConfirm(false);
      toast.show({
        tone: r.unfinalized_count ? "warning" : "success",
        title: "Results published",
        description: r.unfinalized_count ? `${r.unfinalized_count} submission(s) are not finalized yet; learners see them once you finalize.` : undefined,
      });
      await ev.reload();
    } catch (err) {
      fail(err, "Couldn't publish results");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title={d.assignment.title}
        breadcrumbs={[...crumbs, { label: d.assignment.title }]}
        meta={d.published ? <StatusBadge status="published" label="Results published" /> : null}
        description={`${d.submission_count} submission${d.submission_count === 1 ? "" : "s"} · ${fmtMarks(d.max_score)} marks`}
        actions={
          <>
            {isEvaluator ? null : (
              <LinkButton variant="secondary" href={`/trainer/assignments/${encodeURIComponent(assignmentId)}`}>
                Edit assignment
              </LinkButton>
            )}
            <Button variant="secondary" onClick={() => void runAI()} loading={busy === "ai"} disabled={busy !== null || d.submission_count === 0}>
              Run AI grading
            </Button>
            {/* Primary only once every submission is finalized; publishing earlier is allowed
                (unfinalized marks stay hidden) but is not the suggested next step. */}
            <Button
              variant={unfinalized > 0 ? "secondary" : "primary"}
              onClick={() => setConfirm(true)}
              disabled={busy !== null || d.submission_count === 0}
              aria-describedby={unfinalized > 0 ? "publish-hint" : undefined}
            >
              Publish results
            </Button>
          </>
        }
      />
      <AiNotIntegratedNotice className="-mt-3 mb-4" />
      {unfinalized > 0 ? (
        <p id="publish-hint" className="-mt-3 text-sm text-fg-muted">
          {d.rows.length - unfinalized} of {d.rows.length} submission{d.rows.length === 1 ? "" : "s"} finalized. Review and finalize the rest before
          publishing; learners don&apos;t see unfinalized marks.
        </p>
      ) : null}

      {d.sections.length ? (
        <section aria-label="Section averages">
          <StatGrid>
            {d.sections.map((s) => (
              <StatTile key={s.id} size="compact" label={s.title} value={s.avg_marks === null ? null : `${fmtMarks(s.avg_marks)} / ${fmtMarks(s.max_marks)}`} hint="Average" />
            ))}
          </StatGrid>
        </section>
      ) : null}

      <Table<EvaluationRow>
        caption="Learner submissions"
        rows={d.rows}
        rowKey={(r) => r.submission_id}
        empty={{ title: "No submissions yet", description: "Submissions appear here once learners hand in." }}
        columns={[
          {
            key: "l",
            header: "Learner",
            cell: (r) => (
              <div>
                <p className="font-medium text-fg">{r.learner_name ?? "Learner"}</p>
                {r.learner_email ? <p className="text-xs text-fg-muted">{r.learner_email}</p> : null}
              </div>
            ),
          },
          {
            key: "s",
            header: "Progress",
            cell: (r) => (
              <div>
                <p className="tabular-nums text-sm text-fg">
                  {fmtMarks(r.finalized_marks)} / {fmtMarks(r.max_score)} finalized
                  {r.ai_pending + r.ai_queued > 0 ? ` · ${r.ai_pending + r.ai_queued} AI pending` : ""}
                </p>
                <p className="text-xs text-fg-muted">
                  {r.finalized ? "Finalized" : "Not finalized"}
                  {r.submitted_at ? ` · ${formatDateTime(r.submitted_at)}` : ""}
                </p>
              </div>
            ),
          },
          {
            key: "f",
            header: "Flags",
            // No flags → "—", which the stacked phone card drops instead of showing an empty row.
            cell: (r) =>
              rowFlags(r).length === 0 ? (
                "—"
              ) : (
              <div className="flex flex-wrap gap-1">
                {rowFlags(r).map((f) => (
                  <Badge key={f} tone={f === "Late" || f === "Regrade requested" ? "warning" : "neutral"}>
                    {f}
                  </Badge>
                ))}
              </div>
              ),
          },
          {
            key: "a",
            header: <span className="sr-only">Actions</span>,
            align: "right",
            cell: (r) => (
              <Button size="sm" variant={r.finalized ? "ghost" : "secondary"} onClick={() => setReview(r.submission_id)} aria-label={`Review ${r.learner_name ?? "learner"}`}>
                Review
              </Button>
            ),
          },
        ]}
      />

      <RegradePanel assignmentId={assignmentId} onChanged={ev.reload} />

      <ReviewModal submissionId={review} onClose={() => setReview(null)} onFinalized={ev.reload} />

      <Dialog
        open={confirm}
        onClose={() => setConfirm(false)}
        dismissible={busy === null}
        title="Publish results?"
        description="Learners will see their marks and feedback."
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirm(false)} disabled={busy !== null}>
              Cancel
            </Button>
            <Button onClick={() => void publish()} loading={busy === "publish"}>
              Publish
            </Button>
          </>
        }
      >
        {unfinalized ? (
          <p role="alert" className="rounded-md border border-warning-border bg-warning-subtle p-3 text-sm text-warning-fg">
            {unfinalized} submission{unfinalized === 1 ? " is" : "s are"} not finalized yet. Unfinalized marks stay hidden until you finalize them.
          </p>
        ) : (
          <p className="text-sm text-fg-secondary">All submissions are finalized.</p>
        )}
      </Dialog>
    </div>
  );
}


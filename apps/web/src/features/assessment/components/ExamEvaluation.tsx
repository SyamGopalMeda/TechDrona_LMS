"use client";

import { useState } from "react";
import { Badge, Button, Card, Dialog, ErrorState, FormField, Input, useToast } from "@/components/ui";
import { AIErrorState, aiProblemCode, useEnabledApps } from "@/features/ai";
import { Boundary, useFailToast } from "@/features/trainer/shared/ui";
import { seg, useApi } from "@/features/trainer/shared/use-api";
import { api, type ApiResult } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { uuid7 } from "@/lib/ids/uuid7";
import type { ExamProtocol, IntegritySummary } from "../lib/types";
import { RichHtml } from "./RichHtml";

/* ------------------------------------------------------------------ types (evaluation.py) */

export interface EvaluationRow {
  attempt_id: string;
  user_id: string;
  learner_name: string | null;
  attempt_no: number;
  test_assignment_id: string | null;
  status: string;
  submit_reason: string | null;
  submitted_at: string | null;
  score: string | null;
  max_score: string | null;
  released: boolean;
  grading: { items: number; finalized: number; ai_pending: number; manual_pending: number; manual_items: number };
  integrity: IntegritySummary;
}

export interface EvaluationList {
  test: { id: string; title: string; status: string };
  protocol: ExamProtocol;
  assignments: { id: string; batch_id: string | null; release_mode: string; results_release_at: string | null }[];
  totals: { attempts: number; finalized: number; ai_pending: number; manual_pending: number; flagged: number };
  items: EvaluationRow[];
}

interface GradeInfo {
  ai_status: "none" | "pending" | "failed";
  ai_marks: string | null;
  ai_feedback: string | null;
  ai_confidence: number | null;
  ai_error: string | null;
  final_marks: string | null;
  final_feedback: string | null;
  finalized_at: string | null;
}

interface ReviewItem {
  question_version_id: string;
  type: string;
  stem_html: string;
  marks: string;
  response: Record<string, unknown> | null;
  is_correct: boolean | null;
  marks_awarded: string | null;
  needs_human: boolean;
  grade: GradeInfo | null;
}

interface AttemptReview {
  attempt_id: string;
  learner_name: string | null;
  status: string;
  score: string | null;
  max_score: string | null;
  integrity: IntegritySummary;
  sections: { section_id: string; title: string; items: ReviewItem[] }[];
}

function ok<T>(r: ApiResult<T>): T {
  if (r.kind !== "ok") throw new Error("Unexpected approval_pending response");
  return r.data;
}

/* ------------------------------------------------------------------ badges */

/** "Tab switches: 2", "Window inactive: 3 (≥3)" — over-threshold types in red. */
export function IntegrityBadges({ integrity }: { integrity: IntegritySummary }) {
  const over = new Map(integrity.over_threshold.map((o) => [o.type, o]));
  const shown = Object.entries(integrity.counts).filter(([, n]) => (n ?? 0) > 0);
  if (!shown.length && !integrity.flagged) return <span className="text-xs text-fg-muted">No integrity events</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {integrity.flagged ? <Badge tone="danger">Flagged for review</Badge> : null}
      {shown.map(([type, n]) => {
        const o = over.get(type as never);
        return (
          <Badge key={type} tone={o ? "danger" : "warning"}>
            {(o?.label ?? LABELS[type] ?? type) + `: ${n}`}
            {o ? ` (≥${o.threshold})` : ""}
          </Badge>
        );
      })}
    </span>
  );
}

const LABELS: Record<string, string> = {
  focus_lost: "Tab switches",
  window_blur: "Window inactive",
  copy: "Copy",
  cut: "Cut",
  paste: "Paste",
  resize: "Window resized",
  fullscreen_exit: "Left full screen",
  right_click: "Right click",
};

export function gradingLine(g: EvaluationRow["grading"]): string {
  const parts = [`${g.finalized} / ${g.items} finalized`];
  if (g.ai_pending) parts.push(`${g.ai_pending} AI pending`);
  if (g.manual_pending) parts.push(`${g.manual_pending} to grade`);
  return parts.join(" · ");
}

/* ------------------------------------------------------------------ list */

/** Trainer evaluation of one test: integrity badges, grading progress, AI grading, publish. */
export function ExamEvaluation({ testId }: { testId: string }) {
  const toast = useToast();
  const fail = useFailToast();
  const list = useApi<EvaluationList>(`tests/${seg(testId)}/evaluation`);
  const apps = useEnabledApps();
  // Known-off only (a failed lookup doesn't hide the button; the api authorises every call).
  const aiOff = !apps.loading && !apps.error && !apps.isEnabled("ai_grading");
  const [busy, setBusy] = useState<string | null>(null);
  const [aiError, setAiError] = useState<unknown>(null);
  const [reviewing, setReviewing] = useState<EvaluationRow | null>(null);
  const [confirmPublish, setConfirmPublish] = useState(false);

  const runAi = async (attemptId?: string) => {
    setBusy("ai");
    setAiError(null);
    try {
      const r = ok(
        await api.post<{ graded: number; failed: number; skipped: number; stopped_reason: string | null }>(
          `tests/${seg(testId)}/evaluation/ai-grade`,
          attemptId ? { attempt_id: attemptId } : {},
          { idempotencyKey: uuid7() },
        ),
      );
      toast.show({
        tone: r.failed || r.stopped_reason ? "warning" : "success",
        title: `AI suggested marks for ${r.graded} answer${r.graded === 1 ? "" : "s"}`,
        description: `Review and finalize each suggestion.${r.failed ? ` ${r.failed} failed.` : ""}${r.stopped_reason ? " Stopped early: AI limit or outage." : ""}`,
      });
      await list.reload();
    } catch (e) {
      if (aiProblemCode(e)) setAiError(e);
      else fail(e);
    } finally {
      setBusy(null);
    }
  };

  const publish = async (data: EvaluationList) => {
    setBusy("publish");
    try {
      let n = 0;
      for (const a of data.assignments) {
        const r = ok(await api.post<{ results_released: number }>(`tests/${seg(testId)}/results/release`, { test_assignment_id: a.id }, { idempotencyKey: uuid7() }));
        n += r.results_released;
      }
      toast.show({ tone: "success", title: `Results published (${n})` });
      setConfirmPublish(false);
      await list.reload();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  };

  return (
    <Boundary state={list}>
      {(data) => (
        <div className="space-y-4">
          <Card
            title={data.test.title}
            actions={
              <div className="flex flex-wrap gap-2">
                <Button variant="secondary" onClick={() => void runAi()} loading={busy === "ai"} disabled={aiOff} title={aiOff ? "AI grading is turned off" : undefined}>
                  Run AI grading
                </Button>
                <Button onClick={() => setConfirmPublish(true)} disabled={!data.assignments.length}>
                  Publish results
                </Button>
              </div>
            }
          >
            <p className="text-sm text-fg-secondary">
              {data.totals.attempts} attempt{data.totals.attempts === 1 ? "" : "s"} · {data.totals.finalized} fully graded · {data.totals.ai_pending} AI pending ·{" "}
              {data.totals.manual_pending} to grade · {data.totals.flagged} flagged
            </p>
            <p className="mt-1 text-xs text-fg-muted">AI marks are suggestions until you finalize them. Integrity events are evidence; decisions are made in integrity review.</p>
            {aiError ? (
              <div className="mt-3">
                <AIErrorState code={aiProblemCode(aiError) ?? "ai_unavailable"} detail={aiError instanceof ApiError ? aiError.detail : null} onRetry={() => void runAi()} />
              </div>
            ) : null}
          </Card>
          {data.items.length === 0 ? (
            <Card>
              <p className="text-sm text-fg-secondary">No attempts yet.</p>
            </Card>
          ) : (
            <ul className="space-y-2" aria-label="Attempts">
              {data.items.map((row) => (
                <li key={row.attempt_id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-surface p-3">
                  <div className="min-w-0 space-y-1">
                    <p className="font-medium text-fg">
                      {row.learner_name ?? "Learner"} <span className="text-xs text-fg-muted">· attempt {row.attempt_no}</span>
                    </p>
                    <p className="text-xs text-fg-secondary">
                      {gradingLine(row.grading)}
                      {row.score !== null ? ` · ${row.score} / ${row.max_score}` : ""}
                      {row.released ? " · published" : ""}
                      {row.status === "in_progress" ? " · in progress" : ""}
                    </p>
                    <IntegrityBadges integrity={row.integrity} />
                  </div>
                  <Button size="sm" variant="secondary" onClick={() => setReviewing(row)} disabled={row.status === "in_progress"}>
                    Review
                  </Button>
                </li>
              ))}
            </ul>
          )}
          {reviewing ? (
            <ReviewDialog
              row={reviewing}
              onClose={() => {
                setReviewing(null);
                void list.reload();
              }}
              onRunAi={() => void runAi(reviewing.attempt_id)}
              aiBusy={busy === "ai"}
            />
          ) : null}
          <Dialog
            open={confirmPublish}
            onClose={() => setConfirmPublish(false)}
            title="Publish results?"
            description="Learners in the assigned batches will see their results."
            footer={
              <>
                <Button variant="secondary" onClick={() => setConfirmPublish(false)}>
                  Cancel
                </Button>
                <Button onClick={() => void publish(data)} loading={busy === "publish"}>
                  Publish
                </Button>
              </>
            }
          >
            {data.totals.ai_pending + data.totals.manual_pending > 0 ? (
              <p role="alert" className="text-sm text-warning-fg">
                {data.totals.ai_pending + data.totals.manual_pending} answer(s) are not finalized yet. Their marks count as 0 until you finalize them.
              </p>
            ) : (
              <p className="text-sm text-fg-secondary">All submitted answers are finalized.</p>
            )}
          </Dialog>
        </div>
      )}
    </Boundary>
  );
}

/* ------------------------------------------------------------------ review modal */

function ReviewDialog({ row, onClose, onRunAi, aiBusy }: { row: EvaluationRow; onClose: () => void; onRunAi: () => void; aiBusy: boolean }) {
  const review = useApi<AttemptReview>(`attempts/${seg(row.attempt_id)}/evaluation`);
  return (
    <Dialog
      open
      onClose={onClose}
      title={`Review — ${row.learner_name ?? "Learner"}`}
      className="max-w-3xl"
      footer={
        <>
          <Button
            variant="secondary"
            onClick={() => {
              onRunAi();
              setTimeout(() => void review.reload(), 1500);
            }}
            loading={aiBusy}
          >
            Run AI grading
          </Button>
          <Button onClick={onClose}>Close</Button>
        </>
      }
    >
      <Boundary state={review}>
        {(r) => (
          <div className="space-y-4">
            <IntegrityBadges integrity={r.integrity} />
            <p className="text-sm text-fg-secondary">
              Score {r.score ?? "—"} / {r.max_score ?? "—"} · {r.status.replace("_", " ")}
            </p>
            {r.sections.map((s) => (
              <section key={s.section_id} aria-label={s.title} className="space-y-3">
                <h3 className="text-sm font-semibold text-fg">{s.title}</h3>
                {s.items.map((it, i) => (
                  <ItemReview key={it.question_version_id} n={i + 1} attemptId={r.attempt_id} item={it} onSaved={() => void review.reload()} />
                ))}
              </section>
            ))}
          </div>
        )}
      </Boundary>
    </Dialog>
  );
}

function responseText(r: Record<string, unknown> | null): string {
  if (!r) return "(no answer)";
  if (typeof r.text === "string") return r.text;
  if (typeof r.value === "string") return r.value;
  return JSON.stringify(r);
}

function ItemReview({ n, attemptId, item, onSaved }: { n: number; attemptId: string; item: ReviewItem; onSaved: () => void }) {
  const toast = useToast();
  const g = item.grade;
  const [marks, setMarks] = useState(g?.final_marks ?? g?.ai_marks ?? "");
  const [feedback, setFeedback] = useState(g?.final_feedback ?? g?.ai_feedback ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      ok(
        await api.post(
          `attempts/${seg(attemptId)}/items/${seg(item.question_version_id)}/grade`,
          { marks, feedback: feedback || null },
          { idempotencyKey: uuid7() },
        ),
      );
      toast.show({ tone: "success", title: `Question ${n} finalized` });
      onSaved();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <article className="rounded-md border border-line p-3 text-sm">
      <header className="flex items-center justify-between gap-2">
        <span className="font-medium text-fg">Question {n}</span>
        <span className="text-xs text-fg-muted">
          {item.needs_human ? `${item.marks} marks` : `${item.marks_awarded ?? "0"} / ${item.marks}`}
          {!item.needs_human && item.is_correct !== null ? (item.is_correct ? " · correct" : " · incorrect") : ""}
        </span>
      </header>
      <RichHtml html={item.stem_html} className="mt-1 text-fg-secondary" />
      <pre className="mt-2 whitespace-pre-wrap rounded bg-surface-sunken p-2 text-xs text-fg">{responseText(item.response)}</pre>
      {item.needs_human && item.response ? (
        <div className="mt-3 space-y-2">
          {g?.ai_status === "pending" ? (
            <p className="text-xs text-info-fg">
              AI suggestion: {g.ai_marks} / {item.marks}
              {g.ai_confidence !== null ? ` (confidence ${Math.round(g.ai_confidence * 100)}%)` : ""} — pending your review.
            </p>
          ) : g?.ai_status === "failed" ? (
            <p className="text-xs text-danger-fg">{g.ai_error ?? "AI grading failed for this answer."}</p>
          ) : null}
          {g?.finalized_at ? <Badge tone="success">Finalized: {g.final_marks}</Badge> : null}
          <div className="grid gap-2 md:grid-cols-[8rem_1fr]">
            <FormField label="Marks">{(p) => <Input {...p} type="number" min={0} max={Number(item.marks)} step="0.25" value={marks} onChange={(e) => setMarks(e.target.value)} />}</FormField>
            <FormField label="Feedback">
              {(p) => (
                <textarea
                  {...p}
                  rows={2}
                  maxLength={10000}
                  className="w-full rounded-md border border-line-control bg-surface px-3 py-2 text-sm text-fg"
                  value={feedback}
                  onChange={(e) => setFeedback(e.target.value)}
                />
              )}
            </FormField>
          </div>
          {error ? <ErrorState error={error} /> : null}
          <Button size="sm" onClick={() => void save()} loading={busy} disabled={marks === ""}>
            {g?.finalized_at ? "Update marks" : "Finalize & save"}
          </Button>
        </div>
      ) : null}
    </article>
  );
}

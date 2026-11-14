"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge, Button, Card, Dialog, ErrorState, LoadingBlock, PageHeader, useToast } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import { AITutorPanel } from "@/features/ai/components/AITutorPanel";
import type { AITutorMode } from "@/features/ai/types";
import { fmtMarks, itemTypeLabel, learnerApi } from "../assignment-manager/api";
import { QuestionText } from "../assignment-manager/AnswerView";
import type { ItemResponse, WorkspaceItem, WorkspaceOut } from "../assignment-manager/types";
import { ContentErrorState } from "../components/States";
import { ItemEditor } from "./ItemEditors";
import { ResultsView } from "./ResultsView";
import { useAutosave, type SaveState } from "./use-autosave";
import { formatCountdown, formatDateTime } from "@/lib/format";

const DONE = new Set(["submitted", "late", "graded", "returned", "released"]);

export function hasAnswer(r: ItemResponse | null | undefined): boolean {
  if (!r) return false;
  return Object.values(r as Record<string, unknown>).some((v) => (Array.isArray(v) ? v.length > 0 : typeof v === "string" ? v.trim() !== "" : v !== null && v !== undefined));
}

/** Seconds left, ticking down locally from the server's `seconds_left` (or due_at). */
function useCountdown(seconds: number | null, dueAt: string | null): number | null {
  const [base] = useState(() => ({ at: Date.now(), seconds, dueAt }));
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  if (base.seconds !== null && base.seconds !== undefined) return Math.max(0, Math.round(base.seconds - (now - base.at) / 1000));
  if (base.dueAt) return Math.max(0, Math.round((Date.parse(base.dueAt) - now) / 1000));
  return null;
}

function SaveIndicator({ state, onRetry }: { state: SaveState; onRetry: () => void }) {
  if (state === "error")
    return (
      <span role="alert" className="text-xs text-danger-fg">
        Couldn&apos;t save your answer.{" "}
        <button type="button" className="font-medium underline" onClick={onRetry}>
          Retry
        </button>
      </span>
    );
  const label = state === "saving" ? "Saving…" : state === "saved" ? "All changes saved" : "";
  return (
    <span role="status" aria-live="polite" className="text-xs text-fg-muted" data-testid="save-state">
      {label}
    </span>
  );
}

/** Tutor column with the per-assignment allowance; reuses the shared AI tutor panel. */
function TutorColumn({ assignmentId, item, ai }: { assignmentId: string; item: WorkspaceItem; ai: WorkspaceOut["ai_help"] }) {
  const [counter, setCounter] = useState({ used: ai.used, limit: ai.limit });
  const remaining = counter.limit === null ? null : Math.max(0, counter.limit - counter.used);
  return (
    <div className="space-y-2">
      <p className="text-sm text-fg-secondary" data-testid="tutor-left">
        {remaining === null ? "Unlimited tutor interactions" : `${remaining} of ${counter.limit} interactions left`}
      </p>
      <AITutorPanel
        title="AI tutor"
        used={counter.used}
        limit={counter.limit}
        historyKey={`${assignmentId}:${item.id}`}
        loadHistory={() => learnerApi.tutorHistory(assignmentId, item.id)}
        onAsk={async (mode: AITutorMode, input: string) => {
          const r = await learnerApi.tutor(assignmentId, { item_id: item.id, mode, learner_input: input });
          setCounter({ used: r.used, limit: r.limit });
          return { reply_md: r.reply_md, used: r.used, limit: r.limit };
        }}
      />
    </div>
  );
}

function BeforeStart({ ws, onStarted }: { ws: WorkspaceOut; onStarted: (w: WorkspaceOut) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const s = ws.schedule;
  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      onStarted(await learnerApi.start(ws.assignment.id));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card title="Before you start">
      <dl className="grid gap-2 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-fg-muted">You can start</dt>
          <dd className="font-medium text-fg">{s.start_at ? formatDateTime(s.start_at, { year: true }) : "Now"}</dd>
        </div>
        <div>
          <dt className="text-fg-muted">Submit by</dt>
          <dd className="font-medium text-fg">{formatDateTime(s.due_at, { year: true })}</dd>
        </div>
      </dl>
      {ws.assignment.instructions_md ? <p className="mt-4 whitespace-pre-line text-sm text-fg-secondary">{ws.assignment.instructions_md}</p> : null}
      {!s.can_start ? (
        <p className="mt-4 text-sm text-fg-muted" role="status">
          {s.start_at ? `Starting opens at ${formatDateTime(s.start_at, { year: true })}.` : "This assignment can't be started right now."}
        </p>
      ) : null}
      {error ? (
        <div className="mt-4">
          {error instanceof ApiError && error.code === "invalid_state_transition" ? <ErrorState title="Not open right now" detail={error.detail} /> : <ErrorState error={error} />}
        </div>
      ) : null}
      <Button className="mt-4" onClick={() => void start()} loading={busy} disabled={!s.can_start}>
        Start
      </Button>
    </Card>
  );
}

export function Workspace({ ws, onSubmitted }: { ws: WorkspaceOut; onSubmitted: () => Promise<void> }) {
  const toast = useToast();
  const assignmentId = ws.assignment.id;
  const flat = useMemo(() => ws.sections.flatMap((s) => s.items), [ws.sections]);
  const [idx, setIdx] = useState(0);
  const [responses, setResponses] = useState<Record<string, ItemResponse | null>>(() => Object.fromEntries(flat.map((i) => [i.id, i.response])));
  const [confirm, setConfirm] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<unknown>(null);
  const save = useCallback((itemId: string, r: ItemResponse) => learnerApi.saveItem(assignmentId, itemId, r), [assignmentId]);
  const autosave = useAutosave(save);
  const left = useCountdown(ws.schedule.seconds_left, ws.schedule.due_at);
  const item = flat[idx];

  const go = (n: number) => {
    void autosave.flush();
    setIdx(Math.max(0, Math.min(flat.length - 1, n)));
  };

  const submit = async () => {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const ok = await autosave.flush();
      if (!ok) throw new Error("Some answers could not be saved. Check your connection and try again.");
      await learnerApi.submit(assignmentId);
      toast.show({ tone: "success", title: "Assignment submitted" });
      setConfirm(false);
      await onSubmitted();
    } catch (err) {
      setSubmitError(err);
    } finally {
      setSubmitting(false);
    }
  };

  if (!item)
    return (
      <Card>
        <p className="text-sm text-fg-muted">This assignment has no questions yet.</p>
      </Card>
    );
  const unanswered = flat.filter((i) => !hasAnswer(responses[i.id])).length;
  const showTutor = ws.ai_help.enabled;

  return (
    <div className={`grid gap-4 ${showTutor ? "lg:grid-cols-[16rem_minmax(0,1fr)_20rem]" : "lg:grid-cols-[16rem_minmax(0,1fr)]"}`}>
      <aside className="space-y-4" aria-label="Questions">
        <div>
          <h1 className="font-display text-lg font-semibold text-fg">{ws.assignment.title}</h1>
          {left !== null ? (
            <p
              className={`mt-1 inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium tabular-nums ${left < 900 ? "border-warning-border bg-warning-subtle text-warning-fg" : "border-line text-fg-secondary"}`}
            >
              <span aria-hidden="true">⏱</span>
              <span>
                <span className="sr-only">Time left: </span>
                {formatCountdown(left, "compact")}
              </span>
            </p>
          ) : null}
        </div>
        {ws.sections.map((s) => (
          <nav key={s.id} aria-label={s.title}>
            <p className="text-xs font-semibold uppercase tracking-wide text-fg-muted">{s.title}</p>
            <ol className="mt-2 flex flex-wrap gap-2">
              {s.items.map((i) => {
                const n = flat.findIndex((x) => x.id === i.id);
                const answered = hasAnswer(responses[i.id]);
                const current = n === idx;
                return (
                  <li key={i.id}>
                    <button
                      type="button"
                      onClick={() => go(n)}
                      aria-current={current ? "step" : undefined}
                      aria-label={`Question ${n + 1}${answered ? ", answered" : ""}`}
                      className={`h-9 w-9 rounded-full border text-sm font-medium tabular-nums focus-visible:shadow-focus focus-visible:outline-none ${
                        current ? "border-transparent bg-brand text-brand-on" : answered ? "border-success-border bg-success-subtle text-success-fg" : "border-line bg-surface text-fg"
                      }`}
                    >
                      {n + 1}
                    </button>
                  </li>
                );
              })}
            </ol>
          </nav>
        ))}
        <div className="rounded-lg border border-line p-3">
          <p className="text-sm font-semibold text-fg">
            Question {idx + 1} <span className="font-normal text-fg-muted">· {fmtMarks(item.marks)} marks</span>
          </p>
          <QuestionText prompt_md={item.prompt_md} stem_html={item.stem_html} className="mt-2" />
        </div>
        <Button className="w-full" onClick={() => setConfirm(true)} disabled={!ws.schedule.can_submit}>
          Submit assignment
        </Button>
      </aside>

      <section className="min-w-0 space-y-4" aria-label={`Answer for question ${idx + 1}`}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Badge>{itemTypeLabel(item.item_type)}</Badge>
          <SaveIndicator state={autosave.state} onRetry={() => void autosave.flush()} />
        </div>
        <ItemEditor
          key={item.id}
          item={item}
          response={responses[item.id] ?? null}
          onChange={(r, opts) => {
            setResponses((x) => ({ ...x, [item.id]: r }));
            autosave.queue(item.id, r);
            if (opts?.immediate) void autosave.flush();
          }}
        />
        <div className="flex justify-between gap-2 border-t border-line pt-3">
          <Button variant="secondary" onClick={() => go(idx - 1)} disabled={idx === 0}>
            ‹ Previous
          </Button>
          <Button variant="secondary" onClick={() => go(idx + 1)} disabled={idx === flat.length - 1}>
            Next ›
          </Button>
        </div>
      </section>

      {showTutor ? (
        <aside aria-label="AI tutor">
          <TutorColumn assignmentId={assignmentId} item={item} ai={ws.ai_help} />
        </aside>
      ) : null}

      <Dialog
        open={confirm}
        onClose={() => setConfirm(false)}
        dismissible={!submitting}
        title="Submit assignment?"
        description="You can't change your answers after submitting."
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirm(false)} disabled={submitting}>
              Keep working
            </Button>
            <Button onClick={() => void submit()} loading={submitting}>
              Submit
            </Button>
          </>
        }
      >
        {unanswered ? (
          <p className="text-sm text-warning-fg">
            {unanswered} question{unanswered === 1 ? " is" : "s are"} still unanswered.
          </p>
        ) : (
          <p className="text-sm text-fg-secondary">All questions have an answer.</p>
        )}
        {submitError ? (
          <div className="mt-3">
            <ErrorState error={submitError} detail={submitError instanceof ApiError ? undefined : (submitError as Error).message} />
          </div>
        ) : null}
      </Dialog>
    </div>
  );
}

/** Learner view of a structured assignment: start → workspace → submitted/results. */
export function StructuredAssignment({ assignmentId }: { assignmentId: string }) {
  const [ws, setWs] = useState<WorkspaceOut | null>(null);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setWs(await learnerApi.workspace(assignmentId));
    } catch (err) {
      setError(err);
    }
  }, [assignmentId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) return <ContentErrorState error={error} onRetry={() => void load()} />;
  if (!ws) return <LoadingBlock label="Loading assignment" size="card" />;

  const back = (
    <Link href="/app/assignments" className="text-sm font-medium text-fg-link hover:text-fg-link-hover">
      ‹ My assignments
    </Link>
  );

  const sub = ws.submission;
  if (sub && (DONE.has(sub.status) || sub.submitted_at)) {
    return (
      <div className="space-y-4">
        {back}
        <ResultsView assignmentId={assignmentId} />
      </div>
    );
  }

  const started = sub !== null && ws.sections.some((s) => s.items.length > 0);
  if (!started) {
    return (
      <div className="space-y-4">
        {back}
        <PageHeader title={ws.assignment.title} description={ws.schedule.due_at ? `Due ${formatDateTime(ws.schedule.due_at, { year: true })}` : undefined} />
        <BeforeStart ws={ws} onStarted={setWs} />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {back}
      <Workspace ws={ws} onSubmitted={load} />
    </div>
  );
}

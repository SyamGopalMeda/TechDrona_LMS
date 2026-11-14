"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Card, Dialog, EmptyState, ErrorState, FormField, Select, Skeleton, useToast } from "@/components/ui";
import { UUID_PATTERN } from "@/lib/analytics/envelope";
import { useActivityTracker } from "@/lib/analytics/use-activity-tracker";
import { isApiError } from "@/lib/api/errors";
import { uuid7 } from "@/lib/ids/uuid7";
import { cn } from "@/lib/ui/cn";
import { RichHtml } from "@/features/assessment/components/RichHtml";
import { useLoader } from "@/features/assessment/lib/use-resource";
import { indexTopics, practiceApi } from "../lib/api";
import type { PracticeFeedback, PracticeQuestion, PracticeSession as Session, PracticeSummary, QuestionReportCategory } from "../lib/types";
import { isEntitlementError, MasteryChip, PaywallCard } from "./shared";
import { useStartPractice } from "./PracticeHub";

interface Pending {
  question_version_id: string;
  response: Record<string, unknown>;
  time_spent_ms: number;
  client_attempt_no: number;
  key: string;
}

export const PRACTICE_SESSION_ROUTE = "/app/practice/sessions/[session_id]";

const pendingKey = (sessionId: string) => `td.practice.pending.${sessionId}`;

function loadPending(sessionId: string): Pending[] {
  try {
    const raw = window.localStorage.getItem(pendingKey(sessionId));
    return raw ? (JSON.parse(raw) as Pending[]) : [];
  } catch {
    return [];
  }
}

function savePending(sessionId: string, items: Pending[]): void {
  try {
    if (items.length) window.localStorage.setItem(pendingKey(sessionId), JSON.stringify(items));
    else window.localStorage.removeItem(pendingKey(sessionId));
  } catch {
    /* ignore */
  }
}

function difficultyDots(d: PracticeQuestion["difficulty"]): { dots: string; label: string } | null {
  if (!Number.isFinite(d)) return null;
  const n = Math.max(1, Math.min(5, Math.round(d)));
  return { dots: "●".repeat(n) + "○".repeat(5 - n), label: `Difficulty ${n} of 5` };
}

/** PRC-003 practice session: immediate feedback with explanations (PLC-20..23). */
export function PracticeSession({ sessionId }: { sessionId: string }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [index, setIndex] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const [numeric, setNumeric] = useState("");
  const [feedback, setFeedback] = useState<Map<string, PracticeFeedback>>(new Map());
  const [queued, setQueued] = useState<Set<string>>(new Set());
  const [checking, setChecking] = useState(false);
  const [checkError, setCheckError] = useState<unknown>(null);
  const [hint, setHint] = useState<string | null>(null);
  const [noHint, setNoHint] = useState(false);
  const [summary, setSummary] = useState<PracticeSummary | null>(null);
  const [completing, setCompleting] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);
  const [online, setOnline] = useState(true);
  const shownAt = useRef(0);
  const { start, starting } = useStartPractice();
  const subjects = useLoader("subjects", () => practiceApi.subjects());

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const s = await practiceApi.session(sessionId);
      setSession(s);
      const fb = new Map<string, PracticeFeedback>();
      for (const it of s.items) if (it.feedback) fb.set(it.question.question_version_id, it.feedback);
      setFeedback(fb);
      setQueued(new Set(loadPending(sessionId).map((p) => p.question_version_id)));
      const first = s.items.findIndex((it) => !fb.has(it.question.question_version_id));
      setIndex(first === -1 ? Math.max(0, s.items.length - 1) : first);
    } catch (e) {
      setLoadError(e);
    }
  }, [sessionId]);

  useEffect(() => {
    void load();
  }, [load]);

  const question = session?.items[index]?.question ?? null;

  // FE-07: practice is a learning surface (M5); one page instance per session.
  const tracker = useActivityTracker({
    route: PRACTICE_SESSION_ROUTE,
    surface: "practice",
    entity: { topic_id: session?.topic_id ?? undefined },
    enabled: Boolean(session),
  });

  // FE-16: practice.question_viewed {position_in_set, set_id} (analytics-event-schema §2.3).
  useEffect(() => {
    if (!question) return;
    tracker.event("practice.question_viewed", { position_in_set: index, ...(UUID_PATTERN.test(sessionId) ? { set_id: sessionId } : {}) });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per question shown
  }, [question?.question_version_id]);

  useEffect(() => {
    shownAt.current = performance.now();
    setSelected([]);
    setNumeric("");
    setHint(null);
    setNoHint(false);
    setCheckError(null);
  }, [question?.question_version_id]);

  const send = useCallback(
    async (p: Pending): Promise<boolean> => {
      try {
        const { key, ...body } = p;
        const fb = await practiceApi.answer(sessionId, body, key);
        setFeedback((m) => new Map(m).set(p.question_version_id, fb));
        return true;
      } catch (e) {
        if (isApiError(e) && e.status === 0) return false;
        throw e;
      }
    },
    [sessionId],
  );

  // Offline queue: flush stored answers when the browser reconnects (wireframe §7 states).
  useEffect(() => {
    const flush = async () => {
      setOnline(true);
      const items = loadPending(sessionId);
      const left: Pending[] = [];
      for (const p of items) {
        try {
          if (!(await send(p))) left.push(p);
        } catch {
          /* rejected by the server: drop, feedback will show on reload */
        }
      }
      savePending(sessionId, left);
      setQueued(new Set(left.map((p) => p.question_version_id)));
    };
    const off = () => setOnline(false);
    if (navigator.onLine === false) setOnline(false);
    else void flush();
    window.addEventListener("online", flush);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", flush);
      window.removeEventListener("offline", off);
    };
  }, [send, sessionId]);

  if (loadError) return isEntitlementError(loadError) ? <PaywallCard error={loadError} /> : <ErrorState error={loadError} onRetry={() => void load()} />;
  if (!session || !question)
    return (
      <div aria-busy="true" className="space-y-3">
        <Skeleton className="h-8 w-1/2" />
        <Skeleton className="h-64 w-full" />
      </div>
    );

  const total = session.items.length;
  const topics = indexTopics(subjects.data ?? []);
  const topicName = session.topic_id ? topics.get(session.topic_id)?.name : undefined;
  const fb = feedback.get(question.question_version_id);
  const isQueued = queued.has(question.question_version_id);
  const multi = question.type === "mcq_multi";
  const textAnswer = question.type === "numeric" || question.type === "fill_blank";
  const response: Record<string, unknown> | null = textAnswer ? (numeric.trim() ? { value: numeric.trim() } : null) : selected.length ? { option_ids: selected } : null;
  const answeredCount = session.items.filter((it) => feedback.has(it.question.question_version_id) || queued.has(it.question.question_version_id)).length;
  const allDone = answeredCount === total;
  const diff = difficultyDots(question.difficulty);

  const check = async () => {
    if (!response) return;
    setChecking(true);
    setCheckError(null);
    const p: Pending = {
      question_version_id: question.question_version_id,
      response,
      time_spent_ms: Math.round(performance.now() - shownAt.current),
      client_attempt_no: 1,
      key: uuid7(),
    };
    try {
      const ok = await send(p);
      if (!ok) {
        const items = [...loadPending(sessionId).filter((x) => x.question_version_id !== p.question_version_id), p];
        savePending(sessionId, items);
        setQueued((s) => new Set(s).add(p.question_version_id));
      }
    } catch (e) {
      setCheckError(e);
    } finally {
      setChecking(false);
    }
  };

  const complete = async () => {
    setCompleting(true);
    try {
      setSummary(await practiceApi.complete(sessionId));
    } catch (e) {
      setCheckError(e);
    } finally {
      setCompleting(false);
    }
  };

  if (summary) {
    return (
      <Card title="Set complete" className="mx-auto max-w-xl">
        <p className="font-display text-3xl font-bold tabular-nums">
          {summary.correct}/{summary.answered}
        </p>
        <p className="text-sm text-fg-muted">
          {summary.accuracy !== null ? `${Math.round(summary.accuracy * 100)}% accuracy` : "No answers checked"}
          {summary.unanswered ? ` · ${summary.unanswered} unanswered` : ""}
        </p>
        <ul className="mt-3 space-y-1 text-sm">
          {summary.by_topic.map((t) => (
            <li key={t.topic_id}>
              {topics.get(t.topic_id)?.name ?? "Topic"}: {t.correct}/{t.answered} correct
            </li>
          ))}
        </ul>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link className="inline-flex h-10 items-center rounded-md border border-line-control px-4 text-sm font-medium" href="/app/practice/review">
            Retry incorrect
          </Link>
          {session.topic_id ? (
            <Button loading={starting} onClick={() => void start({ mode: "topic_set", topic_id: session.topic_id })}>
              Next set
            </Button>
          ) : null}
          <Link className="inline-flex h-10 items-center px-2 text-sm text-fg-link underline" href="/app/practice">
            Back to practice
          </Link>
        </div>
      </Card>
    );
  }

  const correctIds = fb?.correct_option_ids ?? [];

  return (
    <div className="mx-auto max-w-3xl pb-24 md:pb-0">
      <header className="mb-4 flex flex-wrap items-center gap-3">
        <Link href="/app/practice" className="text-sm text-fg-link underline">
          ← Practice
          {topicName ? ` · ${topicName}` : ""}
        </Link>
        <span className="text-sm text-fg-secondary">
          Question {index + 1} of {total}
        </span>
        <progress className="h-2 flex-1 accent-brand" max={total} value={answeredCount} aria-label={`${answeredCount} of ${total} answered`} />
        <Button size="sm" variant="ghost" onClick={() => setReportOpen(true)}>
          Report
        </Button>
      </header>

      {!online ? (
        <p role="status" className="mb-3 border-l-4 border-warning-border bg-warning-subtle p-2 text-sm text-warning-fg">
          You&apos;re offline. We&apos;ll keep what you&apos;ve done and sync it when you reconnect.
        </p>
      ) : null}

      <Card>
        <p className="mb-3 text-xs text-fg-muted">
          {diff ? <span aria-label={diff.label}>Difficulty {diff.dots}</span> : null}
          {question.expected_seconds ? ` · ~${question.expected_seconds} s` : ""} · Pattern-aligned practice
        </p>
        <RichHtml html={question.stem_html} className="text-base leading-relaxed" />

        {textAnswer ? (
          <div className="mt-4 max-w-xs">
            <label htmlFor="num-answer" className="block text-sm font-medium">
              Your answer
            </label>
            <input
              id="num-answer"
              inputMode={question.type === "numeric" ? "decimal" : "text"}
              disabled={!!fb || isQueued}
              value={numeric}
              onChange={(e) => setNumeric(e.target.value)}
              className="mt-1 h-10 w-full rounded-md border border-line-control bg-surface px-3 focus-visible:shadow-focus focus-visible:outline-none"
            />
          </div>
        ) : (
          <fieldset className="mt-4 space-y-2" disabled={!!fb || isQueued}>
            <legend className="sr-only">{multi ? "Choose all that apply" : "Choose one answer"}</legend>
            {question.options.map((o, i) => {
              const checked = selected.includes(o.option_id);
              const isRight = !!fb && correctIds.includes(o.option_id);
              const isWrongPick = !!fb && checked && !isRight;
              return (
                <label
                  key={o.option_id}
                  className={cn(
                    "flex min-h-target-touch items-center gap-3 rounded-lg border px-4 py-2",
                    isRight ? "border-success-border bg-success-subtle" : isWrongPick ? "border-danger-border bg-danger-subtle" : checked ? "border-brand bg-brand-subtle" : "border-line-control",
                  )}
                >
                  <input
                    type={multi ? "checkbox" : "radio"}
                    name="practice-option"
                    className="h-5 w-5 accent-brand"
                    checked={checked}
                    onChange={() => setSelected(multi ? (checked ? selected.filter((x) => x !== o.option_id) : [...selected, o.option_id]) : [o.option_id])}
                  />
                  <span aria-hidden="true" className="font-semibold text-fg-muted">
                    {String.fromCharCode(65 + i)}
                  </span>
                  <RichHtml as="span" html={o.html} className="flex-1" />
                  {isRight ? <span className="text-xs font-medium text-success-fg">✓ Correct answer</span> : null}
                  {isWrongPick ? <span className="text-xs font-medium text-danger-fg">✕ Your answer</span> : null}
                </label>
              );
            })}
          </fieldset>
        )}

        {hint ? <RichHtml html={hint} className="mt-4 rounded-md bg-info-subtle p-3 text-sm text-info-fg" /> : null}
        {noHint ? (
          <p role="status" className="mt-4 text-sm text-fg-muted">
            No hint is available for this question.
          </p>
        ) : null}

        <div aria-live="polite">
          {fb ? (
            <div className="mt-5 space-y-3">
              <p className={cn("rounded-md p-3 font-medium", fb.is_correct ? "bg-success-subtle text-success-fg" : "bg-danger-subtle text-danger-fg")}>
                {fb.is_correct ? "✓ Correct" : "✕ Not quite — see the correct answer above"}
                {fb.mastery_delta && fb.mastery_delta.band_before !== fb.mastery_delta.band_after ? (
                  <span className="ml-2 inline-flex items-center gap-1 text-sm font-normal">
                    · Mastery now <MasteryChip band={fb.mastery_delta.band_after} />
                  </span>
                ) : null}
              </p>
              {fb.explanation_html ? (
                <section aria-label="Explanation">
                  <h3 className="text-sm font-semibold">Explanation</h3>
                  <RichHtml html={fb.explanation_html} className="mt-1 text-sm leading-relaxed" />
                </section>
              ) : null}
              {textAnswer && fb.correct_answer !== undefined && fb.correct_answer !== null ? (
                <p className="text-sm">
                  Correct answer: <span className="font-medium">{String(fb.correct_answer)}</span>
                </p>
              ) : null}
            </div>
          ) : isQueued ? (
            <p className="mt-5 rounded-md bg-warning-subtle p-3 text-sm text-warning-fg">
              Saved on this device — will sync. Feedback will appear when you&apos;re back online.
            </p>
          ) : null}
        </div>
        {checkError ? (
          <div className="mt-3">
            <ErrorState error={checkError} />
          </div>
        ) : null}
      </Card>

      <div className="fixed inset-x-0 bottom-0 z-sticky flex flex-wrap items-center justify-between gap-2 border-t border-line bg-surface p-3 md:static md:mt-4 md:border-0 md:bg-transparent md:p-0">
        <div className="flex gap-2">
          {!fb && !isQueued ? (
            <Button
              variant="ghost"
              onClick={async () => {
                try {
                  const r = await practiceApi.reveal(sessionId, question.question_version_id, "hint");
                  const html = r.kind === "hint" && r.available ? r.hint_html : null;
                  setHint(html);
                  setNoHint(!html);
                } catch (e) {
                  setCheckError(e);
                }
              }}
            >
              Show hint
            </Button>
          ) : null}
        </div>
        <div className="flex gap-2">
          {!fb && !isQueued ? (
            <Button onClick={() => void check()} loading={checking} disabled={!response}>
              Check answer
            </Button>
          ) : index < total - 1 ? (
            <Button onClick={() => setIndex((i) => i + 1)}>Next question →</Button>
          ) : null}
          {allDone ? (
            <Button variant={index < total - 1 ? "secondary" : "primary"} loading={completing} onClick={() => void complete()}>
              Finish set
            </Button>
          ) : null}
        </div>
      </div>

      <ReportDialog open={reportOpen} questionVersionId={question?.question_version_id ?? null} onClose={() => setReportOpen(false)} />
    </div>
  );
}

const REPORT_CATEGORIES: { value: QuestionReportCategory; label: string }[] = [
  { value: "wrong_answer", label: "The answer key is wrong" },
  { value: "wrong_explanation", label: "The explanation is wrong" },
  { value: "typo", label: "Typo or formatting problem" },
  { value: "unclear", label: "The question is unclear" },
  { value: "other", label: "Something else" },
];
const REPORT_MAX = 1000;

/** PLC-33: report an error in the current question (content team triages it in CMS-013). */
function ReportDialog({ open, questionVersionId, onClose }: { open: boolean; questionVersionId: string | null; onClose: () => void }) {
  const toast = useToast();
  const [category, setCategory] = useState<QuestionReportCategory>("wrong_answer");
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const key = useRef(uuid7());

  useEffect(() => {
    if (open) {
      setCategory("wrong_answer");
      setMessage("");
      setError(null);
      key.current = uuid7();
    }
  }, [open, questionVersionId]);

  const send = async () => {
    const text = message.trim();
    if (!text) {
      setError("Tell us what's wrong with this question.");
      return;
    }
    if (!questionVersionId) return;
    setSending(true);
    setError(null);
    try {
      await practiceApi.reportQuestion(questionVersionId, { category, message: text, question_version_id: questionVersionId }, key.current);
      toast.show({ tone: "success", title: "Thanks — report sent", description: "Our content team will review this question." });
      onClose();
    } catch (e) {
      if (isApiError(e) && e.status === 409) setError("You've already reported this question. We'll let you know when it's reviewed.");
      else if (isApiError(e) && e.code === "validation_failed") setError(e.detail || "Check your report and try again.");
      else setError(isApiError(e) ? e.title : "Couldn't send the report. Check your connection and try again.");
    } finally {
      setSending(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      dismissible={!sending}
      title="Report a problem with this question"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={sending}>
            Cancel
          </Button>
          <Button onClick={() => void send()} loading={sending} disabled={!questionVersionId}>
            Send report
          </Button>
        </>
      }
    >
      {!questionVersionId ? (
        <EmptyState icon="search" title="No question selected" description="Open a question first, then report it." />
      ) : (
        <div className="space-y-3">
          <FormField label="What's wrong?">
            {(p) => <Select {...p} value={category} onChange={(e) => setCategory(e.target.value as QuestionReportCategory)} options={REPORT_CATEGORIES} />}
          </FormField>
          <FormField label="Details" required hint={`${message.length}/${REPORT_MAX} characters`}>
            {(p) => (
              <textarea
                {...p}
                rows={4}
                maxLength={REPORT_MAX}
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                className="w-full rounded-md border border-line-control bg-surface p-2 text-sm text-fg focus-visible:shadow-focus focus-visible:outline-none"
              />
            )}
          </FormField>
          {error ? (
            <p role="alert" className="text-sm font-medium text-danger-fg">
              {error}
            </p>
          ) : null}
        </div>
      )}
    </Dialog>
  );
}

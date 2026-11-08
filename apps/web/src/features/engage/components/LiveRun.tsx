"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Badge, Button, Card, ErrorState, Input, useToast } from "@/components/ui";
import { api } from "@/lib/api/client";
import { isApiError } from "@/lib/api/errors";
import { cn } from "@/lib/ui/cn";
import { seg } from "@/features/trainer/shared/use-api";
import { TYPE_LABEL } from "../lib/labels";
import { usePoll } from "../lib/use-poll";
import type { AnswerIn, LiveQuestion, LiveState } from "../lib/types";
import { errorText, Leaderboard, Loading, QuestionResults, StatusBadge } from "./parts";

function myAnswerText(q: LiveQuestion): string {
  const a = q.my_answer;
  if (!a) return "";
  if (a.option_ids) return q.options.filter((o) => a.option_ids!.includes(o.id)).map((o) => o.text).join(", ");
  if (a.text != null) return a.text;
  if (a.rating != null) return `${a.rating} / 5`;
  return "";
}

function hasDistribution(q: LiveQuestion): boolean {
  if (q.kind === "word") return Array.isArray(q.words);
  if (q.kind === "rating") return !!q.ratings;
  return q.options.some((o) => typeof o.pct === "number");
}

/** One question: answer form, then "Answer received" + whatever the api chose to reveal. */
export function LiveQuestionCard({
  question: q,
  total,
  onSubmit,
}: {
  question: LiveQuestion;
  total: number;
  onSubmit: (body: AnswerIn) => Promise<void>;
}) {
  const [picked, setPicked] = useState<string[]>([]);
  const [text, setText] = useState("");
  const [rating, setRating] = useState<number | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const answered = q.my_answer !== null;
  const showCorrect = q.options.some((o) => typeof o.correct === "boolean");
  const legendId = `q-${q.id}-legend`;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    let body: AnswerIn;
    if (q.kind === "single_choice" || q.kind === "multi_choice") {
      if (!picked.length) return setError("Choose an option.");
      body = { question_id: q.id, option_ids: picked };
    } else if (q.kind === "rating") {
      if (rating == null) return setError("Choose a rating.");
      body = { question_id: q.id, rating };
    } else {
      const t = text.trim();
      if (!t) return setError(q.kind === "word" ? "Enter a word." : "Enter an answer.");
      if (q.kind === "word" && t.split(/\s+/).length > (q.max_words ?? 1)) {
        return setError(`Use at most ${q.max_words ?? 1} word${(q.max_words ?? 1) === 1 ? "" : "s"}.`);
      }
      body = { question_id: q.id, text: t };
    }
    setError(null);
    setSending(true);
    try {
      await onSubmit(body);
    } finally {
      setSending(false);
    }
  };

  return (
    <Card>
      <p className="text-xs font-semibold uppercase tracking-wide text-fg-muted">
        Question {q.position + 1} of {total}
      </p>
      <h2 id={legendId} className="mt-1 break-words font-display text-lg font-semibold text-fg">
        {q.prompt}
      </h2>

      {answered ? (
        <div className="mt-4 space-y-3">
          <p role="status" className="flex flex-wrap items-center gap-2 text-sm">
            <Badge tone="success">Answer received</Badge>
            <span className="text-fg-secondary">You answered: {myAnswerText(q)}</span>
            {typeof q.my_correct === "boolean" ? (
              <Badge tone={q.my_correct ? "success" : "danger"}>{q.my_correct ? "Correct" : "Incorrect"}</Badge>
            ) : null}
          </p>
          {hasDistribution(q) || showCorrect ? (
            <QuestionResults question={q} showCorrect={showCorrect} mine={q.my_answer?.option_ids} />
          ) : (
            <p className="text-sm text-fg-muted">Results will appear when the host shows them.</p>
          )}
        </div>
      ) : !q.answerable ? (
        <div className="mt-4 space-y-3">
          <p className="text-sm text-fg-muted">{q.revealed ? "Answers are closed for this question." : "This question isn't accepting answers right now."}</p>
          {hasDistribution(q) || showCorrect ? <QuestionResults question={q} showCorrect={showCorrect} /> : null}
        </div>
      ) : (
        <form onSubmit={(e) => void submit(e)} noValidate className="mt-4 space-y-3">
          {q.kind === "single_choice" || q.kind === "multi_choice" ? (
            <fieldset aria-labelledby={legendId} className="space-y-2">
              {q.kind === "multi_choice" ? <p className="text-xs text-fg-muted">Choose all that apply.</p> : null}
              {q.options.map((o) => {
                const checked = picked.includes(o.id);
                return (
                  <label
                    key={o.id}
                    className={cn(
                      "flex min-h-touch cursor-pointer items-center gap-3 rounded-lg border px-3 py-2 text-sm focus-within:shadow-focus",
                      checked ? "border-brand bg-brand-subtle" : "border-line-control hover:bg-surface-hover",
                    )}
                  >
                    <input
                      type={q.kind === "single_choice" ? "radio" : "checkbox"}
                      name={`answer-${q.id}`}
                      value={o.id}
                      checked={checked}
                      onChange={() =>
                        setPicked((p) => (q.kind === "single_choice" ? [o.id] : checked ? p.filter((x) => x !== o.id) : [...p, o.id]))
                      }
                      className="h-5 w-5 accent-[var(--td-brand)] focus-visible:outline-none"
                    />
                    <span className="text-fg">{o.text}</span>
                  </label>
                );
              })}
            </fieldset>
          ) : null}
          {q.kind === "rating" ? (
            <fieldset aria-labelledby={legendId} className="flex flex-wrap gap-2">
              {[1, 2, 3, 4, 5].map((r) => (
                <label
                  key={r}
                  className={cn(
                    "flex h-12 w-12 cursor-pointer items-center justify-center rounded-lg border text-lg font-semibold focus-within:shadow-focus",
                    rating === r ? "border-brand bg-brand text-brand-on" : "border-line-control hover:bg-surface-hover",
                  )}
                >
                  <input type="radio" name={`rating-${q.id}`} value={r} checked={rating === r} onChange={() => setRating(r)} className="sr-only" aria-label={`${r} out of 5`} />
                  {r}
                </label>
              ))}
            </fieldset>
          ) : null}
          {q.kind === "word" || q.kind === "text" ? (
            <div>
              <label htmlFor={`text-${q.id}`} className="sr-only">
                Your answer
              </label>
              {q.kind === "text" ? (
                <textarea
                  id={`text-${q.id}`}
                  rows={3}
                  maxLength={500}
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  className="block w-full rounded-md border border-line-control bg-surface px-3 py-2 text-sm text-fg focus-visible:outline-none focus-visible:shadow-focus"
                />
              ) : (
                <Input id={`text-${q.id}`} maxLength={200} value={text} onChange={(e) => setText(e.target.value)} placeholder={`Up to ${q.max_words ?? 1} word${(q.max_words ?? 1) === 1 ? "" : "s"}`} />
              )}
            </div>
          ) : null}
          {error ? (
            <p role="alert" className="text-sm font-medium text-danger-fg">
              {error}
            </p>
          ) : null}
          <Button type="submit" loading={sending}>
            Submit
          </Button>
        </form>
      )}
    </Card>
  );
}

/** Pure view of the participant state (exported for tests). */
export function LiveRunView({ state, onSubmit }: { state: LiveState; onSubmit: (body: AnswerIn) => Promise<void> }) {
  const { run } = state;
  const total = run.question_count;
  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div>
        <Link href="/app/engage" className="text-sm text-fg-link hover:text-fg-link-hover">
          ← Live activities
        </Link>
        <p className="mt-2 text-xs font-semibold uppercase tracking-wide text-fg-muted">{TYPE_LABEL[state.activity.activity_type]}</p>
        <h1 className="break-words font-display text-2xl font-bold text-fg">{state.activity.title}</h1>
        {state.activity.description ? <p className="mt-1 text-sm text-fg-secondary">{state.activity.description}</p> : null}
        <p className="mt-2 flex flex-wrap items-center gap-2 text-sm text-fg-muted">
          <StatusBadge status={run.status} />
          <span>You are {state.me.label}</span>
          <span>· {state.joined} joined</span>
        </p>
      </div>

      {run.status === "scheduled" ? (
        <Card>
          <div role="status" className="py-6 text-center">
            <p className="font-display text-xl font-semibold text-fg">Waiting for the host to start</p>
            <p className="mt-1 text-sm text-fg-muted">Keep this page open — questions will appear here.</p>
          </div>
        </Card>
      ) : null}

      {run.status !== "scheduled" && state.questions.length === 0 ? (
        <Card>
          <p role="status" className="py-4 text-center text-fg-muted">
            {run.status === "open" ? "Waiting for the next question…" : "This activity has ended."}
          </p>
        </Card>
      ) : null}

      {run.status === "closed" ? <p className="text-sm text-fg-muted">This activity is closed. Results appear here if the host publishes them.</p> : null}
      {run.status === "finalised" ? <p className="font-semibold text-fg">Final results</p> : null}

      {state.questions.map((q) => (
        <LiveQuestionCard key={q.id} question={q} total={total} onSubmit={onSubmit} />
      ))}

      {state.my_rank || state.leaderboard.length ? (
        <Card title="Leaderboard">
          {state.my_rank ? (
            <p className="mb-3 text-sm">
              Your rank: <span className="font-semibold">#{state.my_rank.rank}</span> · {state.my_rank.correct} correct
            </p>
          ) : null}
          <Leaderboard rows={state.leaderboard} highlight={state.my_rank?.label} />
        </Card>
      ) : null}
    </div>
  );
}

/** STU-032 participant live page. */
export function LiveRun({ runId, code }: { runId: string; code?: string }) {
  const router = useRouter();
  const toast = useToast();
  const [redirecting, setRedirecting] = useState(false);
  const poll = usePoll<LiveState>(`engage/runs/${seg(runId)}/live`, {
    done: (d) => d.run.status === "finalised",
    onError: (err) => {
      if (isApiError(err) && err.code === "not_joined") {
        setRedirecting(true);
        router.replace(code ? `/app/engage/join/${seg(code)}` : "/app/engage");
      }
    },
  });

  const submit = async (body: AnswerIn) => {
    try {
      await api.post(`engage/runs/${seg(runId)}/responses`, body);
      toast.show({ title: "Answer received", tone: "success" });
    } catch (err) {
      if (isApiError(err) && err.code === "already_answered") toast.show({ title: "You already answered this question", tone: "info" });
      else if (isApiError(err) && err.code === "question_not_open") toast.show({ title: "This question isn't accepting answers right now", tone: "warning" });
      else toast.show({ ...errorText(err, "Couldn't send your answer"), tone: "danger" });
    }
    await poll.refresh();
  };

  if (redirecting) return <Loading label="Redirecting to join" rows={1} />;
  if (poll.data) return <LiveRunView state={poll.data} onSubmit={submit} />;
  if (poll.error) return <ErrorState error={poll.error} onRetry={() => void poll.refresh()} />;
  return <Loading label="Loading activity" rows={2} />;
}


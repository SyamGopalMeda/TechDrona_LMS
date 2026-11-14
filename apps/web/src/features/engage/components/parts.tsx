"use client";

import { useEffect, useState, type ReactNode } from "react";
import { Badge, LoadingBlock, StatusBadge as KitStatusBadge } from "@/components/ui";
import { isApiError } from "@/lib/api/errors";
import { cn } from "@/lib/ui/cn";
import { formatMs, KIND_LABEL, STATUS_LABEL } from "../lib/labels";
import type { LeaderRow, ResultOption, ResultQuestion, RunStatus, WinnerInfo } from "../lib/types";

/* A live run ("open") is the kit's "live" state; the other run statuses map one to one. */
const RUN_TO_KIT: Record<RunStatus, string> = { scheduled: "scheduled", open: "live", closed: "closed", finalised: "finalised" };

export function StatusBadge({ status }: { status: RunStatus }) {
  return <KitStatusBadge status={RUN_TO_KIT[status] ?? status} label={STATUS_LABEL[status]} />;
}

export function Loading({ label = "Loading", rows = 3 }: { label?: string; rows?: number }) {
  return <LoadingBlock label={label} rows={rows} size="card" />;
}

/** Problem title + detail for toasts. */
export function errorText(err: unknown, fallback = "Something went wrong"): { title: string; description?: string; requestId?: string | null } {
  if (isApiError(err)) {
    // SEC-07: launch (10/h) and invite (5/h) are rate limited per activity and host.
    if (err.status === 429 || err.code === "rate_limited") {
      const wait = err.retryAfter ? `about ${Math.max(1, Math.ceil(err.retryAfter / 60))} minute(s)` : "a while";
      return { title: "Too many tries", description: `You've hit the limit for this action. Try again in ${wait}.`, requestId: err.requestId };
    }
    const first = err.problem?.errors?.[0];
    return {
      title: err.title,
      description: first ? `${first.field}: ${first.message}` : err.detail,
      requestId: err.requestId,
    };
  }
  return { title: fallback };
}

/** Join URL from the run's relative join path (client only). */
export function useJoinUrl(joinPath: string | null | undefined): string {
  const [origin, setOrigin] = useState("");
  useEffect(() => {
    setOrigin(window.location.origin);
  }, []);
  return joinPath ? `${origin}${joinPath}` : "";
}

/* ------------------------------------------------------------------ segmented choice */

/** Radio group styled as side-by-side cards: the kit Segmented. */
export { Segmented, type SegmentOption } from "@/components/ui";

/* ------------------------------------------------------------------ results */

export function OptionBar({
  option,
  showCorrect,
  mine,
  large,
}: {
  option: ResultOption;
  showCorrect: boolean;
  mine?: boolean;
  large?: boolean;
}) {
  const hasDist = typeof option.pct === "number" && typeof option.count === "number";
  const correct = showCorrect && option.correct === true;
  const pct = Math.max(0, Math.min(100, option.pct ?? 0));
  return (
    <li
      data-correct={correct || undefined}
      className={cn(
        "relative overflow-hidden rounded-lg border",
        correct ? "border-success-border" : "border-line",
        large ? "px-5 py-4" : "px-3 py-2",
      )}
    >
      {hasDist ? (
        <span
          aria-hidden="true"
          className={cn("absolute inset-y-0 left-0", correct ? "bg-success-subtle" : "bg-brand-subtle")}
          style={{ width: `${pct}%` }}
        />
      ) : null}
      <span className={cn("relative flex items-center justify-between gap-3", large ? "text-2xl md:text-3xl" : "text-sm")}>
        <span className="flex min-w-0 items-center gap-2">
          {correct ? (
            <span className="font-bold text-success-fg" aria-label="Correct answer">
              ✓
            </span>
          ) : null}
          <span className={cn("break-words", correct ? "font-semibold text-success-fg" : "text-fg")}>{option.text}</span>
          {mine ? <Badge tone="info">Your answer</Badge> : null}
        </span>
        {hasDist ? (
          <span className="shrink-0 font-semibold tabular-nums text-fg-secondary">
            {option.pct}% · {option.count}
          </span>
        ) : null}
      </span>
    </li>
  );
}

export function WordCloud({ words, large }: { words: { term: string; count: number }[]; large?: boolean }) {
  if (words.length === 0) return <p className="text-sm text-fg-muted">No words yet.</p>;
  const max = Math.max(...words.map((w) => w.count));
  const min = Math.min(...words.map((w) => w.count));
  const [lo, hi] = large ? [22, 96] : [14, 44];
  const size = (c: number) => (max === min ? (lo + hi) / 2 : lo + ((c - min) / (max - min)) * (hi - lo));
  return (
    <ul aria-label="Word cloud" className="flex flex-wrap items-center justify-center gap-x-4 gap-y-2 p-2">
      {words.map((w, i) => (
        <li
          key={w.term}
          className={cn("font-display font-bold leading-tight", i % 3 === 0 ? "text-brand" : i % 3 === 1 ? "text-fg" : "text-fg-secondary")}
          style={{ fontSize: `${Math.round(size(w.count))}px` }}
        >
          {w.term}
          <span className="sr-only"> ({w.count})</span>
        </li>
      ))}
    </ul>
  );
}

export function RatingSummary({ ratings, average }: { ratings: Record<string, number>; average?: number | null }) {
  const total = Object.values(ratings).reduce((a, b) => a + b, 0);
  return (
    <div className="space-y-2">
      <p className="text-sm text-fg-secondary">
        Average: <span className="font-semibold text-fg">{average != null ? average.toFixed(2) : "—"}</span> / 5
      </p>
      <ul className="space-y-1">
        {["5", "4", "3", "2", "1"].map((k) => {
          const n = ratings[k] ?? 0;
          const pct = total ? Math.round((100 * n) / total) : 0;
          return (
            <li key={k} className="flex items-center gap-2 text-sm">
              <span className="w-10 shrink-0 tabular-nums">{k} ★</span>
              <span className="relative h-3 flex-1 overflow-hidden rounded-full bg-surface-sunken" aria-hidden="true">
                <span className="absolute inset-y-0 left-0 bg-brand" style={{ width: `${pct}%` }} />
              </span>
              <span className="w-16 shrink-0 text-right tabular-nums text-fg-secondary">
                {pct}% · {n}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function WinnerBox({ winner, large }: { winner: WinnerInfo; large?: boolean }) {
  const more = winner.also_correct_count - winner.also_correct.length;
  return (
    <div className={cn("rounded-lg border border-warning-border bg-warning-subtle", large ? "p-5 text-2xl" : "p-3 text-sm")}>
      <p className="font-semibold text-warning-fg">
        <span aria-hidden="true">★ </span>Fastest: {winner.fastest}
      </p>
      {winner.also_correct.length ? (
        <p className="mt-1 text-fg-secondary">
          Also correct: {winner.also_correct.join(", ")}
          {more > 0 ? ` and ${more} more` : ""}
        </p>
      ) : null}
    </div>
  );
}

/** One question's results: bars, word cloud, rating or text answers. */
export function QuestionResults({
  question,
  showCorrect,
  large,
  texts,
  winner,
  mine,
}: {
  question: ResultQuestion;
  showCorrect: boolean;
  large?: boolean;
  texts?: { label: string; text: string | null; filtered: boolean }[];
  winner?: WinnerInfo | null;
  mine?: string[];
}) {
  const q = question;
  if (q.kind === "word") {
    return q.words ? <WordCloud words={q.words} large={large} /> : <p className="text-sm text-fg-muted">Words are hidden until results are shown.</p>;
  }
  if (q.kind === "rating") {
    return q.ratings ? <RatingSummary ratings={q.ratings} average={q.average} /> : <p className="text-sm text-fg-muted">Ratings are hidden until results are shown.</p>;
  }
  if (q.kind === "text") {
    if (!texts) return <p className="text-sm text-fg-muted">{q.answered} answers</p>;
    if (texts.length === 0) return <p className="text-sm text-fg-muted">No answers yet.</p>;
    return (
      <ul className="max-h-96 space-y-2 overflow-y-auto">
        {texts.map((t, i) => (
          <li key={i} className="rounded-md border border-line px-3 py-2 text-sm">
            <span className="font-medium text-fg-secondary">{t.label}: </span>
            {t.filtered ? <span className="italic text-fg-muted">Hidden by the content filter</span> : t.text}
          </li>
        ))}
      </ul>
    );
  }
  return (
    <div className="space-y-3">
      <ul className={cn("space-y-2", large && "space-y-3")}>
        {q.options.map((o) => (
          <OptionBar key={o.id} option={o} showCorrect={showCorrect} large={large} mine={mine?.includes(o.id)} />
        ))}
      </ul>
      {showCorrect && winner ? <WinnerBox winner={winner} large={large} /> : null}
    </div>
  );
}

export function QuestionHeading({ question, total, children }: { question: ResultQuestion; total?: number; children?: ReactNode }) {
  return (
    <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-fg-muted">
          Question {question.position + 1}
          {total ? ` of ${total}` : ""} · {KIND_LABEL[question.kind]}
        </p>
        <h3 className="mt-1 font-display text-base font-semibold text-fg">{question.prompt}</h3>
      </div>
      {children}
    </div>
  );
}

export function Leaderboard({ rows, highlight }: { rows: LeaderRow[]; highlight?: string | null }) {
  if (rows.length === 0) return <p className="text-sm text-fg-muted">No correct answers yet.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Leaderboard</caption>
        <thead>
          <tr className="border-b border-line text-xs uppercase tracking-wide text-fg-muted">
            <th scope="col" className="py-2 pr-3">
              Rank
            </th>
            <th scope="col" className="py-2 pr-3">
              Participant
            </th>
            <th scope="col" className="py-2 pr-3 text-right">
              Wins
            </th>
            <th scope="col" className="py-2 pr-3 text-right">
              Correct
            </th>
            <th scope="col" className="py-2 text-right">
              Time
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.rank}-${r.label}`} className={cn("border-b border-line-subtle", highlight === r.label && "bg-brand-subtle")}>
              <td className="py-2 pr-3 tabular-nums">{r.rank}</td>
              <td className="py-2 pr-3">{r.label}</td>
              <td className="py-2 pr-3 text-right tabular-nums">{r.wins}</td>
              <td className="py-2 pr-3 text-right tabular-nums">{r.correct}</td>
              <td className="py-2 text-right tabular-nums">{formatMs(r.time_ms)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge, Card, EmptyState, ErrorState, PageHeader, Skeleton, StatTile, Tabs } from "@/components/ui";
import { isApiError } from "@/lib/api/errors";
import { assessmentApi } from "../lib/api";
import { formatDuration, formatIstDateTime, formatPercent, formatScore } from "../lib/format";
import { isAnswered } from "../lib/resume";
import type { ReviewItem, ReviewSubmission } from "../lib/types";
import { useLoader } from "../lib/use-resource";
import { VERDICT_NAME } from "@/features/coding/components/VerdictPanel";
import { RichHtml } from "./RichHtml";

type Filter = "all" | "incorrect" | "skipped" | "marked";

function matches(item: ReviewItem, f: Filter): boolean {
  if (f === "incorrect") return item.is_correct === false;
  if (f === "skipped") return !isAnswered(item.your_response);
  if (f === "marked") return !!item.flagged;
  return true;
}

/** BE-23: the learner's own scored code for a coding item, with verdicts when they are visible. */
function CodingReview({ sub }: { sub: ReviewSubmission | null | undefined }) {
  if (!sub) return <p className="mt-3 text-sm text-fg-muted">No judged submission was recorded for this question.</p>;
  return (
    <div className="mt-3 space-y-2 text-sm">
      <p className="text-fg-secondary">
        Your submission{sub.language_key ? ` (${sub.language_key})` : ""}
        {sub.verdict ? ` · ${VERDICT_NAME[sub.verdict] ?? sub.verdict}` : ""}
        {sub.passed_cases != null && sub.total_cases != null ? ` · ${sub.passed_cases}/${sub.total_cases} test cases passed` : ""}
      </p>
      {sub.source_code ? (
        <pre className="max-h-80 overflow-auto rounded-md bg-surface-sunken p-3 font-mono text-xs text-fg" aria-label="Your code">
          <code>{sub.source_code}</code>
        </pre>
      ) : null}
      {sub.cases?.length ? (
        <ul className="flex flex-wrap gap-1" aria-label="Test case results">
          {sub.cases.map((c, i) => (
            <li key={c.ordinal ?? i}>
              <Badge tone={c.verdict === "AC" ? "success" : "danger"}>
                Case {c.ordinal ?? i + 1}
                {c.is_sample === false ? " (hidden)" : ""}: {c.verdict ? (VERDICT_NAME[c.verdict] ?? c.verdict) : "—"}
              </Badge>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function ReviewRow({ item, n }: { item: ReviewItem; n: number }) {
  const [open, setOpen] = useState(false);
  const chosen = item.your_response && "option_ids" in item.your_response ? (item.your_response.option_ids as string[]) : [];
  const keyShown = Array.isArray(item.correct_option_ids) || item.correct_answer !== undefined;
  const typed = item.your_response && "value" in item.your_response ? String(item.your_response.value ?? "") : null;
  return (
    <li className="rounded-xl border border-line bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold text-fg">Question {n}</h3>
        <div className="flex items-center gap-2 text-xs text-fg-muted">
          {item.is_correct === true ? <Badge tone="success">✓ Correct</Badge> : item.is_correct === false ? <Badge tone="danger">✕ Incorrect</Badge> : null}
          {!isAnswered(item.your_response) ? <Badge>Skipped</Badge> : null}
          {item.marks_awarded !== undefined ? <span>Marks {formatScore(item.marks_awarded)}</span> : null}
          <span>· {formatDuration(item.time_spent_ms / 1000)}</span>
        </div>
      </div>
      <RichHtml html={item.stem_html} className="mt-2 text-sm text-fg" />
      {item.options?.length ? (
        <ul className="mt-3 space-y-1 text-sm">
          {item.options.map((o, i) => {
            const mine = chosen.includes(o.option_id);
            const correct = !!item.correct_option_ids?.includes(o.option_id);
            return (
              <li key={o.option_id} className="flex items-start gap-2 rounded-md px-2 py-1">
                <span aria-hidden="true" className="w-4 font-semibold text-fg-muted">
                  {String.fromCharCode(65 + i)}
                </span>
                <RichHtml as="span" html={o.html} className="flex-1" />
                {mine ? <Badge tone={item.is_correct === false ? "danger" : "brand"}>Your answer</Badge> : null}
                {correct ? <Badge tone="success">Correct answer</Badge> : null}
              </li>
            );
          })}
        </ul>
      ) : null}
      {item.coding_problem_id ? <CodingReview sub={item.your_submission} /> : null}
      {!item.options?.length && !item.coding_problem_id ? (
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
          <dt className="text-fg-muted">Your answer</dt>
          <dd>{typed || "—"}</dd>
          {item.correct_answer !== undefined ? (
            <>
              <dt className="text-fg-muted">Correct answer</dt>
              <dd>{item.correct_answer === null ? "—" : String(item.correct_answer)}</dd>
            </>
          ) : null}
        </dl>
      ) : null}
      {!keyShown && !item.coding_problem_id ? <p className="mt-2 text-xs text-fg-muted">The answer key isn&apos;t released for this test yet.</p> : null}
      {item.explanation_html ? (
        <div className="mt-3">
          <button type="button" className="text-sm font-medium text-fg-link underline" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            {open ? "Hide explanation" : "Explanation"}
          </button>
          {open ? <RichHtml html={item.explanation_html} className="mt-2 rounded-md bg-surface-sunken p-3 text-sm" /> : null}
        </div>
      ) : null}
    </li>
  );
}

function Review({ attemptId }: { attemptId: string }) {
  const res = useLoader(`review:${attemptId}`, () => assessmentApi.review(attemptId));
  const [filter, setFilter] = useState<Filter>("all");
  if (res.error) {
    if (isApiError(res.error) && res.error.code === "results_not_released") return null;
    return <ErrorState error={res.error} onRetry={() => void res.reload()} />;
  }
  if (!res.data) return <Skeleton className="h-40 w-full" />;
  const items = res.data.sections.flatMap((s) => s.questions);
  const content = (f: Filter) => {
    const rows = items.map((it, i) => ({ it, n: i + 1 })).filter(({ it }) => matches(it, f));
    return rows.length ? (
      <ul className="space-y-3">
        {rows.map(({ it, n }) => (
          <ReviewRow key={it.question_version_id} item={it} n={n} />
        ))}
      </ul>
    ) : (
      <EmptyState title="No questions in this view" />
    );
  };
  return (
    <section aria-labelledby="review-h" className="mt-8">
      <h2 id="review-h" className="mb-3 font-display text-lg font-semibold">
        Question review
      </h2>
      <Tabs
        label="Filter questions"
        value={filter}
        onValueChange={(v) => setFilter(v as Filter)}
        items={(["all", "incorrect", "skipped", "marked"] as Filter[]).map((f) => ({ id: f, label: f[0]!.toUpperCase() + f.slice(1), content: content(f) }))}
      />
    </section>
  );
}

/** STU-010 Results & review (ATT-11, ATT-12): shows only what the review policy releases. */
export function ResultsView({ attemptId }: { attemptId: string }) {
  const res = useLoader(attemptId, () => assessmentApi.result(attemptId));

  if (res.error) {
    if (isApiError(res.error) && res.error.code === "results_not_released") {
      const at = res.error.problem?.release_at as string | undefined;
      return (
        <EmptyState
          title={at ? `Results on ${formatIstDateTime(at)}` : "Results aren't released yet"}
          description="We'll notify you when they're ready."
          action={<Link className="text-sm font-medium text-fg-link underline" href="/app/tests">Back to tests</Link>}
        />
      );
    }
    return <ErrorState error={res.error} onRetry={() => void res.reload()} />;
  }
  if (!res.data)
    return (
      <div aria-busy="true" className="space-y-4">
        <Skeleton className="h-10 w-1/2" />
        <Skeleton className="h-32 w-full" />
      </div>
    );

  const r = res.data;
  if (r.status === "invalidated") {
    return (
      <div role="alert" className="rounded-xl border border-warning-border bg-warning-subtle p-5 text-warning-fg">
        <p className="font-semibold">This attempt was invalidated after review</p>
        {r.appeal_url ? (
          <Link className="mt-2 inline-block text-sm underline" href={r.appeal_url}>
            Appeal this decision
          </Link>
        ) : null}
      </div>
    );
  }

  const showScore = r.visible?.score !== false && r.score !== undefined;
  return (
    <div>
      <PageHeader
        eyebrow="Results"
        title="Test results"
        description={r.submitted_at ? `Submitted ${formatIstDateTime(r.submitted_at)}` : undefined}
        actions={<Link className="text-sm text-fg-link underline" href="/app/tests">Back to tests</Link>}
      />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile label="Score" value={showScore ? `${formatScore(r.score)} / ${formatScore(r.max_score)}` : null} hint={showScore ? formatPercent(r.percentage, 1) : "Not released"} />
        <StatTile
          label="Percentile"
          value={r.percentile !== null && r.percentile !== undefined ? `${Math.round(r.percentile)}th` : null}
          hint={
            r.percentile_note === "insufficient_cohort"
              ? "Too few students to show a percentile"
              : r.rank_provisional
                ? "Provisional until integrity review completes"
                : undefined
          }
        />
        <StatTile
          label="Correct / incorrect / skipped"
          value={r.correct_count !== undefined ? `${r.correct_count} / ${r.incorrect_count ?? "—"} / ${r.unanswered_count ?? "—"}` : null}
        />
        <StatTile label="Time taken" value={r.time_taken_seconds !== undefined ? formatDuration(r.time_taken_seconds) : null} hint="Server time from start to submit" />
      </div>

      {r.section_scores?.length ? (
        <Card title="Sections" className="mt-6">
          <ul className="space-y-3">
            {r.section_scores.map((s) => {
              // Decimals arrive as strings ("7.00").
              const score = Number(s.score);
              const max = Number(s.max);
              const pct = max > 0 ? Math.max(0, Math.min(100, (score / max) * 100)) : 0;
              return (
                <li key={s.section_id}>
                  <div className="flex flex-wrap justify-between gap-2 text-sm">
                    <span className="font-medium">{s.title}</span>
                    <span className="tabular-nums text-fg-secondary">
                      {formatScore(score)}/{formatScore(max)}
                      {` · ${formatDuration(s.time_s)}`}
                    </span>
                  </div>
                  <div className="mt-1 h-2 rounded-full bg-line" aria-hidden="true">
                    <div className="h-2 rounded-full bg-brand" style={{ width: `${pct}%` }} />
                  </div>
                </li>
              );
            })}
          </ul>
        </Card>
      ) : null}

      <Review attemptId={attemptId} />
    </div>
  );
}

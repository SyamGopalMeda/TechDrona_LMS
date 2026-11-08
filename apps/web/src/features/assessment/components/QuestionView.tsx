"use client";

import { useId } from "react";
import { CodingQuestion } from "@/features/coding/components/CodingQuestion";
import type { ActivityTrackerHandle } from "@/lib/analytics/use-activity-tracker";
import { cn } from "@/lib/ui/cn";
import type { QuestionDelivery, QuestionResponse } from "../lib/types";
import { formatScore } from "../lib/format";
import { RichHtml } from "./RichHtml";

export interface QuestionViewProps {
  number: number;
  question: QuestionDelivery;
  response: QuestionResponse | null;
  flagged: boolean;
  disabled?: boolean;
  /** Needed for coding items: judge submissions are made for this attempt (COD-004). */
  attemptId?: string;
  tracker?: ActivityTrackerHandle;
  onChange: (response: QuestionResponse | null) => void;
  onToggleFlag: (flagged: boolean) => void;
}

function selectedIds(r: QuestionResponse | null): string[] {
  return r && "option_ids" in r && Array.isArray(r.option_ids) ? (r.option_ids as string[]) : [];
}

/** One test question (TST-002 main pane). Options are full-width ≥ 44 px rows. */
export function QuestionView({ number, question, response, flagged, disabled, attemptId, tracker, onChange, onToggleFlag }: QuestionViewProps) {
  const name = useId();
  const sel = selectedIds(response);
  const multi = question.type === "mcq_multi";
  // Decimals arrive as strings ("1.00").
  const pos = question.marks != null ? Number(question.marks) : null;
  const neg = question.negative_marks != null ? Number(question.negative_marks) : 0;
  const marks = pos !== null && Number.isFinite(pos) ? `+${formatScore(pos)}${neg ? ` / −${formatScore(neg)}` : ""}` : null;
  const textEntry = question.type === "numeric" || question.type === "fill_blank";
  // FE-06: coding items carry coding_problem_id; the answer is the pinned judge submission.
  const coding = Boolean(question.coding_problem_id) || question.type === "coding";
  const submissionId = response && "submission_id" in response && typeof response.submission_id === "string" ? response.submission_id : null;

  return (
    <article aria-labelledby={`${name}-h`}>
      <header className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 id={`${name}-h`} className="font-display text-base font-semibold text-fg">
          Question {number}
          {marks ? <span className="ml-2 text-sm font-normal text-fg-muted">· {marks}</span> : null}
        </h2>
        <label className="inline-flex min-h-target items-center gap-2 text-sm text-fg">
          <input
            type="checkbox"
            className="h-5 w-5 accent-brand"
            checked={flagged}
            disabled={disabled}
            onChange={(e) => onToggleFlag(e.target.checked)}
          />
          Mark for review
        </label>
      </header>
      <RichHtml html={question.stem_html} className="text-base leading-relaxed text-fg" />

      {coding ? (
        <div className="mt-4 space-y-2">
          {question.coding_problem_id && attemptId ? (
            disabled ? (
              <p className="text-sm text-fg-muted">The editor is closed.</p>
            ) : (
              <CodingQuestion
                problemId={question.coding_problem_id}
                slug={question.coding_problem_slug}
                attemptId={attemptId}
                tracker={tracker}
                onSubmitted={(id) => onChange({ submission_id: id })}
              />
            )
          ) : (
            <p role="alert" className="text-sm text-danger-fg">
              This coding question is missing its problem. Please contact support.
            </p>
          )}
          <p role="status" className="text-sm text-fg-secondary">
            {submissionId
              ? "Your latest submission is saved as the answer to this question. You can submit again before the test ends."
              : "Submit your code to answer this question. Run only checks the samples and is not saved as an answer."}
          </p>
        </div>
      ) : textEntry ? (
        <div className="mt-4 max-w-xs">
          <label htmlFor={`${name}-num`} className="block text-sm font-medium text-fg">
            Your answer
          </label>
          <input
            id={`${name}-num`}
            inputMode={question.type === "numeric" ? "decimal" : "text"}
            disabled={disabled}
            value={response && "value" in response && typeof response.value === "string" ? response.value : ""}
            onChange={(e) => onChange(e.target.value === "" ? null : { value: e.target.value })}
            className="mt-1 h-10 w-full rounded-md border border-line-control bg-surface px-3 text-fg focus-visible:shadow-focus focus-visible:outline-none"
          />
        </div>
      ) : (
        <fieldset className="mt-4" disabled={disabled}>
          <legend className="sr-only">{multi ? "Choose all that apply" : "Choose one answer"}</legend>
          {multi ? <p className="mb-2 text-sm text-fg-muted">Choose all that apply.</p> : null}
          <div className="space-y-2">
            {(question.options ?? []).map((o, i) => {
              const checked = sel.includes(o.option_id);
              return (
                <label
                  key={o.option_id}
                  className={cn(
                    "flex min-h-target-touch cursor-pointer items-center gap-3 rounded-lg border px-4 py-2 text-fg",
                    checked ? "border-brand bg-brand-subtle" : "border-line-control bg-surface hover:bg-surface-hover",
                  )}
                >
                  <input
                    type={multi ? "checkbox" : "radio"}
                    name={name}
                    className="h-5 w-5 shrink-0 accent-brand"
                    checked={checked}
                    onChange={() => {
                      if (multi) {
                        const next = checked ? sel.filter((x) => x !== o.option_id) : [...sel, o.option_id];
                        onChange(next.length ? { option_ids: next } : null);
                      } else {
                        onChange({ option_ids: [o.option_id] });
                      }
                    }}
                  />
                  <span aria-hidden="true" className="font-semibold text-fg-muted">
                    {String.fromCharCode(65 + i)}
                  </span>
                  <RichHtml html={o.html} as="span" />
                </label>
              );
            })}
          </div>
        </fieldset>
      )}
    </article>
  );
}

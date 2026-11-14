"use client";

import { Button } from "@/components/ui";
import { ApiError } from "@/lib/api/errors";
import { isProblemDetails } from "@/lib/api/problem";
import { AI_PROBLEM_CODES, type AIProblemCode } from "../types";

/**
 * The AI problem code (`ai_disabled` | `ai_quota_exceeded` | `ai_unavailable`) carried by an
 * error thrown from the API client (ApiError with a problem+json body), or by a bare problem
 * object; null for anything else.
 */
export function aiProblemCode(err: unknown): AIProblemCode | null {
  let code: unknown = null;
  if (err instanceof ApiError) code = err.problem?.code ?? err.code;
  else if (isProblemDetails(err)) code = err.code;
  else if (err && typeof err === "object" && "problem" in err && isProblemDetails((err as { problem: unknown }).problem)) {
    code = (err as { problem: { code: string } }).problem.code;
  }
  return typeof code === "string" && (AI_PROBLEM_CODES as readonly string[]).includes(code) ? (code as AIProblemCode) : null;
}

const COPY: Record<AIProblemCode, { title: string; body: string }> = {
  ai_disabled: {
    title: "AI help is turned off",
    body: "A Tech Drona admin has turned AI features off. You can carry on without it.",
  },
  ai_quota_exceeded: {
    title: "AI limit reached",
    body: "The AI allowance has been used up for now. It resets with the next usage period — you can carry on without AI help.",
  },
  ai_unavailable: {
    title: "AI is temporarily unavailable — try again later",
    body: "The AI service did not respond. Nothing you entered was lost.",
  },
};

export interface AIErrorStateProps {
  code: AIProblemCode | (string & {});
  /** Server-provided detail (problem `detail`, user-safe); shown under the friendly copy. */
  detail?: string | null;
  onRetry?: () => void;
}

/** Friendly state for AI problems; retry is offered only where retrying can help. */
export function AIErrorState({ code, detail, onRetry }: AIErrorStateProps) {
  const copy = COPY[code as AIProblemCode] ?? { title: "AI help could not respond", body: "Please try again later." };
  const tone = code === "ai_disabled" ? "border-line bg-surface-sunken" : code === "ai_quota_exceeded" ? "border-warning-border bg-warning-subtle" : "border-danger-border bg-danger-subtle";
  const canRetry = onRetry && code !== "ai_disabled" && code !== "ai_quota_exceeded";
  return (
    <div role="alert" data-ai-code={code} className={`rounded-lg border p-4 text-sm ${tone}`}>
      <p className="font-semibold text-fg">{copy.title}</p>
      <p className="mt-1 text-fg-secondary">{copy.body}</p>
      {detail && detail !== copy.title ? <p className="mt-1 text-xs text-fg-muted">{detail}</p> : null}
      {canRetry ? (
        <Button variant="secondary" size="sm" className="mt-3" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}

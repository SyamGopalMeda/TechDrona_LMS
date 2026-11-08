"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, ErrorState, Skeleton } from "@/components/ui";
import { isApiError } from "@/lib/api/errors";
import { assessmentApi } from "../lib/api";
import { formatIstDateTime, formatIstTime } from "../lib/format";
import type { AttemptResult, SubmitResponse } from "../lib/types";
import { SUBMITTED_KEY } from "./AttemptRunner";

type State =
  | { kind: "loading" }
  | { kind: "released"; result: AttemptResult }
  | { kind: "pending"; mode?: string; releaseAt?: string | null }
  | { kind: "error"; error: unknown };

/** TST-005 Submitted (ATT-11 for the release state). `reason` comes from the runner on auto-submit. */
export function SubmittedView({ attemptId, reason }: { attemptId: string; reason?: string | null }) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [submit, setSubmit] = useState<SubmitResponse | null>(null);
  const [flagged, setFlagged] = useState(false);

  useEffect(() => {
    try {
      const raw = window.sessionStorage.getItem(SUBMITTED_KEY(attemptId));
      if (raw) setSubmit(JSON.parse(raw) as SubmitResponse);
    } catch {
      /* ignore */
    }
    let cancelled = false;
    // The server decides whether the attempt was flagged (exam protocol); the closed-attempt state
    // carries it for auto-submits too.
    assessmentApi
      .state(attemptId)
      .then((p) => !cancelled && setFlagged(!!p.integrity_flagged))
      .catch(() => undefined);
    assessmentApi
      .result(attemptId)
      .then((result) => !cancelled && setState({ kind: "released", result }))
      .catch((e: unknown) => {
        if (cancelled) return;
        if (isApiError(e) && e.code === "results_not_released") {
          setState({ kind: "pending", mode: e.problem?.release_mode as string | undefined, releaseAt: (e.problem?.release_at as string | undefined) ?? null });
        } else setState({ kind: "error", error: e });
      });
    return () => {
      cancelled = true;
    };
  }, [attemptId]);

  const submittedAt = submit?.submitted_at ?? (state.kind === "released" ? state.result.submitted_at : undefined);
  // Results route is keyed by attempt; ATT-11 carries no test id, so the URL segment is cosmetic ("_").
  const testSeg = "_";

  return (
    <div className="mx-auto max-w-xl">
      {reason === "deadline_offline" ? (
        <div role="status" className="mb-4 border-l-4 border-warning-border bg-warning-subtle p-3 text-sm text-warning-fg">
          Time ended while you were offline. We submitted the answers we had received by the deadline. Answers made after that time couldn&apos;t be
          counted.
        </div>
      ) : reason === "integrity_limit" || submit?.submit_reason === "integrity_limit" ? (
        <div role="status" className="mb-4 border-l-4 border-warning-border bg-warning-subtle p-3 text-sm text-warning-fg">
          Your exam was submitted automatically after the allowed number of recorded integrity events.
        </div>
      ) : reason === "deadline" || submit?.submit_reason === "deadline" ? (
        <div role="status" className="mb-4 border-l-4 border-info-border bg-info-subtle p-3 text-sm text-info-fg">
          Time&apos;s up. Your test was submitted automatically{submittedAt ? ` at ${formatIstTime(submittedAt)}` : ""}.
        </div>
      ) : null}
      {flagged || submit?.integrity_flagged ? (
        <div role="status" data-testid="flagged-notice" className="mb-4 border-l-4 border-warning-border bg-warning-subtle p-3 text-sm text-warning-fg">
          <span aria-hidden="true">🛡 </span>
          This attempt was flagged for review because of integrity events recorded during the exam. An evaluator will look at it before any
          decision is made.
        </div>
      ) : null}
      <Card>
        <h1 className="font-display text-xl font-semibold text-fg">Test submitted{submittedAt ? ` at ${formatIstTime(submittedAt)}` : ""}</h1>
        <div className="mt-2 text-sm text-fg-secondary" aria-live="polite">
          {state.kind === "loading" ? (
            <Skeleton className="h-5 w-48" />
          ) : state.kind === "released" ? (
            <p>Your results are ready.</p>
          ) : state.kind === "pending" ? (
            <p>
              Results:{" "}
              {state.releaseAt
                ? formatIstDateTime(state.releaseAt)
                : state.mode === "manual"
                  ? "after your trainer reviews and releases them"
                  : state.mode === "after_window"
                    ? "after the test window closes"
                    : "after review"}
              .
            </p>
          ) : (
            <ErrorState error={state.error} />
          )}
        </div>
        <div className="mt-6 flex flex-wrap gap-3">
          {state.kind === "released" ? (
            <Link
              className="inline-flex h-10 items-center rounded-md bg-brand px-4 text-sm font-medium text-brand-on hover:bg-brand-hover"
              href={`/app/tests/${testSeg}/results/${encodeURIComponent(attemptId)}`}
            >
              View results
            </Link>
          ) : null}
          <Link className="inline-flex h-10 items-center rounded-md border border-line-control px-4 text-sm font-medium text-fg hover:bg-surface-hover" href="/app/tests">
            Back to tests
          </Link>
        </div>
      </Card>
    </div>
  );
}

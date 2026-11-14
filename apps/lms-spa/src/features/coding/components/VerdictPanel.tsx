"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/ui/cn";
import type { CaseResult, Submission, Verdict } from "../lib/types";

export const VERDICT_NAME: Record<string, string> = {
  AC: "Accepted",
  WA: "Wrong answer",
  TLE: "Time limit exceeded",
  MLE: "Memory limit exceeded",
  RE: "Runtime error",
  CE: "Compilation error",
  PARTIAL: "Partially accepted",
};

const VERDICT_ICON: Record<string, string> = { AC: "✓", WA: "✕", TLE: "⏱", MLE: "▣", RE: "⚠", CE: "⚠", PARTIAL: "◐" };

export function VerdictChip({ verdict }: { verdict: Verdict | null | undefined }) {
  const v = verdict ?? "—";
  const ok = v === "AC";
  return (
    <span
      title={VERDICT_NAME[v] ?? v}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium",
        ok ? "border-success-border bg-success-subtle text-success-fg" : "border-danger-border bg-danger-subtle text-danger-fg",
      )}
    >
      <span aria-hidden="true">{VERDICT_ICON[v] ?? "•"}</span>
      {VERDICT_NAME[v] ?? v}
    </span>
  );
}

function Elapsed({ since }: { since: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  const s = Math.max(0, Math.floor((now - since) / 1000));
  return <span className="font-mono tabular-nums">{`${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`}</span>;
}

function SampleCase({ c }: { c: CaseResult }) {
  return (
    <li className="rounded-lg border border-line p-3">
      <div className="flex items-center justify-between gap-2 text-sm">
        <span className="font-medium">{c.is_custom ? "Custom input" : `Sample ${c.ordinal}`}</span>
        <span className="flex items-center gap-2 text-xs text-fg-muted">
          <VerdictChip verdict={c.verdict} />
          {c.time_ms != null ? `${(c.time_ms / 1000).toFixed(2)} s` : null}
        </span>
      </div>
      <dl className="mt-2 grid gap-2 text-xs sm:grid-cols-3">
        {[
          ["Input", c.input],
          ["Expected", c.expected_output],
          ["Your output", c.stdout_excerpt],
        ].map(([label, val]) =>
          val != null ? (
            <div key={label}>
              <dt className="font-semibold text-fg-muted">{label}</dt>
              <dd>
                <pre className="mt-1 max-h-40 overflow-auto rounded bg-surface-sunken p-2 font-mono">{val}</pre>
              </dd>
            </div>
          ) : null,
        )}
      </dl>
    </li>
  );
}

/** Run = sample/custom I/O with diffs; Submit = hidden-case summary + verdict-only list (COD-002). */
export function VerdictPanel({ submission, startedAt }: { submission: Submission | null; startedAt: number | null }) {
  if (!submission) return <p className="text-sm text-fg-muted">Run your code on the samples, or submit it against all test cases.</p>;
  const s = submission;
  if (s.status === "queued" || s.status === "running") {
    return (
      <div role="status" className="text-sm text-fg-secondary">
        {s.status === "queued" ? "Queued — results will appear here" : s.mode === "run" ? "Running on the samples…" : "Running on all test cases…"}
        {startedAt ? (
          <>
            {" · "}
            <Elapsed since={startedAt} />
          </>
        ) : null}
        {s.notice === "judge_degraded" ? <p className="mt-2 text-warning-fg">Code results are delayed. Your submission is queued.</p> : null}
      </div>
    );
  }
  if (s.status === "failed") {
    return (
      <p role="alert" className="text-sm text-danger-fg">
        We couldn&apos;t judge this run. Please try again.
      </p>
    );
  }
  if (s.verdict === "CE") {
    return (
      <div role="status">
        <VerdictChip verdict="CE" />
        <pre className="mt-2 max-h-64 overflow-auto rounded bg-surface-sunken p-3 font-mono text-xs text-fg">{s.compile_output ?? ""}</pre>
      </div>
    );
  }
  const samples = (s.cases ?? []).filter((c) => c.is_sample || c.is_custom);
  const hidden = (s.cases ?? []).filter((c) => !c.is_sample && !c.is_custom);
  const hiddenPassed = hidden.filter((c) => c.verdict === "AC").length;
  const total = s.mode === "submit" ? (s.total_cases ?? hidden.length) : hidden.length;
  const passed = s.mode === "submit" ? (s.passed_cases ?? hiddenPassed) : hiddenPassed;
  return (
    <div role="status" className="space-y-3">
      {s.mode === "submit" ? (
        <div>
          <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
            <VerdictChip verdict={s.verdict} />
            <span>
              {passed} of {total} tests passed{s.score !== null && s.score !== undefined ? ` · Score ${s.score}/100` : ""}
            </span>
          </div>
          <div className="mt-2 h-2 rounded-full bg-line" aria-hidden="true">
            <div className="h-2 rounded-full bg-success-solid" style={{ width: `${total ? (passed / total) * 100 : 0}%` }} />
          </div>
        </div>
      ) : null}
      {samples.length ? <ul className="space-y-2">{samples.map((c) => <SampleCase key={`${c.is_custom ? "c" : "s"}${c.ordinal}`} c={c} />)}</ul> : null}
      {hidden.length ? (
        <div>
          <p className="text-xs text-fg-muted">Hidden tests: no input or output is shown.</p>
          <ul className="mt-1 grid gap-1 text-sm sm:grid-cols-2">
            {hidden
              .filter((c) => c.verdict !== "AC")
              .map((c) => (
                <li key={c.ordinal} className="flex items-center gap-2">
                  Case {c.ordinal}: <VerdictChip verdict={c.verdict} />
                </li>
              ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

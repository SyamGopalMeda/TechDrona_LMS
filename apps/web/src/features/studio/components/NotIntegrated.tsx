"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api/client";

/**
 * "Not integrated yet" notices (owner rule): while the platform runs the fake AI adapter
 * (`AI_PROVIDER=fake`, canned placeholder text) or the fake code judge (`JUDGE_PROVIDER=fake`,
 * code is never run), screens that use them must say so instead of presenting the output as real.
 * The api reports it in `GET me/enabled-apps` (`ai_simulated`) and `GET coding/languages`
 * (`judge.simulated`). On a failed read nothing is shown (the feature's own errors still surface).
 */
const cache: { ai?: Promise<boolean>; judge?: Promise<boolean> } = {};

/** Tests only: forget the cached flags. */
export function resetNotIntegratedCache(): void {
  cache.ai = undefined;
  cache.judge = undefined;
}

function readAi(): Promise<boolean> {
  cache.ai ??= api
    .get<{ ai_simulated?: boolean }>("me/enabled-apps")
    .then((r) => r.ai_simulated === true)
    .catch(() => {
      cache.ai = undefined;
      return false;
    });
  return cache.ai;
}

function readJudge(): Promise<boolean> {
  cache.judge ??= api
    .get<{ judge?: { simulated?: boolean } }>("coding/languages")
    .then((r) => r.judge?.simulated === true)
    .catch(() => {
      cache.judge = undefined;
      return false;
    });
  return cache.judge;
}

function useFlag(read: () => Promise<boolean>): boolean {
  const [on, setOn] = useState(false);
  useEffect(() => {
    let live = true;
    void read().then((v) => {
      if (live) setOn(v);
    });
    return () => {
      live = false;
    };
  }, [read]);
  return on;
}

/** True while AI features run on the placeholder (fake) adapter. */
export function useAiSimulated(): boolean {
  return useFlag(readAi);
}

/** True while code runs/submissions go to the fake judge (no code is executed). */
export function useJudgeSimulated(): boolean {
  return useFlag(readJudge);
}

const TEXT = {
  ai: "AI runs on a placeholder in this environment: it returns sample text, not real AI output. Check everything it suggests yourself.",
  judge:
    "The code runner is a placeholder in this environment: code is not executed, so verdicts, run times and outputs are not real.",
} as const;

export function NotIntegratedNotice({ kind, className }: { kind: keyof typeof TEXT; className?: string }) {
  return (
    <p
      role="note"
      className={`rounded-md border border-warning-border bg-warning-subtle p-3 text-sm text-warning-fg ${className ?? ""}`}
    >
      <span className="font-semibold">Not integrated yet. </span>
      {TEXT[kind]}
    </p>
  );
}

/** Renders the notice only while the AI adapter is the placeholder. */
export function AiNotIntegratedNotice({ className }: { className?: string }) {
  return useAiSimulated() ? <NotIntegratedNotice kind="ai" className={className} /> : null;
}

/** Renders the notice only while the code judge is the placeholder. */
export function JudgeNotIntegratedNotice({ className }: { className?: string }) {
  return useJudgeSimulated() ? <NotIntegratedNotice kind="judge" className={className} /> : null;
}

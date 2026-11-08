"use client";

import Link from "next/link";
import { useState } from "react";
import { Button, ErrorState } from "@/components/ui";
import { cn } from "@/lib/ui/cn";
import { seg } from "@/features/trainer/shared/use-api";
import { TYPE_LABEL } from "../lib/labels";
import { usePoll } from "../lib/use-poll";
import type { PresenterState } from "../lib/types";
import { isRevealed, useRunControl } from "./ControlRoom";
import { QrCode } from "./QrCode";
import { Loading, QuestionResults, useJoinUrl } from "./parts";
import { useEngageScope } from "../lib/scope";

const bigBtn = "min-h-touch px-5 text-base";

/** Full-screen presenter view of the polled state (exported for tests). */
export function PresenterView({
  state,
  onControl,
  busy,
}: {
  state: PresenterState;
  onControl: (action: "start" | "goto" | "reveal" | "hide" | "finalise", position?: number) => void;
  busy: string | null;
}) {
  const run = state.run;
  const joinUrl = useJoinUrl(run.join_path);
  const [view, setView] = useState(0);
  const [hideCorrect, setHideCorrect] = useState(false);
  const oneByOne = run.settings.pacing === "one_by_one";
  const n = run.question_count;
  const pos = oneByOne ? run.current_position : Math.min(view, Math.max(0, n - 1));
  const q = state.questions.find((x) => x.position === pos);
  const revealed = q ? (oneByOne ? isRevealed(run, pos) : run.revealed_positions.includes(pos)) : false;
  const finalised = run.status === "finalised";

  const go = (p: number) => {
    if (p < 0 || p >= n) return;
    if (oneByOne) onControl("goto", p);
    else setView(p);
  };

  if (run.status === "scheduled") {
    return (
      <div className="flex min-h-full flex-col items-center justify-center gap-6 p-6 text-center">
        <p className="text-lg font-semibold uppercase tracking-widest text-fg-muted">Join at</p>
        <h1 className="max-w-4xl break-words font-display text-4xl font-bold md:text-6xl">{state.activity.title}</h1>
        <div className="w-[min(70vh,80vw)] max-w-md">{joinUrl ? <QrCode value={joinUrl} label={`QR code to join: ${joinUrl}`} /> : null}</div>
        <p className="break-all font-mono text-xl md:text-2xl">{joinUrl}</p>
        <p className="text-2xl">
          Code <span className="font-mono text-4xl font-bold tracking-[0.3em] md:text-5xl">{run.join_code}</span>
        </p>
        <p className="text-2xl font-semibold" aria-live="polite">
          <span aria-hidden="true" className="text-success-fg">
            ●{" "}
          </span>
          {state.joined} joined
        </p>
        <Button size="lg" className={bigBtn} onClick={() => onControl("start")} loading={busy === "start"}>
          ▶ Start
        </Button>
      </div>
    );
  }

  return (
    <div className="flex min-h-full flex-col">
      <header className="flex flex-wrap items-center justify-between gap-4 border-b border-line px-6 py-4">
        <div className="min-w-0">
          <p className="text-sm uppercase tracking-widest text-fg-muted">{TYPE_LABEL[state.activity.activity_type]}</p>
          <h1 className="break-words font-display text-2xl font-bold md:text-3xl">{state.activity.title}</h1>
        </div>
        <div className="flex items-center gap-6 text-xl">
          <span className="font-semibold tabular-nums">
            Q{n ? pos + 1 : 0} / {n}
          </span>
          <span aria-live="polite">
            <span aria-hidden="true" className="text-success-fg">
              ●{" "}
            </span>
            {state.joined} joined
          </span>
          <div className="hidden w-20 sm:block">{joinUrl ? <QrCode value={joinUrl} label={`QR code to join: ${joinUrl}`} /> : null}</div>
          <span className="hidden font-mono text-base sm:inline">{run.join_code}</span>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto px-6 py-8">
        {q ? (
          <div className="mx-auto max-w-5xl space-y-6">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <h2 className="font-display text-3xl font-bold leading-snug md:text-5xl">
                {q.position + 1}. {q.prompt}
              </h2>
              <p className="text-2xl tabular-nums text-fg-secondary" aria-live="polite">
                {q.answered} answered
              </p>
            </div>
            {q.kind === "word" && !revealed ? (
              <p className="text-2xl text-fg-muted">Responses are coming in — reveal to show the word cloud.</p>
            ) : (
              <QuestionResults
                question={q}
                large
                showCorrect={revealed && !hideCorrect}
                texts={revealed ? q.texts : undefined}
                winner={revealed && !hideCorrect ? q.winner : null}
              />
            )}
          </div>
        ) : (
          <p className="text-center text-2xl text-fg-muted">No questions in this run.</p>
        )}
        {finalised ? <p className="mt-8 text-center text-2xl font-semibold">Final results</p> : null}
      </main>

      <footer className="flex flex-wrap items-center justify-center gap-3 border-t border-line px-6 py-4">
        <Button variant="secondary" className={bigBtn} onClick={() => go(pos - 1)} disabled={pos <= 0 || (oneByOne && finalised) || busy !== null} aria-label="Previous question">
          ‹ Prev
        </Button>
        <span className="text-lg tabular-nums">
          Q{n ? pos + 1 : 0} / {n}
        </span>
        <Button variant="secondary" className={bigBtn} onClick={() => go(pos + 1)} disabled={pos >= n - 1 || (oneByOne && finalised) || busy !== null} aria-label="Next question">
          Next ›
        </Button>
        <Button
          className={bigBtn}
          variant={revealed ? "secondary" : "primary"}
          onClick={() => onControl(revealed ? "hide" : "reveal", oneByOne ? undefined : pos)}
          loading={busy === "reveal" || busy === "hide"}
        >
          {revealed ? "Hide answers" : "Reveal answers"}
        </Button>
        {!oneByOne ? (
          <Button className={bigBtn} variant="secondary" onClick={() => onControl("reveal")} loading={busy === "reveal"}>
            Reveal all
          </Button>
        ) : null}
        <Button className={bigBtn} variant="ghost" aria-pressed={hideCorrect} onClick={() => setHideCorrect((v) => !v)}>
          {hideCorrect ? "Show correct" : "Hide correct"}
        </Button>
        {!finalised ? (
          <Button className={bigBtn} variant="secondary" onClick={() => onControl("finalise")} loading={busy === "finalise"}>
            ✓ Finalise
          </Button>
        ) : null}
      </footer>
    </div>
  );
}

/** TRN-021 big-screen presenter for a run. */
export function Presenter({ runId }: { runId: string }) {
  const { base } = useEngageScope();
  const poll = usePoll<PresenterState>(`engage/runs/${seg(runId)}/presenter`, { done: (d) => d.run.status === "finalised" });
  const { busy, control } = useRunControl(() => poll.refresh());
  const state = poll.data;
  return (
    <div className="fixed inset-0 z-overlay overflow-y-auto bg-surface-canvas text-fg">
      <Link
        href={state ? `${base}/${seg(state.run.activity_id)}` : base}
        aria-label="Close presenter"
        className={cn("absolute right-4 top-4 z-sticky rounded-md px-3 py-1 text-2xl text-fg-secondary hover:bg-surface-hover focus-visible:outline-none focus-visible:shadow-focus")}
      >
        ✕
      </Link>
      {state ? (
        <PresenterView state={state} busy={busy} onControl={(a, p) => void control(state.run.id, a, p)} />
      ) : poll.error ? (
        <div className="p-8">
          <ErrorState error={poll.error} onRetry={() => void poll.refresh()} />
        </div>
      ) : (
        <div className="p-8">
          <Loading label="Loading presenter" />
        </div>
      )}
    </div>
  );
}

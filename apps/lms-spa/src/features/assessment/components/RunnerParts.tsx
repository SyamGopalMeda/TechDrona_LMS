"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { cn } from "@/lib/ui/cn";
import type { SaveStatus } from "../lib/autosave-queue";
import { PALETTE_LABEL, paletteAriaLabel, type PaletteCounts, type PaletteState } from "../lib/palette";
import { crossedMilestone, formatCountdown, spokenDuration, timerTone, type ServerClock } from "../lib/server-clock";

/* ------------------------------------------------------------------ Timer */

export interface TimerProps {
  clock: ServerClock;
  deadlineAt: string | null;
  onExpire: () => void;
  suppressWarnings?: boolean;
  /** Tick interval (ms); tests may shorten it. */
  tickMs?: number;
}

/**
 * Countdown derived only from the server deadline + server clock sample (§5.11). Announces
 * 10/5/1 minute milestones politely; never flashes; "Hide timer" shows a compact pill.
 */
export function Timer({ clock, deadlineAt, onExpire, suppressWarnings = false, tickMs = 500 }: TimerProps) {
  const [remaining, setRemaining] = useState<number | null>(() => clock.remainingMs(deadlineAt));
  const [hidden, setHidden] = useState(false);
  const [announce, setAnnounce] = useState("");
  const prev = useRef<number | null>(remaining);
  const expired = useRef(false);
  const expireRef = useRef(onExpire);
  expireRef.current = onExpire;

  useEffect(() => {
    expired.current = false;
    const tick = () => {
      const r = clock.remainingMs(deadlineAt);
      setRemaining(r);
      const m = crossedMilestone(prev.current, r);
      if (m && !suppressWarnings) setAnnounce(m === 1 ? "1 minute left." : `${m} minutes left.`);
      prev.current = r;
      if (r === 0 && !expired.current) {
        expired.current = true;
        expireRef.current();
      }
    };
    tick();
    const id = setInterval(tick, tickMs);
    return () => clearInterval(id);
  }, [clock, deadlineAt, suppressWarnings, tickMs]);

  const tone = suppressWarnings ? "default" : timerTone(remaining);
  const text = remaining === null ? "--:--" : formatCountdown(remaining);

  return (
    <div className="flex items-center gap-2">
      {hidden ? (
        <span className="rounded-full bg-surface-sunken px-3 py-1 text-xs font-medium text-fg-secondary">Time is running</span>
      ) : (
        <span
          className={cn(
            "inline-flex items-center gap-1 font-mono text-lg font-bold tabular-nums",
            tone === "default" && "text-timer",
            tone === "warn" && "text-timer-warn",
            tone === "critical" && "text-timer-critical",
          )}
          aria-label={remaining === null ? "Time left: syncing" : `Time left: ${spokenDuration(remaining)}`}
          role="timer"
        >
          {tone !== "default" ? <span aria-hidden="true">⏱</span> : null}
          {text}
        </span>
      )}
      <button
        type="button"
        onClick={() => setHidden((h) => !h)}
        className="rounded px-1 text-xs text-fg-muted underline focus-visible:shadow-focus focus-visible:outline-none"
      >
        {hidden ? "Show timer" : "Hide timer"}
      </button>
      <span className="sr-only" aria-live="polite">
        {announce}
      </span>
    </div>
  );
}

/* ------------------------------------------------------------------ Autosave indicator */

export function autosaveText(status: SaveStatus, lastSavedAt: number | null, now: number): string {
  switch (status) {
    case "saving":
      return "Saving…";
    case "offline":
      return "Offline — answers stored on this device";
    case "reconnecting":
      return "Reconnecting…";
    case "synced":
      return "All answers synced";
    case "retrying":
      return "Couldn't save — retrying. Your answer is stored on this device.";
    case "closed":
      return "Test closed";
    case "bound_elsewhere":
      return "Open on another device";
    case "saved":
    case "idle":
    default:
      if (lastSavedAt === null) return "No changes yet";
      return `Saved ${Math.max(0, Math.round((now - lastSavedAt) / 1000))} s ago`;
  }
}

const dotTone: Record<SaveStatus, string> = {
  idle: "bg-fg-muted",
  saving: "bg-fg-muted",
  saved: "bg-success-solid",
  synced: "bg-success-solid",
  retrying: "bg-warning-solid",
  offline: "bg-warning-solid",
  reconnecting: "bg-warning-solid",
  closed: "bg-fg-muted",
  bound_elsewhere: "bg-warning-solid",
};

export function AutosaveIndicator({ status, lastSavedAt }: { status: SaveStatus; lastSavedAt: number | null }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  // Live region text changes only on status changes, not every second (avoids chatter).
  const text = autosaveText(status, lastSavedAt, now);
  const announced = status === "saved" || status === "idle" ? (lastSavedAt ? "Saved" : "") : text;
  return (
    <span className="inline-flex items-center gap-2 text-sm text-fg-secondary">
      <span aria-hidden="true" className={cn("h-2 w-2 rounded-full", dotTone[status])} />
      <span aria-hidden="true">{text}</span>
      <span role="status" className="sr-only">
        {announced}
      </span>
    </span>
  );
}

/* ------------------------------------------------------------------ Palette */

const tileClass: Record<PaletteState, string> = {
  not_visited: "rounded-sm border border-qstate-not-visited-border bg-qstate-not-visited text-qstate-not-visited-fg",
  not_answered: "rounded-sm rounded-b-none border border-b-4 border-qstate-not-answered-border bg-qstate-not-answered text-qstate-not-answered-fg",
  answered: "rounded-md bg-qstate-answered text-qstate-answered-fg",
  marked: "rounded-full bg-qstate-marked text-qstate-marked-fg",
  answered_marked: "rounded-full bg-qstate-marked text-qstate-marked-fg",
};

export interface PaletteProps {
  states: PaletteState[];
  current: number;
  onSelect: (index: number) => void;
  counts: PaletteCounts;
}

const COLS = 5;

/** Question palette (§3.4): shape + glyph + colour, keyboard grid navigation, legend with counts. */
export function QuestionPalette({ states, current, onSelect, counts }: PaletteProps) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    const map: Record<string, number> = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: COLS, ArrowUp: -COLS };
    let next: number | null = null;
    if (e.key in map) next = i + map[e.key]!;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = states.length - 1;
    if (next !== null && next >= 0 && next < states.length) {
      e.preventDefault();
      refs.current[next]?.focus();
    }
  };
  return (
    <div>
      <ul aria-label="Legend" className="mb-3 grid grid-cols-1 gap-1 text-xs text-fg-secondary sm:grid-cols-2">
        {(Object.keys(PALETTE_LABEL) as PaletteState[]).map((s) => (
          <li key={s} className="flex items-center gap-2">
            <span aria-hidden="true" className={cn("inline-flex h-5 w-5 shrink-0 items-center justify-center text-xs leading-none", tileClass[s])}>
              {s === "answered" || s === "answered_marked" ? "✓" : s === "not_answered" ? "–" : ""}
            </span>
            {PALETTE_LABEL[s]} <span className="tabular-nums">{counts[s]}</span>
          </li>
        ))}
      </ul>
      <div role="group" aria-label="Questions" className="grid grid-cols-5 gap-2">
        {states.map((s, i) => (
          <button
            key={i}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            aria-label={paletteAriaLabel(i + 1, s, i === current)}
            aria-current={i === current ? "step" : undefined}
            onClick={() => onSelect(i)}
            onKeyDown={(e) => onKey(e, i)}
            className={cn(
              "relative flex h-target min-w-target items-center justify-center text-sm font-semibold tabular-nums focus-visible:shadow-focus focus-visible:outline-none",
              tileClass[s],
              i === current && "ring-2 ring-qstate-current-ring ring-offset-2",
            )}
          >
            {i + 1}
            {s === "answered" ? <span aria-hidden="true" className="absolute right-0.5 top-0 text-xs leading-none">✓</span> : null}
            {s === "not_answered" ? <span aria-hidden="true" className="absolute bottom-0 text-xs leading-none">–</span> : null}
            {s === "answered_marked" ? (
              <span aria-hidden="true" className="absolute -bottom-1 -right-1 flex h-5 w-5 items-center justify-center rounded-full bg-qstate-answered text-xs leading-none text-qstate-answered-fg">
                ✓
              </span>
            ) : null}
          </button>
        ))}
      </div>
    </div>
  );
}

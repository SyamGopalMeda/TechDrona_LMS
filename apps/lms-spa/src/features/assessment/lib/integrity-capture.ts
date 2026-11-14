import type { ExamProtocol, IntegrityEventType, RecordableEvent } from "./types";

/**
 * Client-side integrity evidence capture for the exam protocol. The browser only *reports*
 * events; the server stores, counts and decides (flag for review). Nothing here blocks the
 * candidate or changes a score.
 */

/** Events accepted from tests without the exam protocol (server: LEGACY_CLIENT_EVENTS). */
export const LEGACY_EVENTS: ReadonlySet<IntegrityEventType> = new Set<IntegrityEventType>([
  "focus_lost",
  "focus_gained",
  "fullscreen_exit",
  "paste",
  "disconnect",
  "reconnect",
]);
const CONNECTIVITY: ReadonlySet<IntegrityEventType> = new Set<IntegrityEventType>(["focus_gained", "disconnect", "reconnect"]);

/** Which event types this attempt reports. */
export function eventFilter(protocol: ExamProtocol | null | undefined): (type: IntegrityEventType) => boolean {
  if (!protocol?.exam_mode) return (t) => LEGACY_EVENTS.has(t);
  const on = new Set<IntegrityEventType>(protocol.record_events);
  return (t) => on.has(t) || CONNECTIVITY.has(t);
}

export interface ThrottleOptions {
  /** Minimum gap between two events of the same type (a resize drag or key-repeat is one event). */
  minGapMs?: number;
  /** Hard cap of reported events per page session (the server caps per attempt too). */
  maxTotal?: number;
}

/** Rate limiter: returns true when an event of `type` at `now` should be reported. */
export function createEventThrottle({ minGapMs = 1_000, maxTotal = 300 }: ThrottleOptions = {}) {
  const last = new Map<IntegrityEventType, number>();
  let total = 0;
  return (type: IntegrityEventType, now: number): boolean => {
    if (total >= maxTotal) return false;
    const prev = last.get(type);
    if (prev !== undefined && now - prev < minGapMs) return false;
    last.set(type, now);
    total += 1;
    return true;
  };
}

export function isRecordable(type: IntegrityEventType): type is RecordableEvent {
  return !CONNECTIVITY.has(type) && type !== "focus_gained";
}

/** Banner copy (Tech Drona wording). */
export function integrityWarning(total: number, flagged: boolean): string {
  const events = `${total} event${total === 1 ? "" : "s"}`;
  return flagged
    ? `Integrity warning — activity outside the exam has been recorded (${events}). This attempt will be flagged for review by your evaluator.`
    : `Integrity notice — activity outside the exam is being recorded (${events}). Stay on this page until you submit.`;
}

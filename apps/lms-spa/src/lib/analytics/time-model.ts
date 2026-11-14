/**
 * Client side of measurement model tm-1.0 (analytics-event-schema §3.1–§3.2).
 *
 *   visible       = document.visibilityState === "visible"
 *   focused       = document.hasFocus()
 *   input_recent  = (now − last_input_at) ≤ T_idle(surface)
 *   media_playing = player playing (and not muted-and-hidden)
 *
 *   ACTIVE ⇔ visible ∧ ((focused ∧ input_recent) ∨ media_playing)
 *   IDLE   ⇔ visible ∧ ¬ACTIVE
 *   HIDDEN ⇔ ¬visible
 *
 * All durations use a monotonic clock (performance.now()), never the wall clock.
 * The meter is pure: callers feed it state changes with timestamps.
 */

export type Surface =
  | "lesson_text"
  | "lesson_video"
  | "practice"
  | "test"
  | "coding"
  | "dashboard"
  | "catalog"
  | "account"
  | "other";

export type EngagementState = "ACTIVE" | "IDLE" | "HIDDEN";

export interface TimeModelParams {
  measurementVersion: "tm-1.0";
  /** H: heartbeat sample interval while ACTIVE */
  heartbeatMs: number;
  /** F: flush interval */
  flushMs: number;
  /** K: keepalive interval while visible but IDLE */
  keepaliveMs: number;
  /** T_idle generic */
  idleMs: number;
  /** T_idle per surface */
  idleMsBySurface: Partial<Record<Surface, number>>;
}

/** tm-1.0 defaults. Replaced at boot by GET /api/v1/analytics/config (§5.4: never hard-code). */
export const TM_1_0_DEFAULTS: TimeModelParams = {
  measurementVersion: "tm-1.0",
  heartbeatMs: 15_000,
  flushMs: 30_000,
  keepaliveMs: 300_000,
  idleMs: 90_000,
  idleMsBySurface: { lesson_text: 180_000, practice: 240_000, coding: 180_000, test: 300_000, lesson_video: 90_000 },
};

/** Schema cap on a single heartbeat's active_ms (§2.1.1). */
export const MAX_ACTIVE_MS_PER_SAMPLE = 20_000;

export function idleThresholdMs(params: TimeModelParams, surface: Surface): number {
  return params.idleMsBySurface[surface] ?? params.idleMs;
}

export interface MeterSnapshot {
  visible: boolean;
  focused: boolean;
  inputRecent: boolean;
  mediaPlaying: boolean;
}

export class EngagementMeter {
  private visible: boolean;
  private focused: boolean;
  private mediaPlaying = false;
  private lastInputAt: number;
  private lastAccrualAt: number;
  private activeMs = 0;
  private inputEvents = 0;

  constructor(
    private readonly idleMs: number,
    now: number,
    initial: { visible: boolean; focused: boolean },
  ) {
    this.visible = initial.visible;
    this.focused = initial.focused;
    // Opening/focusing a page counts as an interaction; otherwise a freshly opened page is IDLE.
    this.lastInputAt = initial.visible && initial.focused ? now : Number.NEGATIVE_INFINITY;
    this.lastAccrualAt = now;
  }

  /** Credit ACTIVE time between the last accrual and `now` (flags are constant in between). */
  private accrue(now: number): void {
    const from = this.lastAccrualAt;
    if (now <= from) return;
    this.lastAccrualAt = now;
    if (!this.visible) return;
    if (this.mediaPlaying) {
      this.activeMs += now - from;
      return;
    }
    if (!this.focused) return;
    // input_recent stays true until lastInputAt + T_idle (the disclosed timeout heuristic).
    const activeUntil = Math.min(now, this.lastInputAt + this.idleMs);
    if (activeUntil > from) this.activeMs += activeUntil - from;
  }

  setVisible(visible: boolean, now: number): void {
    this.accrue(now);
    this.visible = visible;
  }

  setFocused(focused: boolean, now: number): void {
    this.accrue(now);
    this.focused = focused;
    if (focused) this.lastInputAt = now;
  }

  setMediaPlaying(playing: boolean, now: number): void {
    this.accrue(now);
    this.mediaPlaying = playing;
  }

  recordInput(now: number): void {
    this.accrue(now);
    this.lastInputAt = now;
    this.inputEvents += 1;
  }

  snapshot(now: number): MeterSnapshot {
    return {
      visible: this.visible,
      focused: this.focused,
      inputRecent: now - this.lastInputAt <= this.idleMs,
      mediaPlaying: this.mediaPlaying,
    };
  }

  state(now: number): EngagementState {
    const s = this.snapshot(now);
    if (!s.visible) return "HIDDEN";
    return (s.focused && s.inputRecent) || s.mediaPlaying ? "ACTIVE" : "IDLE";
  }

  /** Active ms and input count since the previous take; resets both counters. */
  take(now: number): { activeMs: number; inputEvents: number } {
    this.accrue(now);
    const out = {
      activeMs: Math.min(Math.round(this.activeMs), MAX_ACTIVE_MS_PER_SAMPLE),
      inputEvents: Math.min(this.inputEvents, 1000),
    };
    this.activeMs = 0;
    this.inputEvents = 0;
    return out;
  }
}

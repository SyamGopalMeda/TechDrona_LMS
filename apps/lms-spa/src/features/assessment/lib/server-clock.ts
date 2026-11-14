/**
 * Server-authoritative timer support (api-specification §15.1, design-system §5.11).
 *
 * The client never trusts its wall clock. Each attempt response carries `server_now`; we
 * pair it with a *monotonic* local reading (performance.now) taken at the midpoint of the
 * request (NTP-style RTT/2 correction). The displayed remaining time is
 *   deadline_at − (sample.serverMs + (monotonicNow − sample.monoMs)).
 * A changed system clock therefore cannot add or remove time, and the server's deadline is
 * the only thing that ends the test.
 */

export interface ClockSample {
  /** server epoch ms at the local monotonic instant `monoMs` */
  serverMs: number;
  monoMs: number;
  /** round-trip time of the request that produced this sample */
  rttMs: number;
}

export type MonotonicNow = () => number;

const defaultMono: MonotonicNow = () =>
  typeof performance !== "undefined" && typeof performance.now === "function" ? performance.now() : Date.now();

/** Samples older than this are replaced even if their RTT was better (drift between devices). */
const SAMPLE_MAX_AGE_MS = 5 * 60_000;
/** A new sample replaces the current one when its RTT is no more than this much worse. */
const RTT_TOLERANCE_MS = 250;

export function sampleFrom(serverNowIso: string, sentMono: number, receivedMono: number): ClockSample | null {
  const serverMs = Date.parse(serverNowIso);
  if (!Number.isFinite(serverMs) || receivedMono < sentMono) return null;
  const rttMs = receivedMono - sentMono;
  return { serverMs, monoMs: sentMono + rttMs / 2, rttMs };
}

export class ServerClock {
  private sample: ClockSample | null = null;

  constructor(private readonly mono: MonotonicNow = defaultMono) {}

  /** Monotonic reading to pass back into `observe` (call right before sending a request). */
  mark(): number {
    return this.mono();
  }

  /**
   * Feed a `server_now` value. `sentMono` is the `mark()` taken before the request; when
   * omitted (e.g. data delivered without a timed request) RTT is assumed 0.
   */
  observe(serverNowIso: string | null | undefined, sentMono?: number): void {
    if (!serverNowIso) return;
    const received = this.mono();
    const next = sampleFrom(serverNowIso, sentMono ?? received, received);
    if (!next) return;
    const cur = this.sample;
    if (!cur || next.rttMs <= cur.rttMs + RTT_TOLERANCE_MS || received - cur.monoMs > SAMPLE_MAX_AGE_MS) {
      this.sample = next;
    }
  }

  get synced(): boolean {
    return this.sample !== null;
  }

  /** Best estimate of server epoch ms now, or null before the first sample. */
  serverNow(): number | null {
    if (!this.sample) return null;
    return this.sample.serverMs + (this.mono() - this.sample.monoMs);
  }

  /** Remaining ms until `deadlineIso` on the server clock (never negative); null if unknown. */
  remainingMs(deadlineIso: string | null | undefined): number | null {
    if (!deadlineIso) return null;
    const now = this.serverNow();
    const deadline = Date.parse(deadlineIso);
    if (now === null || !Number.isFinite(deadline)) return null;
    return Math.max(0, deadline - now);
  }

  /** Offset (server − local wall clock) for diagnostics only; display never uses Date.now(). */
  offsetFromWallClock(wallNow: number = Date.now()): number | null {
    const now = this.serverNow();
    return now === null ? null : now - wallNow;
  }
}

/** Spoken form for screen readers, e.g. "38 minutes 40 seconds". */
export function spokenDuration(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const parts: string[] = [];
  if (h) parts.push(`${h} hour${h === 1 ? "" : "s"}`);
  if (m) parts.push(`${m} minute${m === 1 ? "" : "s"}`);
  if (s || parts.length === 0) parts.push(`${s} second${s === 1 ? "" : "s"}`);
  return parts.join(" ");
}

export type TimerTone = "default" | "warn" | "critical";

export function timerTone(remainingMs: number | null): TimerTone {
  if (remainingMs === null) return "default";
  if (remainingMs <= 60_000) return "critical";
  if (remainingMs <= 10 * 60_000) return "warn";
  return "default";
}

export const MILESTONES_MIN = [10, 5, 1] as const;

/**
 * Milestone (10/5/1 min) newly crossed between two readings, for the polite live region.
 * Returns the smallest milestone crossed so a jump (e.g. resume at 4 min) announces once.
 */
export function crossedMilestone(prevMs: number | null, nextMs: number | null): (typeof MILESTONES_MIN)[number] | null {
  if (prevMs === null || nextMs === null || nextMs >= prevMs) return null;
  let hit: (typeof MILESTONES_MIN)[number] | null = null;
  for (const m of MILESTONES_MIN) {
    const t = m * 60_000;
    if (prevMs > t && nextMs <= t && nextMs > 0) hit = m;
  }
  return hit;
}

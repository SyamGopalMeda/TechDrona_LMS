import { isApiError } from "@/lib/api/errors";
import type { ProblemDetails } from "@/lib/api/problem";
import type { PendingStore, PersistedAttempt } from "./local-store";
import type { AutosaveItem, AutosaveRequest, AutosaveResponse, IntegrityEvent, IntegrityEventType, QuestionResponse } from "./types";

/**
 * Autosave queue for the timed-test runner (ATT-06; design-system §5.11, §9.7).
 *
 * - Every change gets a strictly increasing `client_seq` (server keeps the newest per
 *   question: "newer client_seq wins", so replays and out-of-order deliveries are safe).
 * - Only the latest pending change per question is kept; integrity events ride along.
 * - Flush: `debounceMs` after a change, and never later than `maxIntervalMs` (≤ 10 s) after
 *   the oldest unsaved change. One request in flight at a time; ≤ `maxItems` per request.
 * - The pending set is mirrored to a device-local store before any network call, so a
 *   crash or refresh can resume (TST-004).
 * - Failures: network → "offline" (kept, retried on reconnect and with backoff);
 *   429/5xx → "retrying" with exponential backoff; 409 attempt_closed / attempt_bound_elsewhere
 *   / section_locked are terminal or structural and are reported to the runner.
 */

export type SaveStatus = "idle" | "saving" | "saved" | "retrying" | "offline" | "reconnecting" | "synced" | "closed" | "bound_elsewhere";

export interface QueueSnapshot {
  status: SaveStatus;
  pendingCount: number;
  lastSavedAt: number | null;
  lastAckedSeq: number;
}

export type Sender = (req: AutosaveRequest) => Promise<AutosaveResponse>;

export interface AutosaveQueueOptions {
  attemptId: string;
  send: Sender;
  store?: PendingStore;
  debounceMs?: number;
  maxIntervalMs?: number;
  maxItems?: number;
  initialSeq?: number;
  initialItems?: AutosaveItem[];
  initialEvents?: IntegrityEvent[];
  initialVisited?: string[];
  currentSectionId?: () => string | null | undefined;
  now?: () => number;
  /** Backoff schedule in ms for retryable failures (last value repeats). */
  backoffMs?: number[];
  onChange?: (s: QueueSnapshot) => void;
  onAck?: (r: AutosaveResponse) => void;
  onClosed?: (problem: ProblemDetails | null) => void;
  onBoundElsewhere?: (problem: ProblemDetails | null) => void;
  onSectionLocked?: (sectionId: string | null) => void;
}

export const MAX_INTERVAL_CAP_MS = 10_000;
const DEFAULT_BACKOFF = [1_000, 2_000, 4_000, 8_000, 15_000];

export class AutosaveQueue {
  private seq: number;
  private readonly items = new Map<string, AutosaveItem>();
  private events: IntegrityEvent[] = [];
  private visited: Set<string>;
  private inFlight: Promise<void> | null = null;
  private again = false;
  private debounceTimer: ReturnType<typeof setTimeout> | null = null;
  private maxTimer: ReturnType<typeof setTimeout> | null = null;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private failures = 0;
  private stopped = false;
  private snap: QueueSnapshot = { status: "idle", pendingCount: 0, lastSavedAt: null, lastAckedSeq: 0 };
  private readonly debounceMs: number;
  private readonly maxIntervalMs: number;
  private readonly maxItems: number;
  private readonly now: () => number;
  private readonly backoff: number[];

  constructor(private readonly opts: AutosaveQueueOptions) {
    this.seq = Math.max(1, opts.initialSeq ?? 1);
    this.maxIntervalMs = Math.min(MAX_INTERVAL_CAP_MS, Math.max(1_000, opts.maxIntervalMs ?? MAX_INTERVAL_CAP_MS));
    this.debounceMs = Math.min(this.maxIntervalMs, Math.max(250, opts.debounceMs ?? 2_000));
    this.maxItems = Math.max(1, Math.min(50, opts.maxItems ?? 50));
    this.now = opts.now ?? Date.now;
    this.backoff = opts.backoffMs?.length ? opts.backoffMs : DEFAULT_BACKOFF;
    for (const it of opts.initialItems ?? []) this.items.set(it.question_version_id, it);
    this.events = [...(opts.initialEvents ?? [])];
    this.visited = new Set(opts.initialVisited ?? []);
    for (const it of this.items.values()) this.seq = Math.max(this.seq, it.client_seq + 1);
    for (const e of this.events) this.seq = Math.max(this.seq, e.client_seq + 1);
    this.snap.pendingCount = this.pendingCount;
  }

  /* ------------------------------------------------------------------ inputs */

  get nextSeq(): number {
    return this.seq;
  }

  get pendingCount(): number {
    return this.items.size;
  }

  get snapshot(): QueueSnapshot {
    return this.snap;
  }

  pendingItems(): AutosaveItem[] {
    return [...this.items.values()].sort((a, b) => a.client_seq - b.client_seq);
  }

  visitedIds(): string[] {
    return [...this.visited];
  }

  markVisited(questionVersionId: string): void {
    if (this.visited.has(questionVersionId)) return;
    this.visited.add(questionVersionId);
    this.persist();
  }

  /** Record a change; returns the assigned client_seq. */
  setAnswer(questionVersionId: string, response: QuestionResponse | null, flagged: boolean, timeSpentMs: number): number {
    const client_seq = this.seq++;
    this.items.set(questionVersionId, { question_version_id: questionVersionId, response, flagged, time_spent_ms: Math.max(0, Math.round(timeSpentMs)), client_seq });
    this.visited.add(questionVersionId);
    this.persist();
    this.emit({ pendingCount: this.pendingCount });
    this.schedule();
    return client_seq;
  }

  /** Advisory integrity event (§15.1); never blocks the student. */
  addEvent(type: IntegrityEventType): void {
    this.events.push({ type, client_at: new Date(this.now()).toISOString(), client_seq: this.seq++ });
    if (this.events.length > 200) this.events = this.events.slice(-200);
    this.persist();
    this.schedule();
  }

  /** Drop pending items (e.g. for a section the server reports as locked). */
  drop(questionVersionIds: Iterable<string>): void {
    for (const id of questionVersionIds) this.items.delete(id);
    this.persist();
    this.emit({ pendingCount: this.pendingCount });
  }

  /* ------------------------------------------------------------------ connectivity */

  /** Browser went offline: keep everything locally, stop retry storms. */
  setOffline(): void {
    if (this.stopped) return;
    this.clearRetry();
    this.emit({ status: "offline" });
  }

  /** Browser is back online: flush immediately. */
  setOnline(): void {
    if (this.stopped) return;
    this.failures = 0;
    this.clearRetry();
    if (this.items.size || this.events.length) {
      this.emit({ status: "reconnecting" });
      void this.flush();
    } else if (this.snap.status === "offline") {
      this.emit({ status: "synced" });
    }
  }

  stop(): void {
    this.stopped = true;
    this.clearTimers();
  }

  /** Forget local state (after a successful submit / terminal status). */
  clearLocal(): void {
    this.opts.store?.clear(this.opts.attemptId);
  }

  /* ------------------------------------------------------------------ flushing */

  private schedule(): void {
    if (this.stopped) return;
    if (this.debounceTimer) clearTimeout(this.debounceTimer);
    this.debounceTimer = setTimeout(() => {
      this.debounceTimer = null;
      void this.flush();
    }, this.debounceMs);
    if (!this.maxTimer) {
      this.maxTimer = setTimeout(() => {
        this.maxTimer = null;
        void this.flush();
      }, this.maxIntervalMs);
    }
  }

  /** Send pending items now. Resolves when the queue is drained or a failure parks it. */
  flush(): Promise<void> {
    if (this.stopped) return Promise.resolve();
    if (this.inFlight) {
      this.again = true;
      return this.inFlight;
    }
    if (this.debounceTimer) clearTimeout(this.debounceTimer);
    if (this.maxTimer) clearTimeout(this.maxTimer);
    this.debounceTimer = this.maxTimer = null;
    if (this.items.size === 0 && this.events.length === 0) return Promise.resolve();
    this.inFlight = this.run().finally(() => {
      this.inFlight = null;
    });
    return this.inFlight;
  }

  private async run(): Promise<void> {
    for (;;) {
      this.again = false;
      const batch = this.pendingItems().slice(0, this.maxItems);
      const events = this.events.slice(0, 50);
      if (batch.length === 0 && events.length === 0) return;
      const wasReconnecting = this.snap.status === "reconnecting" || this.snap.status === "offline";
      if (!wasReconnecting) this.emit({ status: "saving" });
      try {
        const res = await this.opts.send({ items: batch, events, current_section_id: this.opts.currentSectionId?.() ?? null });
        if (this.stopped) return;
        this.failures = 0;
        this.ack(res.acked_seq ?? 0, batch, events);
        this.opts.onAck?.(res);
        const drained = this.items.size === 0 && this.events.length === 0;
        this.emit({
          status: drained ? (wasReconnecting ? "synced" : "saved") : this.snap.status,
          lastSavedAt: this.now(),
          lastAckedSeq: Math.max(this.snap.lastAckedSeq, res.acked_seq ?? 0),
          pendingCount: this.pendingCount,
        });
        if (res.status && res.status !== "in_progress") {
          this.stop();
          this.emit({ status: "closed" });
          this.opts.onClosed?.(null);
          return;
        }
        if (!drained || this.again) continue;
        return;
      } catch (err) {
        if (this.stopped) return;
        this.handleFailure(err);
        return;
      }
    }
  }

  private ack(ackedSeq: number, sent: AutosaveItem[], sentEvents: IntegrityEvent[]): void {
    for (const it of sent) {
      const cur = this.items.get(it.question_version_id);
      // Only remove if unchanged since sending (a newer change has a higher seq and stays pending).
      if (cur && cur.client_seq === it.client_seq && it.client_seq <= ackedSeq) this.items.delete(it.question_version_id);
    }
    const sentSeqs = new Set(sentEvents.map((e) => e.client_seq));
    this.events = this.events.filter((e) => !(sentSeqs.has(e.client_seq) && e.client_seq <= ackedSeq));
    this.persist();
  }

  private handleFailure(err: unknown): void {
    const problem = isApiError(err) ? err.problem : null;
    const code = isApiError(err) ? err.code : "network_error";
    const status = isApiError(err) ? err.status : 0;

    if (code === "attempt_closed") {
      this.stop();
      this.emit({ status: "closed" });
      this.opts.onClosed?.(problem);
      return;
    }
    if (code === "attempt_bound_elsewhere") {
      this.clearTimers();
      this.emit({ status: "bound_elsewhere" });
      this.opts.onBoundElsewhere?.(problem);
      return;
    }
    if (code === "section_locked") {
      const sectionId = typeof problem?.section_id === "string" ? problem.section_id : null;
      this.opts.onSectionLocked?.(sectionId);
      // The runner drops the locked section's items; try the rest shortly.
      this.retryIn(this.backoff[0]!);
      return;
    }
    if (status === 0) {
      this.emit({ status: "offline" });
      this.retryIn(this.nextBackoff());
      return;
    }
    if (status === 429) {
      // BE-09: attempt routes are rate limited; wait at least what the server asks for.
      const wait = isApiError(err) && err.retryAfter ? err.retryAfter * 1000 : 0;
      this.emit({ status: "retrying" });
      this.retryIn(Math.max(wait, this.nextBackoff()));
      return;
    }
    if (status >= 500 || code === "idempotency_in_progress") {
      this.emit({ status: "retrying" });
      this.retryIn(this.nextBackoff());
      return;
    }
    // Other 4xx (e.g. validation of one item): keep the answers locally, retry slowly so a
    // transient server-side issue cannot silently drop work.
    this.emit({ status: "retrying" });
    this.retryIn(this.backoff[this.backoff.length - 1]!);
  }

  private nextBackoff(): number {
    const ms = this.backoff[Math.min(this.failures, this.backoff.length - 1)]!;
    this.failures += 1;
    return ms;
  }

  private retryIn(ms: number): void {
    this.clearRetry();
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      void this.flush();
    }, ms);
  }

  private clearRetry(): void {
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retryTimer = null;
  }

  private clearTimers(): void {
    if (this.debounceTimer) clearTimeout(this.debounceTimer);
    if (this.maxTimer) clearTimeout(this.maxTimer);
    this.debounceTimer = this.maxTimer = null;
    this.clearRetry();
  }

  /** Mirror the pending set to the device-local store. */
  persist(): void {
    const data: PersistedAttempt = {
      v: 1,
      attemptId: this.opts.attemptId,
      nextSeq: this.seq,
      items: this.pendingItems(),
      events: this.events,
      visited: [...this.visited],
      updatedAt: this.now(),
    };
    this.opts.store?.save(data);
  }

  private emit(patch: Partial<QueueSnapshot>): void {
    this.snap = { ...this.snap, ...patch };
    this.opts.onChange?.(this.snap);
  }
}

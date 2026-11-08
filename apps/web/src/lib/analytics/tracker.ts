import { uuid4, uuid7 as defaultUuid7 } from "@/lib/ids/uuid7";
import {
  assertRouteTemplate,
  cleanEntity,
  MAX_BATCH_BYTES,
  MAX_EVENTS_PER_BATCH,
  rfc3339WithOffset,
  type AnalyticsBatch,
  type AnalyticsEvent,
  type EntityRef,
} from "./envelope";
import { EngagementMeter, idleThresholdMs, TM_1_0_DEFAULTS, type EngagementState, type Surface, type TimeModelParams } from "./time-model";
import type { Transport } from "./transport";
import { VideoSession, type VideoEvents } from "./video";

/**
 * Page-instance activity tracker (analytics-event-schema §2.1, §3.2, §3.6, §5.4).
 *
 * - page.view opens a page instance (seq 0); page.hide closes it.
 * - ACTIVE: page.heartbeat{kind: engaged} every H (15 s) with client-measured active_ms.
 * - ACTIVE → IDLE: page.idle_change{idle:true} + immediate flush; then keepalives every K.
 * - visibility / focus changes emit their events and force a flush.
 * - Batches flush every F, on every state change, and on pagehide via sendBeacon (CSRF in body).
 * - `tracker.video` is the player-facing API for `video.*` events (§2.2); played media ranges ride
 *   on the next heartbeat as `media` (§3.9).
 *
 * Environment (clocks, timers, transport) is injected so the logic is unit-testable.
 */

/**
 * Client-sourced (Src = C) domain events the UI may emit besides page.* and video.* — each has a
 * payload model in the ingest catalogue (api analytics/schemas.py PAYLOAD_MODELS).
 */
export type ClientEventType = "practice.question_viewed" | "assessment.question_viewed" | "coding.editor_focus" | "coding.editor_blur";

/** Cap for `page.heartbeat.editor.edit_ops` (§2.1.1). */
export const MAX_EDIT_OPS = 5000;

export interface TrackerClock {
  /** Monotonic ms (performance.now()). */
  mono(): number;
  /** Wall clock epoch ms (Date.now()). */
  wall(): number;
}

export interface TrackerTimers {
  setInterval(fn: () => void, ms: number): unknown;
  clearInterval(handle: unknown): void;
}

export interface TrackerOptions {
  route: string;
  surface: Surface;
  entity?: EntityRef;
  navType: "navigate" | "reload" | "back_forward" | "spa";
  tabId: string;
  transport: Transport;
  appVersion: string;
  params?: TimeModelParams;
  clock?: TrackerClock;
  timers?: TrackerTimers;
  initial: { visible: boolean; focused: boolean };
  referrerRoute?: string;
  uuid7?: () => string;
  /** Tick resolution for idle detection. */
  tickMs?: number;
  maxQueue?: number;
}

const defaultClock: TrackerClock = {
  mono: () => (typeof performance !== "undefined" ? performance.now() : Date.now()),
  wall: () => Date.now(),
};

const defaultTimers: TrackerTimers = {
  setInterval: (fn, ms) => globalThis.setInterval(fn, ms),
  clearInterval: (h) => globalThis.clearInterval(h as ReturnType<typeof setInterval>),
};

export class ActivityTracker {
  readonly pageInstanceId = uuid4();
  private readonly params: TimeModelParams;
  private readonly clock: TrackerClock;
  private readonly timers: TrackerTimers;
  private readonly meter: EngagementMeter;
  private readonly makeId: () => string;
  private readonly maxQueue: number;
  private queue: AnalyticsEvent[] = [];
  private inFlight = false;
  private seq = 0;
  private lastState: EngagementState;
  private lastSampleAt: number;
  private lastKeepaliveAt: number;
  private lastFlushAt: number;
  private retryNotBefore = 0;
  private backoffMs = 0;
  private timer: unknown = null;
  private closed = false;
  private readonly videoSession: VideoSession;
  /** `page.heartbeat.editor` (coding surfaces): null until an editor reports focus or edits. */
  private editorState: { focused: boolean; editOps: number } | null = null;
  /** `page.heartbeat.reading.max_scroll_depth_pct`: max depth reached on this page instance. */
  private maxScrollDepth: number | null = null;

  private readonly opts: TrackerOptions;

  constructor(options: TrackerOptions) {
    assertRouteTemplate(options.route);
    const opts: TrackerOptions = { ...options, entity: cleanEntity(options.entity) };
    this.opts = opts;
    this.params = opts.params ?? TM_1_0_DEFAULTS;
    this.clock = opts.clock ?? defaultClock;
    this.timers = opts.timers ?? defaultTimers;
    this.makeId = opts.uuid7 ?? defaultUuid7;
    this.maxQueue = opts.maxQueue ?? 2000;
    const now = this.clock.mono();
    this.meter = new EngagementMeter(idleThresholdMs(this.params, opts.surface), now, opts.initial);
    this.lastState = this.meter.state(now);
    this.lastSampleAt = now;
    this.lastKeepaliveAt = now;
    this.lastFlushAt = now;
    this.videoSession = new VideoSession(
      {
        emit: (type, payload) => this.emit(type, payload),
        setMediaPlaying: (playing) => this.mediaPlaying(playing),
        mono: () => this.clock.mono(),
      },
      opts.entity?.lesson_asset_id,
      () => this.closed,
    );
    this.emit("page.view", {
      nav_type: opts.navType,
      visible: opts.initial.visible,
      focused: opts.initial.focused,
      ...(opts.referrerRoute ? { referrer_route: opts.referrerRoute } : {}),
    });
  }

  start(): void {
    if (this.timer !== null || this.closed) return;
    this.timer = this.timers.setInterval(() => this.tick(), this.opts.tickMs ?? 1000);
    void this.flush();
  }

  /** Player-facing `video.*` API (VdoCipher event mapping lives in the player component). */
  get video(): VideoEvents {
    return this.videoSession;
  }

  /** Pending (unsent) events — for tests and diagnostics. */
  get pending(): readonly AnalyticsEvent[] {
    return this.queue;
  }

  get state(): EngagementState {
    return this.meter.state(this.clock.mono());
  }

  /** Client domain events (§2.3–§2.5), e.g. `practice.question_viewed`. Dropped after close. */
  event(type: ClientEventType, payload: Record<string, unknown>): void {
    if (this.closed) return;
    this.emit(type, payload);
  }

  /** Code editor focus change: emits coding.editor_focus/blur and feeds `heartbeat.editor`. */
  editorFocus(focused: boolean, language?: string): void {
    if (this.closed) return;
    this.editorState = { focused, editOps: this.editorState?.editOps ?? 0 };
    const lang = language && /^[a-z0-9_+#.-]{1,32}$/.test(language) ? language : undefined;
    this.emit(focused ? "coding.editor_focus" : "coding.editor_blur", lang ? { language: lang } : {});
  }

  /** Count editor edit operations (content changes only — never the content itself). */
  editOps(n = 1): void {
    if (this.closed || n <= 0) return;
    const cur = this.editorState ?? { focused: true, editOps: 0 };
    this.editorState = { ...cur, editOps: Math.min(MAX_EDIT_OPS, cur.editOps + Math.round(n)) };
  }

  /** Reading progress (0–100); only increases are kept (`reading.max_scroll_depth_pct`). */
  scrollDepth(pct: number): void {
    if (this.closed || !Number.isFinite(pct)) return;
    const v = Math.max(0, Math.min(100, Math.round(pct)));
    if (this.maxScrollDepth === null || v > this.maxScrollDepth) this.maxScrollDepth = v;
  }

  // ---- inputs from the DOM -------------------------------------------------

  input(): void {
    if (this.closed) return;
    this.meter.recordInput(this.clock.mono());
    this.checkTransition();
  }

  visibilityChange(visible: boolean): void {
    if (this.closed) return;
    const now = this.clock.mono();
    if (!visible && this.lastState === "ACTIVE") this.sample("engaged", now);
    this.meter.setVisible(visible, now);
    this.emit("page.visibility_change", { visible });
    this.lastState = this.meter.state(now);
    if (visible) this.lastSampleAt = now;
    void this.flush();
  }

  focusChange(focused: boolean): void {
    if (this.closed) return;
    const now = this.clock.mono();
    if (!focused && this.lastState === "ACTIVE") this.sample("engaged", now);
    this.meter.setFocused(focused, now);
    this.emit(focused ? "page.focus" : "page.blur", {});
    this.lastState = this.meter.state(now);
    if (focused) this.lastSampleAt = now;
    void this.flush();
  }

  mediaPlaying(playing: boolean): void {
    if (this.closed) return;
    this.meter.setMediaPlaying(playing, this.clock.mono());
    this.checkTransition();
  }

  /**
   * Close the page instance. `pagehide` sends via sendBeacon (falls back to fetch keepalive);
   * `route_change` (SPA) flushes normally.
   */
  close(reason: "pagehide" | "freeze" | "route_change", persisted = false): void {
    if (this.closed) return;
    const now = this.clock.mono();
    if (this.lastState === "ACTIVE") this.sample("engaged", now);
    else if (this.videoSession.hasPendingRanges) this.sample("keepalive", now); // keep hidden-tab coverage
    this.emit("page.hide", { reason, ...(reason === "pagehide" ? { persisted } : {}) });
    this.closed = true;
    if (this.timer !== null) {
      this.timers.clearInterval(this.timer);
      this.timer = null;
    }
    if (reason === "route_change") {
      void this.flush();
      return;
    }
    this.flushOnUnload();
  }

  // ---- periodic work -------------------------------------------------------

  tick(): void {
    if (this.closed) return;
    const now = this.clock.mono();
    this.checkTransition();
    const state = this.lastState;
    if (state === "ACTIVE" && now - this.lastSampleAt >= this.params.heartbeatMs) {
      this.sample("engaged", now);
    } else if (state === "IDLE" && now - this.lastKeepaliveAt >= this.params.keepaliveMs) {
      this.sample("keepalive", now);
    }
    if (now - this.lastFlushAt >= this.params.flushMs) void this.flush();
  }

  private checkTransition(): void {
    const now = this.clock.mono();
    const state = this.meter.state(now);
    if (state === this.lastState) return;
    const prev = this.lastState;
    if (prev === "ACTIVE" && state === "IDLE") {
      this.sample("engaged", now);
      this.emit("page.idle_change", { idle: true, idle_threshold_s: Math.round(idleThresholdMs(this.params, this.opts.surface) / 1000) });
      this.lastKeepaliveAt = now;
      this.lastState = state;
      void this.flush();
      return;
    }
    if (prev === "IDLE" && state === "ACTIVE") {
      this.emit("page.idle_change", { idle: false, idle_threshold_s: Math.round(idleThresholdMs(this.params, this.opts.surface) / 1000) });
      // Idle time is never credited (the meter only accrues ACTIVE time); restart the sample window.
      this.lastSampleAt = now;
      this.lastState = state;
      void this.flush();
      return;
    }
    this.lastState = state;
  }

  private sample(kind: "engaged" | "keepalive", now: number): void {
    const snap = this.meter.snapshot(now);
    const { activeMs, inputEvents } = this.meter.take(now);
    const interval = Math.max(1000, Math.min(330_000, Math.round(now - (kind === "engaged" ? this.lastSampleAt : this.lastKeepaliveAt))));
    const media = this.videoSession.takeHeartbeat();
    const editor = this.editorState ? { focused: this.editorState.focused, edit_ops: this.editorState.editOps } : null;
    if (this.editorState) this.editorState = { ...this.editorState, editOps: 0 };
    this.emit("page.heartbeat", {
      kind,
      sample_interval_ms: interval,
      active_ms: kind === "keepalive" ? 0 : activeMs,
      state: {
        visible: snap.visible,
        focused: snap.focused,
        input_recent: snap.inputRecent,
        media_playing: snap.mediaPlaying,
      },
      input_events: inputEvents,
      ...(media ? { media } : {}),
      ...(editor ? { editor } : {}),
      ...(this.maxScrollDepth !== null ? { reading: { max_scroll_depth_pct: this.maxScrollDepth } } : {}),
    });
    if (kind === "engaged") this.lastSampleAt = now;
    else this.lastKeepaliveAt = now;
  }

  private emit(eventType: string, payload: Record<string, unknown>): void {
    const event: AnalyticsEvent = {
      event_id: this.makeId(),
      event_type: eventType,
      schema_version: 1,
      occurred_at: rfc3339WithOffset(this.clock.wall()),
      mono_ms: Math.max(0, Math.round(this.clock.mono())),
      tab_id: this.opts.tabId,
      page_instance_id: this.pageInstanceId,
      seq: this.seq++,
      route: this.opts.route,
      surface: this.opts.surface,
      ...(this.opts.entity ? { entity: this.opts.entity } : {}),
      payload,
    };
    this.queue.push(event);
    if (this.queue.length > this.maxQueue) {
      // Every page.* event is L-purpose; drop the oldest when the queue is full.
      this.queue.splice(0, this.queue.length - this.maxQueue);
    }
  }

  private batchOf(events: AnalyticsEvent[]): AnalyticsBatch {
    return {
      sent_at: rfc3339WithOffset(this.clock.wall()),
      client: {
        app_version: this.opts.appVersion,
        platform: "web",
        tz_offset_min: -new Date(this.clock.wall()).getTimezoneOffset(),
        measurement_version: "tm-1.0",
      },
      events,
    };
  }

  /** Take the next chunk that fits 100 events / ~60 KiB. */
  private nextChunk(): AnalyticsEvent[] {
    const chunk: AnalyticsEvent[] = [];
    let bytes = 256;
    for (const e of this.queue) {
      const size = JSON.stringify(e).length + 1;
      if (chunk.length >= MAX_EVENTS_PER_BATCH || bytes + size > MAX_BATCH_BYTES) break;
      chunk.push(e);
      bytes += size;
    }
    return chunk;
  }

  private remove(ids: Set<string>): void {
    this.queue = this.queue.filter((e) => !ids.has(e.event_id));
  }

  async flush(): Promise<void> {
    const now = this.clock.mono();
    this.lastFlushAt = now;
    if (this.inFlight || this.queue.length === 0 || now < this.retryNotBefore) return;
    this.inFlight = true;
    try {
      while (this.queue.length > 0) {
        const chunk = this.nextChunk();
        if (chunk.length === 0) break;
        const outcome = await this.opts.transport.send(this.batchOf(chunk), { keepalive: false });
        if (outcome.kind === "retry") {
          this.backoffMs = Math.min(this.backoffMs ? this.backoffMs * 2 : 2000, 300_000);
          const jitter = Math.random() * 0.3 * this.backoffMs;
          this.retryNotBefore = this.clock.mono() + Math.max(outcome.retryAfterMs ?? 0, this.backoffMs + jitter);
          return;
        }
        this.backoffMs = 0;
        // ok: accepted, duplicate and rejected are all removed (§5.3); drop: whole batch is unusable.
        this.remove(new Set(chunk.map((e) => e.event_id)));
      }
    } finally {
      this.inFlight = false;
    }
  }

  private flushOnUnload(): void {
    while (this.queue.length > 0) {
      const chunk = this.nextChunk();
      if (chunk.length === 0) break;
      const batch = this.batchOf(chunk);
      const outcome = this.opts.transport.beacon(batch);
      if (outcome.kind === "beacon_refused") {
        // Fallback: fetch keepalive (fire and forget; the page is going away).
        void this.opts.transport.send(batch, { keepalive: true });
      }
      this.remove(new Set(chunk.map((e) => e.event_id)));
    }
  }
}

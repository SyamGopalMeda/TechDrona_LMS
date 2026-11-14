import { describe, expect, it, vi } from "vitest";
import { createUuid7Generator, UUID7_PATTERN, uuid7Timestamp } from "@/lib/ids/uuid7";
import { loadAnalyticsConfig, parseAnalyticsConfig, resetAnalyticsConfigCache } from "./config";
import { assertRouteTemplate, rfc3339WithOffset, type AnalyticsBatch } from "./envelope";
import { EngagementMeter, TM_1_0_DEFAULTS } from "./time-model";
import { ActivityTracker } from "./tracker";
import { createFetchTransport, type SendOutcome, type Transport } from "./transport";

describe("uuid7", () => {
  it("encodes the timestamp, version and variant", () => {
    const gen = createUuid7Generator(() => 1_762_164_902_123);
    const id = gen();
    expect(id).toMatch(UUID7_PATTERN);
    expect(uuid7Timestamp(id)).toBe(1_762_164_902_123);
  });

  it("is strictly increasing within the same millisecond and when the clock goes back", () => {
    let t = 1_762_164_902_000;
    const gen = createUuid7Generator(() => t);
    const ids: string[] = [];
    for (let i = 0; i < 5000; i++) ids.push(gen()); // forces counter overflow
    t -= 10_000; // wall clock jumps backwards
    ids.push(gen());
    for (let i = 1; i < ids.length; i++) expect(ids[i]! > ids[i - 1]!).toBe(true);
    for (const id of ids) expect(id).toMatch(UUID7_PATTERN);
  });
});

describe("EngagementMeter (tm-1.0 §3.2)", () => {
  it("credits time after the last input only up to T_idle", () => {
    const m = new EngagementMeter(90_000, 0, { visible: true, focused: true });
    expect(m.state(0)).toBe("ACTIVE");
    m.recordInput(10_000);
    expect(m.state(100_000)).toBe("ACTIVE");
    expect(m.state(100_001)).toBe("IDLE");
    // 0 → 100_000 active (last input 10 s + 90 s threshold); nothing after.
    expect(m.take(200_000).activeMs).toBe(20_000); // capped per sample by schema max
  });

  it("credits exactly while visible+focused+recent input", () => {
    const m = new EngagementMeter(90_000, 0, { visible: true, focused: true });
    expect(m.take(15_000).activeMs).toBe(15_000);
    m.setFocused(false, 20_000);
    expect(m.state(21_000)).toBe("IDLE");
    expect(m.take(30_000).activeMs).toBe(5_000);
    m.setVisible(false, 31_000);
    expect(m.state(31_000)).toBe("HIDDEN");
    expect(m.take(45_000).activeMs).toBe(0);
  });

  it("counts playing media as active when visible but unfocused, never when hidden", () => {
    const m = new EngagementMeter(90_000, 0, { visible: true, focused: false });
    expect(m.state(0)).toBe("IDLE");
    m.setMediaPlaying(true, 1_000);
    expect(m.state(1_000)).toBe("ACTIVE");
    expect(m.take(11_000).activeMs).toBe(10_000);
    m.setVisible(false, 12_000);
    expect(m.state(12_000)).toBe("HIDDEN");
    expect(m.take(20_000).activeMs).toBe(1_000);
  });

  it("counts inputs without content", () => {
    const m = new EngagementMeter(90_000, 0, { visible: true, focused: true });
    m.recordInput(1);
    m.recordInput(2);
    expect(m.take(3).inputEvents).toBe(2);
    expect(m.take(4).inputEvents).toBe(0);
  });
});

function harness(initial = { visible: true, focused: true }) {
  let mono = 0;
  const wall0 = Date.UTC(2026, 10, 3, 10, 0, 0);
  const sent: AnalyticsBatch[] = [];
  const beacons: AnalyticsBatch[] = [];
  let nextOutcome: SendOutcome = { kind: "ok", response: null };
  const transport: Transport = {
    send: vi.fn(async (batch: AnalyticsBatch) => {
      sent.push(batch);
      return nextOutcome;
    }),
    beacon: vi.fn((batch: AnalyticsBatch) => {
      beacons.push(batch);
      return { kind: "beacon_queued" } as SendOutcome;
    }),
  };
  const tracker = new ActivityTracker({
    route: "/app/learn/[course_slug]/[lesson_id]",
    surface: "lesson_text",
    navType: "navigate",
    tabId: "11111111-1111-4111-8111-111111111111",
    transport,
    appVersion: "test",
    params: { ...TM_1_0_DEFAULTS, idleMsBySurface: {} }, // T_idle = 90 s for this test
    clock: { mono: () => mono, wall: () => wall0 + mono },
    timers: { setInterval: () => 1, clearInterval: () => undefined },
    initial,
  });
  const advance = async (ms: number, step = 1000) => {
    for (let t = 0; t < ms; t += step) {
      mono += step;
      tracker.tick();
      await Promise.resolve();
    }
  };
  const all = () => [...sent, ...beacons].flatMap((b) => b.events);
  return {
    tracker,
    transport,
    sent,
    beacons,
    advance,
    all,
    setOutcome: (o: SendOutcome) => (nextOutcome = o),
    setMono: (v: number) => (mono = v),
  };
}

describe("ActivityTracker", () => {
  it("opens with page.view seq 0 and samples every 15 s while ACTIVE", async () => {
    const h = harness();
    expect(h.tracker.pending[0]).toMatchObject({ event_type: "page.view", seq: 0, payload: { nav_type: "navigate", visible: true, focused: true } });
    await h.advance(45_000);
    await h.tracker.flush();
    const beats = h.all().filter((e) => e.event_type === "page.heartbeat");
    expect(beats).toHaveLength(3);
    for (const b of beats) {
      expect(b.payload).toMatchObject({ kind: "engaged", active_ms: 15_000, sample_interval_ms: 15_000 });
      expect(b.event_id).toMatch(UUID7_PATTERN);
      expect(b.route).toBe("/app/learn/[course_slug]/[lesson_id]");
    }
    const seqs = h.all().map((e) => e.seq);
    expect(seqs).toEqual([...seqs].sort((a, b) => a - b));
  });

  it("emits idle_change and flushes when input stops, then only keepalives", async () => {
    const h = harness();
    await h.advance(91_000);
    const idle = h.all().find((e) => e.event_type === "page.idle_change");
    expect(idle?.payload).toEqual({ idle: true, idle_threshold_s: 90 });
    const engaged = h.all().filter((e) => e.event_type === "page.heartbeat" && e.payload.kind === "engaged");
    const credited = engaged.reduce((s, e) => s + (e.payload.active_ms as number), 0);
    expect(credited).toBe(90_000); // credit = min(gap, T_idle)
    await h.advance(300_000, 5000);
    await h.tracker.flush();
    const keepalives = h.all().filter((e) => e.event_type === "page.heartbeat" && e.payload.kind === "keepalive");
    expect(keepalives).toHaveLength(1);
    expect(keepalives[0]!.payload.active_ms).toBe(0);
    // input brings it back to ACTIVE
    h.tracker.input();
    await Promise.resolve();
    expect(h.tracker.state).toBe("ACTIVE");
    expect(h.all().some((e) => e.event_type === "page.idle_change" && e.payload.idle === false)).toBe(true);
  });

  it("never credits a hidden tab and flushes on visibility change", async () => {
    const h = harness();
    await h.advance(5_000);
    h.tracker.visibilityChange(false);
    await Promise.resolve();
    const last = h.sent.at(-1)!.events;
    expect(last.some((e) => e.event_type === "page.visibility_change" && e.payload.visible === false)).toBe(true);
    const partial = last.find((e) => e.event_type === "page.heartbeat");
    expect(partial?.payload.active_ms).toBe(5_000);
    await h.advance(60_000);
    await h.tracker.flush();
    expect(h.all().filter((e) => e.event_type === "page.heartbeat")).toHaveLength(1);
  });

  it("sends page.hide through sendBeacon on pagehide", async () => {
    const h = harness();
    await h.advance(3_000);
    h.tracker.close("pagehide", false);
    expect(h.beacons).toHaveLength(1);
    const events = h.beacons[0]!.events;
    expect(events.at(-1)).toMatchObject({ event_type: "page.hide", payload: { reason: "pagehide", persisted: false } });
    expect(h.beacons[0]!.client).toMatchObject({ platform: "web", measurement_version: "tm-1.0" });
    expect(h.tracker.pending).toHaveLength(0);
  });

  it("keeps events and backs off on retryable failures", async () => {
    const h = harness();
    h.setOutcome({ kind: "retry", retryAfterMs: 10_000 });
    await h.tracker.flush();
    expect(h.tracker.pending.length).toBe(1);
    const calls = (h.transport.send as ReturnType<typeof vi.fn>).mock.calls.length;
    await h.tracker.flush(); // inside backoff window: no new request
    expect((h.transport.send as ReturnType<typeof vi.fn>).mock.calls.length).toBe(calls);
    h.setOutcome({ kind: "ok", response: null });
    await h.advance(31_000);
    await h.tracker.flush();
    expect(h.tracker.pending.length).toBe(0);
  });

  it("rejects raw URLs as routes", () => {
    expect(() => assertRouteTemplate("/app/courses/abc?x=1")).toThrow();
    expect(assertRouteTemplate("/app/courses/[slug]")).toBe("/app/courses/[slug]");
  });
});

describe("transport", () => {
  it("adds the CSRF header for fetch and puts the token in the body for sendBeacon", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ accepted: 1, duplicate: 0, rejected: 0, results: [] }), { status: 200 }));
    const beacon = vi.fn((_url: string, _data: BodyInit) => true);
    const t = createFetchTransport(fetchImpl as unknown as typeof fetch, () => "v1.n.s", beacon);
    const batch: AnalyticsBatch = { sent_at: "x", client: { app_version: "1", platform: "web", measurement_version: "tm-1.0" }, events: [] };
    expect((await t.send(batch, { keepalive: true })).kind).toBe("ok");
    const init = (fetchImpl.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect(init.keepalive).toBe(true);
    expect((init.headers as Record<string, string>)["x-csrf-token"]).toBe("v1.n.s");
    expect(t.beacon(batch).kind).toBe("beacon_queued");
    const [url, blob] = beacon.mock.calls[0]!;
    expect(url).toBe("/api/v1/analytics/events/beacon");
    const text = await new Promise<string>((resolve) => {
      const fr = new FileReader();
      fr.onload = () => resolve(String(fr.result));
      fr.readAsText(blob as Blob);
    });
    expect(JSON.parse(text).csrf).toBe("v1.n.s");
  });

  it("classifies 429/5xx as retry and other 4xx as drop", async () => {
    const mk = (status: number) =>
      createFetchTransport((async () => new Response("{}", { status, headers: { "retry-after": "3" } })) as unknown as typeof fetch, () => "t", null);
    const batch = { sent_at: "x", client: { app_version: "1", platform: "web" as const, measurement_version: "tm-1.0" as const }, events: [] };
    expect(await mk(429).send(batch, { keepalive: false })).toEqual({ kind: "retry", retryAfterMs: 3000 });
    expect((await mk(503).send(batch, { keepalive: false })).kind).toBe("retry");
    expect(await mk(422).send(batch, { keepalive: false })).toEqual({ kind: "drop", status: 422 });
  });
});

describe("config and time formatting", () => {
  it("clamps server parameters to the tm-1.0 ranges", () => {
    const p = parseAnalyticsConfig({ measurement_version: "tm-1.0", params: { heartbeat_interval_s: 5, idle_threshold_s: 120, idle_threshold_by_surface_s: { test: 9999 } } });
    expect(p.heartbeatMs).toBe(10_000);
    expect(p.idleMs).toBe(120_000);
    expect(p.idleMsBySurface.test).toBe(600_000);
    expect(parseAnalyticsConfig(null)).toBe(TM_1_0_DEFAULTS);
  });

  it("formats RFC 3339 with offset and ms", () => {
    expect(rfc3339WithOffset(Date.UTC(2026, 10, 3, 10, 15, 2, 123))).toMatch(/^2026-11-0\dT\d{2}:\d{2}:02\.123[+-]\d{2}:\d{2}$/);
  });
});

describe("loadAnalyticsConfig (F15)", () => {
  it("returns null on 403 (analytics refused, e.g. learning access paused) so no tracker starts", async () => {
    resetAnalyticsConfigCache();
    const f = vi.fn(async () => new Response(JSON.stringify({ code: "account_restricted" }), { status: 403 }));
    expect(await loadAnalyticsConfig(f as unknown as typeof fetch)).toBeNull();
    resetAnalyticsConfigCache();
    const g = vi.fn(async () => new Response("", { status: 500 }));
    expect(await loadAnalyticsConfig(g as unknown as typeof fetch)).toBe(TM_1_0_DEFAULTS);
    resetAnalyticsConfigCache();
  });
});

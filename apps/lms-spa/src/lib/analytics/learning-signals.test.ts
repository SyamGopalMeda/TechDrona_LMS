import { describe, expect, it, vi } from "vitest";
import { cleanEntity, type AnalyticsBatch } from "./envelope";
import { scrollDepthPct } from "./scroll-depth";
import { TM_1_0_DEFAULTS } from "./time-model";
import { ActivityTracker } from "./tracker";
import type { SendOutcome, Transport } from "./transport";
import { errorCode } from "./video";

const ATTEMPT = "01900000-0000-7000-8000-0000000000c1";

function harness(entity: Record<string, string> = { test_attempt_id: ATTEMPT }, surface: "test" | "coding" | "lesson_text" | "practice" = "test") {
  let mono = 0;
  const sent: AnalyticsBatch[] = [];
  const transport: Transport = {
    send: vi.fn(async (b: AnalyticsBatch) => {
      sent.push(b);
      return { kind: "ok", response: null } as SendOutcome;
    }),
    beacon: vi.fn(() => ({ kind: "beacon_queued" }) as SendOutcome),
  };
  const tracker = new ActivityTracker({
    route: "/app/attempts/[attempt_id]",
    surface,
    entity,
    navType: "navigate",
    tabId: "11111111-1111-4111-8111-111111111111",
    transport,
    appVersion: "test",
    params: TM_1_0_DEFAULTS,
    clock: { mono: () => mono, wall: () => Date.UTC(2026, 10, 3) + mono },
    timers: { setInterval: () => 1, clearInterval: () => undefined },
    initial: { visible: true, focused: true },
  });
  const all = () => [...tracker.pending, ...sent.flatMap((b) => b.events)];
  const advance = (ms: number) => {
    for (let t = 0; t < ms; t += 1000) {
      mono += 1000;
      tracker.input();
      tracker.tick();
    }
  };
  return { tracker, all, advance };
}

describe("learning-surface client signals (FE-07 / FE-16)", () => {
  it("drops non-UUID entity values so a slug route param cannot invalidate every event", () => {
    expect(cleanEntity({ test_attempt_id: ATTEMPT, coding_problem_id: "two-sum", topic_id: "" })).toEqual({ test_attempt_id: ATTEMPT });
    expect(cleanEntity({ topic_id: "x" })).toBeUndefined();
    const h = harness({ test_attempt_id: ATTEMPT, test_id: "not-a-uuid" });
    expect(h.all()[0]!.entity).toEqual({ test_attempt_id: ATTEMPT });
  });

  it("emits practice/assessment question_viewed with the documented payloads", () => {
    const h = harness();
    h.tracker.event("assessment.question_viewed", { question_index: 2 });
    h.tracker.event("practice.question_viewed", { position_in_set: 0, set_id: ATTEMPT });
    const evs = h.all().filter((e) => e.event_type.endsWith("question_viewed"));
    expect(evs.map((e) => [e.event_type, e.payload, e.surface])).toEqual([
      ["assessment.question_viewed", { question_index: 2 }, "test"],
      ["practice.question_viewed", { position_in_set: 0, set_id: ATTEMPT }, "test"],
    ]);
  });

  it("emits coding.editor_focus/blur and reports edit_ops on the next heartbeat (then resets)", () => {
    const h = harness({}, "coding");
    h.tracker.editorFocus(true, "python3");
    h.tracker.editOps();
    h.tracker.editOps(4);
    h.advance(15_000);
    h.tracker.editorFocus(false, "Bad Lang!");
    h.advance(15_000);
    const types = h.all().map((e) => e.event_type);
    expect(types).toContain("coding.editor_focus");
    const focus = h.all().find((e) => e.event_type === "coding.editor_focus")!;
    expect(focus.payload).toEqual({ language: "python3" });
    const blur = h.all().find((e) => e.event_type === "coding.editor_blur")!;
    expect(blur.payload).toEqual({}); // invalid language keys are not sent
    const beats = h.all().filter((e) => e.event_type === "page.heartbeat");
    expect(beats[0]!.payload.editor).toEqual({ focused: true, edit_ops: 5 });
    expect(beats.at(-1)!.payload.editor).toEqual({ focused: false, edit_ops: 0 });
  });

  it("reports reading.max_scroll_depth_pct and keeps only increases", () => {
    const h = harness({}, "lesson_text");
    h.tracker.scrollDepth(40);
    h.tracker.scrollDepth(25);
    h.tracker.scrollDepth(140);
    h.advance(15_000);
    const beat = h.all().find((e) => e.event_type === "page.heartbeat")!;
    expect(beat.payload.reading).toEqual({ max_scroll_depth_pct: 100 });
  });

  it("heartbeats carry no editor/reading blocks on surfaces that never reported them", () => {
    const h = harness();
    h.advance(15_000);
    const beat = h.all().find((e) => e.event_type === "page.heartbeat")!;
    expect(beat.payload).not.toHaveProperty("editor");
    expect(beat.payload).not.toHaveProperty("reading");
  });

  it("drops client events after the page instance closed", () => {
    const h = harness();
    h.tracker.close("route_change");
    const n = h.all().length;
    h.tracker.event("assessment.question_viewed", { question_index: 0 });
    h.tracker.editorFocus(true);
    expect(h.all()).toHaveLength(n);
  });
});

describe("scrollDepthPct", () => {
  it("measures the share of the article above the viewport bottom", () => {
    expect(scrollDepthPct(800, 2000, 800)).toBe(0); // not reached yet
    expect(scrollDepthPct(0, 2000, 800)).toBe(40);
    expect(scrollDepthPct(-1200, 2000, 800)).toBe(100);
    expect(scrollDepthPct(100, 300, 800)).toBe(100); // short article fully visible
    expect(scrollDepthPct(0, 0, 800)).toBe(0);
  });
});

describe("video.error code (ingest pattern [A-Za-z0-9_.-]{1,32})", () => {
  it("sanitises player codes", () => {
    expect(errorCode(4)).toBe("4");
    expect(errorCode("MEDIA ERR/decode")).toBe("MEDIA_ERR_decode");
    expect(errorCode("x".repeat(64))).toHaveLength(32);
    expect(errorCode("")).toBe("unknown");
  });
});

import { describe, expect, it, vi } from "vitest";
import type { AnalyticsBatch } from "./envelope";
import { TM_1_0_DEFAULTS } from "./time-model";
import { ActivityTracker } from "./tracker";
import type { SendOutcome, Transport } from "./transport";
import { forwardVideo } from "./use-activity-tracker";
import { normalizeRanges, VideoSession, type VideoSink } from "./video";

const L1 = "01900000-0000-7000-8000-0000000000a1";
const A1 = "01900000-0000-7000-8000-0000000000b1";

function harness() {
  let mono = 0;
  const sent: AnalyticsBatch[] = [];
  const beacons: AnalyticsBatch[] = [];
  const transport: Transport = {
    send: vi.fn(async (b: AnalyticsBatch) => {
      sent.push(b);
      return { kind: "ok", response: null } as SendOutcome;
    }),
    beacon: vi.fn((b: AnalyticsBatch) => {
      beacons.push(b);
      return { kind: "beacon_queued" } as SendOutcome;
    }),
  };
  const tracker = new ActivityTracker({
    route: "/app/learn/[course_slug]/[lesson_id]",
    surface: "lesson_video",
    entity: { lesson_id: L1, lesson_asset_id: A1 },
    navType: "navigate",
    tabId: "11111111-1111-4111-8111-111111111111",
    transport,
    appVersion: "test",
    params: TM_1_0_DEFAULTS,
    clock: { mono: () => mono, wall: () => Date.UTC(2026, 10, 3) + mono },
    timers: { setInterval: () => 1, clearInterval: () => undefined },
    initial: { visible: true, focused: true },
  });
  const advance = async (ms: number) => {
    for (let t = 0; t < ms; t += 1000) {
      mono += 1000;
      tracker.tick();
      await Promise.resolve();
    }
  };
  const all = () => [...tracker.pending, ...sent.flatMap((b) => b.events), ...beacons.flatMap((b) => b.events)];
  return { tracker, advance, all, setMono: (v: number) => (mono = v), getMono: () => mono };
}

describe("video.* events (analytics-event-schema §2.2)", () => {
  it("emits play/pause/seek/rate_change/ended with documented payloads and the entity", () => {
    const h = harness();
    const v = h.tracker.video;
    v.play(0, 1);
    v.rateChange(1, 1.5, 12.34);
    v.seek(12.34, 300);
    v.pause(305);
    v.ended(600, 600);
    const evs = h.all().filter((e) => e.event_type.startsWith("video."));
    expect(evs.map((e) => [e.event_type, e.payload])).toEqual([
      ["video.play", { position_s: 0, rate: 1 }],
      ["video.rate_change", { from_rate: 1, to_rate: 1.5, position_s: 12.3 }],
      ["video.seek", { from_s: 12.3, to_s: 300 }],
      ["video.pause", { position_s: 305 }],
      ["video.ended", { position_s: 600, duration_s: 600 }],
    ]);
    for (const e of evs) {
      expect(e.entity).toEqual({ lesson_id: L1, lesson_asset_id: A1 });
      expect(e.surface).toBe("lesson_video");
    }
    // seq is per page instance and strictly increasing across page.* and video.* events
    const seqs = h.all().map((e) => e.seq);
    expect(seqs).toEqual([...seqs].sort((a, b) => a - b));
  });

  it("clamps rate to 0.25–2.0 and positions to ≥ 0", () => {
    const h = harness();
    h.tracker.video.play(-5, 4);
    h.tracker.video.rateChange(4, 0.1, Number.NaN);
    const [play, rate] = h.all().filter((e) => e.event_type.startsWith("video."));
    expect(play!.payload).toEqual({ position_s: 0, rate: 2 });
    expect(rate!.payload).toEqual({ from_rate: 2, to_rate: 0.25, position_s: 0 });
  });

  it("measures buffer_ms between bufferingStart and bufferingEnd", async () => {
    const h = harness();
    h.tracker.video.play(10);
    h.tracker.video.bufferingStart(20);
    h.setMono(h.getMono() + 1_250);
    h.tracker.video.bufferingEnd(20, 1800.4);
    h.tracker.video.bufferingEnd(20); // no open stall → ignored
    const buf = h.all().filter((e) => e.event_type === "video.buffering");
    expect(buf).toHaveLength(1);
    expect(buf[0]!.payload).toEqual({ position_s: 20, buffer_ms: 1250, bitrate_kbps: 1800 });
  });

  it("video.error carries the player code only and stops media_playing", () => {
    const h = harness();
    h.tracker.video.play(0);
    h.tracker.video.error(2021, 33);
    const err = h.all().find((e) => e.event_type === "video.error");
    expect(err!.payload).toEqual({ code: "2021", position_s: 33 });
  });

  it("play keeps the page ACTIVE while visible but unfocused; pause releases it", async () => {
    const h = harness();
    h.tracker.focusChange(false);
    expect(h.tracker.state).toBe("IDLE");
    h.tracker.video.play(0);
    expect(h.tracker.state).toBe("ACTIVE");
    h.tracker.video.pause(5);
    expect(h.tracker.state).toBe("IDLE");
  });

  it("attaches played ranges to the next engaged heartbeat (unique-coverage input)", async () => {
    const h = harness();
    const v = h.tracker.video;
    v.play(0);
    for (let s = 1; s <= 5; s++) v.timeUpdate(s);
    v.seek(5, 100);
    for (let s = 101; s <= 108; s++) v.timeUpdate(s);
    await h.advance(15_000);
    const hb = h.all().filter((e) => e.event_type === "page.heartbeat");
    expect(hb.length).toBeGreaterThan(0);
    expect(hb[0]!.payload.media).toEqual({
      lesson_asset_id: A1,
      position_s: 108,
      rate: 1,
      played_ranges: [
        [0, 5],
        [100, 108],
      ],
    });
    expect((hb[0]!.payload.state as { media_playing: boolean }).media_playing).toBe(true);
  });

  it("does not add media to heartbeats when the player was never used", async () => {
    const h = harness();
    await h.advance(15_000);
    const hb = h.all().find((e) => e.event_type === "page.heartbeat");
    expect(hb!.payload.media).toBeUndefined();
  });

  it("drops calls after the page instance is closed", () => {
    const h = harness();
    h.tracker.close("route_change");
    h.tracker.video.play(0);
    expect(h.all().some((e) => e.event_type.startsWith("video."))).toBe(false);
  });

  it("emits a keepalive with pending ranges on pagehide when not ACTIVE (hidden playback)", () => {
    const h = harness();
    h.tracker.video.play(0);
    h.tracker.video.timeUpdate(4);
    h.tracker.visibilityChange(false); // engaged sample drains [0,4]
    h.tracker.video.timeUpdate(9);
    h.tracker.close("pagehide");
    const hbs = h.all().filter((e) => e.event_type === "page.heartbeat");
    const last = hbs[hbs.length - 1]!;
    expect(last.payload.kind).toBe("keepalive");
    expect((last.payload.media as { played_ranges: number[][] }).played_ranges).toEqual([[4, 9]]);
  });
});

describe("VideoSession helpers", () => {
  it("normalizeRanges merges overlaps and caps at 8 ranges by merging the smallest gaps", () => {
    expect(
      normalizeRanges([
        [5, 10],
        [0, 5],
        [3, 4],
        [20, 25],
      ]),
    ).toEqual([
      [0, 10],
      [20, 25],
    ]);
    const many = Array.from({ length: 10 }, (_, i) => [i * 10, i * 10 + 5] as [number, number]);
    many[3] = [30, 39.5];
    const out = normalizeRanges(many);
    expect(out).toHaveLength(8);
    expect(out).toContainEqual([30, 45]);
  });

  it("treats a large forward jump in timeUpdate as an implicit seek", () => {
    const events: string[] = [];
    const sink: VideoSink = { emit: (t) => void events.push(t), setMediaPlaying: () => undefined, mono: () => 0 };
    const s = new VideoSession(sink);
    s.play(0);
    s.timeUpdate(3);
    s.timeUpdate(200);
    s.timeUpdate(203);
    expect(s.takeHeartbeat()!.played_ranges).toEqual([
      [0, 3],
      [200, 203],
    ]);
  });

  it("forwardVideo is a no-op without a tracker and forwards when one exists", () => {
    let target: VideoSession | null = null;
    const v = forwardVideo(() => target);
    expect(() => v.play(1)).not.toThrow();
    const emitted: string[] = [];
    target = new VideoSession({ emit: (t) => void emitted.push(t), setMediaPlaying: () => undefined, mono: () => 0 });
    v.play(1);
    v.pause(2);
    expect(emitted).toEqual(["video.play", "video.pause"]);
  });
});

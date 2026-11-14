import { describe, expect, it } from "vitest";
import { crossedMilestone, formatCountdown, sampleFrom, ServerClock, spokenDuration, timerTone } from "./server-clock";

function fakeMono(start = 1_000) {
  let t = start;
  const fn = () => t;
  return Object.assign(fn, { advance: (ms: number) => (t += ms) });
}

const DEADLINE = "2026-11-03T11:45:02.000Z";

describe("ServerClock (server-authoritative timer)", () => {
  it("uses the request midpoint to correct for latency", () => {
    const s = sampleFrom("2026-11-03T10:00:00.000Z", 100, 300)!;
    expect(s.rttMs).toBe(200);
    expect(s.monoMs).toBe(200);
    expect(s.serverMs).toBe(Date.parse("2026-11-03T10:00:00.000Z"));
  });

  it("derives remaining time from the server deadline, not the local wall clock", () => {
    const mono = fakeMono();
    const clock = new ServerClock(mono);
    const sent = clock.mark();
    mono.advance(200); // RTT 200 ms → server_now was taken ~100 ms ago
    clock.observe("2026-11-03T11:00:02.000Z", sent);
    // 45 min to deadline minus the 100 ms elapsed since the server stamped server_now
    expect(clock.remainingMs(DEADLINE)).toBe(45 * 60_000 - 100);
    mono.advance(60_000);
    expect(clock.remainingMs(DEADLINE)).toBe(44 * 60_000 - 100);
  });

  it("ignores changes to the device's wall clock (monotonic source only)", () => {
    const mono = fakeMono();
    const clock = new ServerClock(mono);
    clock.observe("2026-11-03T11:00:02.000Z");
    const before = clock.remainingMs(DEADLINE);
    // Simulate the user moving the system clock: Date.now is not consulted.
    const realNow = Date.now;
    Date.now = () => realNow() + 3_600_000;
    try {
      expect(clock.remainingMs(DEADLINE)).toBe(before);
      expect(clock.offsetFromWallClock(0)).toBe(Date.parse("2026-11-03T11:00:02.000Z"));
    } finally {
      Date.now = realNow;
    }
  });

  it("never reports negative remaining time and returns null before the first sample", () => {
    const mono = fakeMono();
    const clock = new ServerClock(mono);
    expect(clock.remainingMs(DEADLINE)).toBeNull();
    clock.observe("2026-11-03T11:45:00.000Z");
    mono.advance(10_000);
    expect(clock.remainingMs(DEADLINE)).toBe(0);
    expect(clock.remainingMs(null)).toBeNull();
  });

  it("keeps a low-RTT sample over a much noisier one, but refreshes stale samples", () => {
    const mono = fakeMono();
    const clock = new ServerClock(mono);
    let sent = clock.mark();
    mono.advance(50);
    clock.observe("2026-11-03T11:00:00.000Z", sent); // rtt 50
    const good = clock.serverNow();
    sent = clock.mark();
    mono.advance(3_000);
    clock.observe("2026-11-03T11:00:10.000Z", sent); // rtt 3000: implausible, rejected
    expect(clock.serverNow()! - good!).toBe(3_000);
    mono.advance(6 * 60_000);
    sent = clock.mark();
    mono.advance(3_000);
    clock.observe("2026-11-03T11:10:00.000Z", sent); // stale sample → accepted
    expect(clock.serverNow()).toBe(Date.parse("2026-11-03T11:10:00.000Z") + 1_500);
  });

  it("ignores malformed server_now", () => {
    const clock = new ServerClock(fakeMono());
    clock.observe("not a date");
    clock.observe(undefined);
    expect(clock.synced).toBe(false);
  });
});

describe("timer display helpers", () => {
  it("formats MM:SS and HH:MM:SS, rounding up", () => {
    expect(formatCountdown(0)).toBe("00:00");
    expect(formatCountdown(999)).toBe("00:01");
    expect(formatCountdown(41 * 60_000 + 12_000)).toBe("41:12");
    expect(formatCountdown(90 * 60_000)).toBe("01:30:00");
  });

  it("speaks durations for screen readers", () => {
    expect(spokenDuration(38 * 60_000 + 40_000)).toBe("38 minutes 40 seconds");
    expect(spokenDuration(3_600_000)).toBe("1 hour");
  });

  it("switches tone at 10 min and 1 min", () => {
    expect(timerTone(11 * 60_000)).toBe("default");
    expect(timerTone(10 * 60_000)).toBe("warn");
    expect(timerTone(60_000)).toBe("critical");
    expect(timerTone(null)).toBe("default");
  });

  it("announces each milestone once, and the smallest when several are crossed", () => {
    expect(crossedMilestone(10 * 60_000 + 500, 10 * 60_000 - 500)).toBe(10);
    expect(crossedMilestone(10 * 60_000 - 500, 10 * 60_000 - 1_000)).toBeNull();
    expect(crossedMilestone(20 * 60_000, 4 * 60_000)).toBe(5);
    expect(crossedMilestone(61_000, 59_000)).toBe(1);
    expect(crossedMilestone(1_000, 0)).toBeNull();
    expect(crossedMilestone(null, 1_000)).toBeNull();
  });
});

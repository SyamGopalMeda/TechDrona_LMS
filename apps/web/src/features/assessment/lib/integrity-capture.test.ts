import { describe, expect, it } from "vitest";
import { createEventThrottle, eventFilter, integrityWarning } from "./integrity-capture";
import type { ExamProtocol } from "./types";

const protocol = (extra: Partial<ExamProtocol> = {}): ExamProtocol => ({
  exam_mode: true,
  require_agreement: true,
  conduct_instructions: "Stay here",
  record_events: ["focus_lost", "window_blur", "copy"],
  require_fullscreen: false,
  type_thresholds: {},
  flag_threshold: 5,
  auto_submit_after: null,
  ai_hints: false,
  labels: {},
  ...extra,
});

describe("integrity capture", () => {
  it("filters events by protocol (legacy tests keep the historical set)", () => {
    const legacy = eventFilter(null);
    expect(legacy("paste")).toBe(true);
    expect(legacy("window_blur")).toBe(false);
    const exam = eventFilter(protocol());
    expect(exam("window_blur")).toBe(true);
    expect(exam("paste")).toBe(false);
    expect(exam("disconnect")).toBe(true);
  });

  it("rate-limits per type and caps the total", () => {
    const allow = createEventThrottle({ minGapMs: 1000, maxTotal: 3 });
    expect(allow("copy", 0)).toBe(true);
    expect(allow("copy", 500)).toBe(false);
    expect(allow("paste", 600)).toBe(true);
    expect(allow("copy", 1500)).toBe(true);
    expect(allow("resize", 5000)).toBe(false); // cap reached
  });

  it("words the banner by flag state", () => {
    expect(integrityWarning(1, false)).toMatch(/\(1 event\)/);
    expect(integrityWarning(5, true)).toMatch(/flagged for review/);
  });
});

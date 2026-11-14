import { describe, expect, it } from "vitest";
import type { PersistedAttempt } from "./local-store";
import { paletteCounts, paletteState, paletteAriaLabel } from "./palette";
import { isAnswered, planResume } from "./resume";

const local = (items: PersistedAttempt["items"], extra: Partial<PersistedAttempt> = {}): PersistedAttempt => ({
  v: 1,
  attemptId: "a1",
  nextSeq: 1,
  items,
  events: [],
  visited: [],
  updatedAt: 0,
  ...extra,
});

describe("planResume (TST-004)", () => {
  it("restores server answers on a fresh device with no local state", () => {
    const plan = planResume(
      [
        { question_version_id: "q1", response: { option_ids: ["a"] }, client_seq: 4, flagged: false },
        { question_version_id: "q2", response: null, client_seq: 5, flagged: true },
      ],
      null,
    );
    expect(plan.restoredCount).toBe(1);
    expect(plan.toSync).toEqual([]);
    expect(plan.nextSeq).toBe(6);
    expect(plan.hadLocalState).toBe(false);
    expect(plan.answers.get("q2")?.flagged).toBe(true);
  });

  it("queues local answers newer than the server copy and shows them immediately", () => {
    const plan = planResume(
      [{ question_version_id: "q1", response: { option_ids: ["a"] }, client_seq: 4, flagged: false }],
      local([
        { question_version_id: "q1", response: { option_ids: ["b"] }, client_seq: 9, time_spent_ms: 0, flagged: false },
        { question_version_id: "q3", response: { value: "12.5" }, client_seq: 10, time_spent_ms: 0, flagged: false },
      ], { nextSeq: 11 }),
    );
    expect(plan.toSync.map((i) => i.client_seq)).toEqual([9, 10]);
    expect(plan.answers.get("q1")?.response).toEqual({ option_ids: ["b"] });
    expect(plan.nextSeq).toBe(11);
    expect(plan.conflicts).toBe(0);
  });

  it("keeps the newer answer from another device and counts the conflict", () => {
    const plan = planResume(
      [{ question_version_id: "q1", response: { option_ids: ["c"] }, client_seq: 20, flagged: false }],
      local([{ question_version_id: "q1", response: { option_ids: ["b"] }, client_seq: 9, time_spent_ms: 0, flagged: false }]),
    );
    expect(plan.toSync).toEqual([]);
    expect(plan.conflicts).toBe(1);
    expect(plan.answers.get("q1")?.response).toEqual({ option_ids: ["c"] });
    expect(plan.nextSeq).toBe(21);
  });

  it("does not resend an answer the server already acknowledged (equal seq)", () => {
    const plan = planResume(
      [{ question_version_id: "q1", response: { option_ids: ["b"] }, client_seq: 9, flagged: false }],
      local([{ question_version_id: "q1", response: { option_ids: ["b"] }, client_seq: 9, time_spent_ms: 0, flagged: false }]),
    );
    expect(plan.toSync).toEqual([]);
    expect(plan.conflicts).toBe(0);
    expect(plan.hadLocalState).toBe(true);
  });

  it("keeps the sequence above stored integrity events and merges visited questions", () => {
    const plan = planResume([], local([], { events: [{ type: "paste", client_at: "x", client_seq: 30 }], visited: ["q7"] }));
    expect(plan.nextSeq).toBe(31);
    expect(plan.visited).toEqual(["q7"]);
  });
});

describe("palette states (§3.4)", () => {
  it("derives the five states and counts", () => {
    const answers = new Map([
      ["q1", { response: { option_ids: ["a"] }, flagged: false, client_seq: 1 }],
      ["q2", { response: null, flagged: true, client_seq: 2 }],
      ["q3", { response: { option_ids: ["a"] }, flagged: true, client_seq: 3 }],
    ]);
    const visited = new Set(["q1", "q2", "q3", "q4"]);
    expect(paletteState(answers.get("q1"), true)).toBe("answered");
    expect(paletteState(answers.get("q2"), true)).toBe("marked");
    expect(paletteState(answers.get("q3"), true)).toBe("answered_marked");
    expect(paletteState(undefined, true)).toBe("not_answered");
    expect(paletteState(undefined, false)).toBe("not_visited");
    expect(paletteCounts(["q1", "q2", "q3", "q4", "q5"], answers, visited)).toEqual({
      not_visited: 1,
      not_answered: 1,
      answered: 1,
      marked: 1,
      answered_marked: 1,
    });
    expect(paletteAriaLabel(12, "answered_marked", true)).toBe("Question 12, answered, marked for review, current");
  });

  it("treats empty selections and blank numeric answers as unanswered", () => {
    expect(isAnswered({ option_ids: [] })).toBe(false);
    expect(isAnswered({ value: "  " })).toBe(false);
    expect(isAnswered({ value: "0" })).toBe(true);
    expect(isAnswered(null)).toBe(false);
  });
});

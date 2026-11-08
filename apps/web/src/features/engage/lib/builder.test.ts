import { describe, expect, it } from "vitest";
import {
  appendQuestions,
  blankQuestion,
  fromActivity,
  fromDrafts,
  initialState,
  toActivityIn,
  toggleCorrect,
  validateBuilder,
  withKind,
  type BuilderState,
} from "./builder";
import type { Activity } from "./types";

function quiz(): BuilderState {
  const s = initialState("quiz");
  s.title = "  Arrays warm-up ";
  s.batch_id = "b1";
  const q = s.questions[0]!;
  q.prompt = "Index of the first element?";
  q.options[0]!.text = "0";
  q.options[1]!.text = "1";
  return s;
}

describe("activity builder", () => {
  it("requires a ticked correct option for quiz questions", () => {
    const s = quiz();
    expect(validateBuilder(s)["questions[0].options"]).toBe("Tick the correct answer.");
    s.questions[0] = toggleCorrect(s.questions[0]!, s.questions[0]!.options[0]!.key);
    expect(validateBuilder(s)).toEqual({});
  });

  it("does not require a correct option for polls and drops correct flags", () => {
    const s = initialState("poll");
    s.title = "Lunch?";
    s.batch_id = "b1";
    s.questions[0]!.prompt = "Where?";
    s.questions[0]!.options = s.questions[0]!.options.map((o, i) => ({ ...o, text: `Place ${i}`, is_correct: true }));
    expect(validateBuilder(s)).toEqual({});
    const body = toActivityIn(s);
    expect(body.winner_rule).toBeNull();
    expect(body.questions[0]!.options.every((o) => !o.is_correct)).toBe(true);
  });

  it("requires a window when scheduled, closing after opening and in the future", () => {
    const s = quiz();
    s.questions[0] = toggleCorrect(s.questions[0]!, s.questions[0]!.options[0]!.key);
    s.run_mode = "scheduled";
    const e = validateBuilder(s);
    expect(e.opens_at).toBeDefined();
    expect(e.closes_at).toBeDefined();
    s.opens_at = "2030-01-02T10:00";
    s.closes_at = "2030-01-02T09:00";
    expect(validateBuilder(s).closes_at).toMatch(/after/);
    s.closes_at = "2030-01-02T11:00";
    expect(validateBuilder(s, new Date("2026-11-06T00:00:00Z"))).toEqual({});
    const body = toActivityIn(s);
    expect(body.opens_at).toBe(new Date("2030-01-02T10:00").toISOString());
    expect(body.closes_at).toBe(new Date("2030-01-02T11:00").toISOString());
  });

  it("serializes the ActivityIn body shape", () => {
    const s = quiz();
    s.questions[0] = toggleCorrect(s.questions[0]!, s.questions[0]!.options[1]!.key);
    s.participant_limit = "30";
    s.opens_at = "2030-01-02T10:00"; // ignored when instant
    expect(toActivityIn(s)).toEqual({
      activity_type: "quiz",
      title: "Arrays warm-up",
      description: null,
      batch_id: "b1",
      run_mode: "instant",
      audience: "members",
      identity_mode: "named",
      results_mode: "on_publish",
      pacing: "one_by_one",
      winner_rule: "fastest_first",
      participant_limit: 30,
      opens_at: null,
      closes_at: null,
      questions: [
        {
          kind: "single_choice",
          prompt: "Index of the first element?",
          options: [
            { text: "0", is_correct: false },
            { text: "1", is_correct: true },
          ],
          max_words: null,
          source_question_id: null,
          source_version_id: null,
        },
      ],
    });
  });

  it("validates batch, title, participant limit and word count", () => {
    const s = initialState("word_cloud");
    s.participant_limit = "0";
    s.questions[0]!.max_words = 9;
    const e = validateBuilder(s);
    expect(e.title).toBeDefined();
    expect(e.batch_id).toBeDefined();
    expect(e.participant_limit).toBeDefined();
    expect(e["questions[0].prompt"]).toBeDefined();
    expect(e["questions[0].max_words"]).toBeDefined();
    expect(toActivityIn(s).questions[0]).toMatchObject({ kind: "word", options: [], max_words: 9 });
  });

  it("no batch means a platform activity: allowed only when chosen explicitly, never sends organization_id", () => {
    const s = quiz();
    s.questions[0] = toggleCorrect(s.questions[0]!, s.questions[0]!.options[0]!.key);
    s.batch_id = null;
    expect(validateBuilder(s).batch_id).toBeDefined();
    s.platform_wide = true;
    expect(validateBuilder(s)).toEqual({});
    const body = toActivityIn(s);
    expect(body.batch_id).toBeNull();
    expect(body).not.toHaveProperty("organization_id");
  });

  it("single choice keeps only one correct option; text kinds have no options", () => {
    let q = withKind(blankQuestion("survey"), "multi_choice");
    q = toggleCorrect(q, q.options[0]!.key);
    q = toggleCorrect(q, q.options[1]!.key);
    expect(q.options.filter((o) => o.is_correct)).toHaveLength(2);
    expect(withKind(q, "single_choice").options.filter((o) => o.is_correct)).toHaveLength(1);
    expect(withKind(q, "rating").options).toEqual([]);
  });

  it("round-trips an existing activity keeping option ids", () => {
    const a = {
      id: "a1",
      activity_type: "quiz",
      title: "T",
      description: null,
      organization_id: "o1",
      batch_id: "b1",
      owner_id: "u1",
      run_mode: "instant",
      audience: "public",
      identity_mode: "anonymous",
      results_mode: "live",
      pacing: "all_at_once",
      winner_rule: "all_correct",
      participant_limit: null,
      opens_at: null,
      closes_at: null,
      created_at: null,
      updated_at: null,
      question_count: 1,
      questions: [
        {
          id: "q1",
          position: 0,
          kind: "single_choice",
          prompt: "P",
          options: [
            { id: "o-a", text: "A", is_correct: true },
            { id: "o-b", text: "B", is_correct: false },
          ],
          max_words: null,
          source_question_id: null,
        },
      ],
    } satisfies Activity;
    const body = toActivityIn(fromActivity(a));
    expect(body).toMatchObject({ audience: "public", identity_mode: "anonymous", winner_rule: "all_correct", batch_id: "b1" });
    expect(fromActivity({ ...a, batch_id: null }).platform_wide).toBe(true);
    expect(body.questions[0]!.options).toEqual([
      { id: "o-a", text: "A", is_correct: true },
      { id: "o-b", text: "B", is_correct: false },
    ]);
    expect(body.questions[0]).not.toHaveProperty("id");
  });

  it("appends bank drafts, replacing the blank starter question", () => {
    const drafts = fromDrafts(
      [
        {
          kind: "single_choice",
          prompt: "Imported",
          options: [
            { text: "x", is_correct: true },
            { text: "y", is_correct: false },
          ],
          max_words: null,
          source_question_id: "sq",
          source_version_id: "sv",
          key_copied: false,
        },
      ],
      "quiz",
    );
    const list = appendQuestions(initialState("quiz").questions, drafts);
    expect(list).toHaveLength(1);
    expect(list[0]).toMatchObject({ prompt: "Imported", source_question_id: "sq", key_missing: true });
  });
});

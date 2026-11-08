// Regressions for the assess-backend follow-ups: ATT-13 cursor (BE-21), coding review
// `your_submission` (BE-23), 429 + Retry-After on attempt routes (BE-09), no client batch_id (BE-02).
import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { cleanEntity } from "@/lib/analytics/envelope";
import { ApiError } from "@/lib/api/errors";
import type { ProblemDetails } from "@/lib/api/problem";
import { ResultsView } from "../components/ResultsView";
import { assessmentApi } from "./api";
import { AutosaveQueue } from "./autosave-queue";
import { memoryStore } from "./local-store";
import type { AutosaveResponse } from "./types";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

let restore: (() => void) | undefined;
afterEach(() => {
  restore?.();
  vi.useRealTimers();
});

const attempt = (id: string, testId: string) => ({ attempt_id: id, test_id: testId, test_title: "T", attempt_no: 1, status: "graded", started_at: "2026-11-01T00:00:00Z", deadline_at: null, submitted_at: "2026-11-01T01:00:00Z", submit_reason: "user" });

describe("ATT-13 pagination (BE-21)", () => {
  it("follows page.next_cursor so older attempts still count", async () => {
    const api = mockApi({
      "GET me/tests": { body: { items: [{ test_id: "t1", title: "One" }, { test_id: "t2", title: "Two" }] } },
      "GET me/attempts": (c) =>
        c.url.includes("cursor=c2")
          ? { body: { items: [attempt("a2", "t2")], page: { next_cursor: null, has_more: false, limit: 100 } } }
          : { body: { items: [attempt("a1", "t1")], page: { next_cursor: "c2", has_more: true, limit: 100 } } },
    });
    restore = api.restore;
    const rows = await assessmentApi.listTests();
    expect(api.calls.filter((c) => c.path === "me/attempts")).toHaveLength(2);
    expect(rows.find((r) => r.test_id === "t2")?.last_attempt?.attempt_id).toBe("a2");
  });
});

describe("coding review (BE-23)", () => {
  it("shows the learner's own code and case verdicts on a coding item", async () => {
    const api = mockApi({
      "GET attempts/a1/result": { body: { attempt_id: "a1", status: "graded", phase: "after_submit", visible: { score: true }, score: 5, max_score: 10, percentage: 50 } },
      "GET attempts/a1/review": {
        body: {
          attempt_id: "a1",
          phase: "after_submit",
          visible: { correctness: true },
          sections: [
            {
              section_id: "s1",
              title: "Coding",
              questions: [
                {
                  question_version_id: "q1",
                  type: "coding",
                  stem_html: "<p>Reverse a string</p>",
                  coding_problem_id: "cp1",
                  your_response: { submission_id: "sub1" },
                  time_spent_ms: 1000,
                  flagged: false,
                  is_correct: false,
                  your_submission: {
                    submission_id: "sub1",
                    language_key: "python3",
                    source_code: "print(input()[::-1])",
                    verdict: "PARTIAL",
                    passed_cases: 1,
                    total_cases: 2,
                    cases: [
                      { ordinal: 1, is_sample: true, verdict: "AC" },
                      { ordinal: 2, is_sample: false, verdict: "WA" },
                    ],
                  },
                },
              ],
            },
          ],
        },
      },
    });
    restore = api.restore;
    renderWithProviders(<ResultsView attemptId="a1" />);
    expect(await screen.findByText("print(input()[::-1])")).toBeInTheDocument();
    expect(screen.getByText(/1\/2 test cases passed/)).toBeInTheDocument();
    expect(screen.getByText(/Case 2 \(hidden\)/)).toBeInTheDocument();
    expect(screen.queryByText(/answer key isn't released/)).not.toBeInTheDocument();
  });
});

describe("attempt rate limit (BE-09)", () => {
  it("waits at least the Retry-After before resending autosave", async () => {
    vi.useFakeTimers();
    const ok: AutosaveResponse = { acked_seq: 1, server_now: "2026-11-03T10:00:00Z", deadline_at: "2026-11-03T11:00:00Z", section_deadline_at: null, status: "in_progress" };
    let n = 0;
    const send = vi.fn(async () => {
      n += 1;
      if (n === 1) throw new ApiError(429, { type: "x", title: "rate_limited", status: 429, code: "rate_limited" } as ProblemDetails, "r", undefined, 30);
      return ok;
    });
    const q = new AutosaveQueue({ attemptId: "a1", send, store: memoryStore(), debounceMs: 250, maxIntervalMs: 1_000, backoffMs: [1_000, 2_000] });
    q.setAnswer("q1", { option_ids: ["o"] }, false, 0);
    await vi.advanceTimersByTimeAsync(250);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(29_000);
    expect(send).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1_500);
    expect(send).toHaveBeenCalledTimes(2);
    q.stop();
  });
});

describe("activity tracker entity (BE-02 / E2E-05)", () => {
  it("never sends batch_id", () => {
    const id = "0192f0a0-0000-7000-8000-000000000001";
    expect(cleanEntity({ course_id: id, batch_id: id } as never)).toEqual({ course_id: id });
  });
});

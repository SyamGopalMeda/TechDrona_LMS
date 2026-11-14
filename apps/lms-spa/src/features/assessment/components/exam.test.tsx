import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { memoryStore } from "../lib/local-store";
import type { AttemptPayload, ExamProtocol, IntegritySummary } from "../lib/types";
import { AttemptRunner } from "./AttemptRunner";
import { ExamEvaluation, gradingLine } from "./ExamEvaluation";
import { SubmittedView } from "./SubmittedView";
import { TestInstructions } from "./TestInstructions";

const push = vi.fn();
const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace }) }));

let restore: (() => void) | undefined;
afterEach(() => {
  restore?.();
  push.mockReset();
  replace.mockReset();
});

const NOW = new Date().toISOString();
const DEADLINE = new Date(Date.now() + 30 * 60_000).toISOString();

const protocol: ExamProtocol = {
  exam_mode: true,
  require_agreement: true,
  conduct_instructions: "Keep this page open until you submit.",
  record_events: ["focus_lost", "window_blur", "copy", "paste"],
  require_fullscreen: false,
  type_thresholds: { focus_lost: 3, window_blur: 3, copy: 3, paste: 3 },
  flag_threshold: 5,
  auto_submit_after: null,
  ai_hints: false,
  labels: { focus_lost: "Tab switches", window_blur: "Window inactive", copy: "Copy", paste: "Paste" },
};

const summary = (extra: Partial<IntegritySummary> = {}): IntegritySummary => ({
  exam_mode: true,
  counts: { focus_lost: 0, window_blur: 0, copy: 0, paste: 0 },
  total: 0,
  over_threshold: [],
  flag_threshold: 5,
  flagged: false,
  integrity_status: "none",
  ...extra,
});

function payload(extra: Partial<AttemptPayload> = {}): AttemptPayload {
  return {
    attempt_id: "a1",
    status: "in_progress",
    attempt_no: 1,
    test: { id: "t1", version: 1, title: "Python Lists Exam", navigation_mode: "free", grace_seconds: 30 },
    started_at: NOW,
    server_now: NOW,
    deadline_at: DEADLINE,
    sections: [
      {
        section_id: "s1",
        title: "Programming",
        position: 1,
        status: "active",
        deadline_at: null,
        duration_seconds: null,
        question_count: 1,
        questions: [{ question_version_id: "q1", type: "numeric", topic_id: "tp", difficulty: 1, stem_html: "<p>2 + 2?</p>", options: [] }],
      },
    ],
    binding: { bound_session_id: "current", rebinds_remaining: 2 },
    autosave: { debounce_ms: 100, max_interval_ms: 500, max_items: 50 },
    responses: [],
    protocol,
    integrity: summary(),
    ...extra,
  };
}

describe("Exam agreement screen", () => {
  const detail = {
    id: "t1",
    title: "Python Lists Exam",
    test_kind: "mock",
    version: 1,
    duration_seconds: 1800,
    grace_seconds: 30,
    navigation_mode: "free",
    pass_percentage: null,
    marking: "",
    sections: [{ section_id: "s1", title: "Programming", position: 1, question_count: 1, duration_seconds: null, instructions_md: null }],
    integrity_notice: { settings: { exam_mode: true }, text: "" },
    protocol,
    window: { available_from: null, available_until: null, window_extension_seconds: 0 },
    attempts_allowed: 1,
    attempts_left: 1,
    eligibility: { eligible: true, via: "assignment", test_assignment_id: "ta1" },
    server_now: NOW,
  };

  it("shows conduct + recorded events and starts only after agreement", async () => {
    const api = mockApi({ "GET tests/t1": { body: detail }, "POST attempts": { status: 201, body: payload() } });
    restore = api.restore;
    renderWithProviders(<TestInstructions testId="t1" />);
    const start = await screen.findByRole("button", { name: "Agree and start exam" });
    expect(screen.getByText("Keep this page open until you submit.")).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "Recorded events" })).getByText("Window inactive")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("I've read the instructions"));
    expect(start).toBeDisabled();
    await userEvent.click(screen.getByLabelText(/I agree to the exam conduct instructions/));
    await userEvent.click(start);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/app/attempts/a1"));
    expect(api.calls.find((c) => c.path === "attempts")!.body).toMatchObject({ instructions_agreed: true });
  });
});

describe("Exam runner integrity", () => {
  it("records a copy event, sends it with autosave and shows the server's count in a warning banner", async () => {
    const api = mockApi({
      "GET attempts/a1/state": { body: payload() },
      "POST attempts/a1/autosave": (c) => {
        const events = (c.body as { events: { client_seq: number }[] }).events;
        return {
          body: {
            acked_seq: events.at(-1)?.client_seq ?? null,
            server_now: NOW,
            deadline_at: DEADLINE,
            section_deadline_at: null,
            status: "in_progress",
            integrity: summary({ counts: { copy: 5 }, total: 5, flagged: true, integrity_status: "review_recommended" }),
          },
        };
      },
    });
    restore = api.restore;
    renderWithProviders(<AttemptRunner attemptId="a1" store={memoryStore()} />);
    await screen.findByText("2 + 2?");
    expect(screen.queryByTestId("integrity-banner")).toBeNull();
    document.dispatchEvent(new Event("copy"));
    expect(await screen.findByTestId("integrity-banner")).toHaveTextContent("(1 event)");
    await waitFor(() => expect(screen.getByTestId("integrity-banner")).toHaveTextContent(/5 events.*flagged for review/), { timeout: 3000 });
    const sent = api.calls.find((c) => c.path === "attempts/a1/autosave")!.body as { events: { type: string }[] };
    expect(sent.events.map((e) => e.type)).toEqual(["copy"]);
    // right_click isn't in this exam's record_events: not reported
    document.dispatchEvent(new Event("contextmenu"));
    expect(api.calls.filter((c) => c.path === "attempts/a1/autosave").every((c) => !JSON.stringify(c.body).includes("right_click"))).toBe(true);
  });
});

describe("Submitted view", () => {
  it("shows the flagged-for-review notice from the server", async () => {
    const api = mockApi({
      "GET attempts/a1/result": problem(409, "results_not_released", "results_not_released", { release_mode: "manual" }),
      "GET attempts/a1/state": { body: { ...payload({ status: "graded", sections: [] }), integrity_flagged: true } },
    });
    restore = api.restore;
    renderWithProviders(<SubmittedView attemptId="a1" />);
    expect(await screen.findByTestId("flagged-notice")).toHaveTextContent(/flagged for review/);
  });
});

describe("Exam evaluation", () => {
  const list = {
    test: { id: "t1", title: "Python Lists Exam", status: "published" },
    protocol,
    assignments: [{ id: "ta1", batch_id: "b1", release_mode: "manual", results_release_at: null }],
    totals: { attempts: 1, finalized: 0, ai_pending: 0, manual_pending: 1, flagged: 1 },
    items: [
      {
        attempt_id: "a1",
        user_id: "u1",
        learner_name: "Asha",
        attempt_no: 1,
        test_assignment_id: "ta1",
        status: "awaiting_manual",
        submit_reason: "user",
        submitted_at: NOW,
        score: "2.00",
        max_score: "12.00",
        released: false,
        grading: { items: 2, finalized: 1, ai_pending: 0, manual_pending: 1, manual_items: 1 },
        integrity: summary({
          counts: { focus_lost: 2, window_blur: 3 },
          total: 5,
          flagged: true,
          over_threshold: [{ type: "window_blur", label: "Window inactive", count: 3, threshold: 3 }],
        }),
      },
    ],
  };

  it("lists integrity badges and grading progress; AI errors use the shared AI state", async () => {
    const api = mockApi({
      "GET tests/t1/evaluation": { body: list },
      "POST tests/t1/evaluation/ai-grade": problem(403, "ai_disabled", "ai_disabled"),
    });
    restore = api.restore;
    renderWithProviders(<ExamEvaluation testId="t1" />);
    expect(await screen.findByText("Tab switches: 2")).toBeInTheDocument();
    expect(screen.getByText("Window inactive: 3 (≥3)")).toBeInTheDocument();
    expect(screen.getByText(/1 \/ 2 finalized · 1 to grade/)).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: "Run AI grading" })[0]!);
    expect(await screen.findByRole("alert")).toHaveAttribute("data-ai-code", "ai_disabled");
  });

  it("explains a refusal instead of an error with a useless Try again (WS-UI 0.4)", async () => {
    const api = mockApi({ "GET tests/t1/evaluation": problem(403, "permission_denied", "You don't have permission to do this") });
    restore = api.restore;
    renderWithProviders(<ExamEvaluation testId="t1" />);
    expect(await screen.findByText("You can't evaluate this test")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /try again/i })).not.toBeInTheDocument();
  });

  it("keeps Publish results secondary with a reason while answers are not finalized", async () => {
    const api = mockApi({ "GET tests/t1/evaluation": { body: list } });
    restore = api.restore;
    renderWithProviders(<ExamEvaluation testId="t1" />);
    const publish = await screen.findByRole("button", { name: "Publish results" });
    expect(publish.className.split(" ")).not.toContain("bg-brand"); // not the primary fill
    expect(publish).toHaveAccessibleDescription("1 answer is not finalized yet. Finalize them before publishing.");
  });

  it("formats the grading line", () => {
    expect(gradingLine({ items: 20, finalized: 0, ai_pending: 2, manual_pending: 0, manual_items: 2 })).toBe("0 / 20 finalized · 2 AI pending");
  });
});

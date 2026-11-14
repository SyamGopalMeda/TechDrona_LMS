import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { memoryStore } from "../lib/local-store";
import type { AttemptPayload } from "../lib/types";
import { AttemptRunner } from "./AttemptRunner";
import { ResultsView } from "./ResultsView";
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
const DEADLINE = new Date(Date.now() + 40 * 60_000).toISOString();

function payload(extra: Partial<AttemptPayload> = {}): AttemptPayload {
  return {
    attempt_id: "a1",
    status: "in_progress",
    attempt_no: 1,
    test: { id: "t1", version: 1, title: "TCS NQT Mock 3", navigation_mode: "free", grace_seconds: 30 },
    started_at: NOW,
    server_now: NOW,
    deadline_at: DEADLINE,
    sections: [
      {
        section_id: "s1",
        title: "Quant",
        position: 1,
        status: "active",
        deadline_at: null,
        duration_seconds: null,
        question_count: 2,
        questions: [
          {
            question_version_id: "q1",
            type: "mcq_single",
            topic_id: "tp1",
            difficulty: 2,
            stem_html: "<p>A train 240 m long passes a pole in 12 s.</p>",
            options: [
              { option_id: "o1", label: "A", html: "18 km/h" },
              { option_id: "o2", label: "B", html: "72 km/h" },
            ],
            marks: "1.00",
            negative_marks: "0.25",
          },
          { question_version_id: "q2", type: "numeric", topic_id: "tp1", difficulty: 1, stem_html: "<p>2 + 2?</p>", options: [] },
        ],
      },
    ],
    binding: { bound_session_id: "current", rebinds_remaining: 2 },
    autosave: { debounce_ms: 250, max_interval_ms: 1_000, max_items: 50 },
    responses: [],
    ...extra,
  };
}

const ack = (seq: number) => ({ body: { acked_seq: seq, server_now: NOW, deadline_at: DEADLINE, section_deadline_at: null, status: "in_progress" } });

describe("AttemptRunner (TST-002)", () => {
  it("shows the server-derived timer and autosaves a change with a client_seq", async () => {
    const api = mockApi({
      "GET attempts/a1/state": { body: payload() },
      "POST attempts/a1/autosave": (c) => ack((c.body as { items: { client_seq: number }[] }).items.at(-1)!.client_seq),
    });
    restore = api.restore;
    const store = memoryStore();
    renderWithProviders(<AttemptRunner attemptId="a1" store={store} />);

    expect(await screen.findByText(/A train 240 m long/)).toBeInTheDocument();
    expect(screen.getByRole("timer")).toHaveAccessibleName(/Time left: (39|40) minutes/);
    expect(await screen.findByRole("button", { name: "Question 1, not answered, current" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("radio", { name: /72 km\/h/ }));
    expect(store.load("a1")?.items[0]).toMatchObject({ question_version_id: "q1", client_seq: 1 });

    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.path === "attempts/a1/autosave")).toBe(true), { timeout: 5_000 });
    const save = api.calls.find((c) => c.path === "attempts/a1/autosave")!;
    expect(save.body).toMatchObject({ items: [{ question_version_id: "q1", response: { option_ids: ["o2"] }, client_seq: 1, flagged: false }], current_section_id: "s1" });
    await waitFor(() => expect(store.load("a1")?.items).toEqual([]), { timeout: 5_000 });
    expect(screen.getByRole("button", { name: "Question 1, answered, current" })).toBeInTheDocument();
  });

  it("shows the 'open on another device' flow and rebinds after confirmation", async () => {
    const api = mockApi({
      "GET attempts/a1/state": problem(409, "attempt_bound_elsewhere", "attempt_bound_elsewhere", {
        bound_device_label: "Chrome on Windows",
        rebind_allowed: true,
        rebinds_remaining: 2,
        otp_required: false,
        trainer_override_required: false,
        read_only: { answered_count: 14, deadline_at: DEADLINE, server_now: NOW },
      }),
      "POST attempts/a1/rebind": { body: payload() },
    });
    restore = api.restore;
    renderWithProviders(<AttemptRunner attemptId="a1" store={memoryStore()} />);

    expect(await screen.findByRole("heading", { name: "This test is open on another device" })).toBeInTheDocument();
    expect(screen.getByText(/in progress on Chrome on Windows/)).toBeInTheDocument();
    expect(screen.getByText(/You can do this 2 more times for this test/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Continue on this device" }));
    await waitFor(() => expect(screen.getByText(/A train 240 m long/)).toBeInTheDocument());
    const rebind = api.calls.find((c) => c.path === "attempts/a1/rebind")!;
    expect(rebind.body).toEqual({ confirm: true, otp_code: null });
    expect(rebind.headers["idempotency-key"]).toBeTruthy();
  });

  it("hides 'Continue' on supervised drives", async () => {
    const api = mockApi({
      "GET attempts/a1/state": problem(409, "attempt_bound_elsewhere", "attempt_bound_elsewhere", { bound_device_label: "Lab PC", trainer_override_required: true, rebinds_remaining: 2 }),
    });
    restore = api.restore;
    renderWithProviders(<AttemptRunner attemptId="a1" store={memoryStore()} />);
    expect(await screen.findByText(/This is a supervised drive/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Continue on this device" })).not.toBeInTheDocument();
  });

  it("resumes after a refresh: restores answers, syncs answers saved on this device", async () => {
    const store = memoryStore([
      {
        v: 1,
        attemptId: "a1",
        nextSeq: 10,
        items: [{ question_version_id: "q2", response: { value: "4" }, client_seq: 9, time_spent_ms: 1_000, flagged: false }],
        events: [],
        visited: ["q1", "q2"],
        updatedAt: 0,
      },
    ]);
    const api = mockApi({
      "POST attempts/a1/resume": {
        body: payload({ responses: [{ question_version_id: "q1", response: { option_ids: ["o1"] }, client_seq: 3, flagged: false }] }),
      },
      "POST attempts/a1/autosave": ack(9),
    });
    restore = api.restore;
    renderWithProviders(<AttemptRunner attemptId="a1" store={store} />);

    const dialog = await screen.findByRole("dialog", { name: "Welcome back — your test is safe" });
    expect(within(dialog).getByText(/We've restored 1 answers/)).toBeInTheDocument();
    await waitFor(() => expect(within(dialog).getByText(/All answers synced/)).toBeInTheDocument(), { timeout: 5_000 });
    const save = api.calls.find((c) => c.path === "attempts/a1/autosave")!;
    expect(save.body).toMatchObject({ items: [{ question_version_id: "q2", client_seq: 9, response: { value: "4" } }] });
    expect(api.calls.some((c) => c.path === "attempts/a1/state")).toBe(false);

    await userEvent.click(within(dialog).getByRole("button", { name: "Resume test" }));
    expect(screen.getByRole("button", { name: "Question 1, answered, current" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Question 2, answered" })).toBeInTheDocument();
  });

  it("shows an answer the server refused as not saved, and counts it as not answered at submission", async () => {
    const api = mockApi({
      "GET attempts/a1/state": { body: payload() },
      "POST attempts/a1/autosave": (c) => {
        const seq = (c.body as { items: { client_seq: number }[] }).items.at(-1)!.client_seq;
        return { body: { ...ack(seq).body, rejected: [{ question_version_id: "q2", client_seq: seq, field: "response.value", code: "invalid", message: "must be a number" }] } };
      },
    });
    restore = api.restore;
    renderWithProviders(<AttemptRunner attemptId="a1" store={memoryStore()} />);
    await screen.findByText(/A train 240 m long/);
    await userEvent.click(screen.getByRole("button", { name: /Question 2,/ }));
    await userEvent.type(await screen.findByRole("textbox"), "abc");
    expect(await screen.findByText(/Your answer to this question was not saved: must be a number/, undefined, { timeout: 5_000 })).toBeInTheDocument();
    expect(screen.getByText("1 answer not saved")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Submit test" }));
    const dialog = await screen.findByRole("dialog", { name: "Submit test?" });
    expect(within(dialog).getByText(/1 answer was not saved because it is not valid/)).toBeInTheDocument();
    expect(within(dialog).getByText("2 questions are not answered.")).toBeInTheDocument();
  });

  it("confirms and submits the test with an Idempotency-Key, then goes to TST-005", async () => {
    const api = mockApi({
      "GET attempts/a1/state": { body: payload() },
      "POST attempts/a1/submit": { body: { status: "submitted", submitted_at: NOW, submit_reason: "user", redirect: "/app/attempts/a1/submitted" } },
    });
    restore = api.restore;
    const store = memoryStore();
    renderWithProviders(<AttemptRunner attemptId="a1" store={store} />);
    await screen.findByText(/A train 240 m long/);

    await userEvent.click(screen.getByRole("button", { name: "Submit test" }));
    const dialog = await screen.findByRole("dialog", { name: "Submit test?" });
    expect(within(dialog).getByText("2 questions are not answered.")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Submit test" }));

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/app/attempts/a1/submitted"));
    const submit = api.calls.find((c) => c.path === "attempts/a1/submit")!;
    expect(submit.body).toEqual({ final_items: [], confirm_unanswered: 2 });
    expect(submit.headers["idempotency-key"]).toBeTruthy();
    expect(store.load("a1")).toBeNull();
  });

  it("goes to the submitted page when the attempt was already auto-submitted", async () => {
    const api = mockApi({ "GET attempts/a1/state": { body: payload({ status: "auto_submitted" }) } });
    restore = api.restore;
    renderWithProviders(<AttemptRunner attemptId="a1" store={memoryStore()} />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/app/attempts/a1/submitted?reason=deadline"));
  });
});

describe("TestInstructions (TST-001)", () => {
  // Shape of router.py asm_02_test_detail.
  const test = {
    id: "t1",
    title: "TCS NQT Full Mock 3",
    test_kind: "mock",
    version: 1,
    duration_seconds: 5400,
    grace_seconds: 30,
    navigation_mode: "section_locked",
    pass_percentage: null,
    marking: "Per question as shown; negative marks apply to wrong answers only, unanswered = 0.",
    sections: [{ section_id: "s1", title: "Quant", position: 1, question_count: 30, duration_seconds: 2400, instructions_md: null }],
    integrity_notice: { settings: { consent_mandatory: true }, text: "Focus changes are logged as advisory signals only." },
    window: { available_from: null, available_until: null, window_extension_seconds: 0 },
    attempts_allowed: 3,
    attempts_left: 3,
    eligibility: { eligible: true, via: "assignment", test_assignment_id: "ta1" },
    server_now: NOW,
  };

  it("requires reading + integrity consent, starts with an Idempotency-Key and opens the runner", async () => {
    const api = mockApi({ "GET tests/t1": { body: test }, "POST attempts": { status: 201, body: payload() } });
    restore = api.restore;
    renderWithProviders(<TestInstructions testId="t1" />);
    const start = await screen.findByRole("button", { name: "Start test" });
    expect(start).toBeDisabled();
    await userEvent.click(screen.getByLabelText("I've read the instructions"));
    expect(start).toBeDisabled();
    await userEvent.click(screen.getByLabelText(/I agree to integrity events/));
    await userEvent.click(start);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/app/attempts/a1"));
    const call = api.calls.find((c) => c.path === "attempts")!;
    expect(call.body).toMatchObject({ test_id: "t1", test_assignment_id: "ta1", integrity_consent: true });
    expect(call.headers["idempotency-key"]).toBeTruthy();
  });

  it("resumes an existing in-progress attempt instead of failing", async () => {
    const api = mockApi({ "GET tests/t1": { body: { ...test, integrity_notice: { settings: {}, text: "" } } }, "POST attempts": problem(409, "active_attempt_exists", "active_attempt_exists", { attempt_id: "a9" }) });
    restore = api.restore;
    renderWithProviders(<TestInstructions testId="t1" />);
    await userEvent.click(await screen.findByLabelText("I've read the instructions"));
    await userEvent.click(screen.getByRole("button", { name: "Start test" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/app/attempts/a9"));
  });
});

describe("ResultsView (STU-010)", () => {
  it("shows the key only when the review policy releases it", async () => {
    const api = mockApi({
      "GET attempts/a1/result": {
        body: { attempt_id: "a1", status: "graded", phase: "after_submit", visible: { score: true, rank: true }, score: 61.75, max_score: 90, percentage: 68.61, percentile: null, percentile_note: "insufficient_cohort" },
      },
      "GET attempts/a1/review": {
        body: {
          attempt_id: "a1",
          phase: "after_submit",
          visible: { correctness: true, answer_key: false, explanation: false },
          sections: [
            {
              section_id: "s1",
              title: "Quant",
              questions: [
                { question_version_id: "q1", type: "mcq_single", stem_html: "<p>Q one</p>", options: [{ option_id: "o1", label: "A", html: "A1" }], your_response: { option_ids: ["o1"] }, time_spent_ms: 0, flagged: false },
                { question_version_id: "q2", type: "mcq_single", stem_html: "<p>Q two</p>", options: [{ option_id: "o2", label: "A", html: "B1" }, { option_id: "o3", label: "B", html: "B2" }], your_response: { option_ids: ["o2"] }, time_spent_ms: 4000, flagged: false, is_correct: false, correct_option_ids: ["o3"] },
              ],
            },
          ],
        },
      },
    });
    restore = api.restore;
    renderWithProviders(<ResultsView attemptId="a1" />);
    expect(await screen.findByText("61.75 / 90")).toBeInTheDocument();
    expect(screen.getByText("Too few students to show a percentile")).toBeInTheDocument();
    await screen.findByText("Q one");
    expect(screen.getAllByText("Correct answer")).toHaveLength(1);
    expect(screen.getByText(/answer key isn't released/)).toBeInTheDocument();
  });

  it("shows the release date before results are released", async () => {
    const api = mockApi({ "GET attempts/a1/result": problem(409, "results_not_released", "results_not_released", { release_mode: "scheduled", release_at: "2026-11-05T04:30:00.000Z" }) });
    restore = api.restore;
    renderWithProviders(<ResultsView attemptId="a1" />);
    expect(await screen.findByText("Results on 5 Nov 2026, 10:00 IST")).toBeInTheDocument();
  });
});

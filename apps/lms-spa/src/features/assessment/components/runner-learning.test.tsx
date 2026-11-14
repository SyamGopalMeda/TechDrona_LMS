import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { useActivityTracker } from "@/lib/analytics/use-activity-tracker";
import { memoryStore } from "../lib/local-store";
import type { AttemptPayload, QuestionDelivery } from "../lib/types";
import { AttemptRunner, inertOutside } from "./AttemptRunner";
import { QuestionView } from "./QuestionView";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace }) }));

const tracker = vi.hoisted(() => {
  const noop = () => undefined;
  return {
    video: { play: noop, pause: noop, seek: noop, rateChange: noop, ended: noop, bufferingStart: noop, bufferingEnd: noop, error: noop, timeUpdate: noop },
    event: vi.fn(),
    editor: { focus: vi.fn(), blur: vi.fn(), edit: vi.fn() },
    scrollDepth: vi.fn(),
  };
});
vi.mock("@/lib/analytics/use-activity-tracker", () => ({ getTabId: () => "tab-1", useActivityTracker: vi.fn(() => tracker) }));

// The coding workspace is covered in coding tests; here we only need its submit callback.
const codingProps = vi.hoisted(() => ({ last: null as null | Record<string, unknown> }));
vi.mock("@/features/coding/components/CodingQuestion", () => ({
  CodingQuestion: (p: { problemId: string; attemptId: string; onSubmitted?: (id: string) => void }) => {
    codingProps.last = p;
    return (
      <button type="button" onClick={() => p.onSubmitted?.("01900000-0000-7000-8000-00000000sub1".replace("sub1", "5ab1"))}>
        Fake submit code
      </button>
    );
  },
}));

let restore: (() => void) | undefined;
beforeEach(() => {
  tracker.event.mockClear();
  vi.mocked(useActivityTracker).mockClear();
});
afterEach(() => {
  restore?.();
  replace.mockReset();
  vi.useRealTimers();
});

const NOW = new Date().toISOString();
const ATTEMPT = "01900000-0000-7000-8000-0000000000a1";
const TEST = "01900000-0000-7000-8000-0000000000e1";

function payload(extra: Partial<AttemptPayload> = {}, deadline = new Date(Date.now() + 40 * 60_000).toISOString()): AttemptPayload {
  return {
    attempt_id: ATTEMPT,
    status: "in_progress",
    attempt_no: 1,
    test: { id: TEST, version: 1, title: "Mock", navigation_mode: "free", grace_seconds: 30 },
    started_at: NOW,
    server_now: NOW,
    deadline_at: deadline,
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
          { question_version_id: "q1", type: "numeric", topic_id: "tp", difficulty: 1, stem_html: "<p>1 + 1?</p>", options: [] },
          { question_version_id: "q2", type: "numeric", topic_id: "tp", difficulty: 1, stem_html: "<p>2 + 2?</p>", options: [] },
        ],
      },
    ],
    binding: { bound_session_id: "current", rebinds_remaining: 2 },
    autosave: { debounce_ms: 250, max_interval_ms: 1_000, max_items: 50 },
    responses: [],
    ...extra,
  };
}

describe("AttemptRunner learning signals and layout", () => {
  it("FE-07/FE-16: mounts the activity tracker on the test surface and emits assessment.question_viewed", async () => {
    const api = mockApi({ [`GET attempts/${ATTEMPT}/state`]: { body: payload() } });
    restore = api.restore;
    renderWithProviders(<AttemptRunner attemptId={ATTEMPT} store={memoryStore()} />);
    await screen.findByText("1 + 1?");
    expect(vi.mocked(useActivityTracker)).toHaveBeenLastCalledWith(
      expect.objectContaining({ route: "/app/attempts/[attempt_id]", surface: "test", enabled: true, entity: { test_attempt_id: ATTEMPT, test_id: TEST } }),
    );
    expect(tracker.event).toHaveBeenCalledWith("assessment.question_viewed", { question_index: 0 });
    await userEvent.click(screen.getByRole("button", { name: "Save and go to the next question" }));
    await screen.findByText("2 + 2?");
    expect(tracker.event).toHaveBeenLastCalledWith("assessment.question_viewed", { question_index: 1 });
  });

  it("FE-18: the bottom action bar wraps and Prev/Next keep accessible names on narrow screens", async () => {
    const api = mockApi({ [`GET attempts/${ATTEMPT}/state`]: { body: payload() } });
    restore = api.restore;
    renderWithProviders(<AttemptRunner attemptId={ATTEMPT} store={memoryStore()} />);
    await screen.findByText("1 + 1?");
    expect(screen.getByTestId("runner-actions").className).toContain("flex-wrap");
    expect(screen.getByRole("button", { name: "Previous question" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save and go to the next question" })).toBeEnabled();
  });

  it("FE-20: palette dialog title is neutral in free navigation; time's up is a non-dismissible modal", async () => {
    const api = mockApi({
      [`GET attempts/${ATTEMPT}/state`]: { body: payload({}, new Date(Date.now() + 1_500).toISOString()) },
      // First poll: still in progress (the modal stays up); then the sweeper has auto-submitted.
      [`GET attempts/${ATTEMPT}/time`]: () => ({ body: { server_now: NOW, deadline_at: NOW, status: ++polls === 1 ? "in_progress" : "auto_submitted" } }),
    });
    let polls = 0;
    restore = api.restore;
    renderWithProviders(<AttemptRunner attemptId={ATTEMPT} store={memoryStore()} expiryPollMs={3_000} />);
    await screen.findByText("1 + 1?");
    await userEvent.click(screen.getByRole("button", { name: /Questions 1\/2/ }));
    expect(await screen.findByRole("dialog", { name: "Questions" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    const dialog = await screen.findByRole("dialog", { name: "Time's up" }, { timeout: 5_000 });
    expect(dialog).toBeInTheDocument();
    await userEvent.keyboard("{Escape}"); // not dismissible
    expect(screen.queryByRole("dialog", { name: "Time's up" })).toBeInTheDocument();
    await waitFor(() => expect(replace).toHaveBeenCalledWith(`/app/attempts/${encodeURIComponent(ATTEMPT)}/submitted?reason=deadline`), { timeout: 8_000 });
  }, 20_000);

  it("ATT-07 4/min: after expiry a 429 poll waits for Retry-After before polling again", async () => {
    const stamps: number[] = [];
    const api = mockApi({
      // Fresh server_now: the module-level NOW is stale by the time this test runs.
      [`GET attempts/${ATTEMPT}/state`]: { body: payload({ server_now: new Date().toISOString() }, new Date(Date.now() + 1_000).toISOString()) },
      [`GET attempts/${ATTEMPT}/time`]: () => {
        stamps.push(Date.now());
        return stamps.length === 1
          ? { status: 429, body: { type: "x", title: "Too many requests", status: 429, code: "rate_limited", request_id: "r" }, headers: { "retry-after": "2" } }
          : { body: { server_now: NOW, deadline_at: NOW, status: "auto_submitted" } };
      },
    });
    restore = api.restore;
    renderWithProviders(<AttemptRunner attemptId={ATTEMPT} store={memoryStore()} expiryPollMs={50} />);
    await screen.findByText("1 + 1?");
    await waitFor(() => expect(replace).toHaveBeenCalledWith(`/app/attempts/${encodeURIComponent(ATTEMPT)}/submitted?reason=deadline`), { timeout: 8_000 });
    expect(stamps.length).toBe(2);
    expect(stamps[1]! - stamps[0]!).toBeGreaterThanOrEqual(1_900);
  }, 15_000);

  it("FE-20: the focus shell makes the portal chrome inert and restores it", () => {
    document.body.innerHTML = '<nav id="nav"><a href="/x">x</a></nav><div aria-live="polite" id="toasts"></div><main><div id="shell"></div></main>';
    const shell = document.getElementById("shell")!;
    const undo = inertOutside(shell);
    expect(document.getElementById("nav")!.hasAttribute("inert")).toBe(true);
    expect(document.getElementById("toasts")!.hasAttribute("inert")).toBe(false);
    undo();
    expect(document.getElementById("nav")!.hasAttribute("inert")).toBe(false);
    document.body.innerHTML = "";
  });
});

describe("QuestionView coding items (FE-06 / COD-004)", () => {
  const coding: QuestionDelivery = {
    question_version_id: "qc",
    type: "coding",
    topic_id: "tp",
    difficulty: 3,
    stem_html: "<p>Reverse a string.</p>",
    options: [],
    coding_problem_id: "01900000-0000-7000-8000-0000000000d1",
  };

  it("embeds the coding workspace for the attempt and saves the submission as the answer", async () => {
    const onChange = vi.fn();
    renderWithProviders(<QuestionView number={1} question={coding} response={null} flagged={false} attemptId={ATTEMPT} onChange={onChange} onToggleFlag={() => undefined} />);
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(codingProps.last).toMatchObject({ problemId: coding.coding_problem_id, attemptId: ATTEMPT });
    await act(async () => {
      await userEvent.click(screen.getByRole("button", { name: "Fake submit code" }));
    });
    expect(onChange).toHaveBeenCalledWith({ submission_id: "01900000-0000-7000-8000-000000005ab1" });
  });

  it("says when a submission is already saved as the answer", () => {
    renderWithProviders(
      <QuestionView number={1} question={coding} response={{ submission_id: "x" }} flagged={false} attemptId={ATTEMPT} onChange={() => undefined} onToggleFlag={() => undefined} />,
    );
    expect(screen.getByText(/latest submission is saved as the answer/)).toBeInTheDocument();
  });
});

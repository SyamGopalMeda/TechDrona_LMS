import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { useActivityTracker } from "@/lib/analytics/use-activity-tracker";
import { PracticeHub } from "./components/PracticeHub";
import { PracticeSession } from "./components/PracticeSession";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));
const tracker = vi.hoisted(() => ({ video: {}, event: vi.fn(), editor: { focus: vi.fn(), blur: vi.fn(), edit: vi.fn() }, scrollDepth: vi.fn() }));
vi.mock("@/lib/analytics/use-activity-tracker", () => ({ getTabId: () => "tab-1", useActivityTracker: vi.fn(() => tracker) }));

let restore: (() => void) | undefined;
afterEach(() => {
  restore?.();
  push.mockReset();
  window.localStorage.clear();
});

const node = (id: string, slug: string, name: string, children: unknown[] = [], question_count = 0) => ({
  id,
  parent_id: null,
  kind: "topic",
  slug,
  name,
  path: slug,
  depth: 0,
  position: 0,
  is_active: true,
  question_count,
  children,
});

// verified shape: placement router plc_01_subjects → {items: TaxonomyNode[]}
const subjects = {
  items: [
    node("sub-l", "logical", "Logical", [node("top-seat", "seating", "Seating arrangement", [], 120)], 120),
    node("sub-q", "quant", "Quant", [node("top-pct", "percentages", "Percentages")]),
  ],
};

const question = (id: string, stem: string, options: { option_id: string; label: string; html: string }[]) => ({
  question_version_id: id,
  type: "mcq_single",
  topic_id: "top-seat",
  difficulty: 3,
  stem_html: stem,
  options,
  marks: null,
  negative_marks: null,
  expected_seconds: 90,
});

// verified shape: placement practice.state()
const session = {
  session_id: "ps1",
  mode: "topic_set",
  topic_id: "top-seat",
  status: "active",
  target_count: 2,
  answered_count: 0,
  correct_count: 0,
  started_at: "2026-11-03T10:00:00Z",
  ended_at: null,
  next_question_version_id: "qv1",
  items: [
    {
      position: 1,
      served_at: "2026-11-03T10:00:00Z",
      answered: false,
      feedback: null,
      question: question("qv1", "<p>Who sits second to the left of D?</p>", [
        { option_id: "oA", label: "A", html: "E" },
        { option_id: "oC", label: "B", html: "G" },
      ]),
    },
    { position: 2, served_at: "2026-11-03T10:00:00Z", answered: false, feedback: null, question: question("qv2", "<p>Second question</p>", [{ option_id: "x", label: "A", html: "X" }]) },
  ],
};

const rec = (id: string, why: string) => ({
  id,
  rule_key: "weak_topic",
  why_recommended: why,
  evidence: {},
  target_type: "topic",
  target_id: "top-seat",
  priority: 1,
  generated_at: "2026-11-03T10:00:00Z",
  expires_at: "2026-11-10T10:00:00Z",
});

describe("PracticeHub (PRC-001)", () => {
  it("starts a set from the topic/difficulty pickers with an Idempotency-Key", async () => {
    const api = mockApi({
      "GET placement/subjects": { body: subjects },
      "GET me/recommendations": { body: { personalised: true, items: [rec("r1", "Weak topic in your TCS path")] } },
      "POST practice/sessions": { status: 201, body: { session_id: "ps1" } },
    });
    restore = api.restore;
    renderWithProviders(<PracticeHub />);
    expect(await screen.findByText("Why: Weak topic in your TCS path")).toBeInTheDocument();
    await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Topic" }), "top-seat");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Difficulty" }), "hard");
    await userEvent.click(screen.getByRole("button", { name: "Start 10-question set" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/app/practice/sessions/ps1"));
    const call = api.calls.find((c) => c.path === "practice/sessions")!;
    expect(call.body).toEqual({ mode: "topic_set", topic_id: "top-seat", difficulty_min: 4, difficulty_max: 5 });
    expect(call.headers["idempotency-key"]).toBeTruthy();
  });

  it("dismisses a recommendation", async () => {
    const api = mockApi({
      "GET placement/subjects": { body: subjects },
      "GET me/recommendations": { body: { personalised: true, items: [rec("r1", "Not practised for 3 weeks")] } },
      "POST me/recommendations/r1/dismiss": { status: 204 },
    });
    restore = api.restore;
    renderWithProviders(<PracticeHub />);
    await userEvent.click(await screen.findByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText("Why: Not practised for 3 weeks")).not.toBeInTheDocument();
    await waitFor(() => expect(api.calls.some((c) => c.path === "me/recommendations/r1/dismiss")).toBe(true));
  });
});

describe("PracticeSession (PRC-003)", () => {
  it("FE-07/FE-16: mounts the practice tracker and emits practice.question_viewed per question", async () => {
    tracker.event.mockClear();
    const api = mockApi({ "GET placement/subjects": { body: subjects }, "GET practice/sessions/ps1": { body: session } });
    restore = api.restore;
    renderWithProviders(<PracticeSession sessionId="ps1" />);
    // FE-24: under a full parallel run the first render (two loaders) can exceed waitFor's 1 s default.
    expect(await screen.findByText("Who sits second to the left of D?", {}, { timeout: 5000 })).toBeInTheDocument();
    // The view event fires from an effect after the question renders.
    await waitFor(() => expect(tracker.event).toHaveBeenCalledWith("practice.question_viewed", { position_in_set: 0 }));
    expect(vi.mocked(useActivityTracker)).toHaveBeenLastCalledWith(
      expect.objectContaining({ route: "/app/practice/sessions/[session_id]", surface: "practice", entity: { topic_id: "top-seat" }, enabled: true }),
    );
    // "ps1" is not a UUID, so set_id is omitted rather than sent invalid.
    expect(tracker.event).toHaveBeenCalledWith("practice.question_viewed", { position_in_set: 0 });
  });

  it("gives immediate feedback with the correct answer and explanation", async () => {
    const api = mockApi({
      "GET placement/subjects": { body: subjects },
      "GET practice/sessions/ps1": { body: session },
      "POST practice/sessions/ps1/answers": {
        body: {
          question_version_id: "qv1",
          is_correct: false,
          your_response: { option_ids: ["oA"] },
          correct_option_ids: ["oC"],
          explanation_html: "<p>Place D first, then count two seats to the left.</p>",
          attempt_no: 1,
          solution_viewed: false,
          answered_at: "2026-11-03T10:01:00Z",
          mastery_delta: null,
          next_question_version_id: "qv2",
        },
      },
    });
    restore = api.restore;
    renderWithProviders(<PracticeSession sessionId="ps1" />);
    // The question block can re-mount once while ancillary loaders settle; assert on a fresh query.
    await waitFor(() => expect(screen.getByText("Who sits second to the left of D?")).toBeInTheDocument());
    const check = screen.getByRole("button", { name: "Check answer" });
    expect(check).toBeDisabled();
    await userEvent.click(screen.getByRole("radio", { name: /E/ }));
    await userEvent.click(check);
    expect(await screen.findByText(/Not quite/)).toBeInTheDocument();
    expect(screen.getByText("Place D first, then count two seats to the left.")).toBeInTheDocument();
    expect(screen.getByText("✓ Correct answer")).toBeInTheDocument();
    expect(screen.getByText("✕ Your answer")).toBeInTheDocument();
    const call = api.calls.find((c) => c.path === "practice/sessions/ps1/answers")!;
    expect(call.body).toMatchObject({ question_version_id: "qv1", response: { option_ids: ["oA"] }, client_attempt_no: 1 });
    expect(call.body).not.toHaveProperty("key");
    expect(call.headers["idempotency-key"]).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Next question →" }));
    expect(await screen.findByText("Second question")).toBeInTheDocument();
  });

  it("queues the answer on this device when offline", async () => {
    const api = mockApi({ "GET practice/sessions/ps1": { body: session } });
    restore = api.restore;
    renderWithProviders(<PracticeSession sessionId="ps1" />);
    await screen.findByText("Who sits second to the left of D?");
    api.fetchImpl.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await userEvent.click(screen.getByRole("radio", { name: /G/ }));
    await userEvent.click(screen.getByRole("button", { name: "Check answer" }));
    expect(await screen.findByText(/Saved on this device — will sync/)).toBeInTheDocument();
    expect(JSON.parse(window.localStorage.getItem("td.practice.pending.ps1")!)).toHaveLength(1);
  });

  it("reports the current question (PLC-33) with category and message", async () => {
    const api = mockApi({
      "GET practice/sessions/ps1": { body: session },
      "POST questions/qv1/reports": { status: 201, body: { report_id: "r1", question_id: "q1", question_version_id: "qv1", category: "typo", message: "x", status: "open", created_at: "2026-11-03T10:00:00Z" } },
    });
    restore = api.restore;
    renderWithProviders(<PracticeSession sessionId="ps1" />);
    await screen.findByText("Who sits second to the left of D?");
    await userEvent.click(screen.getByRole("button", { name: "Report" }));
    await userEvent.click(await screen.findByRole("button", { name: "Send report" }));
    expect(await screen.findByText("Tell us what's wrong with this question.")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("What's wrong?"), "typo");
    await userEvent.type(screen.getByLabelText(/^Details/), "Option C is misspelt");
    expect(screen.getByText("20/1000 characters")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Send report" }));
    expect(await screen.findByText("Thanks — report sent")).toBeInTheDocument();
    const call = api.calls.find((c) => c.method === "POST" && c.path === "questions/qv1/reports")!;
    expect(call.body).toEqual({ category: "typo", message: "Option C is misspelt", question_version_id: "qv1" });
    expect(call.headers["Idempotency-Key"] ?? call.headers["idempotency-key"]).toBeTruthy();
  });

  it("explains a duplicate open report", async () => {
    const api = mockApi({
      "GET practice/sessions/ps1": { body: session },
      "POST questions/qv1/reports": problem(409, "invalid_state_transition", "Already reported", { reason: "report_already_open" }),
    });
    restore = api.restore;
    renderWithProviders(<PracticeSession sessionId="ps1" />);
    await screen.findByText("Who sits second to the left of D?");
    await userEvent.click(screen.getByRole("button", { name: "Report" }));
    await userEvent.type(await screen.findByLabelText(/^Details/), "Wrong key");
    await userEvent.click(screen.getByRole("button", { name: "Send report" }));
    expect(await screen.findByText(/already reported this question/)).toBeInTheDocument();
  });

  it("shows a paywall card for premium topics", async () => {
    const api = mockApi({ "GET practice/sessions/ps1": problem(403, "entitlement_required", "Upgrade needed", { detail: "This topic is part of the TCS NQT path." }) });
    restore = api.restore;
    renderWithProviders(<PracticeSession sessionId="ps1" />);
    expect(await screen.findByText("This is part of a paid plan")).toBeInTheDocument();
    expect(screen.getByText("This topic is part of the TCS NQT path.")).toBeInTheDocument();
  });
});

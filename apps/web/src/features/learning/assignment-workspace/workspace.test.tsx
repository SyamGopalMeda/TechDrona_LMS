import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders, type MockReply } from "@/features/auth/test/mock-api";
import { AssignmentDetail } from "../components/Assignments";
import type { AssignmentOut, ResultOut, WorkspaceOut } from "../assignment-manager/types";
import { reasonError } from "./ResultsView";
import { StructuredAssignment } from "./StructuredAssignment";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }), usePathname: () => "/app" }));
vi.mock("@/features/coding/components/CodeEditor", () => ({
  CodeEditor: ({ value, onChange, ariaLabel }: { value: string; onChange: (v: string) => void; ariaLabel: string }) => (
    <textarea aria-label={ariaLabel} value={value} onChange={(e) => onChange(e.target.value)} />
  ),
}));

let restore: (() => void) | undefined;
afterEach(() => restore?.());

const assignment: AssignmentOut = {
  id: "a1",
  title: "Arrays practice",
  instructions_md: "Answer every question.",
  submission_type: "structured",
  max_score: 20,
  rubric: null,
  allowed_file_types: [],
  course_id: null,
  batch_id: "b1",
  available_from: null,
  due_at: "2026-11-30T10:00:00Z",
  late_until: null,
  late_penalty_pct: 0,
  max_attempts: 1,
  status: "active",
  grades_released: false,
  window: "on_time",
  organization_id: "o1",
  ai_help_enabled: true,
  ai_help_limit: 1,
  structured: true,
};

const ws = (over: Partial<WorkspaceOut> = {}): WorkspaceOut => ({
  assignment,
  schedule: { visible_from: null, visible_until: null, start_at: null, due_at: "2026-11-30T10:00:00Z", can_start: true, can_submit: true, seconds_left: 86000 },
  submission: { id: "sub1", status: "in_progress", submitted_at: null, ai_help_used: 0 },
  ai_help: { enabled: true, limit: 1, used: 0, remaining: 1 },
  sections: [
    {
      id: "s1",
      title: "Section 1",
      items: [
        { id: "i1", position: 1, item_type: "essay", marks: 10, prompt_md: "Explain two pointers.", stem_html: null, options: [], coding_problem_id: null, response: null, saved_at: null },
        {
          id: "i2",
          position: 2,
          item_type: "mcq_single",
          marks: 10,
          prompt_md: null,
          stem_html: "<p>Pick one</p>",
          options: [
            { option_id: "o1", label: "A", html: "Yes" },
            { option_id: "o2", label: "B", html: "No" },
          ],
          coding_problem_id: null,
          response: null,
          saved_at: null,
        },
      ],
    },
  ],
  ...over,
});

describe("StructuredAssignment workspace", () => {
  it("shows the start time and a disabled Start before the window opens", async () => {
    const api = mockApi({
      "GET me/assignments/a1/workspace": {
        body: ws({ submission: null, sections: [], schedule: { ...ws().schedule, start_at: "2026-11-20T04:30:00Z", can_start: false } }),
      },
    });
    restore = api.restore;
    renderWithProviders(<StructuredAssignment assignmentId="a1" />);
    expect(await screen.findByText(/Starting opens at 20 Nov 2026, 10:00 IST/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();
  });

  it("autosaves answers with a debounced PUT and on navigation", async () => {
    const api = mockApi({
      "GET me/assignments/a1/workspace": { body: ws() },
      "PUT me/assignments/a1/workspace/items/i1": { body: { item_id: "i1", saved_at: "2026-11-06T10:00:00Z" } },
      "PUT me/assignments/a1/workspace/items/i2": { body: { item_id: "i2", saved_at: "2026-11-06T10:00:00Z" } },
    });
    restore = api.restore;
    renderWithProviders(<StructuredAssignment assignmentId="a1" />);
    await userEvent.type(await screen.findByRole("textbox", { name: "Your answer" }), "Two indices");
    expect(api.calls.some((c) => c.method === "PUT")).toBe(false);
    await waitFor(() => expect(api.calls.filter((c) => c.method === "PUT")).toHaveLength(1), { timeout: 4000 });
    expect(api.calls.find((c) => c.method === "PUT")!.body).toEqual({ response: { text: "Two indices" } });
    expect(await screen.findByText("All changes saved")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Next ›" }));
    await userEvent.click(await screen.findByLabelText(/B\./));
    await userEvent.click(screen.getByRole("button", { name: /Question 1/ }));
    await waitFor(() => expect(api.calls.some((c) => c.path.endsWith("items/i2"))).toBe(true));
    expect(api.calls.find((c) => c.path.endsWith("items/i2"))!.body).toEqual({ response: { option_ids: ["o2"] } });
  }, 10000);

  it("tracks the tutor allowance and disables asking at 0", async () => {
    const api = mockApi({
      "GET me/assignments/a1/workspace": { body: ws() },
      "GET me/assignments/a1/tutor/history": { body: { data: [{ role: "learner", content: "Earlier question", created_at: "2026-11-07T09:00:00Z" }, { role: "tutor", content: "Earlier server reply", created_at: "2026-11-07T09:00:01Z" }] } },
      "POST me/assignments/a1/tutor": { body: { reply_md: "Think about where each pointer starts.", used: 1, limit: 1, remaining: 0 } },
    });
    restore = api.restore;
    renderWithProviders(<StructuredAssignment assignmentId="a1" />);
    expect(await screen.findByTestId("tutor-left")).toHaveTextContent("1 of 1 interactions left");
    // History comes from the server per question (SEC-17); the POST body carries no history.
    expect(await screen.findByText("Earlier server reply")).toBeInTheDocument();
    expect(api.calls.find((c) => c.path === "me/assignments/a1/tutor/history")!.url).toContain("item_id=i1");
    await userEvent.type(screen.getByLabelText("Your question or code"), "How do I start?");
    await userEvent.click(screen.getByRole("button", { name: "Guide (1)" }));
    expect(await screen.findByText("Think about where each pointer starts.")).toBeInTheDocument();
    expect(api.calls.find((c) => c.path === "me/assignments/a1/tutor")!.body).toEqual({ item_id: "i1", mode: "guide", learner_input: "How do I start?" });
    expect(screen.getByTestId("tutor-left")).toHaveTextContent("0 of 1 interactions left");
    expect(screen.getByRole("button", { name: "Guide (0)" })).toBeDisabled();
    expect(screen.getByText(/used all your tutor interactions/)).toBeInTheDocument();
  });

  it.each<[string, MockReply, RegExp]>([
    ["ai_disabled", problem(403, "ai_disabled", "AI disabled"), /AI help is turned off/],
    ["ai_quota_exceeded", problem(429, "ai_quota_exceeded", "Quota"), /AI limit reached/],
    ["ai_unavailable", problem(503, "ai_unavailable", "Unavailable"), /temporarily unavailable/],
  ])("shows a clear state for %s", async (_code, reply, text) => {
    const api = mockApi({ "GET me/assignments/a1/workspace": { body: ws() }, "POST me/assignments/a1/tutor": reply });
    restore = api.restore;
    renderWithProviders(<StructuredAssignment assignmentId="a1" />);
    await userEvent.type(await screen.findByLabelText("Your question or code"), "Help");
    await userEvent.click(screen.getByRole("button", { name: "Explain (1)" }));
    expect(await screen.findByText(text)).toBeInTheDocument();
  });

  it("hides the tutor when AI help is off and submits with an Idempotency-Key", async () => {
    let submitted = false;
    const api = mockApi({
      "GET me/assignments/a1/workspace": () => ({ body: submitted ? ws({ submission: { id: "sub1", status: "submitted", submitted_at: "2026-11-06T10:00:00Z", ai_help_used: 0 } }) : ws({ ai_help: { enabled: false, limit: null, used: 0, remaining: null } }) }),
      "POST me/assignments/a1/workspace/submit": () => {
        submitted = true;
        return { body: { id: "sub1", status: "submitted", submitted_at: "2026-11-06T10:00:00Z" } };
      },
      "GET me/assignments/a1/result": { body: { assignment, published: false, submission: { id: "sub1", status: "submitted", submitted_at: "2026-11-06T10:00:00Z", score: null, max_score: 20, feedback_md: null }, items: [], regrade: null } },
    });
    restore = api.restore;
    renderWithProviders(<StructuredAssignment assignmentId="a1" />);
    await screen.findByRole("textbox", { name: "Your answer" });
    expect(screen.queryByLabelText("Your question or code")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Submit assignment" }));
    expect(screen.getByText("2 questions are still unanswered.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByText("Awaiting results")).toBeInTheDocument();
    expect(api.calls.find((c) => c.path.endsWith("workspace/submit"))!.headers["idempotency-key"]).toBeTruthy();
  });

  it("AssignmentDetail renders the structured workspace for structured assignments", async () => {
    const api = mockApi({
      "GET me/assignments/a1": { body: { ...assignment, submissions: [] } },
      "GET me/assignments/a1/workspace": { body: ws() },
    });
    restore = api.restore;
    renderWithProviders(<AssignmentDetail assignmentId="a1" />);
    expect(await screen.findByRole("button", { name: "Submit assignment" })).toBeInTheDocument();
  });
});

const result = (over: Partial<ResultOut> = {}): ResultOut => ({
  assignment: { ...assignment, grades_released: true },
  published: true,
  submission: { id: "sub1", status: "submitted", submitted_at: "2026-11-06T10:00:00Z", score: 9, max_score: 20, feedback_md: null },
  items: [
    {
      id: "i1",
      section_id: "s1",
      section_title: "Section 1",
      position: 1,
      item_type: "essay",
      marks: 10,
      prompt_md: "Explain two pointers.",
      stem_html: null,
      options: [],
      response: { text: "Two indices moving inward." },
      final_marks: 9,
      feedback_md: "Clear and correct.",
    },
  ],
  regrade: null,
  ...over,
});

describe("Results and modification requests", () => {
  const submittedWs = ws({ submission: { id: "sub1", status: "submitted", submitted_at: "2026-11-06T10:00:00Z", ai_help_used: 0 } });

  it("validates the reason length", () => {
    expect(reasonError("short")).toMatch(/at least 10/);
    expect(reasonError("x".repeat(2001))).toMatch(/under 2000/);
    expect(reasonError("Please check question one again")).toBeNull();
  });

  it("shows the final score, opens a question and sends a modification request", async () => {
    let sent = false;
    const api = mockApi({
      "GET me/assignments/a1/workspace": { body: submittedWs },
      "GET me/assignments/a1/result": () => ({
        body: result(sent ? { regrade: { id: "r1", submission_id: "sub1", assignment_id: "a1", user_id: "u1", learner_name: null, item_id: "i1", reason: "Please recheck my explanation.", status: "open", resolution_note: null, resolved_at: null, created_at: "2026-11-06T11:00:00Z" } } : {}),
      }),
      "POST me/assignment-submissions/sub1/regrade-requests": () => {
        sent = true;
        return { status: 201, body: {} };
      },
    });
    restore = api.restore;
    renderWithProviders(<StructuredAssignment assignmentId="a1" />);
    expect(await screen.findByTestId("final-score")).toHaveTextContent("Final score: 9 / 20");
    await userEvent.click(screen.getByRole("button", { name: "Open question 1" }));
    expect(screen.getByText("Two indices moving inward.")).toBeInTheDocument();
    expect(screen.getByText("Clear and correct.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Close" }));

    await userEvent.click(screen.getByRole("button", { name: "Request modification" }));
    await userEvent.type(screen.getByRole("textbox", { name: /Reason/ }), "too short");
    await userEvent.click(screen.getByRole("button", { name: "Send request" }));
    expect(await screen.findByText(/at least 10 characters/)).toBeInTheDocument();
    await userEvent.clear(screen.getByRole("textbox", { name: /Reason/ }));
    await userEvent.type(screen.getByRole("textbox", { name: /Reason/ }), "Please recheck my explanation.");
    await userEvent.selectOptions(screen.getByLabelText("Question (optional)"), "i1");
    await userEvent.click(screen.getByRole("button", { name: "Send request" }));
    expect(await screen.findByText("Modification request open")).toBeInTheDocument();
    expect(api.calls.find((c) => c.path.endsWith("regrade-requests"))!.body).toEqual({ reason: "Please recheck my explanation.", item_id: "i1" });
    expect(screen.getByRole("button", { name: "Request modification" })).toBeDisabled();
  });
});

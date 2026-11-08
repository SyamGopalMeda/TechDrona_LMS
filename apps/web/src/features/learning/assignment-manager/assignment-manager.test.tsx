import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { AllocateDialog, validateAllocation } from "./AllocateDialog";
import { AssignmentEditor, MarksMeter, marksWarning } from "./AssignmentEditor";
import { EvaluationView, rowFlags } from "./EvaluationView";
import { ReviewModal, buildFinalize } from "./ReviewModal";
import type { AssignmentOut, EvaluationRow, ItemStaff, ReviewItem, ReviewOut, StructureOut } from "./types";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }), usePathname: () => "/trainer/grading" }));

let restore: (() => void) | undefined;
afterEach(() => restore?.());

const assignment: AssignmentOut = {
  id: "a1",
  title: "Arrays practice",
  instructions_md: null,
  submission_type: "structured",
  max_score: 50,
  rubric: null,
  allowed_file_types: [],
  course_id: null,
  batch_id: null,
  available_from: null,
  due_at: null,
  late_until: null,
  late_penalty_pct: 0,
  max_attempts: 1,
  status: "draft",
  grades_released: false,
  window: "on_time",
  organization_id: "o1",
  ai_help_enabled: true,
  ai_help_limit: 3,
  structured: true,
};

const item = (id: string, marks: number): ItemStaff => ({
  id,
  position: 1,
  source: "bank" as const,
  item_type: "mcq_single",
  question_id: `q-${id}`,
  question_version_id: `qv-${id}`,
  coding_problem_id: null,
  prompt_md: null,
  stem_html: `<p>Question ${id}</p>`,
  options: [],
  marks,
  rubric: null,
  reference_answer_md: null,
});

const structure = (marks: number[], locked = false): StructureOut => ({
  assignment,
  locked,
  sections: [{ id: "s1", title: "Section 1", position: 1, max_score: null, marks_total: marks.reduce((a, b) => a + b, 0), items: marks.map((m, i) => item(`i${i + 1}`, m)) }],
  marks: { allocated: marks.reduce((a, b) => a + b, 0), total: 50, ok: marks.reduce((a, b) => a + b, 0) === 50, issues: [] },
  allocations: [],
});

const noPicker = () => null;

describe("Marks meter", () => {
  it("shows allocated / total and success styling only when equal", () => {
    const { rerender } = renderWithProviders(<MarksMeter allocated={30} total={50} />);
    expect(screen.getByRole("status")).toHaveTextContent("30 / 50 allocated");
    expect(screen.getByRole("status").className).toContain("warning");
    rerender(<MarksMeter allocated={50} total={50} />);
    expect(screen.getByRole("status").className).toContain("success");
  });

  it("explains a mismatch and counts zero-mark questions", () => {
    expect(marksWarning(50, 50, 0)).toBeNull();
    expect(marksWarning(30, 50, 2)).toMatch(/add up to 30, but the total is 50.*2 questions have 0 marks/);
  });
});

describe("AssignmentEditor", () => {
  it("updates the meter while editing marks and saves the structure with PUT", async () => {
    const api = mockApi({
      "GET assignments/a1/structure": { body: structure([20, 10]) },
      "PUT assignments/a1/structure": (c) => ({ body: { ...structure([20, 30]), sections: structure([20, 30]).sections, marks: { allocated: 50, total: 50, ok: true, issues: [] }, _echo: c.body } }),
    });
    restore = api.restore;
    renderWithProviders(<AssignmentEditor assignmentId="a1" renderPicker={noPicker} />);
    expect(await screen.findByRole("status", { name: "30 of 50 marks allocated" })).toBeInTheDocument();
    expect(screen.getByText(/add up to 30, but the total is 50/)).toBeInTheDocument();

    const marks = screen.getByLabelText("Marks for question 2");
    await userEvent.clear(marks);
    await userEvent.type(marks, "30");
    expect(screen.getByRole("status", { name: "50 of 50 marks allocated" })).toBeInTheDocument();
    expect(screen.queryByText(/add up to/)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "PUT")).toBe(true));
    const put = api.calls.find((c) => c.method === "PUT")!;
    expect(put.body).toEqual({
      sections: [
        {
          title: "Section 1",
          max_score: null,
          items: [
            { source: "bank", question_id: "q-i1", question_version_id: "qv-i1", marks: 20 },
            { source: "bank", question_id: "q-i2", question_version_id: "qv-i2", marks: 30 },
          ],
        },
      ],
    });
  });

  it("keeps locked assignments read-only", async () => {
    const api = mockApi({ "GET assignments/a1/structure": { body: structure([50], true) } });
    restore = api.restore;
    renderWithProviders(<AssignmentEditor assignmentId="a1" renderPicker={noPicker} />);
    expect(await screen.findByText(/questions and marks are locked/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Import from bank" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Marks for question 1")).toBeDisabled();
  });

  it("adds a written question to a section", async () => {
    const api = mockApi({ "GET assignments/a1/structure": { body: structure([]) } });
    restore = api.restore;
    renderWithProviders(<AssignmentEditor assignmentId="a1" renderPicker={noPicker} />);
    await userEvent.click(await screen.findByRole("button", { name: "Add written question" }));
    await userEvent.type(screen.getByRole("textbox", { name: /^Question/ }), "Explain two pointers.");
    await userEvent.click(screen.getByRole("button", { name: "Add question" }));
    expect(screen.getByText("Explain two pointers.")).toBeInTheDocument();
    expect(screen.getByText("Essay")).toBeInTheDocument();
  });
});

describe("AllocateDialog", () => {
  const grants = { data: [{ grant_id: "g1", role_key: "trainer", scope_type: "batch", scope_id: "b1", organization_id: "o1" }] };
  const batch = { id: "b1", organization_id: "o1", name: "CSE 2027", code: "CSE27", status: "active" };

  it("validates schedule order", () => {
    expect(validateAllocation({ batch_id: "", visible_from: "", visible_until: "", start_at: "", due_at: "" })).toMatchObject({ batch_id: expect.any(String), due_at: expect.any(String) });
    expect(validateAllocation({ batch_id: "b1", visible_from: "", visible_until: "", start_at: "2026-11-10T10:00", due_at: "2026-11-09T10:00" }).due_at).toMatch(/after/);
    expect(validateAllocation({ batch_id: "b1", visible_from: "2026-11-10T10:00", visible_until: "2026-11-09T10:00", start_at: "", due_at: "2026-11-09T09:00" }).visible_until).toBeTruthy();
  });

  it("requires a batch and due date, then posts engines + evaluators and shows 422 errors", async () => {
    const api = mockApi({
      "GET me/grants": { body: grants },
      "GET batches/b1": { body: batch },
      "GET batches/b1/members": {
        body: {
          data: [
            { user_id: "u9", full_name: "Asha Rao", member_role: "trainer" },
            { user_id: "u1", full_name: "Student One", member_role: "student" },
          ],
        },
      },
      "GET rbac/grants": problem(403, "permission_denied", "Forbidden"),
      "POST assignments/a1/allocations": problem(422, "validation_failed", "Invalid", { errors: [{ field: "marks", code: "marks_mismatch", message: "Marks don't add up to the total." }] }),
    });
    restore = api.restore;
    renderWithProviders(<AllocateDialog open onClose={vi.fn()} assignment={assignment} sections={[{ id: "s1", title: "Section 1" }]} marksOk onAllocated={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Allocate to batch" }));
    expect(screen.getByText("Choose a batch.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);

    await screen.findByRole("option", { name: "CSE 2027" });
    await userEvent.selectOptions(screen.getByLabelText(/^Batch/), "b1");
    await userEvent.type(screen.getByLabelText(/^Must submit by/), "2026-11-20T18:00");
    await userEvent.selectOptions(screen.getByLabelText("Section 1"), "adaptive");
    expect(screen.getByText(/low-confidence AI marks are flagged/)).toBeInTheDocument();
    await userEvent.click(await screen.findByLabelText(/Asha Rao/));
    await userEvent.click(screen.getByRole("button", { name: "Allocate to batch" }));

    expect(await screen.findByText("Marks don't add up to the total.")).toBeInTheDocument();
    const post = api.calls.find((c) => c.method === "POST")!;
    expect(post.body).toMatchObject({ batch_id: "b1", section_engines: { s1: "adaptive" }, evaluator_ids: ["u9"], visible_from: null, start_at: null });
    expect((post.body as { due_at: string }).due_at).toBe(new Date("2026-11-20T18:00").toISOString());
    expect(post.headers["idempotency-key"]).toBeTruthy();
    // Students are never offered as evaluators.
    expect(screen.queryByLabelText(/Student One/)).not.toBeInTheDocument();
  });

  it("lists batch evaluators from RBAC grants for Admin and explains 422 not_evaluator", async () => {
    const api = mockApi({
      "GET me/grants": { body: { data: [{ grant_id: "g0", role_key: "super_admin", scope_type: "platform", scope_id: null }] } },
      "GET batches": { body: { data: [batch] } },
      "GET batches/b1/members": { body: { data: [] } },
      "GET rbac/grants": { body: { data: [{ user_id: "e1234567-0000", role_key: "evaluator" }, { user_id: "s1", role_key: "student" }] } },
      "POST assignments/a1/allocations": problem(422, "validation_failed", "Invalid", { errors: [{ field: "evaluator_ids", code: "not_evaluator", message: "Not an evaluator." }] }),
    });
    restore = api.restore;
    renderWithProviders(<AllocateDialog open onClose={vi.fn()} assignment={assignment} sections={[{ id: "s1", title: "Section 1" }]} marksOk onAllocated={vi.fn()} />);
    await screen.findByRole("option", { name: "CSE 2027" });
    await userEvent.selectOptions(screen.getByLabelText(/^Batch/), "b1");
    await userEvent.type(screen.getByLabelText(/^Must submit by/), "2026-11-20T18:00");
    await userEvent.click(await screen.findByLabelText(/Evaluator · e1234567/));
    await userEvent.click(screen.getByRole("button", { name: "Allocate to batch" }));
    expect(await screen.findByText(/One of the chosen evaluators can't grade/)).toBeInTheDocument();
    expect(api.calls.find((c) => c.method === "GET" && c.url.includes("rbac/grants"))?.url).toContain("scope_id=b1");
  });
});

const review = (items: ReviewItem[]): ReviewOut => ({
  submission: { id: "sub1", assignment_id: "a1", status: "submitted", submitted_at: "2026-11-05T10:00:00Z", file_s3_keys: [] },
  learner: { user_id: "u1", name: "Ravi Kumar", email: "ravi@x.in" },
  sections: [{ id: "s1", title: "Section 1", engine: "pure_ai", items }],
  totals: { final: null, suggested: 8, max: 10 },
});

const rItem = (extra: Partial<ReviewItem> = {}): ReviewItem => ({
  ...item("i1", 10),
  item_type: "coding",
  source: "ai",
  response: null,
  code: { language_key: "python3", source_code: "print(1)", submission_id: "cs1", judge: { status: "completed", verdict: "AC", score: 10, max_score: 10, passed_cases: 5, total_cases: 5 } },
  auto_marks: null,
  ai: { status: "accepted", marks: 8, feedback_md: "Good use of loops.", confidence: 0.9, error: null },
  suggested_marks: 8,
  final_marks: null,
  final_feedback_md: null,
  ...extra,
});

describe("ReviewModal", () => {
  it("buildFinalize requires an override reason when marks differ from the suggestion", () => {
    const i = rItem();
    expect(buildFinalize([i], { i1: { marks: "8", feedback: "ok", reason: "" } }).body).toEqual({ items: [{ item_id: "i1", marks: 8, feedback_md: "ok" }] });
    const bad = buildFinalize([i], { i1: { marks: "9", feedback: "", reason: "abc" } });
    expect(bad.body).toBeNull();
    expect(bad.errors.i1?.reason).toBeTruthy();
    expect(buildFinalize([i], { i1: { marks: "11", feedback: "", reason: "" } }).errors.i1?.marks).toMatch(/At most 10/);
    expect(buildFinalize([i], { i1: { marks: "9", feedback: "", reason: "Edge case handled" } }).body).toEqual({ items: [{ item_id: "i1", marks: 9, override_reason: "Edge case handled" }] });
  });

  it("shows the reason field on override and finalizes with the payload", async () => {
    const api = mockApi({
      "GET assignment-submissions/sub1/review": { body: review([rItem()]) },
      "POST assignment-submissions/sub1/finalize": { body: review([rItem({ final_marks: 9, source: "human" })]) },
    });
    restore = api.restore;
    const onFinalized = vi.fn();
    renderWithProviders(<ReviewModal submissionId="sub1" onClose={vi.fn()} onFinalized={onFinalized} />);
    expect(await screen.findByText("Review — Ravi Kumar")).toBeInTheDocument();
    expect(screen.getByLabelText("Submitted code")).toHaveTextContent("print(1)");
    expect(screen.getByText("5/5 tests passed")).toBeInTheDocument();
    const marks = screen.getByLabelText("Marks for Q1");
    expect(marks).toHaveValue(8);
    expect(screen.queryByLabelText(/Reason for changing/)).not.toBeInTheDocument();
    await userEvent.clear(marks);
    await userEvent.type(marks, "9");
    const reason = screen.getByLabelText(/Reason for changing/);
    await userEvent.click(screen.getByRole("button", { name: "Finalize & save" }));
    expect(await screen.findByText(/at least 5 characters/)).toBeInTheDocument();
    expect(api.calls.some((c) => c.path.endsWith("finalize"))).toBe(false);
    await userEvent.type(reason, "Handles the empty input case");
    await userEvent.click(screen.getByRole("button", { name: "Finalize & save" }));
    await waitFor(() => expect(onFinalized).toHaveBeenCalled());
    expect(api.calls.find((c) => c.path.endsWith("finalize"))!.body).toEqual({
      items: [{ item_id: "i1", marks: 9, feedback_md: "Good use of loops.", override_reason: "Handles the empty input case" }],
    });
  });

  it("maps 422 items.<i>.override_reason to the item", async () => {
    const api = mockApi({
      "GET assignment-submissions/sub1/review": { body: review([rItem()]) },
      "POST assignment-submissions/sub1/finalize": problem(422, "validation_failed", "Invalid", { errors: [{ field: "items.0.marks", code: "too_high", message: "Too many marks." }] }),
    });
    restore = api.restore;
    renderWithProviders(<ReviewModal submissionId="sub1" onClose={vi.fn()} onFinalized={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Finalize & save" }));
    expect(await screen.findByText("Too many marks.")).toBeInTheDocument();
  });
});

describe("EvaluationView", () => {
  const row: EvaluationRow = {
    submission_id: "sub1",
    user_id: "u1",
    learner_name: "Ravi Kumar",
    learner_email: "ravi@x.in",
    status: "late",
    submitted_at: "2026-11-05T10:00:00Z",
    late: true,
    finalized: false,
    finalized_marks: 0,
    score: null,
    max_score: 50,
    ai_pending: 5,
    ai_queued: 0,
    needs_review: 0,
    ai_help_used: 2,
    regrade_open: true,
    flags: ["extension"],
  };

  it("derives row flags", () => {
    expect(rowFlags(row)).toEqual(["Late", "Extension", "Regrade requested", "AI help used 2"]);
  });

  it("lists learners, runs AI grading and warns before publishing with unfinalized rows", async () => {
    const api = mockApi({
      "GET assignments/a1/evaluation": { body: { assignment, submission_count: 1, max_score: 50, published: false, sections: [{ id: "s1", title: "Section 1", max_marks: 50, avg_marks: 0 }], rows: [row] } },
      "GET assignments/a1/regrade-requests": { body: { data: [] } },
      "POST assignments/a1/ai-grading": { status: 202, body: { queued_items: 5, auto_scored_items: 0, submissions: 1 } },
      "POST assignments/a1/release-grades": { body: { ...assignment, grades_released: true, unfinalized_count: 1 } },
    });
    restore = api.restore;
    renderWithProviders(<EvaluationView assignmentId="a1" />);
    expect(await screen.findByText("1 submission · 50 marks")).toBeInTheDocument();
    expect(screen.getByText("0 / 50 finalized · 5 AI pending")).toBeInTheDocument();
    expect(screen.getByText("AI help used 2")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Run AI grading" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.path === "assignments/a1/ai-grading")).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: "Publish results" }));
    expect(screen.getByText(/1 submission is not finalized/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(api.calls.some((c) => c.path === "assignments/a1/release-grades")).toBe(true));
  });
});

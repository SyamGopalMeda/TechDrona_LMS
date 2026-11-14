import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { isValidElement, type ReactElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { CourseEditor } from "@/features/studio/components/Courses";
import { TestBuilder, validateBuilder, type SettingsDraft } from "@/features/studio/components/Tests";
import TrainerCourseEditPage from "@/app/trainer/courses/[course_id]/edit/page";
import { GradingQueue, TrainerAssignments, buildRubric, parseRubric, rubricErrors } from "./Grading";
import { BatchProgress, GradingBacklog, pickLive } from "./Insights";
import { TestOverrides, TestReportView, isReleased } from "./TestOps";
import { TestsList } from "./TestsList";
import { TrainerCourses } from "./TrainerCourses";
import type { TestAssignment, TestSummary } from "../lib/types";

const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn() }), usePathname: () => "/trainer/tests" }));

let restore: (() => void) | undefined;
afterEach(() => {
  restore?.();
  push.mockReset();
});

const grants = { data: [{ grant_id: "g1", role_key: "trainer", scope_type: "batch", scope_id: "b1", organization_id: "o1" }] };
const batch = { id: "b1", organization_id: "o1", name: "CSE 2027 A", code: "CSE-A", status: "active" };
const assignment = (over: Partial<TestAssignment> = {}): TestAssignment => ({
  id: "ta1",
  test_id: "t1",
  organization_id: "o1",
  batch_id: "b1",
  available_from: "2026-11-01T09:00:00.000Z",
  available_until: "2026-11-30T09:00:00.000Z",
  attempts_allowed: 1,
  release_mode: "manual",
  results_release_at: null,
  ...over,
});

describe("ADM-43 trainer can create a test for a batch", () => {
  const batches = [
    { value: "b1", label: "CSE 2027 A" },
    { value: "b2", label: "ECE 2027 B" },
  ];

  it("requires a batch and sends batch_id on POST studio/tests", async () => {
    const api = mockApi({
      "GET studio/tests": { body: { items: [] } },
      "POST studio/tests": { status: 201, body: { id: "t9", title: "Arrays mock" } },
    });
    restore = api.restore;
    renderWithProviders(<TestsList batches={batches} basePath="/trainer" />);
    await userEvent.click((await screen.findAllByRole("button", { name: "New test" }))[0]!);
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/^Title/), "Arrays mock");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create draft" }));
    expect(await within(dialog).findByText("Choose the batch this test is for.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.selectOptions(within(dialog).getByLabelText(/^Batch/), "b2");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create draft" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/trainer/tests/t9/edit"));
    expect(api.calls.find((c) => c.method === "POST")?.body).toMatchObject({ title: "Arrays mock", test_kind: "mock", duration_seconds: 3600, batch_id: "b2" });
  });

  it("is not offered in the evaluator portal, which only links to grading", async () => {
    const api = mockApi({ "GET studio/tests": { body: { items: [{ id: "t1", title: "Arrays mock", test_kind: "mock", duration_seconds: 3600, status: "published" }] } } });
    restore = api.restore;
    renderWithProviders(<TestsList batches={batches} basePath="/evaluator" evaluateOnly />);
    expect(await screen.findByText("Arrays mock")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New test" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Assign Arrays mock" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Arrays mock" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Evaluate Arrays mock" })).toHaveAttribute("href", "/evaluator/tests/t1/evaluation");
    expect(screen.queryByRole("link", { name: "Overrides" })).not.toBeInTheDocument();
  });
});

describe("ADM-42 per-student override for batch-scoped trainers", () => {
  const routes = (assignments: TestAssignment[]) => ({
    "GET tests/t1/overrides": { body: { items: [] } },
    "GET tests/t1/assignments": { body: { items: assignments } },
    "GET me/grants": { body: grants },
    "GET batches/b1": { body: batch },
    "GET batches/b1/members": { body: { data: [{ user_id: "u1", full_name: "Ravi Kumar", member_role: "student" }] } },
    "POST tests/t1/overrides": { status: 201, body: { id: "ov1" } },
  });

  const fill = async () => {
    await screen.findByRole("option", { name: "CSE 2027 A" });
    await userEvent.selectOptions(screen.getByLabelText(/^Batch/), "b1");
    await screen.findByRole("option", { name: "Ravi Kumar" });
    await userEvent.selectOptions(screen.getByLabelText(/^Student/), "u1");
    await userEvent.clear(screen.getByLabelText(/Extra time/));
    await userEvent.type(screen.getByLabelText(/Extra time/), "10");
    await userEvent.type(screen.getByLabelText(/^Reason/), "Power cut");
  };

  it("anchors the override to the batch's assignment (test_assignment_id + user_id)", async () => {
    const api = mockApi(routes([assignment({ id: "ta-other", batch_id: "b2" }), assignment()]));
    restore = api.restore;
    renderWithProviders(<TestOverrides testId="t1" />);
    await fill();
    await waitFor(() => expect(api.calls.some((c) => c.path === "tests/t1/assignments")).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: "Grant override" }));
    await waitFor(() =>
      expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({
        user_id: "u1",
        test_assignment_id: "ta1",
        extra_time_seconds: 600,
        extra_attempts: 0,
        window_extension_seconds: 0,
        reason: "Power cut",
      }),
    );
  });

  it("asks to assign the test first when the batch has no assignment", async () => {
    const api = mockApi(routes([]));
    restore = api.restore;
    renderWithProviders(<TestOverrides testId="t1" />);
    await fill();
    await waitFor(() => expect(api.calls.some((c) => c.path === "tests/t1/assignments")).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: "Grant override" }));
    expect(await screen.findByText(/Assign this test to the batch/)).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
  });
});

describe("ADM-56 release and publish controls", () => {
  it("isReleased only once the release time has passed", () => {
    const now = Date.parse("2026-11-03T12:00:00.000Z");
    expect(isReleased({ results_release_at: null }, now)).toBe(false);
    expect(isReleased({ results_release_at: "2026-11-03T11:00:00.000Z" }, now)).toBe(true);
    expect(isReleased({ results_release_at: "2026-11-04T11:00:00.000Z" }, now)).toBe(false);
  });

  it("disables Release results for an already released assignment", async () => {
    const api = mockApi({
      "GET tests/t1/assignments": { body: { items: [assignment({ id: "ta1", results_release_at: "2026-11-02T10:00:00.000Z" }), assignment({ id: "ta2", batch_id: "b1x" })] } },
      "GET me/grants": { body: grants },
      "GET batches/b1": { body: batch },
      "GET tests/t1/report": problem(404, "not_found", "Not found"),
    });
    restore = api.restore;
    renderWithProviders(<TestReportView testId="t1" />);
    const released = await screen.findByRole("button", { name: "Release results for CSE 2027 A" });
    expect(released).toBeDisabled();
    expect(released).toHaveTextContent("Released");
    // An unknown batch name is never invented ("Batch"): the row reads "—" and the button names the window.
    const unknown = screen.getByRole("button", { name: /^Release results for the assignment / });
    expect(unknown).toBeEnabled();
    expect(within(unknown.closest("tr")!).getAllByRole("cell")[0]).toHaveTextContent("—");
  });

  it("trainer course editor page hides publishing (canPublish=false)", async () => {
    const tree = await TrainerCourseEditPage.server({ params: Promise.resolve({ course_id: "c1" }) });
    const find = (n: ReactNode): ReactElement | null => {
      if (!isValidElement(n)) return null;
      if (n.type === CourseEditor) return n;
      const kids = (n.props as { children?: ReactNode }).children;
      for (const k of Array.isArray(kids) ? kids : [kids]) {
        const hit = find(k);
        if (hit) return hit;
      }
      return null;
    };
    expect(find(tree)?.props).toMatchObject({ courseId: "c1", canPublish: false });
  });
});

describe("ADM-52 test builder", () => {
  const settings: SettingsDraft = {
    title: "DSA Weekly",
    duration_minutes: "60",
    grace_seconds: "",
    navigation_mode: "free",
    attempts_allowed: "1",
    grading_method: "highest",
    shuffle_questions: true,
    shuffle_options: true,
    pass_percentage: "",
    available_from: "",
    available_until: "",
    release_at: "",
    during: { score: false, correctness: false, answer_key: false, explanation: false, section_analytics: false, rank: false },
    after_submit: { score: true, correctness: false, answer_key: false, explanation: false, section_analytics: true, rank: false },
    after_close: { score: true, correctness: true, answer_key: true, explanation: true, section_analytics: true, rank: true },
    integrity: {},
  };

  it("validateBuilder catches the shapes the api would 422", () => {
    const rule = { rule_type: "random" as const, topic_id: "", difficulty_min: 4, difficulty_max: 2, draw_count: 0, marks_each: 1, negative_marks_each: 0 };
    const e = validateBuilder({ ...settings, grace_seconds: "400", available_from: "2026-11-05T10:00", available_until: "2026-11-04T10:00" }, [
      { title: "A", duration_minutes: null, rules: [rule] },
      { title: "", duration_minutes: null, rules: [] },
    ]);
    expect(e).toMatchObject({
      grace_seconds: expect.any(String),
      available_until: expect.any(String),
      "sections.0.rules.0.topic_id": expect.any(String),
      "sections.0.rules.0.difficulty_min": expect.any(String),
      "sections.0.rules.0.draw_count": expect.any(String),
      "sections.1.title": expect.any(String),
      "sections.1.rules": expect.any(String),
    });
    expect(validateBuilder(settings, [{ title: "A", duration_minutes: null, rules: [{ ...rule, topic_id: "t", difficulty_min: 1, draw_count: 5 }] }])).toEqual({});
  });

  const blank = {
    id: "t1",
    title: "DSA Weekly",
    test_kind: "mock",
    status: "draft",
    version: 1,
    duration_seconds: 3600,
    grace_seconds: 30,
    navigation_mode: "free",
    attempts_allowed: 1,
    grading_method: "highest",
    shuffle_questions: true,
    shuffle_options: true,
    review_policy: null,
    integrity_settings: { fullscreen: false, log_focus: true, log_paste: true },
    pass_percentage: null,
    available_from: null,
    available_until: null,
    settings_locked_at: null,
    sections: [],
  };

  it("a new test has no empty default rule; Save is blocked client-side until a question is picked", async () => {
    const api = mockApi({
      "GET studio/tests/t1": { body: blank },
      "GET studio/questions": {
        body: {
          items: [
            { question_id: "q1", organization_id: null, question_type: "mcq_single", primary_topic_id: "tp", status: "active", latest_version: { question_version_id: "v1", version_no: 1, status: "published", difficulty: 2, stem_html: "<p>Reverse a linked list</p>" } },
            { question_id: "q2", organization_id: null, question_type: "mcq_single", primary_topic_id: "tp", status: "active", latest_version: { question_version_id: "v2", version_no: 1, status: "published", difficulty: 3, stem_html: "<p>Binary search bounds</p>" } },
          ],
        },
      },
      "PATCH studio/tests/t1": { body: blank },
      "PUT studio/tests/t1/sections": { body: blank },
    });
    restore = api.restore;
    renderWithProviders(<TestBuilder testId="t1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Save" }));
    expect(await screen.findByText("Add a draw rule or pick questions for this section.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "PATCH" || c.method === "PUT")).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Pick questions" }));
    const dialog = await screen.findByRole("dialog");
    expect(api.calls.find((c) => c.path === "studio/questions")?.url).toContain("version_status=published");
    await userEvent.click(within(dialog).getByLabelText("Search question text"));
    await userEvent.paste("binary");
    expect(within(dialog).queryByText("Reverse a linked list")).not.toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: /Add Binary search bounds/ }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Done" }));
    expect(screen.getByText(/Fixed question: Binary search bounds/)).toBeInTheDocument();

    await userEvent.click(screen.getByLabelText("After they submit: Answer key"));
    await userEvent.click(screen.getByLabelText(/Ask for full screen/));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "PUT")).toBe(true));
    const patch = api.calls.find((c) => c.method === "PATCH")!.body as Record<string, unknown>;
    expect(patch).toMatchObject({
      grace_seconds: 30,
      shuffle_options: true,
      review_policy: { after_submit: { score: true, answer_key: true }, release_at: null },
      integrity_settings: { fullscreen: true, log_focus: true, log_paste: true },
    });
    expect(api.calls.find((c) => c.method === "PUT")!.body).toEqual({
      sections: [{ title: "Section A", duration_seconds: null, rules: [{ rule_type: "fixed", question_id: "q2", question_version_id: null, draw_count: 1, marks_each: "1", negative_marks_each: "0" }] }],
    });
  });

  it("maps problem+json errors[] to the matching rule fields", async () => {
    const withRule = {
      ...blank,
      sections: [{ section_id: "s1", title: "Section A", position: 0, duration_seconds: null, instructions_md: null, question_count: 5, rules: [{ rule_id: "r1", position: 0, rule_type: "random", question_id: null, question_version_id: null, topic_id: "not-a-uuid", company_id: null, question_types: null, difficulty_min: 1, difficulty_max: 5, draw_count: 5, marks_each: "1", negative_marks_each: null }] }],
    };
    const api = mockApi({
      "GET studio/tests/t1": { body: withRule },
      "PATCH studio/tests/t1": { body: withRule },
      "PUT studio/tests/t1/sections": problem(422, "validation_error", "Invalid request", {
        errors: [
          { field: "sections.0.rules.0.topic_id", code: "uuid_parsing", message: "Input should be a valid UUID" },
          { field: "sections.0.instructions_md", code: "too_long", message: "Too long" },
        ],
      }),
    });
    restore = api.restore;
    renderWithProviders(<TestBuilder testId="t1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Save" }));
    expect(await screen.findByText("Input should be a valid UUID")).toBeInTheDocument();
    expect(screen.getByLabelText(/^Topic id/)).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText(/sections\.0\.instructions_md/)).toBeInTheDocument();
  });
});

describe("ADM-47 grading: files, code and rubric", () => {
  const routes = (submission: Record<string, unknown>, rubric: unknown) => ({
    "GET assignments": {
      body: {
        data: [{ id: "as1", assignment_id: "as1", title: "Arrays worksheet", batch_id: "b1", batch_name: "CSE-A", max_score: 10, max_points: 10, pending_count: 1, grades_released: false, rubric }],
        page: { next_cursor: null, has_more: false, limit: 100 },
      },
    },
    "GET batches/b1/members": { body: { data: [{ user_id: "u1", full_name: "Ravi Kumar", member_role: "student" }] } },
    "GET assignments/as1/submissions": {
      body: {
        data: [{ id: "s1", assignment_id: "as1", user_id: "u1", attempt_no: 1, submitted_at: "2026-11-02T10:00:00.000Z", status: "submitted", body_text: null, link_url: null, file_s3_keys: [], code_submission_id: null, score: null, rubric_scores: null, ...submission }],
        page: { next_cursor: null, has_more: false, limit: 200 },
      },
    },
    "GET assignment-submissions/s1/files/0": { body: { url: "https://files.example.test/report.pdf?sig=1", filename: "report.pdf", expires_at: "2026-11-03T10:05:00Z" } },
    "GET coding/submissions/cs1": { body: { language_key: "python3", status: "completed", verdict: "accepted", passed_cases: 8, total_cases: 10, source_code: "print('hi')" } },
    "POST assignment-submissions/s1/grade": { body: { ok: true } },
  });

  const openGrade = async () => {
    await userEvent.click(await screen.findByRole("button", { name: "Show submissions for Arrays worksheet" }));
    await userEvent.click(await screen.findByRole("button", { name: "Grade Ravi Kumar" }));
  };

  it("downloads attachments and shows the code submission", async () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    const api = mockApi(routes({ file_s3_keys: ["uploads/s1/report.pdf"], code_submission_id: "cs1" }, null));
    restore = api.restore;
    renderWithProviders(<GradingQueue />);
    await openGrade();
    expect(await screen.findByLabelText("Submitted code")).toHaveTextContent("print('hi')");
    expect(screen.getByText(/8\/10 tests passed/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Download report.pdf" }));
    await waitFor(() => expect(open).toHaveBeenCalledWith("https://files.example.test/report.pdf?sig=1", "_blank", "noopener,noreferrer"));
    open.mockRestore();
  });

  it("scores by rubric and sends rubric_scores without score (the api totals them)", async () => {
    const api = mockApi(routes({}, { criteria: [{ key: "logic", label: "Logic", max_points: 6 }, { key: "style", label: "Style", max_points: 4 }] }));
    restore = api.restore;
    renderWithProviders(<GradingQueue />);
    await openGrade();
    await userEvent.type(await screen.findByLabelText(/^Logic/), "7");
    await userEvent.type(screen.getByLabelText(/^Style/), "3");
    await userEvent.click(screen.getByRole("button", { name: "Save grade" }));
    expect(await screen.findByText("Enter 0 to 6.")).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText(/^Logic/));
    await userEvent.type(screen.getByLabelText(/^Logic/), "5");
    await userEvent.click(screen.getByRole("button", { name: "Save grade" }));
    await waitFor(() =>
      expect(api.calls.find((c) => c.method === "POST")?.body).toMatchObject({ action: "grade", rubric_scores: { logic: 5, style: 3 } }),
    );
    expect(api.calls.find((c) => c.method === "POST")?.body).not.toHaveProperty("score");
  });

  it("shows the raw score and late penalty of a late graded submission (BE-08)", async () => {
    const api = mockApi(routes({ status: "graded", score: 7.2, raw_score: 8, late_penalty_pct: 10 }, null));
    restore = api.restore;
    renderWithProviders(<GradingQueue />);
    await userEvent.click(await screen.findByRole("button", { name: "Show submissions for Arrays worksheet" }));
    expect(await screen.findByText(/8 before −10% late penalty/)).toBeInTheDocument();
  });

  it("buildRubric / rubricErrors produce the documented {criteria:[{key,label,max_points}]} shape", () => {
    expect(buildRubric([{ label: "Logic & flow", max_points: "6" }, { label: "Logic & flow", max_points: "4" }])).toEqual({
      criteria: [
        { key: "logic_flow", label: "Logic & flow", max_points: 6 },
        { key: "logic_flow_2", label: "Logic & flow", max_points: 4 },
      ],
    });
    expect(buildRubric([{ label: "", max_points: "" }])).toBeNull();
    expect(rubricErrors([{ label: "A", max_points: "8" }, { label: "B", max_points: "4" }], 10)).toMatch(/add up to 12/);
    expect(rubricErrors([{ label: "", max_points: "3" }], 10)).toMatch(/name/);
    expect(rubricErrors([{ label: "A", max_points: "5" }], 10)).toBeNull();
  });

  it("parseRubric understands both rubric shapes and ignores others", () => {
    expect(parseRubric({ Logic: 6, Style: 4, note: "x" })).toEqual([
      { key: "Logic", label: "Logic", max: 6 },
      { key: "Style", label: "Style", max: 4 },
    ]);
    expect(parseRubric({ criteria: [{ name: "Clarity", points: 5 }] })).toEqual([{ key: "Clarity", label: "Clarity", max: 5 }]);
    expect(parseRubric(null)).toEqual([]);
    expect(parseRubric("free text")).toEqual([]);
  });
});

describe("Trainer assignment rubric (w2b R4)", () => {
  it("creates an assignment with a rubric in the documented shape", async () => {
    const api = mockApi({
      "GET assignments": { body: { data: [], page: { next_cursor: null, has_more: false, limit: 100 } } },
      "GET me/grants": { body: { data: [{ role_key: "trainer", scope_type: "batch", scope_id: "b1" }] } },
      "GET batches/b1": { body: { id: "b1", name: "CSE-A" } },
      "POST assignments": { status: 201, body: { id: "as1" } },
    });
    restore = api.restore;
    renderWithProviders(<TrainerAssignments />);
    await userEvent.click((await screen.findAllByRole("button", { name: "New assignment" }))[0]!);
    const dialog = await screen.findByRole("dialog");
    const batch = within(dialog).getByLabelText(/Batch/) as HTMLSelectElement;
    await waitFor(() => expect(batch.options.length).toBeGreaterThan(1));
    await userEvent.selectOptions(batch, batch.options[1]!.value);
    await userEvent.type(within(dialog).getByLabelText(/Title/), "Arrays");
    await userEvent.type(within(dialog).getByLabelText(/Instructions/), "Solve all.");
    await userEvent.type(within(dialog).getByLabelText(/Due/), "2026-12-01T10:00");
    await userEvent.click(within(dialog).getByRole("button", { name: "Add criterion" }));
    await userEvent.type(within(dialog).getByLabelText("Criterion 1"), "Correctness");
    await userEvent.type(within(dialog).getByLabelText("Criterion 1 points"), "10");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    expect(api.calls.find((c) => c.method === "POST")!.body).toMatchObject({ rubric: { criteria: [{ key: "correctness", label: "Correctness", max_points: 10 }] } });
  });
});

describe("ADM-53 dashboard and batch widgets", () => {
  it("GradingBacklog totals pending submissions from the assignment list", async () => {
    const api = mockApi({
      "GET assignments": {
        body: {
          data: [
            { assignment_id: "a1", title: "Arrays worksheet", batch_name: "CSE-A", pending_count: 3 },
            { assignment_id: "a2", title: "Graphs", batch_name: "CSE-A", pending_count: 0 },
            { assignment_id: "a3", title: "DP set", batch_name: null, pending_count: 2 },
          ],
          page: { next_cursor: null, has_more: false, limit: 100 },
        },
      },
    });
    restore = api.restore;
    renderWithProviders(<GradingBacklog />);
    expect(await screen.findByText("5")).toBeInTheDocument();
    expect(screen.getByText(/Arrays worksheet/)).toBeInTheDocument();
    expect(screen.queryByText("Graphs")).not.toBeInTheDocument();
  });

  it("pickLive keeps open and soon-opening windows for the trainer's batches only", () => {
    const now = Date.parse("2026-11-03T12:00:00.000Z");
    const t = { id: "t1", title: "Mock 1" } as TestSummary;
    const rows = pickLive(
      [t],
      [[
        assignment({ id: "open" }),
        assignment({ id: "soon", available_from: "2026-11-05T09:00:00.000Z" }),
        assignment({ id: "far", available_from: "2026-12-20T09:00:00.000Z", available_until: "2026-12-21T09:00:00.000Z" }),
        assignment({ id: "closed", available_until: "2026-11-02T09:00:00.000Z" }),
        assignment({ id: "other", batch_id: "b9" }),
      ]],
      ["b1"],
      now,
    );
    expect(rows.map((r) => [r.assignment.id, r.live])).toEqual([
      ["open", true],
      ["soon", false],
    ]);
  });

  it("BatchProgress lists students needing attention and says when there is no course progress yet", async () => {
    const api = mockApi({
      "GET analytics/reports/batches/b1": {
        body: {
          batch_id: "b1",
          week_start: "2026-11-02",
          learners_total: 2,
          weekly_learning_time: { n: "<5", median_s: "<5", p90_s: "<5", suppressed: true },
          learners: [
            { user_id: "u1", weekly_learning_s: 1200, weak_topics: 3, needs_attention: true, reasons: ["weak_required_topics"] },
            { user_id: "u2", weekly_learning_s: 3600, weak_topics: 0, needs_attention: false, reasons: [] },
          ],
          progress_distribution: null,
          lesson_funnel: null,
        },
      },
      "GET batches/b1/members": { body: { data: [{ user_id: "u1", full_name: "Ravi Kumar", member_role: "student" }] } },
    });
    restore = api.restore;
    renderWithProviders(<BatchProgress batchId="b1" />);
    expect(await screen.findByText("Ravi Kumar")).toBeInTheDocument();
    expect(screen.getByText(/too few active learners/)).toBeInTheDocument();
    expect(screen.getByText("No course progress yet.")).toBeInTheDocument();
  });

  it("BatchProgress renders the progress buckets and the lesson funnel, k-floored per course (webstaff R11)", async () => {
    const api = mockApi({
      "GET analytics/reports/batches/b1": {
        body: {
          batch_id: "b1",
          week_start: "2026-11-02",
          learners_total: 12,
          weekly_learning_time: { n: 12, median_s: 1800, p90_s: 3600, suppressed: false },
          learners: [],
          progress_distribution: {
            enrolments: 12,
            suppressed: false,
            buckets: [
              { bucket: "not_started", min_pct: 0, max_pct: 0, enrolments: 2 },
              { bucket: "1-25", min_pct: 0.01, max_pct: 25, enrolments: 3 },
              { bucket: "26-50", min_pct: 25.01, max_pct: 50, enrolments: 1 },
              { bucket: "51-75", min_pct: 50.01, max_pct: 75, enrolments: 0 },
              { bucket: "76-99", min_pct: 75.01, max_pct: 99.99, enrolments: 2 },
              { bucket: "completed", min_pct: 100, max_pct: 100, enrolments: 4 },
            ],
          },
          lesson_funnel: [
            { course_id: "c1", course_title: "DSA Basics", enrolments: 12, suppressed: false, steps: [
              { lesson_key: "k1", title: "Arrays", is_required: true, started: 11, completed: 9 },
              { lesson_key: "k2", title: "Bonus", is_required: false, started: 4, completed: 2 },
            ] },
            { course_id: "c2", course_title: "SQL", enrolments: "<10", suppressed: true, steps: [] },
          ],
        },
      },
      "GET batches/b1/members": { body: { data: [] } },
    });
    restore = api.restore;
    renderWithProviders(<BatchProgress batchId="b1" />);
    const buckets = await screen.findByRole("list", { name: "Enrolments by course progress" });
    expect(within(buckets).getAllByRole("listitem")).toHaveLength(6);
    expect(within(buckets).getByText("Completed")).toBeInTheDocument();
    expect(within(buckets).getByText("1–25%")).toBeInTheDocument();
    expect(screen.getByText("Arrays")).toBeInTheDocument();
    expect(screen.getByText("Bonus (optional)")).toBeInTheDocument();
    expect(screen.getByText("11")).toBeInTheDocument();
    expect(screen.getByText(/SQL/)).toBeInTheDocument();
    expect(screen.getAllByText("Too few students to show").length).toBeGreaterThanOrEqual(1);
  });
});

describe("ADM-41 trainer course create (single company: the api picks the owner)", () => {
  it("creates a course without organization_id or org_only visibility", async () => {
    const api = mockApi({
      "GET me/grants": { body: grants },
      "GET batches/b1": { body: batch },
      "GET studio/courses": { body: { data: [], page: { next_cursor: null, has_more: false, limit: 100 } } },
      "POST studio/courses": { status: 201, body: { id: "c9" } },
    });
    restore = api.restore;
    renderWithProviders(<TrainerCourses hrefPattern="/trainer/courses/:id/edit" />);
    await userEvent.click((await screen.findAllByRole("button", { name: "New course" }))[0]!);
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/^Title/), "Aptitude basics");
    expect(within(dialog).getByLabelText(/^URL slug/)).toHaveValue("aptitude-basics");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create draft" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/trainer/courses/c9/edit"));
    expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ title: "Aptitude basics", slug: "aptitude-basics" });
  });
});

describe("BE-21 test lists follow page.next_cursor", () => {
  const t = (id: string, title: string): TestSummary =>
    ({ id, title, test_kind: "mock", duration_seconds: 600, status: "draft" }) as unknown as TestSummary;
  it("trainer TestsList pages through studio/tests", async () => {
    const api = mockApi({
      "GET studio/tests": (call) =>
        call.url.includes("cursor=n2")
          ? { body: { items: [t("t2", "Second page test")], page: { next_cursor: null, has_more: false, limit: 100 } } }
          : { body: { items: [t("t1", "First page test")], page: { next_cursor: "n2", has_more: true, limit: 100 } } },
    });
    restore = api.restore;
    renderWithProviders(<TestsList batches={[{ value: "b1", label: "CSE 2027 A" }]} basePath="/trainer" />);
    expect(await screen.findByText("First page test")).toBeInTheDocument();
    await userEvent.click(within(screen.getByRole("navigation", { name: "Tests pages" })).getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Second page test")).toBeInTheDocument();
    await userEvent.click(within(screen.getByRole("navigation", { name: "Tests pages" })).getByRole("button", { name: "Previous" }));
    expect(await screen.findByText("First page test")).toBeInTheDocument();
  });
});

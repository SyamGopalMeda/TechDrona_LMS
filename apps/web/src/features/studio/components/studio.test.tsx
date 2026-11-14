import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { CodingProblemEditor } from "./Coding";
import { QuestionReportQueue } from "./QuestionReports";
import { StudioDashboard } from "./StudioDashboard";
import { QuestionEditor, ReviewQueue, questionTypeLabel, validateQuestion } from "./Questions";
import { TestBuilder, testKindLabel } from "./Tests";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace }) }));

let restore: (() => void) | undefined;
afterEach(() => restore?.());

describe("enum labels", () => {
  it("humanises question types and test kinds", () => {
    expect(questionTypeLabel("fill_blank")).toBe("Fill in the blank");
    expect(questionTypeLabel("mcq_single")).toBe("Multiple choice — one answer");
    expect(questionTypeLabel("long_answer")).toBe("Long answer");
    expect(testKindLabel("mock")).toBe("Mock test");
    expect(testKindLabel("weekly_quiz")).toBe("Weekly quiz");
  });
});

describe("validateQuestion", () => {
  const base = { type: "mcq_single", stem: "What is 2 + 2?", options: [{ text: "3" }, { text: "4", is_correct: true }], explanation: "", difficulty: "2", topic_id: "", tags: "" };
  it("requires an explanation only for review", () => {
    expect(validateQuestion(base, false)).toEqual({});
    expect(validateQuestion(base, true).explanation_html).toMatch(/required before review/);
  });
  it("requires exactly one correct option for single-answer MCQ", () => {
    expect(validateQuestion({ ...base, options: [{ text: "3", is_correct: true }, { text: "4", is_correct: true }] }, false).options).toMatch(/exactly one/);
    expect(validateQuestion({ ...base, options: [{ text: "3" }, { text: "4" }] }, false).options).toMatch(/Mark the correct/);
  });
  it("requires a topic for new questions and a value for numeric ones", () => {
    expect(validateQuestion(base, false, true).primary_topic_id).toBeTruthy();
    expect(validateQuestion({ ...base, type: "numeric", options: [], numeric_value: "" }, false)["answer_key.value"]).toBeTruthy();
  });
});

const version = (over: Record<string, unknown> = {}) => ({
  question_version_id: "v1",
  version_no: 1,
  status: "draft",
  difficulty: 2,
  stem_html: "A train covers 120 km in 2 h. Speed?",
  default_marks: "1",
  default_negative: "0",
  expected_seconds: null,
  authored_by: "u1",
  reviewed_by: null,
  published_at: null,
  options: [
    { option_id: "o1", label: "A", html: "50 km/h", is_correct: false },
    { option_id: "o2", label: "B", html: "60 km/h", is_correct: true },
  ],
  explanation_html: null,
  answer_key: null,
  ...over,
});

const draft = {
  question_id: "q1",
  organization_id: null,
  question_type: "mcq_single",
  primary_topic_id: "t1",
  status: "draft",
  current_version_id: null,
  created_by: "u1",
  keys_visible: true,
  tags: [{ tag_type: "custom", topic_id: null, company_id: null, value: "speed" }],
  versions: [version()],
};

describe("QuestionEditor (CMS-005)", () => {
  it("blocks review until an explanation is saved, then submits", async () => {
    const api = mockApi({
      "GET studio/questions/q1": () => ({ body: api.calls.some((c) => c.path.endsWith("/versions")) ? { ...draft, versions: [version({ explanation_html: "120 / 2 = 60" })] } : draft }),
      "POST studio/questions/q1/versions": { body: draft },
      "POST studio/questions/q1/submit-review": { body: { question_id: "q1", status: "draft", latest_version: { version_no: 1, status: "in_review", reviewed: false } } },
    });
    restore = api.restore;
    renderWithProviders(<QuestionEditor questionId="q1" />);
    const submit = await screen.findByRole("button", { name: "Submit for review" });
    expect(submit).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/^Explanation/), "120 / 2 = 60");
    await userEvent.click(screen.getByRole("button", { name: "Submit for review" }));
    expect(await screen.findByText("Save your changes before submitting")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() =>
      expect(api.calls.find((c) => c.path === "studio/questions/q1/versions")?.body).toMatchObject({
        explanation_html: "120 / 2 = 60",
        options: [
          { html: "50 km/h", is_correct: false },
          { html: "60 km/h", is_correct: true },
        ],
        difficulty: 2,
      }),
    );
    await waitFor(() => expect(screen.getByRole("button", { name: "Submit for review" })).toBeEnabled());
    await userEvent.click(screen.getByRole("button", { name: "Submit for review" }));
    await waitFor(() => expect(api.calls.some((c) => c.path === "studio/questions/q1/submit-review")).toBe(true));
  });

  it("does not show answer-key fields when the api withholds them", async () => {
    const hidden = version({ status: "published", options: [{ option_id: "o1", label: "A", html: "50 km/h" }] });
    delete (hidden as Record<string, unknown>).explanation_html;
    const api = mockApi({ "GET studio/questions/q1": { body: { ...draft, status: "active", keys_visible: false, versions: [hidden] } } });
    restore = api.restore;
    renderWithProviders(<QuestionEditor questionId="q1" />);
    expect(await screen.findByText(/only shown to the author and reviewers/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/^Explanation/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Save/ })).not.toBeInTheDocument();
  });
});

describe("ReviewQueue (CMS-007)", () => {
  it("admin mode: questions only, read-only preview with the key, may publish", async () => {
    const api = mockApi({
      "GET studio/questions": {
        body: {
          items: [{ question_id: "q1", organization_id: null, question_type: "mcq_single", primary_topic_id: "t1", status: "draft", latest_version: { question_version_id: "v1", version_no: 1, status: "in_review", reviewed: false, difficulty: 2, stem_html: "<p>2 + 2?</p>" } }],
          limit: 200,
          offset: 0,
        },
      },
      "GET studio/questions/q1": {
        body: {
          question_id: "q1", organization_id: null, question_type: "mcq_single", primary_topic_id: "t1", status: "draft", current_version_id: null, created_by: "u1", keys_visible: true, tags: [],
          versions: [{ question_version_id: "v1", version_no: 1, status: "in_review", difficulty: 2, stem_html: "<p>2 + 2?</p>", default_marks: "1", default_negative: "0", expected_seconds: null, authored_by: "u1", reviewed_by: null, published_at: null, options: [{ option_id: "o1", label: "A", html: "3", is_correct: false }, { option_id: "o2", label: "B", html: "4", is_correct: true }] }],
        },
      },
      "POST studio/questions/q1/review": { body: { question_id: "q1" } },
    });
    restore = api.restore;
    renderWithProviders(<ReviewQueue mode="admin" />);
    await userEvent.click(await screen.findByRole("button", { name: "Review" }));
    expect(await screen.findByText("(correct)", { exact: false })).toBeInTheDocument();
    expect(screen.getByLabelText("Publish right away")).toBeInTheDocument(); // Admin holds question.publish (≠ author)
    expect(screen.queryByText("Courses waiting for review")).toBeNull();
    expect(api.calls.some((c) => c.path === "studio/courses")).toBe(false);
    expect(screen.queryByRole("link", { name: /2 \+ 2/ })).toBeNull();
  });

  it("explains author ≠ reviewer", async () => {
    const api = mockApi({
      "GET studio/questions": {
        body: {
          items: [
            { question_id: "q1", organization_id: null, question_type: "mcq_single", primary_topic_id: "t1", status: "draft", latest_version: { question_version_id: "v1", version_no: 1, status: "in_review", difficulty: 2, stem_html: "<p>Find the odd one out</p>" } },
            { question_id: "q2", organization_id: null, question_type: "mcq_single", primary_topic_id: "t1", status: "draft", latest_version: { question_version_id: "v2", version_no: 1, status: "draft", difficulty: 2, stem_html: "Not yet" } },
          ],
          limit: 200,
          offset: 0,
        },
      },
      "GET studio/courses": { body: { data: [], page: { next_cursor: null, has_more: false, limit: 100 } } },
      "POST studio/questions/q1/review": problem(403, "sod_violation", "Separation of duties"),
    });
    restore = api.restore;
    renderWithProviders(<ReviewQueue />);
    expect(await screen.findByRole("link", { name: "Find the odd one out" })).toBeInTheDocument();
    expect(screen.queryByText("Not yet")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Review" }));
    await userEvent.click(screen.getByRole("button", { name: "Save review" }));
    expect(await screen.findByText("You can't review your own question")).toBeInTheDocument();
  });
});

describe("CodingProblemEditor (CMS-010)", () => {
  const problemBody = {
    problem_id: "p1",
    slug: "two-sum",
    title: "Two Sum",
    status: "draft",
    version_no: 3,
    statement_md: "Find two numbers.",
    input_format_md: null,
    output_format_md: null,
    constraints_md: null,
    difficulty: 2,
    limits: { time_limit_ms: 2000, wall_limit_ms: null, memory_limit_kb: 262144 },
    allowed_languages: ["python3"],
    scoring_mode: "weighted_cases",
    is_free: false,
    organization_id: null,
    checker_type: "exact",
    created_by: "u1",
    time_limit_ms: 2000,
    memory_limit_mb: 256,
    languages: ["python3"],
    test_cases: { sample: 1, hidden: 0 },
    updated_at: "2026-11-03T10:00:00Z",
    published_at: null,
  };
  const routes = () => ({
    "GET studio/coding/problems/p1": { body: problemBody },
    "GET studio/coding/problems/p1/test-cases": {
      body: {
        problem_version: 3,
        data: [
          { test_case_id: "c1", ordinal: 1, is_sample: true, weight: 1, input: "4\n2 7 11 15\n9", expected_output: "0 1" },
          { test_case_id: "c2", ordinal: 2, is_sample: false, weight: 5, size_bytes: 2048, input_sha256: "abcdef0123456789abcdef", expected_sha256: "fff" },
        ],
      },
    },
    "PATCH studio/coding/problems/p1": { body: problemBody },
  });

  it("lists hidden cases as metadata only and gates publishing on having both case kinds", async () => {
    const api = mockApi(routes());
    restore = api.restore;
    renderWithProviders(<CodingProblemEditor problemId="p1" />);
    const hidden = await screen.findByRole("table", { name: /Hidden test cases/ });
    expect(within(hidden).getByText("2.0 KiB")).toBeInTheDocument();
    expect(within(hidden).getByText("abcdef012345…")).toBeInTheDocument();
    expect(screen.getByText("0 1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "View content of hidden case 2" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Publish" })).toBeDisabled();
    // The problem title is the h1, with a trail back to the list.
    expect(screen.getByRole("heading", { level: 1, name: "Two Sum" })).toBeInTheDocument();
    expect(within(screen.getByRole("navigation", { name: "Breadcrumb" })).getByRole("link", { name: "Coding problems" })).toHaveAttribute("href", "/studio/coding");
    expect(screen.getByRole("navigation", { name: "Coding problem sections" })).toBeInTheDocument();
    // No stored reference solution → no GET …/validation (it can only 404).
    expect(api.calls.some((c) => c.path.endsWith("/validation"))).toBe(false);
    expect(await screen.findByText("Not validated yet.")).toBeInTheDocument();
  });

  it("saves limits in kilobytes", async () => {
    const api = mockApi(routes());
    restore = api.restore;
    renderWithProviders(<CodingProblemEditor problemId="p1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.calls.find((c) => c.method === "PATCH")?.body).toMatchObject({ memory_limit_kb: 262144, time_limit_ms: 2000 }));
  });
});

describe("CodingProblemEditor validation and hidden content (COD-17/18)", () => {
  const problemBody = {
    problem_id: "p1", slug: "two-sum", title: "Two Sum", status: "draft", version_no: 3, statement_md: "Find two numbers.",
    input_format_md: null, output_format_md: null, constraints_md: null, difficulty: 2,
    limits: { time_limit_ms: 2000, wall_limit_ms: null, memory_limit_kb: 262144 }, allowed_languages: ["python3", "cpp17"],
    scoring_mode: "weighted_cases", is_free: false, organization_id: null, checker_type: "exact", created_by: "u1",
    time_limit_ms: 2000, memory_limit_mb: 256, languages: ["python3", "cpp17"], test_cases: { sample: 1, hidden: 1 },
    updated_at: "2026-11-03T10:00:00Z", published_at: null,
  };
  const validation = {
    validation_id: "v1", problem_id: "p1", problem_version: 3, status: "failed", is_current: true, validated_at: "2026-11-03T10:00:00Z",
    requested_by: "u1", detail: null,
    solutions: [{ language_key: "python3", verdict: "WA", passed_cases: 1, total_cases: 2, cases: [
      { ordinal: 1, is_sample: true, verdict: "AC", time_ms: 7, memory_kb: 3200 },
      { ordinal: 2, is_sample: false, verdict: "WA", time_ms: 8, memory_kb: 3200 },
    ] }],
  };
  const routes = (extra: Record<string, unknown> = {}) => ({
    "GET studio/coding/problems/p1": { body: problemBody },
    "GET studio/coding/problems/p1/test-cases": {
      body: { problem_version: 3, data: [
        { test_case_id: "c1", ordinal: 1, is_sample: true, weight: 1, input: "1", expected_output: "1" },
        { test_case_id: "c2", ordinal: 2, is_sample: false, weight: 1, size_bytes: 10, input_sha256: "aa", expected_sha256: "bb" },
      ] },
    },
    "GET studio/coding/problems/p1/reference-solutions": { body: { data: [{ language_key: "python3", source_code: "print(1)", size_bytes: 8, updated_at: "2026-11-03T10:00:00Z" }] } },
    ...extra,
  });

  it("prefills the stored reference solution and shows verdict-only results after Validate", async () => {
    const api = mockApi(routes({ "POST studio/coding/problems/p1/validate": { body: { ...validation, validation_id: "v2", status: "passed", solutions: [{ ...validation.solutions[0], verdict: "AC", passed_cases: 2, cases: validation.solutions[0]!.cases.map((c) => ({ ...c, verdict: "AC" })) }] } } }));
    restore = api.restore;
    renderWithProviders(<CodingProblemEditor problemId="p1" />);
    expect(await screen.findByText("Not validated yet.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Reference solution")).toHaveValue("print(1)"));
    await userEvent.click(screen.getByRole("button", { name: "Validate" }));
    const table = await screen.findByRole("table", { name: /Validation results \(python3\): AC, 2\/2/ });
    expect(within(table).getByText("Hidden")).toBeInTheDocument();
    expect(api.calls.find((c) => c.path.endsWith("/validate"))?.body).toEqual({ reference_solutions: [{ language_key: "python3", source_code: "print(1)" }] });
  });

  it("shows the latest validation on load and explains a validation_required publish refusal", async () => {
    const api = mockApi(routes({
      "GET studio/coding/problems/p1/validation": { body: validation },
      "POST studio/coding/problems/p1/publish": problem(409, "invalid_state_transition", "Not allowed", { reason: "validation_required" }),
    }));
    restore = api.restore;
    renderWithProviders(<CodingProblemEditor problemId="p1" />);
    // The latest validation is fetched once the stored reference solutions load (sequential calls).
    expect(await screen.findByRole("table", { name: /Validation results \(python3\): WA, 1\/2/ }, { timeout: 4000 })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Publish" }));
    expect(await screen.findByText("Validate before publishing")).toBeInTheDocument();
  });

  it("asks for a reason before issuing short-lived hidden-case links", async () => {
    const api = mockApi(routes({
      "GET studio/coding/test-cases/c2/content": {
        body: { test_case_id: "c2", ordinal: 2, input_url: "/api/v1/studio/coding/test-cases/content-downloads/tok-in", expected_url: "/api/v1/studio/coding/test-cases/content-downloads/tok-out", expires_at: "2026-11-03T10:05:00Z", sha256: { input: "aa", expected: "bb" } },
        headers: { "cache-control": "no-store" },
      },
    }));
    restore = api.restore;
    renderWithProviders(<CodingProblemEditor problemId="p1" />);
    await userEvent.click(await screen.findByRole("button", { name: "View content of hidden case 2" }));
    await userEvent.type(screen.getByLabelText(/^Reason/), "short");
    await userEvent.click(screen.getByRole("button", { name: "Get download links" }));
    expect(await screen.findByText(/at least 10 characters/)).toBeInTheDocument();
    expect(api.calls.some((c) => c.path.endsWith("/content"))).toBe(false);
    await userEvent.type(screen.getByLabelText(/^Reason/), " — fixing reported issue");
    await userEvent.click(screen.getByRole("button", { name: "Get download links" }));
    const link = await screen.findByRole("link", { name: "Download input" });
    expect(link).toHaveAttribute("href", "/api/v1/studio/coding/test-cases/content-downloads/tok-in");
    expect(screen.getByRole("link", { name: "Download expected output" })).toBeInTheDocument();
    const call = api.calls.find((c) => c.path.endsWith("/content"))!;
    expect(new URL(call.url, "http://x").searchParams.get("reason")).toBe("short — fixing reported issue");
  });
});

describe("QuestionReportQueue (CMS-013)", () => {
  const report = {
    report_id: "r1", question_id: "q1", question_version_id: "qv1", organization_id: null, category: "wrong_answer",
    message: "Option B should be correct", status: "open", resolution: null, resolution_note: null, reporter_user_id: "u9",
    created_at: "2026-11-03T10:00:00Z", resolved_at: null, resolved_by: null,
  };

  it("lists open reports and resolves one with a note", async () => {
    const api = mockApi({
      "GET studio/question-reports": () => {
        const resolved = api.calls.some((x) => x.method === "POST");
        return { body: { data: resolved ? [] : [report], meta: { next_cursor: null, has_more: false, limit: 25 }, open_count: resolved ? 0 : 1 } };
      },
      "POST studio/question-reports/r1/resolve": { body: { ...report, status: "resolved", resolution: "fixed", resolution_note: "Key corrected" } },
    });
    restore = api.restore;
    renderWithProviders(<QuestionReportQueue />);
    expect(await screen.findByText("Option B should be correct")).toBeInTheDocument();
    expect(screen.getByText("1 open report")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Resolve report r1" }));
    await userEvent.type(screen.getByLabelText(/^Note to the reporter/), "Key corrected");
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Resolve" }));
    expect(await screen.findByText("Report resolved")).toBeInTheDocument();
    const post = api.calls.find((c) => c.method === "POST")!;
    expect(post.body).toEqual({ resolution: "fixed", note: "Key corrected" });
    expect(await screen.findByText("No open reports")).toBeInTheDocument();
  });
});

describe("StudioDashboard", () => {
  it("shows the open error report count from the queue", async () => {
    const api = mockApi({
      "GET studio/questions": { body: { items: [] } },
      "GET studio/courses": { body: { data: [], page: { next_cursor: null, has_more: false } } },
      "GET studio/question-reports": { body: { data: [], meta: { next_cursor: null, has_more: false, limit: 1 }, open_count: 7 } },
    });
    restore = api.restore;
    renderWithProviders(<StudioDashboard />);
    expect(await screen.findByText("7")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open error reports.*Triage reports/ })).toHaveAttribute("href", "/studio/reports/errors");
    expect(screen.getByRole("link", { name: /^Template mocks/ })).toHaveAttribute("href", "/studio/tests");
  });
});

describe("TestBuilder", () => {
  const def = {
    id: "t1",
    title: "DSA Weekly 3",
    test_kind: "mock",
    status: "draft",
    version: 1,
    duration_seconds: 3600,
    navigation_mode: "free",
    attempts_allowed: 1,
    shuffle_questions: true,
    pass_percentage: null,
    settings_locked_at: null,
    sections: [
      {
        section_id: "s1",
        title: "Section A",
        position: 0,
        duration_seconds: null,
        instructions_md: null,
        question_count: 15,
        rules: [
          { rule_id: "r1", position: 0, rule_type: "random", question_id: null, question_version_id: null, topic_id: "arrays", company_id: null, question_types: null, difficulty_min: 2, difficulty_max: 4, draw_count: 15, marks_each: "1", negative_marks_each: null },
        ],
      },
    ],
  };

  it("highlights draw rules without enough questions and keeps publish disabled", async () => {
    const api = mockApi({
      "GET studio/tests/t1": { body: def },
      "POST studio/tests/t1/validate": {
        body: { test_id: "t1", feasible: false, has_sections: true, rules: [{ section_id: "s1", rule_id: "r1", rule_type: "random", pool_size: 9, required: 15, ok: false, recommended_ok: false }] },
      },
    });
    restore = api.restore;
    renderWithProviders(<TestBuilder testId="t1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Check question supply" }));
    expect(await screen.findByText("Only 9 published questions match")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Publish" })).toBeDisabled();
  });

  it("uses the test title as the h1, adds section links and labels remove buttons", async () => {
    const api = mockApi({ "GET studio/tests/t1": { body: def } });
    restore = api.restore;
    renderWithProviders(<TestBuilder testId="t1" crumbs={[{ label: "Template mocks", href: "/studio/tests" }]} />);
    expect(await screen.findByRole("heading", { level: 1, name: "DSA Weekly 3" })).toBeInTheDocument();
    expect(screen.getByText("Mock test")).toBeInTheDocument();
    expect(within(screen.getByRole("navigation", { name: "Breadcrumb" })).getByRole("link", { name: "Template mocks" })).toHaveAttribute("href", "/studio/tests");
    const nav = await screen.findByRole("navigation", { name: "Test builder sections" });
    expect(within(nav).getByRole("link", { name: "Sections" })).toHaveAttribute("href", "#test-sections");
    expect(document.getElementById("test-sections")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Remove rule 1 from section 1" })).toBeInTheDocument();
  });

  it("goes read-only when settings are locked", async () => {
    const api = mockApi({
      "GET studio/tests/t1": { body: def },
      "PATCH studio/tests/t1": problem(409, "test_settings_locked", "Locked"),
    });
    restore = api.restore;
    renderWithProviders(<TestBuilder testId="t1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Save" }));
    expect(await screen.findByText(/Settings are read-only/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Title/)).toBeDisabled();
    const patch = api.calls.find((c) => c.method === "PATCH")!.body;
    expect(patch).toMatchObject({ duration_seconds: 3600, attempts_allowed: 1 });
  });
});

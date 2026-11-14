import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { CodingWorkspace } from "./components/CodingWorkspace";
import { ProblemList } from "./components/ProblemList";
import { VerdictPanel } from "./components/VerdictPanel";
import { codingApi, monacoLanguage, parseRetryAfter, pollSubmission, RetryAfterError } from "./lib/api";
import type { Submission } from "./lib/types";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));
// Monaco is lazy-loaded in the browser; component tests use a plain textarea stand-in.
vi.mock("./components/CodeEditor", () => ({
  CodeEditor: ({ value, onChange, ariaLabel }: { value: string; onChange: (v: string) => void; ariaLabel: string }) => (
    <textarea aria-label={ariaLabel} value={value} onChange={(e) => onChange(e.target.value)} />
  ),
}));

let restore: (() => void) | undefined;
afterEach(() => {
  restore?.();
  vi.unstubAllGlobals();
});

describe("Retry-After handling", () => {
  it("parses delta-seconds, HTTP dates and problem members", () => {
    expect(parseRetryAfter("40", null)).toBe(40);
    expect(parseRetryAfter("Tue, 03 Nov 2026 10:00:30 GMT", null, Date.parse("2026-11-03T10:00:00Z"))).toBe(30);
    expect(parseRetryAfter(null, { retry_after: 12 } as never)).toBe(12);
    expect(parseRetryAfter(null, null)).toBe(30);
  });

  it("throws RetryAfterError for 429 with the server's Retry-After, and sends CSRF + Idempotency-Key", async () => {
    const api = mockApi({ "POST coding/problems/p1/submit": { ...problem(429, "rate_limited", "Too many submissions"), headers: { "retry-after": "40" } } });
    restore = api.restore;
    const err = await codingApi.submit("p1", { language_key: "python3", source_code: "print(1)" }, "key-1", api.fetchImpl as unknown as typeof fetch).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(RetryAfterError);
    expect((err as RetryAfterError).retryAfterSeconds).toBe(40);
    expect(api.calls[0]!.headers["idempotency-key"]).toBe("key-1");
    expect(api.calls[0]!.headers["x-csrf-token"]).toBe("test-csrf-token");
  });

  it("polls a submission until it is terminal", async () => {
    const states: Submission[] = [
      { submission_id: "s1", mode: "submit", status: "queued" },
      { submission_id: "s1", mode: "submit", status: "running" },
      { submission_id: "s1", mode: "submit", status: "completed", verdict: "AC" },
    ];
    const seen: string[] = [];
    const final = await pollSubmission("s1", (s) => seen.push(s.status), { get: async () => states.shift()!, sleep: async () => undefined });
    expect(seen).toEqual(["queued", "running", "completed"]);
    expect(final.verdict).toBe("AC");
  });

  it("maps judge language keys to editor languages", () => {
    expect(monacoLanguage("cpp17")).toBe("cpp");
    expect(monacoLanguage("python3")).toBe("python");
    expect(monacoLanguage("java17")).toBe("java");
    expect(monacoLanguage("javascript")).toBe("javascript");
  });
});

describe("VerdictPanel", () => {
  it("shows sample I/O for runs but only a summary and verdicts for hidden cases", () => {
    renderWithProviders(
      <VerdictPanel
        startedAt={null}
        submission={{
          submission_id: "s1",
          mode: "submit",
          status: "completed",
          verdict: "PARTIAL",
          score: 70,
          passed_cases: 7,
          total_cases: 10,
          cases: [
            { ordinal: 1, is_sample: true, verdict: "AC", time_ms: 3, memory_kb: 900, input: "3\n1 2 3\n", expected_output: "6\n", stdout_excerpt: "6\n" },
            { ordinal: 7, is_sample: false, verdict: "WA", time_ms: 120, memory_kb: 900 },
            { ordinal: 9, is_sample: false, verdict: "TLE", time_ms: 2000, memory_kb: null },
          ],
        }}
      />,
    );
    expect(screen.getByText(/7 of 10 tests passed · Score 70\/100/)).toBeInTheDocument();
    expect(screen.getByText(/Case 7:/)).toBeInTheDocument();
    expect(screen.getByText("Time limit exceeded")).toBeInTheDocument();
    expect(screen.getByText("Hidden tests: no input or output is shown.")).toBeInTheDocument();
  });

  it("shows compiler output for CE", () => {
    renderWithProviders(<VerdictPanel startedAt={null} submission={{ submission_id: "s", mode: "run", status: "completed", verdict: "CE", compile_output: "main.cpp:3: error" }} />);
    expect(screen.getByText("main.cpp:3: error")).toBeInTheDocument();
  });
});

describe("CodingWorkspace (COD-002)", () => {
  // Shape of coding/router.py get_problem.
  const problemBody = {
    problem_id: "p1",
    slug: "two-sum",
    title: "Two Sum Variants",
    version_no: 1,
    statement_md: "Given an array of numbers.",
    input_format_md: null,
    output_format_md: null,
    constraints_md: null,
    difficulty: 3,
    limits: { time_limit_ms: 2000, wall_limit_ms: 5000, memory_limit_kb: 262144 },
    allowed_languages: ["python3", "cpp17"],
    scoring_mode: "partial",
    is_free: true,
    samples: [{ ordinal: 1, input: "3\n1 2 3\n", expected_output: "6\n" }],
    languages: [
      { language_key: "python3", display_name: "Python", starter_template: "def solve():\n    pass\n" },
      { language_key: "cpp17", display_name: "C++17", starter_template: null },
    ],
  };

  it("runs on samples, polls the verdict, and shows the rate-limit countdown on 429", async () => {
    let submitCalls = 0;
    const api = mockApi({
      "GET coding/problems/two-sum": { body: problemBody },
      "GET coding/languages": { body: { data: [{ language_key: "python3", display_name: "Python", version: "3.11", starter_template: "" }, { language_key: "cpp17", display_name: "C++17", version: "17", starter_template: "" }] } },
      "POST coding/problems/p1/run": { status: 202, body: { submission_id: "s1", status: "queued", mode: "run", queue: "run", queue_position: 0, problem_version: 1, poll_url: "/api/v1/coding/submissions/s1" } },
      "GET coding/submissions/s1": {
        body: { submission_id: "s1", mode: "run", status: "completed", verdict: "AC", cases: [{ ordinal: 1, is_sample: true, verdict: "AC", input: "3", expected_output: "6", stdout_excerpt: "6" }] },
      },
      "POST coding/problems/p1/submit": () => {
        submitCalls += 1;
        return { ...problem(429, "rate_limited", "Too many submissions"), headers: { "retry-after": "40" } };
      },
    });
    restore = api.restore;
    vi.stubGlobal("fetch", api.fetchImpl);
    renderWithProviders(<CodingWorkspace slug="two-sum" />);

    const editor = await screen.findByLabelText("Code editor, python3", {}, { timeout: 5_000 });
    await waitFor(() => expect(editor).toHaveValue("def solve():\n    pass\n"), { timeout: 5_000 });
    expect(screen.getByRole("combobox", { name: "Language" })).toHaveValue("python3");

    await userEvent.click(screen.getByRole("button", { name: /^Run/ }));
    expect(await screen.findAllByText("Accepted", {}, { timeout: 5_000 })).not.toHaveLength(0);
    const run = api.calls.find((c) => c.path === "coding/problems/p1/run")!;
    expect(run.body).toMatchObject({ language_key: "python3", custom_input: null });

    await userEvent.click(screen.getByRole("button", { name: /^Submit/ }));
    expect(await screen.findByText(/You can submit again in 0:(40|39|38)/, {}, { timeout: 5_000 })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Submit/ })).toBeDisabled();
    expect(submitCalls).toBe(1);
  });
  it("renders the problem statement as Markdown, never as raw markup", async () => {
    const api = mockApi({
      "GET coding/problems/two-sum": {
        body: { ...problemBody, statement_md: "Read `n` integers and **print** their sum.", constraints_md: "1 <= n <= 10\n<img src=x onerror=alert(1)>" },
      },
      "GET coding/languages": { body: { data: [{ language_key: "python3", display_name: "Python" }, { language_key: "cpp17", display_name: "C++17" }] } },
    });
    restore = api.restore;
    vi.stubGlobal("fetch", api.fetchImpl);
    const { container } = renderWithProviders(<CodingWorkspace slug="two-sum" />);
    // The statement is rendered in both the wide and the narrow layout.
    expect(await screen.findAllByText("n", { selector: "code" }, { timeout: 5_000 })).not.toHaveLength(0);
    expect(screen.getAllByText("print", { selector: "strong" })).not.toHaveLength(0);
    expect(container.textContent).not.toContain("`n`");
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<img src=x onerror=alert(1)>");
  }, 15_000);

  it("restores the saved draft (COD-05) and autosaves edits (COD-04)", async () => {
    const api = mockApi({
      "GET coding/problems/two-sum": { body: problemBody },
      "GET coding/languages": { body: { data: [{ language_key: "python3", display_name: "Python" }, { language_key: "cpp17", display_name: "C++17" }] } },
      "GET coding/problems/p1/drafts/python3": { body: { problem_id: "p1", language_key: "python3", source_code: "print(1)", size_bytes: 15, updated_at: "2026-11-03T10:00:00Z" } },
      "PUT coding/problems/p1/drafts/python3": (c) => ({ body: { problem_id: "p1", language_key: "python3", source_code: (c.body as { source_code: string }).source_code, size_bytes: 1, updated_at: "2026-11-03T10:00:05Z" } }),
    });
    restore = api.restore;
    vi.stubGlobal("fetch", api.fetchImpl);
    renderWithProviders(<CodingWorkspace slug="two-sum" />);

    const editor = await screen.findByLabelText("Code editor, python3", {}, { timeout: 5_000 });
    await waitFor(() => expect(editor).toHaveValue("print(1)"), { timeout: 5_000 });
    expect(screen.getByText("Draft saved")).toBeInTheDocument();

    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      fireEvent.change(editor, { target: { value: "print(42)" } });
      expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
      await vi.advanceTimersByTimeAsync(5_100);
    } finally {
      vi.useRealTimers();
    }
    await waitFor(() => expect(api.calls.some((c) => c.method === "PUT" && c.path === "coding/problems/p1/drafts/python3")).toBe(true));
    const put = api.calls.filter((c) => c.method === "PUT").at(-1)!;
    expect(put.body).toEqual({ source_code: "print(42)" });
    expect(await screen.findByText("Draft saved")).toBeInTheDocument();
  });
});

describe("ProblemList empty states (live audit F-9)", () => {
  const empty = { body: { data: [], meta: { next_cursor: null, has_more: false, limit: 25 } } };

  it("says there are no problems yet when nothing is filtered", async () => {
    restore = mockApi({ "GET coding/problems": empty }).restore;
    renderWithProviders(<ProblemList />);
    expect(await screen.findByText("No coding problems yet")).toBeInTheDocument();
    expect(screen.queryByText("No problems match these filters")).not.toBeInTheDocument();
  });

  it("keeps the 'match these filters' wording once a filter is set", async () => {
    restore = mockApi({ "GET coding/problems": empty }).restore;
    renderWithProviders(<ProblemList />);
    await screen.findByText("No coding problems yet");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Difficulty" }), "2");
    expect(await screen.findByText("No problems match these filters")).toBeInTheDocument();
  });
});

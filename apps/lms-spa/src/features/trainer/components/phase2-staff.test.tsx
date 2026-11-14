import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { GradingQueue } from "./Grading";
import { TestPageHeader } from "./TestPageHeader";
import { TestReportPanel, TestReportView } from "./TestOps";
import { TestsList } from "./TestsList";
import { batchDates } from "./TrainerDashboard";

const nav = vi.hoisted(() => ({ path: "/trainer/grading" }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => nav.path,
}));

let restore: (() => void) | undefined;
afterEach(() => {
  restore?.();
  nav.path = "/trainer/grading";
});

const page = { next_cursor: null, has_more: false, limit: 100 };

describe("GradingQueue is a queue, not a picker (Phase 2)", () => {
  const assignments = [
    { id: "a1", assignment_id: "a1", title: "Essay draft", batch_id: "b1", batch_name: "CSE-A", max_points: 10, pending_count: 0, grades_released: true, submission_type: "text", due_at: null },
    { id: "a2", assignment_id: "a2", title: "Arrays worksheet", batch_id: "b1", batch_name: "CSE-A", max_points: 10, pending_count: 3, grades_released: false, submission_type: "structured", structured: true, due_at: null },
  ];

  it("lists every assignment with its waiting count, most work first, without a select", async () => {
    const api = mockApi({ "GET assignments": { body: { data: assignments, page } }, "GET batches/b1/members": { body: { data: [] } } });
    restore = api.restore;
    renderWithProviders(<GradingQueue />);
    const table = await screen.findByRole("table", { name: "Assignments to grade" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("Arrays worksheet");
    expect(rows[0]).toHaveTextContent("3 to grade");
    expect(rows[1]).toHaveTextContent("Essay draft");
    expect(screen.queryByLabelText("Assignment")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Evaluate Arrays worksheet" })).toHaveAttribute("href", "/trainer/grading/assignments/a2");
    // Two assignments: nothing is opened until one is chosen.
    expect(screen.queryByRole("table", { name: /Submissions for/ })).not.toBeInTheDocument();
  });

  it("opens a single-submission assignment's submissions below the table", async () => {
    const api = mockApi({
      "GET assignments": { body: { data: assignments, page } },
      "GET batches/b1/members": { body: { data: [] } },
      "GET assignments/a1/submissions": { body: { data: [], page } },
    });
    restore = api.restore;
    renderWithProviders(<GradingQueue />);
    await userEvent.click(await screen.findByRole("button", { name: "Show submissions for Essay draft" }));
    expect(await screen.findByRole("heading", { name: "Submissions · Essay draft" })).toBeInTheDocument();
    expect(await screen.findByText("No submissions for this assignment yet.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Grades released" })).toBeDisabled();
  });

  it("keeps evaluator links inside the evaluator portal", async () => {
    nav.path = "/evaluator";
    const api = mockApi({ "GET assignments": { body: { data: assignments, page } }, "GET batches/b1/members": { body: { data: [] } } });
    restore = api.restore;
    renderWithProviders(<GradingQueue />);
    expect(await screen.findByRole("link", { name: "Evaluate Arrays worksheet" })).toHaveAttribute("href", "/evaluator/grading/assignments/a2");
  });
});

describe("TestReportPanel with no graded attempts", () => {
  it("shows one empty state instead of zero charts and tiles", async () => {
    const api = mockApi({
      "GET tests/t1/report": {
        body: {
          test_id: "t1",
          title: "DSA Weekly 3",
          scope: "full",
          k_min: 10,
          attempts_count: 0,
          distribution: { buckets: [{ label: "0-10", from: 0, to: 10, count: 0 }], mean: null, median: null },
          submissions: { submitted: 0, auto_submitted: 0, admin_force: 0, total: 0 },
          sections: [],
          items: { suppressed: false, data: [] },
        },
      },
    });
    restore = api.restore;
    renderWithProviders(<TestReportPanel testId="t1" />);
    expect(await screen.findByText("No graded attempts yet")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Attempts per score band" })).not.toBeInTheDocument();
    expect(screen.queryByText("Auto-submitted")).not.toBeInTheDocument();
  });
});

describe("Release results asks first", () => {
  it("confirms before POSTing the release", async () => {
    const api = mockApi({
      "GET tests/t1/report": { body: { test_id: "t1", title: "T", scope: "full", k_min: 10, attempts_count: 0, distribution: null, submissions: null, sections: null, items: { suppressed: false, data: [] } } },
      "GET tests/t1/assignments": {
        body: { items: [{ id: "ta1", test_id: "t1", organization_id: "o1", batch_id: null, available_from: "2026-11-01T09:00:00.000Z", available_until: "2026-11-30T09:00:00.000Z", attempts_allowed: 1, release_mode: "manual", results_release_at: null }] },
      },
      "GET me/grants": { body: { data: [] } },
      "POST tests/t1/results/release": { body: { results_released: 4 } },
    });
    restore = api.restore;
    renderWithProviders(<TestReportView testId="t1" />);
    await userEvent.click(await screen.findByRole("button", { name: /Release results for/ }));
    const dialog = await screen.findByRole("dialog", { name: "Release results?" });
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.click(within(dialog).getByRole("button", { name: "Release results" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.path === "tests/t1/results/release")).toBe(true));
  });
});

describe("TestsList row actions", () => {
  const tests = { items: [{ id: "t1", title: "Arrays mock", test_kind: "mock", duration_seconds: 3600, status: "published" }] };

  it("humanises the kind and keeps two visible actions plus a More menu (trainer)", async () => {
    const api = mockApi({ "GET studio/tests": { body: tests } });
    restore = api.restore;
    renderWithProviders(<TestsList batches={[{ value: "b1", label: "CSE" }]} basePath="/trainer" />);
    expect(await screen.findByText("Mock test")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Assign Arrays mock" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Evaluate Arrays mock" })).toHaveAttribute("href", "/trainer/tests/t1/evaluation");
    await userEvent.click(screen.getByText("More", { exact: false, selector: "summary" }));
    expect(screen.getByRole("link", { name: "Attempts" })).toHaveAttribute("href", "/trainer/tests/t1/attempts");
    expect(screen.getByRole("link", { name: "Overrides" })).toHaveAttribute("href", "/trainer/tests/t1/overrides");
  });

  it("puts New test in the given header", async () => {
    const api = mockApi({ "GET studio/tests": { body: tests } });
    restore = api.restore;
    renderWithProviders(
      <TestsList batches={[{ value: "b1", label: "CSE" }]} basePath="/trainer" header={(create) => <header data-testid="hdr">{create}</header>} />,
    );
    expect(await within(await screen.findByTestId("hdr")).findByRole("button", { name: "New test" })).toBeInTheDocument();
  });
});

describe("TestPageHeader", () => {
  it("uses the test name as the h1 with breadcrumbs back to Tests", async () => {
    nav.path = "/evaluator/tests/t1/report";
    const api = mockApi({ "GET studio/tests/t1": { body: { id: "t1", title: "DSA Weekly 3", status: "published" } } });
    restore = api.restore;
    renderWithProviders(<TestPageHeader testId="t1" page="report" />);
    expect(await screen.findByRole("heading", { level: 1, name: "DSA Weekly 3" })).toBeInTheDocument();
    const trail = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(trail).getByRole("link", { name: "Tests" })).toHaveAttribute("href", "/evaluator/tests");
    expect(within(trail).getByText("Test report")).toHaveAttribute("aria-current", "page");
  });

  it("falls back to the page name when the test can't be read", async () => {
    const api = mockApi({});
    restore = api.restore;
    renderWithProviders(<TestPageHeader testId="t1" page="evaluation" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Evaluation" })).toBeInTheDocument();
  });
});

describe("batchDates", () => {
  it("never prints an empty range", () => {
    expect(batchDates({ starts_on: null, ends_on: null })).toBe("No dates set");
    expect(batchDates({ starts_on: "2026-11-01", ends_on: null })).toMatch(/^From /);
    expect(batchDates({ starts_on: null, ends_on: "2027-04-30" })).toMatch(/^Until /);
  });
});

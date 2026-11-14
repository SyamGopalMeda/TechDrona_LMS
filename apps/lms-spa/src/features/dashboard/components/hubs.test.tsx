import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { GetStarted, InterviewPrep, LearningPath, subjectOf } from "./LearnerHubs";
import { StudentDashboard, dueSoonItems } from "./StudentDashboard";

vi.mock("next/navigation", () => ({ usePathname: () => "/app", useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));
vi.mock("@/lib/analytics/use-activity-tracker", () => ({ useActivityTracker: () => undefined }));

let restore: (() => void) | undefined;
afterEach(() => restore?.());

const t = (id: string, kind: string, status: string) => ({
  test_id: id,
  title: `Test ${id}`,
  test_kind: kind,
  duration_seconds: 1800,
  test_assignment_id: null,
  available_from: null,
  available_until: null,
  attempts_used: 0,
  attempts_left: 1,
  status,
  in_progress_attempt_id: null,
});
const tests = { items: [t("a", "diagnostic", "available"), t("b", "mock", "scheduled"), t("c", "mock", "closed")], server_now: "2026-11-03T00:00:00Z" };
const node = (id: string, parent: string | null, slug: string, name: string, children: unknown[] = []) => ({
  id,
  parent_id: parent,
  kind: parent ? "topic" : "subject",
  slug,
  name,
  path: slug,
  depth: parent ? 1 : 0,
  position: 0,
  is_active: true,
  question_count: 10,
  children,
});
const emptyDash = { continue_learning: [], assigned_work: [], tests: [], expiring: [], certificates: [], banners: [] };

describe("Learner hubs (FE-05)", () => {
  it("interview prep links only to the résumé builder (mentoring and company paths were removed)", async () => {
    restore = mockApi({ "GET me/tests": { body: tests } }).restore;
    renderWithProviders(<InterviewPrep />);
    expect(screen.getByRole("link", { name: /Résumé/ })).toHaveAttribute("href", "/app/resume");
    expect(screen.queryByText("Mock interviews")).not.toBeInTheDocument();
    expect(screen.queryByText("Company paths")).not.toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Test b" })).toHaveAttribute("href", "/app/tests/b");
    expect(screen.queryByText("Test a")).not.toBeInTheDocument();
  });

  it("learning path links a topic recommendation to its subject", async () => {
    const tree = [node("s1", null, "aptitude", "Aptitude", [node("t1", "s1", "percentages", "Percentages")])];
    expect(subjectOf("t1", tree as never)?.slug).toBe("aptitude");
    restore = mockApi({
      "GET me/dashboard": { body: emptyDash },
      "GET me/recommendations": {
        body: { personalised: true, items: [{ id: "r1", rule_key: "weak", why_recommended: "Accuracy below 50%", evidence: {}, target_type: "topic", target_id: "t1", priority: 1, generated_at: "", expires_at: "" }] },
      },
      "GET placement/subjects": { body: { items: tree } },
    }).restore;
    renderWithProviders(<LearningPath />);
    expect(await screen.findByText("Percentages")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Practise" })).toHaveAttribute("href", "/app/practice/aptitude");
  });
});

describe("StudentDashboard upcoming tests (FE-23)", () => {
  it("shows upcoming tests instead of the old 'not shown here yet' note", async () => {
    restore = mockApi({ "GET me/dashboard": { body: emptyDash }, "GET me/tests": { body: tests } }).restore;
    renderWithProviders(<StudentDashboard />);
    expect(await screen.findByRole("link", { name: "Test b" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Test a" })).toBeInTheDocument();
    expect(screen.queryByText("Test c")).not.toBeInTheDocument();
    expect(screen.queryByText(/not shown here yet/)).not.toBeInTheDocument();
  });
});

describe("Dashboard layout (UI audit: description, stat tiles, Due soon)", () => {
  const work = (id: string, due: string | null, my_status = "not_submitted") => ({ id, title: `Work ${id}`, due_at: due, my_status, my_score: null }) as never;

  it("merges open assignments and tests, in-progress first then soonest", () => {
    const testsIn = [
      { ...t("x", "mock", "in_progress"), available_until: "2026-12-30T00:00:00Z" },
      { ...t("y", "mock", "available"), available_until: "2026-11-20T00:00:00Z" },
      t("z", "mock", "closed"),
    ];
    const items = dueSoonItems([work("a1", "2026-11-15T00:00:00Z"), work("a2", null), work("a3", "2026-11-10T00:00:00Z", "graded")], testsIn as never);
    expect(items.map((i) => i.key)).toEqual(["t-x", "a-a1", "t-y", "a-a2"]);
    expect(items[1]).toMatchObject({ kind: "Assignment", statusLabel: "To do", href: "/app/assignments/a1" });
  });

  it("shows a description, linked stat tiles and one Due soon list", async () => {
    restore = mockApi({ "GET me/dashboard": { body: { ...emptyDash, assigned_work: [work("a1", "2026-11-15T00:00:00Z")] } }, "GET me/tests": { body: tests } }).restore;
    renderWithProviders(<StudentDashboard />);
    expect(await screen.findByText("Pick up where you left off and see what's due next.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Assignments to do/ })).toHaveAttribute("href", "/app/assignments");
    const due = await screen.findByRole("list", { name: "Due soon" });
    expect(within(due).getByRole("link", { name: "Work a1" })).toBeInTheDocument();
    expect(await within(due).findByRole("link", { name: "Test a" })).toBeInTheDocument();
  });

  it("quick actions skip removed pages; the access card links to My access until payments are connected", async () => {
    restore = mockApi({ "GET me/dashboard": { body: emptyDash }, "GET me/tests": { body: tests } }).restore;
    renderWithProviders(<StudentDashboard />);
    expect(await screen.findByRole("link", { name: /Diagnostic and mock tests/ })).toHaveAttribute("href", "/app/tests");
    for (const gone of ["/app/diagnostic", "/app/mentoring", "/app/billing"]) expect(document.querySelector(`a[href="${gone}"]`), gone).toBeNull();
    expect(screen.getByRole("link", { name: "My access" })).toHaveAttribute("href", "/app/access");
  });
});

describe("Get started (STU-002)", () => {
  it("offers a mock test when no diagnostic is open instead of a dead-end page", async () => {
    restore = mockApi({ "GET me/tests": { body: { items: [t("m", "mock", "available")], server_now: "" } }, "GET placement/subjects": { body: { items: [] } } }).restore;
    renderWithProviders(<GetStarted />);
    expect(await screen.findByRole("link", { name: "Take a mock test" })).toHaveAttribute("href", "/app/tests");
    expect(screen.queryByRole("link", { name: "Take the free diagnostic" })).not.toBeInTheDocument();
  });

  it("links straight to an open diagnostic test", async () => {
    restore = mockApi({ "GET me/tests": { body: tests }, "GET placement/subjects": { body: { items: [] } } }).restore;
    renderWithProviders(<GetStarted />);
    expect(await screen.findByRole("link", { name: "Take the free diagnostic" })).toHaveAttribute("href", "/app/tests/a");
  });
});

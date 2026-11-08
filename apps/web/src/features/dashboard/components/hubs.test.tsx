import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { DiagnosticLauncher, LearningPath, subjectOf } from "./LearnerHubs";
import { StudentDashboard } from "./StudentDashboard";

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
  it("diagnostic launcher lists only diagnostic tests from me/tests", async () => {
    restore = mockApi({ "GET me/tests": { body: tests } }).restore;
    renderWithProviders(<DiagnosticLauncher />);
    expect(await screen.findByRole("link", { name: "Test a" })).toHaveAttribute("href", "/app/tests/a");
    expect(screen.queryByText("Test b")).not.toBeInTheDocument();
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

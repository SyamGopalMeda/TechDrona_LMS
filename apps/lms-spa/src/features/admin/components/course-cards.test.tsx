import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { AdminCoursesSection, CourseCards, courseGroup, topCourses, type CoursesOverview, type OverviewBatch, type OverviewCourse } from "./CourseCards";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

const cleanups: (() => void)[] = [];
afterEach(() => {
  while (cleanups.length) cleanups.pop()!();
});

const TODAY = "2026-11-11";
const batch = (over: Partial<OverviewBatch> = {}): OverviewBatch => ({ batch_id: "b1", name: "CSE 2027", code: "B1", status: "active", starts_on: "2026-11-01", ends_on: "2027-01-31", enrolled: 3, ...over });
const course = (over: Partial<OverviewCourse> = {}): OverviewCourse => ({
  course_id: "c1",
  title: "Data Structures",
  slug: "dsa",
  status: "published",
  visibility: "public",
  course_kind: "cohort",
  is_free: false,
  published_at: "2026-10-01T10:00:00Z",
  updated_at: null,
  enrolled: 0,
  completed: 0,
  certificates_issued: 0,
  certificates_ready: 0,
  batch_count: 0,
  batches: [],
  ...over,
});

const running = course({ course_id: "run", title: "Running Course", enrolled: 42, completed: 7, certificates_issued: 5, certificates_ready: 2, batch_count: 1, batches: [batch()] });
const selfPaced = course({ course_id: "self", title: "Self Paced", enrolled: 3 });
const soon = course({ course_id: "soon", title: "Soon Course", batch_count: 1, batches: [batch({ batch_id: "b2", name: "Jan batch", status: "planned", starts_on: "2026-12-01", ends_on: "2027-02-01", enrolled: 4 })] });
const draft = course({ course_id: "draft", title: "Draft Course", status: "draft", published_at: null });
const done = course({ course_id: "done", title: "Done Course", completed: 9, batch_count: 1, batches: [batch({ batch_id: "b3", status: "completed", starts_on: "2026-05-01", ends_on: "2026-08-01", enrolled: 0 })] });
const archived = course({ course_id: "arch", title: "Archived Course", status: "archived" });

describe("courseGroup", () => {
  it("puts each course in Running / Coming soon / Draft / Completed", () => {
    expect(courseGroup(running, TODAY)).toBe("running");
    expect(courseGroup(selfPaced, TODAY)).toBe("running"); // published, no batch = open
    expect(courseGroup(soon, TODAY)).toBe("upcoming");
    expect(courseGroup(draft, TODAY)).toBe("draft");
    expect(courseGroup(done, TODAY)).toBe("completed");
    expect(courseGroup(archived, TODAY)).toBe("completed");
    // batches ended but learners still active: still running
    expect(courseGroup({ ...done, enrolled: 2 }, TODAY)).toBe("running");
  });

  it("orders the dashboard strip running first, then by enrolments, capped", () => {
    const top = topCourses([draft, soon, selfPaced, done, running, archived], 3, TODAY);
    expect(top.map((c) => c.course_id)).toEqual(["run", "self", "soon"]);
  });
});

describe("CourseCards (ADM-016)", () => {
  it("renders the groups in order with counts, the number strip and the actions", () => {
    renderWithProviders(<CourseCards courses={[draft, done, soon, running, selfPaced, archived]} today={TODAY} />);
    const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(headings).toEqual(["Running2", "Coming soon1", "Draft1", "Completed2"]);

    const runningSection = screen.getByRole("heading", { level: 2, name: /^Running/ }).closest("section")!;
    expect(within(runningSection).getAllByRole("article").map((a) => a.getAttribute("aria-label"))).toEqual(["Running Course", "Self Paced"]);

    const card = screen.getByRole("article", { name: "Running Course" });
    const strip = within(card).getByRole("list");
    expect(within(strip).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["42Enrolled", "7Completed", "1Batch", "5Certificates issued"]);
    expect(within(card).getByText("2 learners ready for a certificate")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: /Open course/ })).toHaveAttribute("href", "/studio/courses/run");
    expect(within(card).getByRole("link", { name: /Batches/ })).toHaveAttribute("href", "/admin/batches");
    expect(within(card).getByRole("link", { name: /Certificates/ })).toHaveAttribute("href", "/admin/certificates?course=run");

    expect(within(screen.getByRole("article", { name: "Self Paced" })).queryByText(/ready for a certificate/)).not.toBeInTheDocument();
    expect(within(screen.getByRole("article", { name: "Soon Course" })).getByText(/Jan batch starts .* 4 learners enrolled/)).toBeInTheDocument();
    expect(within(screen.getByRole("article", { name: "Draft Course" })).getByText("Not published")).toBeInTheDocument();
  });

  it("shows an empty state with no courses", () => {
    renderWithProviders(<CourseCards courses={[]} today={TODAY} />);
    expect(screen.getByText("No courses yet")).toBeInTheDocument();
  });
});

describe("AdminCoursesSection (dashboard)", () => {
  const overview: CoursesOverview = {
    generated_at: "2026-11-11T10:00:00Z",
    totals: { courses: 2, courses_published: 1, courses_draft: 1, learners: 1234, enrolled: 42, completed: 7 },
    certificates: { issued_valid: 5, revoked: 1, issued_30d: 3, ready: 2 },
    courses: [running, draft],
  };

  it("shows the four KPI cards and the course strip", async () => {
    const api = mockApi({ "GET admin/courses/overview": { body: overview } });
    cleanups.push(api.restore);
    renderWithProviders(<AdminCoursesSection />);
    expect(await screen.findByRole("link", { name: /1,234.*Learners/ })).toHaveAttribute("href", "/admin/users?status=active");
    expect(screen.getByRole("link", { name: /42.*Active enrolments/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /5.*Certificates issued.*3 in the last 30 days/ })).toHaveAttribute("href", "/admin/certificates");
    expect(screen.getByRole("link", { name: /2.*Ready for certificate/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /All courses/ })).toHaveAttribute("href", "/admin/courses");
    expect(screen.getAllByRole("article").map((a) => a.getAttribute("aria-label"))).toEqual(["Running Course", "Draft Course"]);
  });

  it("renders nothing when the api has no overview (older api)", async () => {
    const api = mockApi({});
    cleanups.push(api.restore);
    renderWithProviders(<AdminCoursesSection />);
    await vi.waitFor(() => expect(api.calls.some((c) => c.path === "admin/courses/overview")).toBe(true));
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText("Learners")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /All courses/ })).not.toBeInTheDocument();
  });
});

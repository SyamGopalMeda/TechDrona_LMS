import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { useActivityTracker } from "@/lib/analytics/use-activity-tracker";
import { StudentDashboard } from "@/features/dashboard/components/StudentDashboard";
import { AssignmentsList } from "./Assignments";
import { Certificates } from "./Certificates";
import { CourseOverview } from "./CourseOverview";
import { LessonView } from "./LessonView";
import { MyCourses } from "./MyCourses";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));
vi.mock("@/lib/analytics/use-activity-tracker", () => {
  const noop = () => undefined;
  const handle = {
    video: { play: noop, pause: noop, seek: noop, rateChange: noop, ended: noop, bufferingStart: noop, bufferingEnd: noop, error: noop, timeUpdate: noop },
    event: noop,
    editor: { focus: noop, blur: noop, edit: noop },
    scrollDepth: vi.fn(),
  };
  return { getTabId: () => "tab-1", useActivityTracker: vi.fn(() => handle) };
});

let restore: (() => void) | undefined;
beforeEach(() => vi.mocked(useActivityTracker).mockClear());
afterEach(() => restore?.());

// Fixtures follow the verified backend shapes (learning/router.py, catalog/service.py).
const page = { next_cursor: null, has_more: false, limit: 100 };
const catalogCourse = { id: "c1", slug: "dsa", title: "DSA Foundations", price_type: "free" };
const enrolment = {
  id: "e1",
  course_id: "c1",
  course_slug: "dsa",
  course_title: "DSA Foundations",
  course_version_id: "v1",
  organization_id: null,
  batch_id: null,
  source: "self",
  status: "active",
  progress_pct: 25,
  enrolled_at: "2026-10-01T10:00:00.000Z",
  completed_at: null,
  expires_at: "2027-05-02T10:15:00.000Z",
  last_activity_at: null,
};
const lessonRef = (id: string, title: string, lesson_type: string, status: string) => ({ id, lesson_key: `k${id.slice(1)}`, title, lesson_type, position: Number(id.slice(1)), is_required: true, is_free_preview: false, duration_seconds: null, est_reading_minutes: 5, status, progress_pct: 0, video_position_s: null });
const overview = {
  enrolment,
  title: "DSA Foundations",
  modules: [
    {
      id: "m1",
      module_key: "mk1",
      title: "Arrays",
      lessons: [lessonRef("l1", "Sliding window", "article", "completed"), lessonRef("l2", "Two pointers", "article", "not_started"), lessonRef("l3", "Practice quiz", "quiz", "not_started")],
    },
  ],
  next_lesson: { lesson_id: "l2", title: "Two pointers" },
  certificate: { status: "not_eligible", reason: "Finish all lessons and pass the final quiz." },
  version_migration: null,
};
const article = {
  ...lessonRef("l2", "Two pointers", "article", "not_started"),
  course_module_id: "m1",
  article_body: { type: "doc", content: [{ type: "paragraph", text: "Use two indices moving towards each other." }] },
  test_id: null,
  coding_problem_id: null,
  assignment_id: null,
  live_url: null,
  assets: [],
  playback: null,
  resources: [{ id: "r1", title: "Cheat sheet", resource_type: "pdf", access_level: "entitled" }],
  progress: { status: "not_started", progress_pct: 0, video_position_s: null, watched_seconds: 0 },
  access: { reason: "free" },
};
const assignment = {
  id: "a1",
  title: "Assignment 3",
  instructions_md: "Solve it.",
  submission_type: "file",
  max_score: 10,
  rubric: null,
  allowed_file_types: ["pdf"],
  course_id: "c1",
  batch_id: null,
  available_from: null,
  due_at: "2026-11-09T12:30:00.000Z",
  late_until: null,
  late_penalty_pct: 0,
  max_attempts: 1,
  status: "active",
  grades_released: false,
  window: "on_time",
};

describe("MyCourses (STU-004)", () => {
  it("lists enrolments with server progress and an overview link", async () => {
    const api = mockApi({ "GET me/enrolments": { body: { data: [{ ...enrolment, progress_pct: 62 }], page } } });
    restore = api.restore;
    renderWithProviders(<MyCourses />);
    expect(await screen.findByText("DSA Foundations")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Progress in DSA Foundations" })).toHaveAttribute("aria-valuenow", "62");
    expect(screen.getByRole("link", { name: "Open DSA Foundations overview" })).toHaveAttribute("href", "/app/courses/dsa");
    expect(screen.getByText(/Access until 2 May 2027/)).toBeInTheDocument();
  });

  it("shows the empty state with a next action", async () => {
    const api = mockApi({ "GET me/enrolments": { body: { data: [], page } } });
    restore = api.restore;
    renderWithProviders(<MyCourses />);
    expect(await screen.findByText(/haven.t enrolled in a course yet/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Browse free courses" })).toHaveAttribute("href", "/courses?price_type=free");
  });
});

describe("CourseOverview (STU-005)", () => {
  it("resolves the slug, shows contents with status and resumes at the next lesson", async () => {
    const api = mockApi({ "GET catalog/courses/dsa": { body: catalogCourse }, "GET me/courses/c1": { body: overview } });
    restore = api.restore;
    renderWithProviders(<CourseOverview slug="dsa" />);
    expect(await screen.findByRole("heading", { name: "DSA Foundations" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Resume" })).toHaveAttribute("href", "/app/learn/dsa/l2");
    expect(screen.getByLabelText("Completed")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Practice quiz" })).toHaveAttribute("href", "/app/learn/dsa/l3");
    expect(screen.getByText("Finish all lessons and pass the final quiz.")).toBeInTheDocument();
  });

  it("shows the restricted card when learning access is paused", async () => {
    const api = mockApi({ "GET catalog/courses/dsa": { body: catalogCourse }, "GET me/courses/c1": problem(403, "account_restricted", "Account access paused", { case_ref: "SEC-2611-7KQ4MZ", level: 3, until: "2026-11-04T04:45:00.000Z" }) });
    restore = api.restore;
    renderWithProviders(<CourseOverview slug="dsa" />);
    expect(await screen.findByText("Learning access paused")).toBeInTheDocument();
    expect(screen.getByText(/paused until 4 Nov 2026, 10:15 IST/)).toBeInTheDocument();
    expect(screen.getByText(/SEC-2611-7KQ4MZ/)).toBeInTheDocument();
  });
});

describe("LessonView (PLY-002)", () => {
  it("renders an article, wires the activity tracker and records completion evidence", async () => {
    let completed = false;
    const api = mockApi({
      "GET catalog/courses/dsa": { body: catalogCourse },
      "GET me/courses/c1": { body: overview },
      "GET me/courses/c1/lessons/l2": () => ({ body: { ...article, progress: { ...article.progress, status: completed ? "completed" : "not_started" } } }),
      "POST me/lessons/k2/completion": () => {
        completed = true;
        return { status: 200, body: { lesson_key: "k2", status: "completed" } };
      },
    });
    restore = api.restore;
    renderWithProviders(<LessonView slug="dsa" lessonId="l2" />);
    expect(await screen.findByText("Use two indices moving towards each other.")).toBeInTheDocument();
    expect(await screen.findByText("Lesson 2 of 3")).toBeInTheDocument();
    expect(vi.mocked(useActivityTracker)).toHaveBeenLastCalledWith(
      expect.objectContaining({ route: "/app/learn/[course_slug]/[lesson_id]", surface: "lesson_text", enabled: true, entity: expect.objectContaining({ course_id: "c1", lesson_id: "l2" }) }),
    );
    const nav = screen.getAllByRole("navigation", { name: "Course contents" })[0]!;
    expect(within(nav).getByRole("link", { name: /Two pointers/ })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "← Previous" })).toHaveAttribute("href", "/app/learn/dsa/l1");

    await userEvent.click(screen.getByRole("button", { name: "Mark as complete" }));
    expect(await screen.findByText("Completed")).toBeInTheDocument();
    const post = api.calls.find((c) => c.method === "POST" && c.path === "me/lessons/k2/completion")!;
    expect(post.body).toEqual({ evidence: { scrolled_to_end: true } });
    expect(post.headers["idempotency-key"]).toBeTruthy();
  });

  it("uses the video surface for video lessons and shows server progress only", async () => {
    Object.defineProperty(navigator, "requestMediaKeySystemAccess", { value: vi.fn(), configurable: true });
    const api = mockApi({
      "GET catalog/courses/dsa": { body: catalogCourse },
      "GET me/courses/c1": { body: overview },
      "GET me/courses/c1/lessons/l2": {
        body: { ...article, lesson_type: "video", article_body: null, assets: [{ id: "a1", asset_type: "video", provider: "vdocipher", status: "ready" }], progress: { status: "in_progress", progress_pct: 40, video_position_s: 10, watched_seconds: 100 } },
      },
      "POST media/playback-tokens": { status: 201, body: { playback_session_id: "ps", provider: "vdocipher", otp: "o", playback_info: "i" } },
    });
    restore = api.restore;
    renderWithProviders(<LessonView slug="dsa" lessonId="l2" />);
    expect(await screen.findByText(/Watched 40% so far/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Mark as complete" })).not.toBeInTheDocument();
    expect(vi.mocked(useActivityTracker)).toHaveBeenLastCalledWith(expect.objectContaining({ surface: "lesson_video", entity: expect.objectContaining({ lesson_asset_id: "a1" }) }));
  });

  it("shows the paywall for a lesson outside the learner's plan", async () => {
    const api = mockApi({
      "GET catalog/courses/dsa": { body: catalogCourse },
      "GET me/courses/c1": { body: overview },
      "GET me/courses/c1/lessons/l2": problem(403, "entitlement_required", "Get access", { detail: "This lesson is part of All-access.", purchase_options: [] }),
    });
    restore = api.restore;
    renderWithProviders(<LessonView slug="dsa" lessonId="l2" />);
    expect(await screen.findByText("This content needs access")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See all plans" })).toHaveAttribute("href", "/pricing");
  });
});

describe("Assignments (STU-007)", () => {
  it("lists due assignments with status (client-side filter over LRN-08)", async () => {
    const api = mockApi({
      "GET me/assignments": {
        body: { data: [{ ...assignment, my_status: "not_submitted", my_score: null }, { ...assignment, id: "a2", title: "Assignment 2", my_status: "submitted", my_score: null }], page },
      },
    });
    restore = api.restore;
    renderWithProviders(<AssignmentsList />);
    expect(await screen.findByRole("link", { name: "Assignment 3" })).toHaveAttribute("href", "/app/assignments/a1");
    expect(screen.queryByRole("link", { name: "Assignment 2" })).not.toBeInTheDocument();
    expect(screen.getByText("9 Nov 2026, 18:00 IST")).toBeInTheDocument();
  });
});

describe("Certificates (STU-012)", () => {
  it("lists certificates with verification links and downloads a signed PDF", async () => {
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    const cert = { id: "cert1", public_code: "K7Q2M9XH4TPA", course_id: "c1", course_title: "DSA Foundations", name_on_certificate: "Ananya", issued_at: "2026-10-28T10:00:00.000Z", status: "valid", revoked_at: null, verify_url: "/verify/K7Q2M9XH4TPA", pdf_available: true };
    const api = mockApi({
      "GET me/certificates": { body: { data: [cert], page } },
      "GET me/certificates/cert1/pdf": { body: { url: "https://files.example/cert.pdf", expires_at: "2026-11-03T10:05:00.000Z" } },
    });
    restore = api.restore;
    renderWithProviders(<Certificates />);
    expect(await screen.findByRole("link", { name: "K7Q2M9XH4TPA" })).toHaveAttribute("href", "/verify/K7Q2M9XH4TPA");
    await userEvent.click(screen.getByRole("button", { name: "Download certificate for DSA Foundations" }));
    await waitFor(() => expect(open).toHaveBeenCalledWith("https://files.example/cert.pdf", "_blank", "noopener,noreferrer"));
    open.mockRestore();
  });
});

describe("StudentDashboard (STU-001)", () => {
  it("shows continue learning and upcoming work from LRN-01", async () => {
    const api = mockApi({
      "GET me/dashboard": {
        body: {
          continue_learning: [{ ...enrolment, progress_pct: 62 }],
          assigned_work: [{ ...assignment, my_status: "not_submitted", my_score: null }],
          tests: [],
          expiring: [{ ...enrolment, expires_at: "2026-11-12T18:29:59.000Z" }],
          certificates: [],
          banners: [],
        },
      },
    });
    restore = api.restore;
    renderWithProviders(<StudentDashboard />);
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Resume DSA Foundations" })).toHaveAttribute("href", "/app/courses/dsa");
    expect(screen.getByRole("link", { name: "Assignment 3" })).toHaveAttribute("href", "/app/assignments/a1");
    expect(screen.getByText(/DSA Foundations access ends 12 Nov 2026/)).toBeInTheDocument();
  });

  it("shows the error state with the request id", async () => {
    const api = mockApi({ "GET me/dashboard": problem(503, "service_unavailable", "Service temporarily unavailable") });
    restore = api.restore;
    renderWithProviders(<StudentDashboard />);
    expect((await screen.findAllByText("Service temporarily unavailable"))[0]).toBeInTheDocument();
    expect(screen.getByText("req-123")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

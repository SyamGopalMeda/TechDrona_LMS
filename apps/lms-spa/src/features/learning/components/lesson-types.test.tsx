import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
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
afterEach(() => restore?.());

// w2b R4: lesson types `pdf` and `practice_set` (catalog_0002, verified: catalog/schemas.py LessonType).
const catalogCourse = { id: "c1", slug: "dsa", title: "DSA Foundations", price_type: "free" };
const ref = (id: string, lesson_type: string) => ({ id, lesson_key: `k${id}`, title: `Lesson ${id}`, lesson_type, status: "not_started", progress_pct: 0 });
const overview = {
  enrolment: { id: "e1", course_id: "c1", status: "active" },
  title: "DSA Foundations",
  modules: [{ id: "m1", module_key: "mk1", title: "Arrays", lessons: [ref("p", "pdf"), ref("s", "practice_set")] }],
  next_lesson: null,
  certificate: { status: "not_eligible" },
  version_migration: null,
};
const base = {
  course_module_id: "m1",
  article_body: null,
  test_id: null,
  coding_problem_id: null,
  assignment_id: null,
  live_url: null,
  assets: [],
  playback: null,
  resources: [],
  progress: { status: "not_started", progress_pct: 0, video_position_s: null, watched_seconds: 0 },
  access: { reason: "free" },
};

describe("LessonView lesson types", () => {
  it("opens a PDF lesson through MED-07 with lesson_asset_id and then allows completion", async () => {
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    const api = mockApi({
      "GET catalog/courses/dsa": { body: catalogCourse },
      "GET me/courses/c1": { body: overview },
      "GET me/courses/c1/lessons/p": { body: { ...ref("p", "pdf"), ...base, assets: [{ id: "as1", asset_type: "pdf", provider: "s3", status: "ready" }] } },
      "POST media/downloads": { body: { url: "https://content.example/f.pdf", expires_at: null } },
    });
    restore = api.restore;
    renderWithProviders(<LessonView slug="dsa" lessonId="p" />);
    const complete = await screen.findByRole("button", { name: "Mark as complete" });
    expect(complete).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Open PDF" }));
    expect(api.calls.find((c) => c.method === "POST" && c.path === "media/downloads")!.body).toEqual({ lesson_asset_id: "as1" });
    expect(open).toHaveBeenCalledWith("https://content.example/f.pdf", "_blank", "noopener,noreferrer");
    expect(screen.getByRole("button", { name: "Mark as complete" })).toBeEnabled();
    open.mockRestore();
  });

  it("launches the linked test for a practice_set lesson", async () => {
    const api = mockApi({
      "GET catalog/courses/dsa": { body: catalogCourse },
      "GET me/courses/c1": { body: overview },
      "GET me/courses/c1/lessons/s": { body: { ...ref("s", "practice_set"), ...base, test_id: "t9" } },
    });
    restore = api.restore;
    renderWithProviders(<LessonView slug="dsa" lessonId="s" />);
    expect(await screen.findByRole("link", { name: /Open practice set/i })).toHaveAttribute("href", "/app/tests/t9");
    expect(screen.getByText("This lesson completes when you submit the practice set.")).toBeInTheDocument();
  });
});

describe("MyCourses pagination (learn R5: LRN-02 paginates)", () => {
  it("follows page.next_cursor until the last page", async () => {
    const row = (id: string, title: string) => ({ id, course_id: id, course_slug: id, course_title: title, status: "active", progress_pct: 0, expires_at: null, last_activity_at: null });
    const api = mockApi({
      "GET me/enrolments": (call) =>
        call.url.includes("cursor=c2")
          ? { body: { data: [row("e2", "Second course")], page: { next_cursor: null, has_more: false, limit: 100 } } }
          : { body: { data: [row("e1", "First course")], page: { next_cursor: "c2", has_more: true, limit: 100 } } },
    });
    restore = api.restore;
    renderWithProviders(<MyCourses />);
    expect(await screen.findByText("Second course")).toBeInTheDocument();
    expect(screen.getByText("First course")).toBeInTheDocument();
    expect(api.calls.filter((c) => c.path === "me/enrolments")).toHaveLength(2);
  });
});

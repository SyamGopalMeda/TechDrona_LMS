import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import type { Allocation, ArticleDetail, PathDetail, Step } from "../lib/types";
import { AllocationProgressView } from "./AllocationProgressView";
import { ArticleEditor } from "./Articles";
import { PathEditor } from "./PathEditor";

/* UI/UX audit Phase 2 (staff): editor h1 + breadcrumbs, ConfirmDialog instead of window.confirm,
   sticky Save/Publish, labelled step controls, one primary per view. */

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn() }), usePathname: () => "/trainer/paths/p1" }));

let restore: (() => void) | undefined;
afterEach(() => {
  restore?.();
  restore = undefined;
  push.mockReset();
  vi.restoreAllMocks();
});

const step: Step = {
  step_key: "s1",
  step_type: "reading",
  title: "Read the intro",
  description_md: null,
  est_hours: 1,
  credits: 10,
  url: "https://example.org",
  lesson_id: null,
  assignment_id: null,
  test_id: null,
  article_id: null,
  children: [],
} as Step;

const allocation: Allocation = {
  id: "al1",
  path_id: "p1",
  path_version_id: "v1",
  version_no: 1,
  target_type: "batch",
  batch_id: "b1",
  batch_name: "CSE 2027",
  user_ids: [],
  flow: "lenient",
  sequential: true,
  start_date: "2026-11-01",
  pace: { mode: "weekly", per_day: {} },
  weekly_hours: 5,
  total_hours: 1,
  finish_date: "2026-11-30",
  status: "active",
  learner_count: 6,
  created_at: "2026-11-01T00:00:00Z",
} as unknown as Allocation;

const path: PathDetail = {
  id: "p1",
  organization_id: "o1",
  title: "Python basics",
  description_md: null,
  level: null,
  status: "published",
  has_unpublished_changes: false,
  version_no: 2,
  step_count: 1,
  total_credits: 10,
  total_hours: 1,
  source: "manual",
  updated_at: "2026-11-01T00:00:00Z",
  steps: [step, { ...step, step_key: "s2", title: "Watch the video", step_type: "video" }],
  allocations: [allocation],
};

const linkOptions = { "GET paths/link-options": { body: { data: [] } } };

describe("PathEditor (Phase 2)", () => {
  it("has breadcrumbs, the path name as h1, a status badge and a sticky Save/Publish bar", async () => {
    const api = mockApi({ "GET paths/p1": { body: path }, ...linkOptions });
    restore = api.restore;
    renderWithProviders(<PathEditor pathId="p1" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Python basics" })).toBeInTheDocument();
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "Learning paths" })).toHaveAttribute("href", "/trainer/paths");
    expect(screen.getByText("Published v2")).toBeInTheDocument();
    // Publish is the one primary; Allocate is secondary.
    expect(screen.getByRole("button", { name: "Publish" }).className.split(" ")).toContain("bg-brand");
    expect(screen.getByRole("button", { name: "Allocate" }).className.split(" ")).not.toContain("bg-brand");
    expect(screen.getByText("All changes saved.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Steps \(2\)/ })).toHaveAttribute("href", "#path-steps");
  });

  it("labels move/delete step buttons with words, not glyphs", async () => {
    const api = mockApi({ "GET paths/p1": { body: path }, ...linkOptions });
    restore = api.restore;
    renderWithProviders(<PathEditor pathId="p1" />);
    const down = await screen.findByRole("button", { name: "Move step 1 down" });
    expect(down).toHaveTextContent("Down");
    expect(screen.getByRole("button", { name: "Delete step 2" })).toHaveTextContent("Delete");
    await userEvent.click(down);
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
  });

  it("archives through ConfirmDialog, never window.confirm", async () => {
    const confirmSpy = vi.spyOn(window, "confirm");
    const api = mockApi({ "GET paths/p1": { body: path }, "DELETE paths/p1": { status: 204 }, ...linkOptions });
    restore = api.restore;
    renderWithProviders(<PathEditor pathId="p1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Archive path" }));
    const dialog = screen.getByRole("dialog", { name: "Archive this path?", hidden: true });
    expect(api.calls.some((c) => c.method === "DELETE")).toBe(false);
    await userEvent.click(within(dialog).getByRole("button", { name: "Archive path", hidden: true }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/trainer/paths"));
    expect(confirmSpy).not.toHaveBeenCalled();
  });

  it("removes an allocation through ConfirmDialog", async () => {
    const api = mockApi({ "GET paths/p1": { body: path }, "DELETE path-allocations/al1": { status: 204 }, ...linkOptions });
    restore = api.restore;
    renderWithProviders(<PathEditor pathId="p1" />);
    expect(await screen.findByRole("link", { name: "Progress" })).toHaveAttribute("href", "/trainer/paths/allocations/al1");
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    const dialog = screen.getByRole("dialog", { name: "Remove this allocation?", hidden: true });
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove allocation", hidden: true }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "DELETE" && c.path === "path-allocations/al1")).toBe(true));
  });
});

const article: ArticleDetail = {
  id: "ar1",
  organization_id: "o1",
  title: "Welcome to CSE 2027",
  subtitle: null,
  level: null,
  est_minutes: null,
  status: "draft",
  audience: null,
  batch_ids: [],
  user_ids: [],
  updated_at: "2026-11-01T00:00:00Z",
  body_md: "## Intro\n\nHello.",
  toc: [],
};

describe("ArticleEditor (Phase 2)", () => {
  it("has breadcrumbs, the article name as h1 and deletes through ConfirmDialog", async () => {
    const confirmSpy = vi.spyOn(window, "confirm");
    const api = mockApi({ "GET path-articles/ar1": { body: article }, "DELETE path-articles/ar1": { status: 204 } });
    restore = api.restore;
    renderWithProviders(<ArticleEditor articleId="ar1" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Welcome to CSE 2027" })).toBeInTheDocument();
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "Articles" })).toHaveAttribute("href", "/trainer/paths/articles");
    expect(screen.getByText("Not published")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Delete article" }));
    const dialog = screen.getByRole("dialog", { name: "Delete this article?", hidden: true });
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete article", hidden: true }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/trainer/paths/articles"));
    expect(confirmSpy).not.toHaveBeenCalled();
  });
});

describe("AllocationProgressView (Phase 2)", () => {
  it("names the allocated batch as h1 with breadcrumbs back to the path", async () => {
    const api = mockApi({ "GET path-allocations/al1/progress": { body: { allocation, path: { id: "p1", title: "Python basics" }, steps: [], learners: [] } } });
    restore = api.restore;
    renderWithProviders(<AllocationProgressView allocationId="al1" />);
    expect(await screen.findByRole("heading", { level: 1, name: "CSE 2027" })).toBeInTheDocument();
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "Python basics" })).toHaveAttribute("href", "/trainer/paths/p1");
  });
});

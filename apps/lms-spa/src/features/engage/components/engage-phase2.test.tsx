import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import type { Activity, ActivitySummary, PresenterState, RunSummary } from "../lib/types";
import { ActivityBuilder } from "./ActivityBuilder";
import { EngageActivities } from "./ActivityList";
import { ControlRoom } from "./ControlRoom";
import { RunResults } from "./RunResults";

/* UI/UX audit Phase 2 (staff): engage headers, breadcrumbs, one primary per view, labelled controls. */

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn() }), usePathname: () => "/trainer/engage/new" }));

let restore: (() => void) | undefined;
afterEach(() => {
  restore?.();
  restore = undefined;
  push.mockReset();
});

const settings = {
  run_mode: "instant",
  audience: "public",
  identity_mode: "named",
  results_mode: "on_publish",
  pacing: "one_by_one",
  winner_rule: "fastest_first",
  participant_limit: null,
} as const;

const run: RunSummary = {
  id: "r1",
  activity_id: "a1",
  run_no: 2,
  join_code: "ABCD2345",
  join_path: "/app/engage/join/ABCD2345",
  status: "scheduled",
  current_position: 0,
  revealed_positions: [],
  results_published: false,
  question_count: 1,
  settings,
  opens_at: null,
  closes_at: null,
  opened_at: null,
  closed_at: null,
  finalised_at: null,
  created_at: null,
};

const summary: ActivitySummary = {
  id: "a1",
  activity_type: "quiz",
  title: "Arrays quiz",
  organization_id: "o1",
  description: null,
  batch_id: "b1",
  owner_id: "u1",
  ...settings,
  opens_at: null,
  closes_at: null,
  created_at: null,
  updated_at: null,
  question_count: 1,
  latest_run: null,
};

const activity: Activity = {
  ...summary,
  questions: [
    {
      id: "q1",
      position: 0,
      kind: "single_choice",
      prompt: "Which is O(1)?",
      max_words: null,
      options: [
        { id: "o1", position: 0, text: "Index", is_correct: true },
        { id: "o2", position: 1, text: "Search", is_correct: false },
      ],
    },
  ],
  runs: [],
} as unknown as Activity;

describe("Engage list (Phase 2)", () => {
  it("deletes through ConfirmDialog and shows a failure inside the dialog", async () => {
    const api = mockApi({
      "GET engage/activities": { body: { data: [summary], counts: { total: 1 } } },
      "DELETE engage/activities/a1": { status: 409, body: problem(409, "activity_live", "Activity is running") },
    });
    restore = api.restore;
    renderWithProviders(<EngageActivities />);
    const del = await screen.findByRole("button", { name: "Delete Arrays quiz" });
    expect(del.className).toContain("text-danger-fg");
    await userEvent.click(del);
    const dialog = screen.getByRole("dialog", { hidden: true });
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete activity", hidden: true }));
    expect(await within(dialog).findByRole("alert", { hidden: true })).toBeInTheDocument();
    expect(screen.getByRole("dialog", { hidden: true })).toBeInTheDocument();
  });
});

describe("ControlRoom (Phase 2)", () => {
  it("has breadcrumbs, the activity name as h1 and no primary in the header once a run exists", async () => {
    const api = mockApi({
      "GET engage/activities/a1": { body: { ...activity, runs: [run] } },
      "GET engage/runs/r1/presenter": { status: 404, body: problem(404, "not_found", "Not found") },
    });
    restore = api.restore;
    renderWithProviders(<ControlRoom activityId="a1" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Arrays quiz" })).toBeInTheDocument();
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "Engage" })).toHaveAttribute("href", "/trainer/engage");
    const rerun = screen.getByRole("button", { name: "Rerun" });
    expect(rerun.className.split(" ")).not.toContain("bg-brand");
    // The scheduled run's Start is the one primary; the big-screen link is secondary.
    expect(screen.getByRole("button", { name: /Start/ }).className.split(" ")).toContain("bg-brand");
    expect(screen.getByRole("link", { name: /Present on big screen/ }).className.split(" ")).not.toContain("bg-brand");
  });

  it("offers Launch only in the empty state before the first run", async () => {
    const api = mockApi({ "GET engage/activities/a1": { body: activity } });
    restore = api.restore;
    renderWithProviders(<ControlRoom activityId="a1" />);
    expect(await screen.findByText("Not launched yet")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Launch" })).toHaveLength(1);
  });
});

describe("RunResults (Phase 2)", () => {
  it("shows breadcrumbs back to the control room", async () => {
    const state = {
      run: { ...run, status: "finalised", results_published: true },
      activity: { id: "a1", title: "Arrays quiz", activity_type: "quiz" },
      joined: 3,
      voted: 2,
      total_votes: 2,
      questions: [],
      leaderboard: [],
      participants: [],
    } as unknown as PresenterState;
    const api = mockApi({ "GET engage/runs/r1/results": { body: state } });
    restore = api.restore;
    renderWithProviders(<RunResults runId="r1" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Arrays quiz" })).toBeInTheDocument();
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "Arrays quiz" })).toHaveAttribute("href", "/trainer/engage/a1");
    expect(within(crumbs).getByText("Run 2 results")).toBeInTheDocument();
  });
});

describe("ActivityBuilder (Phase 2)", () => {
  it('titles a new activity "New activity" (not "New poll") with the type beside it', async () => {
    const api = mockApi({ "GET batches": { body: { data: [] } }, "GET me/grants": { body: { data: [] } } });
    restore = api.restore;
    renderWithProviders(<ActivityBuilder type="poll" />);
    expect(screen.getByRole("heading", { level: 1, name: "New activity" })).toBeInTheDocument();
    expect(screen.getAllByText("Poll").length).toBeGreaterThan(0);
    expect(screen.getByRole("navigation", { name: "Jump to section" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Questions \(1\)/ })).toHaveAttribute("href", "#activity-questions");
    await waitFor(() => expect(api.calls.some((c) => c.path === "me/grants")).toBe(true));
  });

  it("uses the activity name as h1 when editing, with labelled move buttons and a 44px correct-answer target", async () => {
    const api = mockApi({
      "GET engage/activities/a1": { body: activity },
      "GET batches": { body: { data: [] } },
      "GET me/grants": { body: { data: [] } },
    });
    restore = api.restore;
    renderWithProviders(<ActivityBuilder activityId="a1" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Arrays quiz" })).toBeInTheDocument();
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "Arrays quiz" })).toHaveAttribute("href", "/trainer/engage/a1");
    expect(screen.getByRole("button", { name: "Move question 1 up" })).toHaveTextContent("Up");
    const correct = screen.getByRole("radio", { name: "Option 1 is correct" });
    expect(correct.closest("label")?.className).toContain("min-h-touch");
    expect(screen.getByRole("button", { name: "Save quiz" })).toBeInTheDocument();
  });
});

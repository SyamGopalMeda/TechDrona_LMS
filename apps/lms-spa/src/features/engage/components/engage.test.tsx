import { act, renderHook, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { usePoll } from "../lib/use-poll";
import type { ActivitySummary, LiveQuestion, LiveState, PresenterState, RunSummary } from "../lib/types";
import { EngageScopeProvider } from "../lib/scope";
import { EngageActivities } from "./ActivityList";
import { JoinRun } from "./Learner";
import { LiveRunView } from "./LiveRun";
import { PresenterView } from "./Presenter";

const push = vi.fn();
const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace }), usePathname: () => "/trainer/engage" }));

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
  status: "open",
  current_position: 0,
  revealed_positions: [],
  results_published: false,
  question_count: 2,
  settings,
  opens_at: null,
  closes_at: null,
  opened_at: null,
  closed_at: null,
  finalised_at: null,
  created_at: null,
};

const activity: ActivitySummary = {
  id: "a1",
  activity_type: "quiz",
  title: "Arrays quiz",
  description: null,
  organization_id: "o1",
  batch_id: "b1",
  owner_id: "u1",
  ...settings,
  opens_at: null,
  closes_at: null,
  created_at: null,
  updated_at: null,
  question_count: 5,
  latest_run: run,
};

describe("EngageActivities (TRN-020)", () => {
  it("renders cards with type, count, settings and status", async () => {
    const api = mockApi({ "GET engage/activities": { body: { data: [activity], counts: { total: 1 } } } });
    restore = api.restore;
    renderWithProviders(<EngageActivities />);
    expect(await screen.findByText("Arrays quiz")).toBeInTheDocument();
    expect(screen.getByText("Quiz · 5 questions")).toBeInTheDocument();
    expect(screen.getByText("Public · Named · Fastest first")).toBeInTheDocument();
    expect(screen.getByText("Live")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open control room for Arrays quiz" })).toHaveAttribute("href", "/trainer/engage/a1");
    // The card title also opens the control room.
    expect(screen.getByRole("link", { name: "Arrays quiz" })).toHaveAttribute("href", "/trainer/engage/a1");
  });

  it("keeps per-card actions secondary (the header's New is the one primary)", async () => {
    const api = mockApi({ "GET engage/activities": { body: { data: [activity], counts: { total: 1 } } } });
    restore = api.restore;
    renderWithProviders(<EngageActivities />);
    const open = await screen.findByRole("link", { name: "Open control room for Arrays quiz" });
    expect(open.className.split(" ")).not.toContain("bg-brand");
    expect(screen.getByRole("link", { name: "Edit Arrays quiz" }).className.split(" ")).not.toContain("bg-brand");
  });

  it("points links at a custom scope base", async () => {
    const api = mockApi({ "GET engage/activities": { body: { data: [activity], counts: { total: 1 } } } });
    restore = api.restore;
    renderWithProviders(
      <EngageScopeProvider base="/evaluator/engage">
        <EngageActivities />
      </EngageScopeProvider>,
    );
    expect(await screen.findByRole("link", { name: "Open control room for Arrays quiz" })).toHaveAttribute("href", "/evaluator/engage/a1");
    expect(screen.getByRole("link", { name: "Edit Arrays quiz" })).toHaveAttribute("href", "/evaluator/engage/a1/edit");
  });

  it("duplicates through POST …/duplicate with an idempotency key", async () => {
    const api = mockApi({
      "GET engage/activities": { body: { data: [activity], counts: { total: 1 } } },
      "POST engage/activities/a1/duplicate": { status: 201, body: { ...activity, id: "a2", title: "Arrays quiz (copy)" } },
    });
    restore = api.restore;
    renderWithProviders(<EngageActivities />);
    await userEvent.click(await screen.findByRole("button", { name: "Duplicate Arrays quiz" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.path === "engage/activities/a1/duplicate")).toBe(true));
    const call = api.calls.find((c) => c.path === "engage/activities/a1/duplicate")!;
    expect(Object.keys(call.headers).map((h) => h.toLowerCase())).toContain("idempotency-key");
    expect(await screen.findByText('Created "Arrays quiz (copy)"')).toBeInTheDocument();
    expect(api.calls.filter((c) => c.method === "GET" && c.path === "engage/activities")).toHaveLength(2);
  });

  it("asks for confirmation, then deletes through DELETE", async () => {
    const api = mockApi({
      "GET engage/activities": { body: { data: [activity], counts: { total: 1 } } },
      "DELETE engage/activities/a1": { status: 204 },
    });
    restore = api.restore;
    renderWithProviders(<EngageActivities />);
    await userEvent.click(await screen.findByRole("button", { name: "Delete Arrays quiz" }));
    expect(screen.getByText(/Delete "Arrays quiz"\?.*This cannot be undone\./)).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "DELETE")).toBe(false);
    const dialog = screen.getByRole("dialog", { hidden: true });
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete activity", hidden: true }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "DELETE" && c.path === "engage/activities/a1")).toBe(true));
  });

  it("passes search and type filters as query parameters", async () => {
    const api = mockApi({ "GET engage/activities": { body: { data: [], counts: { total: 0 } } } });
    restore = api.restore;
    renderWithProviders(<EngageActivities />);
    await screen.findByText("No activities yet");
    await userEvent.selectOptions(screen.getByLabelText("Activity type"), "word_cloud");
    await waitFor(() => expect(api.calls.some((c) => c.url.includes("type=word_cloud"))).toBe(true));
  });
});

describe("usePoll", () => {
  it("sends since=<last version> and keeps the state when unchanged", async () => {
    let n = 0;
    const api = mockApi({
      "GET engage/runs/r1/live": () => {
        n += 1;
        return n === 1 ? { body: { version: "v1", value: 1 } } : { body: { unchanged: true, version: "v1" } };
      },
    });
    restore = api.restore;
    const { result, unmount } = renderHook(() => usePoll<{ version: string; value: number }>("engage/runs/r1/live", { intervalMs: 20 }));
    await waitFor(() => expect(api.calls.length).toBeGreaterThanOrEqual(3));
    unmount();
    expect(api.calls[0]!.url).not.toContain("since=");
    expect(api.calls[1]!.url).toContain("since=v1");
    expect(result.current.data).toEqual({ version: "v1", value: 1 });
  });

  it("stops polling once done() is true", async () => {
    const api = mockApi({ "GET engage/runs/r1/presenter": { body: { version: "v9", run: { status: "finalised" } } } });
    restore = api.restore;
    const { unmount } = renderHook(() =>
      usePoll<{ version: string; run: { status: string } }>("engage/runs/r1/presenter", { intervalMs: 10, done: (d) => d.run.status === "finalised" }),
    );
    await waitFor(() => expect(api.calls).toHaveLength(1));
    await act(() => new Promise((r) => setTimeout(r, 60)));
    expect(api.calls).toHaveLength(1);
    unmount();
  });

  it("pauses while the tab is hidden", async () => {
    const api = mockApi({ "GET x/live": { body: { version: "v1" } } });
    restore = api.restore;
    const spy = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    const { unmount } = renderHook(() => usePoll<{ version: string }>("x/live", { intervalMs: 10 }));
    await act(() => new Promise((r) => setTimeout(r, 50)));
    expect(api.calls).toHaveLength(0);
    spy.mockReturnValue("visible");
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await waitFor(() => expect(api.calls.length).toBeGreaterThan(0));
    unmount();
    spy.mockRestore();
  });
});

function liveState(q: Partial<LiveQuestion>, extra: Partial<LiveState> = {}): LiveState {
  return {
    version: "v",
    run: {
      id: "r1",
      status: "open",
      pacing: "one_by_one",
      results_mode: "on_publish",
      identity_mode: "named",
      current_position: 0,
      question_count: 1,
      results_published: false,
      closes_at: null,
    },
    activity: { title: "Arrays quiz", description: null, activity_type: "quiz" },
    me: { label: "Asha", answered: 0 },
    joined: 3,
    questions: [
      {
        id: "q1",
        position: 0,
        kind: "single_choice",
        prompt: "First index?",
        options: [
          { id: "o1", text: "Zero" },
          { id: "o2", text: "One" },
        ],
        max_words: null,
        answered: 0,
        revealed: false,
        answerable: true,
        my_answer: null,
        ...q,
      },
    ],
    leaderboard: [],
    my_rank: null,
    ...extra,
  };
}

describe("LiveRunView (STU-032)", () => {
  it("shows the waiting room while scheduled", () => {
    const s = liveState({});
    s.run.status = "scheduled";
    s.questions = [];
    renderWithProviders(<LiveRunView state={s} onSubmit={vi.fn()} />);
    expect(screen.getByText("Waiting for the host to start")).toBeInTheDocument();
  });

  it("submits the chosen option", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    renderWithProviders(<LiveRunView state={liveState({})} onSubmit={onSubmit} />);
    await userEvent.click(screen.getByRole("radio", { name: "One" }));
    await userEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(onSubmit).toHaveBeenCalledWith({ question_id: "q1", option_ids: ["o2"] });
  });

  it("never renders correctness before the api provides it", () => {
    renderWithProviders(<LiveRunView state={liveState({ my_answer: { option_ids: ["o2"] }, answerable: false })} onSubmit={vi.fn()} />);
    expect(screen.getByText("Answer received")).toBeInTheDocument();
    expect(screen.queryByText("Correct")).toBeNull();
    expect(screen.queryByText("Incorrect")).toBeNull();
    expect(screen.queryByLabelText("Correct answer")).toBeNull();
    expect(screen.queryByText(/%/)).toBeNull();
    expect(screen.getByText("Results will appear when the host shows them.")).toBeInTheDocument();
  });

  it("shows own result, correct option and distribution after reveal", () => {
    renderWithProviders(
      <LiveRunView
        state={liveState({
          my_answer: { option_ids: ["o2"] },
          answerable: false,
          revealed: true,
          my_correct: false,
          answered: 3,
          options: [
            { id: "o1", text: "Zero", count: 2, pct: 67, correct: true },
            { id: "o2", text: "One", count: 1, pct: 33, correct: false },
          ],
        })}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByText("Incorrect")).toBeInTheDocument();
    expect(screen.getByLabelText("Correct answer")).toBeInTheDocument();
    expect(screen.getByText("67% · 2")).toBeInTheDocument();
    expect(screen.getByText("Your answer")).toBeInTheDocument();
  });

  it("shows the final leaderboard and my rank when published", () => {
    const s = liveState(
      {},
      {
        leaderboard: [{ rank: 1, label: "Asha", wins: 2, correct: 3, time_ms: 4200 }],
        my_rank: { rank: 1, label: "Asha", wins: 2, correct: 3, time_ms: 4200 },
      },
    );
    s.run.status = "finalised";
    renderWithProviders(<LiveRunView state={s} onSubmit={vi.fn()} />);
    expect(screen.getByText("#1")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Leaderboard" })).toBeInTheDocument();
  });
});

function presenter(revealed: boolean): PresenterState {
  return {
    version: "v",
    run: { ...run, revealed_positions: revealed ? [0] : [] },
    activity: { id: "a1", title: "Arrays quiz", description: null, activity_type: "quiz" },
    joined: 3,
    voted: 3,
    total_votes: 3,
    participants: [],
    questions: [
      {
        id: "q1",
        position: 0,
        kind: "single_choice",
        prompt: "First index?",
        options: [
          { id: "o1", text: "Zero", count: 2, pct: 67, correct: true },
          { id: "o2", text: "One", count: 1, pct: 33, correct: false },
        ],
        max_words: null,
        answered: 3,
        revealed,
        winner: { fastest: "Krishna", also_correct: ["Varun"], also_correct_count: 1 },
      },
    ],
    leaderboard: [],
  };
}

describe("PresenterView (big screen)", () => {
  it("renders percent bars but hides the correct answer and winner until revealed", () => {
    renderWithProviders(<PresenterView state={presenter(false)} onControl={vi.fn()} busy={null} />);
    expect(screen.getByText("Q1 / 2", { selector: "span.font-semibold" })).toBeInTheDocument();
    expect(screen.getByText("3 answered")).toBeInTheDocument();
    expect(screen.getByText("67% · 2")).toBeInTheDocument();
    expect(screen.getByText("33% · 1")).toBeInTheDocument();
    expect(screen.queryByLabelText("Correct answer")).toBeNull();
    expect(screen.queryByText(/Fastest:/)).toBeNull();
  });

  it("highlights the correct option and the winner after reveal; Hide correct toggles locally", async () => {
    const onControl = vi.fn();
    renderWithProviders(<PresenterView state={presenter(true)} onControl={onControl} busy={null} />);
    expect(screen.getByLabelText("Correct answer")).toBeInTheDocument();
    expect(screen.getByText("Fastest: Krishna")).toBeInTheDocument();
    expect(screen.getByText("Also correct: Varun")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Hide correct" }));
    expect(screen.queryByLabelText("Correct answer")).toBeNull();
    expect(onControl).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Next question" }));
    expect(onControl).toHaveBeenCalledWith("goto", 1);
  });

  it("shows the join screen with QR, code and joined count while scheduled", async () => {
    const onControl = vi.fn();
    const s = presenter(false);
    s.run = { ...s.run, status: "scheduled" };
    renderWithProviders(<PresenterView state={s} onControl={onControl} busy={null} />);
    expect(screen.getByText("ABCD2345")).toBeInTheDocument();
    expect(screen.getByText("3 joined")).toBeInTheDocument();
    expect(await screen.findByRole("img", { name: /QR code to join: .*\/app\/engage\/join\/ABCD2345/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Start/ }));
    expect(onControl).toHaveBeenCalledWith("start");
  });
});

describe("JoinRun (STU-031)", () => {
  it("joins and continues to the run page", async () => {
    const api = mockApi({
      "GET engage/join/ABCD2345": {
        body: { run_id: "r1", title: "Arrays quiz", description: null, activity_type: "quiz", status: "open", audience: "members", identity_mode: "anonymous", eligible: true, joined: false },
      },
      "POST engage/join/ABCD2345": { body: { run_id: "r1", status: "open", joined: true } },
    });
    restore = api.restore;
    renderWithProviders(<JoinRun code="abcd2345" />);
    expect(await screen.findByText("Your name won't be shown with your answers.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Join" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/app/engage/runs/r1?code=ABCD2345"));
  });

  it("explains a full activity", async () => {
    const api = mockApi({
      "GET engage/join/ABCD2345": {
        body: { run_id: "r1", title: "Q", description: null, activity_type: "poll", status: "open", audience: "public", identity_mode: "named", eligible: true, joined: false },
      },
      "POST engage/join/ABCD2345": problem(409, "participant_limit_reached", "This activity is full"),
    });
    restore = api.restore;
    renderWithProviders(<JoinRun code="ABCD2345" />);
    await userEvent.click(await screen.findByRole("button", { name: "Join" }));
    expect(await screen.findByText("The host set a participant limit and it has been reached.")).toBeInTheDocument();
  });

  it("shows not found for a bad code", async () => {
    const api = mockApi({ "GET engage/join/ABCD2345": problem(404, "not_found", "Not found") });
    restore = api.restore;
    renderWithProviders(<JoinRun code="ABCD2345" />);
    expect(await screen.findByText("Code not found")).toBeInTheDocument();
  });
});

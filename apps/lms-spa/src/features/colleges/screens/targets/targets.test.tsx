import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { FormsHost } from "../../forms";
import { Targets } from "../Targets";
import { cleanup, currentSearch, mockApi, renderAt, resetAll, type Call } from "../shared/test-utils";
import { openTargetDialog } from "./TargetDialog";
import { act } from "react";

const dash = { program: { target: 400, confirmed: 40, remaining: 360, pct: 0.1, deadline: "2026-12-31" }, days_left: 48, required_weekly: 52.5 };
const perfRows = [
  { id: 1, name: "Ravi", role: "college_lead", college: { id: "c1", short_name: "AEC" }, target: 10, actual_own: 2, actual: 2, remaining: 8, pct: 20, status: "behind", team: { size: 2, actual: 3, target: 6 }, combined: { actual: 5, target: 16 } },
  { id: 2, name: "Sita", role: "ambassador", college: { id: "c1", short_name: "AEC" }, target: 5, actual: 6, exceeded_by: 1, remaining: 0, pct: 120, status: "exceeded" },
  { id: 3, name: "Arun", role: "ambassador", college: { id: "c1", short_name: "AEC" }, target: null, actual: 0, status: "no_target" },
];

beforeEach(resetAll);
afterEach(cleanup);

describe("Targets › Performance", () => {
  it("shows the programme card, one card per status that occurs, and the table with server values", async () => {
    mockApi({
      "GET target-dashboard": dash,
      "GET colleges": [{ id: "c1", name: "Alpha", short_name: "AEC" }],
      "GET performance": { rows: perfRows, period: { start: "2026-09-01", end: "2026-12-31", days_elapsed: 75, days_total: 122 } },
      "GET meta": { districts: [], cities: [], today: "2026-11-14" },
    });
    renderAt(<Targets />, { path: "/colleges/targets" });
    expect(await screen.findByText("Programme target")).toBeInTheDocument();
    expect(screen.getByText(/48 days left including today/)).toBeInTheDocument();
    // only statuses that occur: Behind, Exceeded, No target (no "On track" / "Met" cards)
    await screen.findByText("Ravi");
    const cards = document.querySelector(".tgp-cards")!;
    expect(within(cards as HTMLElement).getAllByRole("button")).toHaveLength(3);
    expect(within(cards as HTMLElement).queryByText("On track")).toBeNull();
    // lead row: own / team / total; exceeded row: "+1 over"; no target: "not set"
    expect(screen.getByText("+1 over")).toBeInTheDocument();
    expect(screen.getByText("not set")).toBeInTheDocument();
    expect(screen.getByText(/For college leads and ambassador leads/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ravi" })).toHaveAttribute("href", "/colleges/person/1");
    // clicking a status card filters the table (kept in the URL)
    fireEvent.click(within(cards as HTMLElement).getByText("Exceeded").closest("button")!);
    await waitFor(() => expect(currentSearch()).toContain("status=exceeded"));
    await waitFor(() => expect(screen.queryByRole("link", { name: "Ravi" })).toBeNull());
    expect(screen.getByText(/filtered from 3/)).toBeInTheDocument();
  });

  it("switches to colleges and keeps the level in the URL", async () => {
    const calls = mockApi({ "GET target-dashboard": dash, "GET colleges": [], "GET performance": { rows: [] }, "GET meta": { today: "2026-11-14" } });
    renderAt(<Targets />, { path: "/colleges/targets" });
    fireEvent.click(await screen.findByRole("radio", { name: "Colleges" }));
    await waitFor(() => expect(currentSearch()).toContain("level=college"));
    await waitFor(() => expect(calls.some((c) => c.path === "performance" && c.query.get("level") === "college")).toBe(true));
  });
});

describe("Targets › by place", () => {
  it("renders the programme target, reconciliation state and the tree", async () => {
    mockApi({
      "GET meta": { districts: [{ id: "guntur", name: "Guntur", targeted: 1 }], cities: [], courses: [], today: "2026-11-14" },
      "GET summary": { target: 400, enrolled: 40, remaining: 360, pct: 0.1, deadline: "2026-12-31", target_source: "explicit", reached: 0 },
      "GET leaderboard": [{ id: "guntur", type: "district", label: "Guntur", target: 200, enrolled: 20, pct: 0.1, target_source: "explicit" }],
      "GET targets/unreconciled": [],
      "GET targets": [],
      "GET colleges": [],
    });
    renderAt(<Targets />, { path: "/colleges/targets?tab=places" });
    expect(await screen.findByText(/Everything adds up/)).toBeInTheDocument();
    expect(screen.getByRole("treegrid", { name: "Targets by place" })).toBeInTheDocument();
    expect(screen.getByText("Guntur")).toBeInTheDocument();
    expect(screen.getByText("Split a target", { selector: "h2" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Preview the split" })).toBeInTheDocument();
  });
});

describe("Target dialog", () => {
  it("validates min / target / max and saves with PUT /targets", async () => {
    const calls: Call[] = mockApi({
      "GET targets": [],
      "GET health": { version: "v4", today: "2026-11-14" },
      "GET meta": { today: "2026-11-14" },
      "PUT targets": { id: 7 },
    });
    renderAt(<FormsHost />);
    let done: Promise<unknown> = Promise.resolve();
    act(() => {
      done = openTargetDialog({ scope_type: "person", scope_id: "12", label: "Ravi", period: "programme", v4: true });
    });
    await screen.findByText("Target — Ravi");
    fireEvent.change(screen.getByLabelText("Target"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Minimum (optional)"), { target: { value: "9" } });
    fireEvent.click(screen.getByRole("button", { name: "Save target" }));
    expect(await screen.findByText("The minimum cannot be more than the target.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Minimum (optional)"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Save target" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && c.path === "targets")).toBe(true));
    const put = calls.find((c) => c.method === "PUT")!;
    expect(put.body).toMatchObject({ scope_type: "person", scope_id: "12", period: "programme", min: 2, target: 5, max: null });
    await expect(done).resolves.toBe(true);
  });
});

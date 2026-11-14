import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { People } from "./People";
import { Person } from "./Person";
import { Plan } from "./Plan";
import { computePlan, normalizeAssumptions } from "./plan/model";
import { cleanup, currentSearch, mockApi, renderAt, resetAll } from "./shared/test-utils";

beforeEach(resetAll);
afterEach(cleanup);

const planCollege = (id: string, rank: number, extra: Record<string, unknown> = {}) => ({
  college_id: id,
  name: `College ${id}`,
  short_name: id.toUpperCase(),
  district_id: "guntur",
  city: "Guntur",
  rank,
  p_level: "P1",
  status_final: "active",
  type: "b",
  access_x: 1,
  it_fy: { value: 600, basis: "verified" },
  it_3rd: { value: 600, basis: "estimated" },
  it_2nd: { value: 600, basis: "estimated" },
  it_branch_count: 4,
  branches: [{ name: "CSE", is_it: true, intake_2023_24: 300, intake_latest: 360, basis: "verified" }],
  actual: { confirmed: 2, ambassadors: 1, people: [{ id: 5, full_name: "Ravi", role: "college_lead", status: "active" }] },
  ...extra,
});

describe("Planner model", () => {
  it("is the research formula: buffered minimum → ambassadors, leads and standby", () => {
    const plan = computePlan([planCollege("c1", 1)], normalizeAssumptions({}), { today: "2026-11-14" });
    const r = plan.colleges[0];
    expect(r.targeted).toBe(true);
    // 1.0 × 1 × (0.0075×600 + 0.00375×600×0.5 + 0.0015×600×0.5) = 6.075 → 6
    expect(r.min).toBe(6);
    expect(r.ambassadors).toBe(Math.max(3, Math.ceil(Math.ceil(1.2 * 6) / 2.5)));
    expect(plan.progress.days_left).toBe(48);
  });
});

describe("Target planner", () => {
  it("renders the strip, the tables and expands a college row with its team", async () => {
    mockApi({
      "GET plan": { program: { target: 400, deadline: "2026-12-31" }, colleges: [planCollege("c1", 1), planCollege("c2", 2, { p_level: "P2" })], research_version: "v2" },
      "GET meta": { districts: [{ id: "guntur", name: "Guntur" }], cities: [], today: "2026-11-14" },
    });
    renderAt(<Plan />, { path: "/colleges/plan?college=c2" });
    expect(await screen.findByText("Goal", { selector: ".vp-tile__label" })).toBeInTheDocument();
    expect(screen.getByText("400 paid")).toBeInTheDocument();
    expect(screen.getByText(/What it takes to reach 400/)).toBeInTheDocument();
    expect(screen.getByText("District breakdown")).toBeInTheDocument();
    // ?college=c2 opened that row
    const exp = await screen.findByRole("button", { name: /Hide branches and team for College c2/ });
    expect(exp).toHaveAttribute("aria-expanded", "true");
    expect(screen.getAllByText("Team for this college").length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: "Ravi" })[0]).toHaveAttribute("href", "/colleges/person/5");
    // expand another row
    fireEvent.click(screen.getByRole("button", { name: /Show branches and team for College c1/ }));
    expect(screen.getAllByText("Team for this college")).toHaveLength(2);
    // changing an assumption recomputes and is remembered in this browser
    fireEvent.change(screen.getByRole("spinbutton", { name: /Programme goal/ }), { target: { value: "500" } });
    await screen.findByText("500 paid");
    expect(JSON.parse(localStorage.getItem("td.plan.assumptions")!).program_target).toBe(500);
    expect(screen.getByText("Changed from research defaults")).toBeVisible();
  });

  it("explains when the research data is not imported", async () => {
    mockApi({ "GET plan": { imported: false, colleges: [] }, "GET meta": {} });
    renderAt(<Plan />, { path: "/colleges/plan" });
    expect(await screen.findByText("Research data has not been imported yet")).toBeInTheDocument();
  });
});

const person = (id: number, extra: Record<string, unknown> = {}) => ({
  id,
  full_name: `Person ${id}`,
  role: "ambassador",
  status: "active",
  college_id: "c1",
  college: { id: "c1", name: "Alpha", short_name: "AEC" },
  phone: "+919876543210",
  assignment_status: "assigned",
  target_summary: { target: 5, min: null, max: null, remaining: 3, exceeded_by: 0, pct: 40, status: "behind" },
  actual_own: 2,
  ...extra,
});

describe("Team", () => {
  it("lists people with segment counts, filters in the URL and row actions", async () => {
    const calls = mockApi({
      "GET people": (c: { query: URLSearchParams }) =>
        c.query.get("page_size") === "1"
          ? { items: [], total: c.query.get("status") === "inactive" ? 2 : 3, page: 1, page_size: 1, counts: { college_lead: 1, ambassador: 2, unassigned: 1 } }
          : { items: [person(1, { role: "college_lead" }), person(2, { assignment_status: "unassigned", assignment_issue: "no_lead" })], total: 2, page: 1, page_size: 50 },
      "GET colleges": [{ id: "c1", name: "Alpha", short_name: "AEC" }],
    });
    renderAt(<People />, { path: "/colleges/people" });
    expect(await screen.findByRole("link", { name: "Person 1" })).toHaveAttribute("href", "/colleges/person/1");
    expect(screen.getByText("Leads the college")).toBeInTheDocument();
    const segs = screen.getByRole("group", { name: "Show" });
    expect(within(segs).getByRole("button", { name: /Without a lead/ })).toHaveTextContent("1");
    expect(screen.getByText(/2 people who left are not listed/)).toBeInTheDocument();
    fireEvent.click(within(segs).getByRole("button", { name: /Without a lead/ }));
    await waitFor(() => expect(currentSearch()).toContain("seg=unassigned"));
    await waitFor(() => expect(calls.some((c) => c.path === "people" && c.query.get("assignment") === "unassigned,invalid_link" && c.query.get("page_size") === "50")).toBe(true));
    expect(screen.getAllByRole("button", { name: "Row actions" }).length).toBeGreaterThan(0);
  });

  it("says nobody matches when filtered and offers to clear", async () => {
    mockApi({ "GET people": { items: [], total: 0, page: 1, page_size: 50 }, "GET colleges": [] });
    renderAt(<People />, { path: "/colleges/people?role=ambassador" });
    expect(await screen.findByText("Nobody matches these filters")).toBeInTheDocument();
    const clear = screen.getAllByRole("button", { name: "Clear filters" });
    fireEvent.click(clear[clear.length - 1]!);
    await waitFor(() => expect(currentSearch()).not.toContain("role="));
  });
});

describe("Person", () => {
  it("shows where they fit, own / team performance and their lists", async () => {
    mockApi({
      "GET people/1": { person: person(1, { role: "college_lead", team_size: 1 }), college: { id: "c1", name: "Alpha", short_name: "AEC" }, enrollments: [], followups: [], activities: [] },
      "GET people": { items: [person(1, { role: "college_lead" }), person(2, { reports_to: 1 })], total: 2 },
      "GET performance": { period: { label: "Programme", start: "2026-09-01", end: "2026-12-31" }, rows: [{ id: 1, target: 10, actual_own: 4, remaining: 6, pct: 40, status: "behind", team: { size: 1, target: 5, actual: 2, status: "behind", pct: 40 } }] },
      "GET targets": [],
      "GET audit": [],
      "GET meta": { today: "2026-11-14", courses: [] },
    });
    renderAt(<Person />, { path: "/colleges/person/1", pattern: "/colleges/person/:id" });
    expect(await screen.findByRole("heading", { name: "Person 1" })).toBeInTheDocument();
    expect(screen.getByText("This person")).toBeInTheDocument();
    expect(await screen.findByText("Own")).toBeInTheDocument();
    expect(screen.getByText("Team", { selector: "strong" })).toBeInTheDocument();
    expect(screen.getByText("Team (1)")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Person 2" })).toHaveAttribute("href", "/colleges/person/2");
    expect(screen.getByText("No enrollments credited yet")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "This month" }));
    await waitFor(() => expect(currentSearch()).toContain("period=month%3A2026-11"));
  });

  it("says when the person does not exist", async () => {
    mockApi({ "GET meta": {} });
    renderAt(<Person />, { path: "/colleges/person/99", pattern: "/colleges/person/:id" });
    expect(await screen.findByText("Person not found")).toBeInTheDocument();
  });
});

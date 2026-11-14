import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { Home } from "./Home";
import { Reports } from "./Reports";
import { cleanup, currentSearch, mockApi, renderAt, resetAll } from "./shared/test-utils";

const summary = { scope: "state", label: "Selected districts", target: 400, enrolled: 40, reached: 120, remaining: 360, pct: 0.1, deadline: "2026-12-31", followups_open: 5, followups_overdue: 2, target_source: "explicit", by_course: [] };
const road = {
  target: 400,
  confirmed: 40,
  remaining: 360,
  pct: 0.1,
  required_weekly: 52.3,
  required_daily: 7.5,
  current_weekly: 12,
  days_left: 48,
  deadline: "2026-12-31",
  program: { target: 400, deadline: "2026-12-31" },
  confirmed_last_14d: 24,
  projection: { status: "after_deadline", date: "2027-03-01", explanation: "At the current pace" },
  funnel: { total: 3, stages: [{ stage: "lead", label: "Lead", count: 2 }, { stage: "confirmed", label: "Confirmed", count: 1, counts_toward_target: true }] },
  contacts: {},
  calls: { today: 1, last_7d: 4 },
  pending_calls: {},
  people: [],
};
const colleges = [
  { id: "c1", name: "Alpha Engineering College", short_name: "AEC", district_id: "guntur", targeted: 1, op_status: "operational" },
  { id: "c2", name: "Beta Institute", short_name: "BIT", district_id: "guntur", targeted: 1, op_status: "operational", lead: { id: 9, name: "Ravi" } },
  { id: "c3", name: "Gamma", district_id: "krishna", targeted: 0, op_status: "possibly_closed" },
];

beforeEach(() => {
  resetAll();
  localStorage.setItem("td.home.map", "0"); // keep Leaflet out of jsdom
});
afterEach(cleanup);

describe("Home", () => {
  it("shows the 4 KPI tiles, needs-attention cards, the call queue and the next 14 days", async () => {
    mockApi({
      "GET summary": summary,
      "GET target-dashboard": road,
      "GET colleges": colleges,
      "GET attention": [{ type: "college", id: "c1", label: "AEC", reasons: ["Exams start 2026-11-20"], severity: "high" }],
      "GET followups": [],
      "GET exams": [],
      "GET calls/queue": { rows: [{ college_id: "c1", name: "Alpha Engineering College", short_name: "AEC", district_name: "Guntur", call_status: "not_called", priority: { score: 87 }, best_contact: { phone: "+919876543210", basis: "verified", status: "working", role: "tpo" } }] },
      "GET people": { items: [], total: 3, page: 1, page_size: 1 },
      "GET performance": { rows: [{ id: 1, status: "behind", target: 5 }, { id: 2, status: "on_track", target: 5 }] },
      "GET meta": { districts: [], cities: [], courses: [], settings: {}, counts: {}, demo: false },
    });
    renderAt(<Home />);
    const strip = await screen.findByRole("region", { name: "Progress to the target" });
    expect(within(strip).getByText("400")).toBeInTheDocument();
    expect(within(strip).getByText("Paid enrollments")).toBeInTheDocument();
    expect(within(strip).getByText("10% of target")).toBeInTheDocument();
    expect(within(strip).getByText("Still needed")).toBeInTheDocument();
    expect(within(strip).getByText("52")).toBeInTheDocument();
    expect(within(strip).getByText(/current pace 12 a week/)).toBeInTheDocument();
    // needs attention: overdue follow-ups, colleges without a lead (1 of 2 targeted), ambassadors without a lead (3), behind (1)
    const lead = screen.getByText("Colleges without a college lead").closest("a")!;
    expect(lead).toHaveAttribute("href", "/colleges/colleges?team=no_lead&targeted=1");
    expect(within(lead).getByText("1")).toBeInTheDocument();
    expect(screen.getByText("Ambassadors without a lead").closest("a")).toHaveAttribute("href", "/colleges/people?seg=unassigned");
    expect(screen.getByText("Team members behind their target").closest("a")).toHaveAttribute("href", "/colleges/targets?level=person&status=behind");
    expect(screen.getByText("Show every issue, college by college (1)")).toBeInTheDocument();
    // call queue
    await screen.findByText("AEC", { selector: "a.vdc-name" });
    expect(screen.getByText(/priority 87\/100/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Call \+91 98765 43210/ })).toHaveAttribute("href", "tel:+919876543210");
    expect(screen.getByRole("button", { name: "Log call" })).toBeInTheDocument();
    // map: one count matching the pins, collapsed (remembered) and toggled open
    expect(screen.getByText(/2 colleges in the selected districts · 1 more may have shut down/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show map" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("No open follow-up is due in the next 14 days.")).toBeInTheDocument();
  });

  it("hides the two team cards while they are 0 and the Log call button for viewers", async () => {
    mockApi({
      "GET summary": summary,
      "GET target-dashboard": road,
      "GET colleges": colleges,
      "GET attention": [],
      "GET followups": [],
      "GET exams": [],
      "GET calls/queue": { rows: [{ college_id: "c1", name: "A", short_name: "AEC", call_status: "not_called" }] },
      "GET people": { items: [], total: 0 },
      "GET performance": { rows: [] },
      "GET meta": { districts: [], cities: [] },
    });
    renderAt(<Home />, { ui: { canWrite: false } });
    await screen.findByText("Colleges without a college lead");
    expect(screen.queryByText("Ambassadors without a lead")).toBeNull();
    expect(screen.queryByText("Team members behind their target")).toBeNull();
    await screen.findByText("AEC", { selector: "a.vdc-name" });
    expect(screen.queryByRole("button", { name: "Log call" })).toBeNull();
  });

  it("shows an error card with retry when the summary fails", async () => {
    mockApi({ "GET summary": () => new Response("{}", { status: 500 }) });
    renderAt(<Home />);
    expect(await screen.findByText("Could not load the programme summary")).toBeInTheDocument();
  });
});

describe("Reports", () => {
  it("renders the headline, road block and key facts, and keeps 'Report on' in the URL", async () => {
    mockApi({
      "GET summary": { ...summary, eligible: { value: 900, basis: "estimated" }, operational_colleges: 2, colleges: 3, exams: {} },
      "GET target-dashboard": road,
      "GET leaderboard": [],
      "GET timeseries": [{ date: "2026-11-10", enrolled: 1, reached: 3, cum_enrolled: 40, cum_reached: 100 }],
      "GET colleges": colleges,
      "GET plan": { totals_research: { college_leads: 63, ambassadors: 296, min: 377, avg: 655, max: 1143 }, totals_actual: { college_leads: 1, ambassadors: 2 } },
      "GET meta": { districts: [{ id: "guntur", name: "Guntur" }], cities: [] },
    });
    renderAt(<Reports />, { path: "/colleges/analytics" });
    expect(await screen.findByText("Road to 400")).toBeInTheDocument();
    expect(screen.getByText("Likely prospects (est.)", { selector: ".td-stat__label" })).toBeInTheDocument();
    expect(screen.getByText("Recruitment structure")).toBeInTheDocument();
    expect(screen.getByText(/of 63 needed/)).toBeInTheDocument();
    expect(screen.getByText("Operational colleges").closest("a")).toHaveAttribute("href", "/colleges/colleges");
    fireEvent.change(screen.getByLabelText("Report on"), { target: { value: "district" } });
    await waitFor(() => expect(currentSearch()).toContain("level=district"));
    expect(screen.getByLabelText("District")).toBeInTheDocument();
  });
});

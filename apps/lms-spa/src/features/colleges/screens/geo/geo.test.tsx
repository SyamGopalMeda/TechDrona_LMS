import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { configurePortalApi, resetPortalApiForTests } from "../../lib/api";
import { clearPortalCacheForTests } from "../../lib/cache";
import { getScope, resetScopeForTests } from "../../lib/scope";
import { OverlayHost, PortalUiProvider } from "../../ui";
import { FormsHost } from "../../forms/host";
import { resetOverlaysForTests } from "../../ui/Overlay";
import { District } from "../District";
import { Town } from "../Town";

vi.mock("../college-list/AddCollege", async () => {
  const { useState } = await import("react");
  return {
    useAddCollege: () => {
      const [d, setD] = useState<Record<string, string> | null>(null);
      return [(x?: Record<string, string>) => setD(x ?? {}), d ? <div role="dialog" aria-label="College form">{`defaults:${JSON.stringify(d)}`}</div> : null];
    },
  };
});
vi.mock("../../map/CollegeMap", () => ({
  CollegeMap: ({ focus, colleges }: { focus: unknown; colleges: unknown[] | null }) => (
    <div data-testid="map">{`focus:${JSON.stringify(focus)} pins:${colleges ? colleges.length : "-"}`}</div>
  ),
}));

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const META = {
  districts: [
    { id: "guntur", name: "Guntur" },
    { id: "kurnool", name: "Kurnool", old_district: "Kurnool" },
  ],
  cities: [
    { id: "guntur--tenali", district_id: "guntur", name: "Tenali" },
    { id: "guntur--guntur", district_id: "guntur", name: "Guntur city" },
  ],
  courses: [],
  settings: {},
  counts: {},
  demo: false,
};
const SUMMARY = {
  scope: "district:guntur",
  label: "Guntur",
  target: 100,
  target_source: "sum_of_children",
  enrolled: 25,
  remaining: 75,
  pct: 0.25,
  deadline: "2027-03-31",
  on_track: false,
  pace_status: "behind",
  diagnosis: "behind_pace",
  colleges: 20,
  targeted_colleges: 12,
  operational_colleges: 18,
  cities: 2,
  colleges_with_lead: 5,
  ambassadors: 9,
  ambassador_leads: 2,
  branches_needing_ambassadors: 4,
  eligible: { value: 1800, basis: "estimated" },
  followups_open: 3,
  followups_overdue: 1,
  exams: { in_exams: 2, exams_soon: 1, unknown: 4 },
};

let calls: string[] = [];
let summaryStatus = 200;

beforeEach(() => {
  localStorage.clear();
  resetScopeForTests();
  resetPortalApiForTests();
  clearPortalCacheForTests();
  calls = [];
  summaryStatus = 200;
  configurePortalApi({
    fetchImpl: (async (input: RequestInfo | URL) => {
      const url = String(input);
      calls.push(url);
      const path = url.replace(/^.*\/college-portal\/api\//, "").split("?")[0];
      const sp = new URL(url, "http://x").searchParams;
      if (path === "meta") return json(META);
      if (path === "summary") return summaryStatus === 200 ? json({ ...SUMMARY, label: sp.get("scope") === "city:guntur--tenali" ? "Tenali" : sp.get("scope") === "district:kurnool" ? "Kurnool" : "Guntur" }) : json({ error: "unknown scope" }, summaryStatus);
      if (path === "attention") return json([{ type: "college", id: "c1", label: "ABC College", href: "#/college/c1", reasons: ["Exams start 2026-11-20"], diagnosis: "exams", severity: "high" }]);
      if (path === "leaderboard") return json(sp.get("level") === "city" ? [{ id: "guntur--tenali", target: 0, enrolled: 7, colleges: 3 }] : [{ id: "c1", target: 10 }, { id: "c2", target: null }]);
      if (path === "plan") return json({ colleges: [] });
      if (path === "colleges") return json([{ id: "c1", sno: 1, name: "ABC College", short_name: "ABC", district_id: "guntur", city_id: "guntur--tenali", op_status: "operational", targeted: 1, target: null, enrolled: 0, remaining: null, pct: null, on_track: null, diagnosis: null, exam_state: "in_exams", next_exam: null, lead: null, ambassador_count: 0, unassigned_count: 0 }]);
      return json({ error: "nope" }, 404);
    }) as typeof fetch,
  });
});
afterEach(() => act(() => resetOverlaysForTests()));

function Loc() {
  const l = useLocation();
  return <output data-testid="loc">{`${l.pathname}${l.search}`}</output>;
}
function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <PortalUiProvider value={{ overlayRoot: document.body, form: "desktop", coarse: false, canWrite: true }}>
        <Routes>
          <Route path="/colleges/d/:district" element={<District />} />
          <Route path="/colleges/d/:district/:city" element={<Town />} />
          <Route path="*" element={<div>elsewhere</div>} />
        </Routes>
        <Loc />
        <FormsHost />
        <OverlayHost />
      </PortalUiProvider>
    </MemoryRouter>,
  );
}

describe("District page", () => {
  it("shows the summary, KPIs with the reviewed wording, cities, alerts, map and the fixed list", async () => {
    renderAt("/colleges/d/guntur");
    expect(await screen.findByRole("heading", { name: "Guntur", level: 1 })).toBeInTheDocument();
    expect(screen.getByText("Target district · Guntur")).toBeInTheDocument();
    expect(screen.getByText("20 colleges · 12 targeted · 2 cities and towns")).toBeInTheDocument();
    expect(screen.getByText("Target branches without ambassador")).toBeInTheDocument();
    expect(screen.getByText("Likely prospects (est.)", { selector: ".td-stat__label" })).toBeInTheDocument();
    expect(screen.getByText("Exams now or in 14 days")).toBeInTheDocument();
    expect(screen.getByText("75 to go · 25% achieved")).toBeInTheDocument();
    expect(await screen.findByText("Sum of lower-level targets · covers 1 of 2")).toBeInTheDocument();
    expect(screen.getByText("Cities & towns (2)")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Tenali/ })).toHaveAttribute("href", "/colleges/d/guntur/guntur--tenali");
    expect(await screen.findByText("Alerts in Guntur (1)")).toBeInTheDocument();
    expect(screen.getByText("Exams start 20 Nov 2026")).toBeInTheDocument();
    expect(screen.getByTestId("map")).toHaveTextContent('focus:{"kind":"district","id":"guntur"}');
    expect(await screen.findByRole("heading", { name: "Colleges in Guntur" })).toBeInTheDocument();
    await waitFor(() => expect(calls.some((u) => /\/api\/colleges\?.*district=guntur/.test(u) && !u.includes("districts=guntur,"))).toBe(true));
    expect(await screen.findByRole("link", { name: "ABC" })).toHaveAttribute("href", "/colleges/college/c1");
    // the KPI tiles open the list with that filter
    fireEvent.click(screen.getByText("Target branches without ambassador"));
    await waitFor(() => expect(screen.getByTestId("loc")).toHaveTextContent("/colleges/d/guntur?amb=gap"));
    // add college opens with the district preset
    fireEvent.click(screen.getByRole("button", { name: "Add college" }));
    expect(await screen.findByRole("dialog", { name: "College form" })).toHaveTextContent('defaults:{"district_id":"guntur"}');
  });

  it("switches district and offers to add an out-of-scope district to the selection", async () => {
    renderAt("/colleges/d/kurnool");
    expect(await screen.findByText("Kurnool is outside the selected districts")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add Kurnool" }));
    expect(getScope().ids).toContain("kurnool");
    fireEvent.change(screen.getByLabelText("Switch district"), { target: { value: "guntur" } });
    await waitFor(() => expect(screen.getByTestId("loc")).toHaveTextContent("/colleges/d/guntur"));
  });

  it("says when the district does not exist", async () => {
    summaryStatus = 400;
    renderAt("/colleges/d/nowhere");
    expect(await screen.findByText("District not found")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "All colleges" })).toHaveAttribute("href", "/colleges/colleges");
  });
});

describe("Town page", () => {
  it("resolves a short town id, shows any status by default and focuses the map on the town", async () => {
    renderAt("/colleges/d/guntur/tenali");
    expect(await screen.findByRole("heading", { name: "Tenali", level: 1 })).toBeInTheDocument();
    expect(calls.some((u) => u.includes("scope=city%3Aguntur--tenali") || u.includes("scope=city:guntur--tenali"))).toBe(true);
    expect(screen.getByRole("link", { name: "Guntur" })).toHaveAttribute("href", "/colleges/d/guntur");
    expect(screen.getByTestId("map")).toHaveTextContent('"kind":"city","district":"guntur","id":"guntur--tenali"');
    expect(await screen.findByText("1 college · any status")).toBeInTheDocument();
    const q = calls.find((u) => u.includes("/api/colleges?") && u.includes("city="))!;
    expect(q).not.toContain("op_status=");
  });

  it("says when the town does not exist", async () => {
    summaryStatus = 404;
    renderAt("/colleges/d/guntur/nowhere");
    expect(await screen.findByText("City not found")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "← Back to Guntur" })).toBeInTheDocument();
  });
});

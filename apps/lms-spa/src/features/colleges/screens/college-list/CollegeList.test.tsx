import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { configurePortalApi, resetPortalApiForTests } from "../../lib/api";
import { clearPortalCacheForTests } from "../../lib/cache";
import { csvCell, csvText } from "../../lib/csv";
import { resetScopeForTests } from "../../lib/scope";
import { OverlayHost, PortalUiProvider, type PortalUi } from "../../ui";
import { FormsHost } from "../../forms/host";
import { resetOverlaysForTests } from "../../ui/Overlay";
import { CollegeList } from "../CollegeList";

// the college create dialog is the College page's (screens/college/CollegeForm.tsx): stub the hook that opens it
vi.mock("./AddCollege", async () => {
  const { useState } = await import("react");
  return {
    useAddCollege: () => {
      const [d, setD] = useState<Record<string, string> | null>(null);
      return [
        (defaults?: Record<string, string>) => setD(defaults ?? {}),
        d ? <div role="dialog" aria-label="College form">{`defaults:${JSON.stringify(d)}`}</div> : null,
      ];
    },
  };
});

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

const META = {
  districts: [
    { id: "guntur", name: "Guntur" },
    { id: "krishna", name: "Krishna" },
  ],
  cities: [{ id: "guntur--tenali", district_id: "guntur", name: "Tenali" }],
  courses: [],
  settings: {},
  counts: {},
  demo: false,
};

function college(i: number, over: Record<string, unknown> = {}) {
  return {
    id: `c${i}`,
    sno: i,
    name: `College ${String(i).padStart(2, "0")}`,
    short_name: null,
    district_id: "guntur",
    city_id: "guntur--tenali",
    op_status: "operational",
    targeted: 1,
    target: null,
    enrolled: 0,
    remaining: null,
    pct: null,
    on_track: null,
    diagnosis: null,
    exam_state: "clear",
    next_exam: null,
    lead: null,
    ambassador_count: 0,
    unassigned_count: 0,
    data_status: "unverified",
    ...over,
  };
}

let calls: string[] = [];
let colleges: unknown[] = [];

function install() {
  calls = [];
  configurePortalApi({
    fetchImpl: (async (input: RequestInfo | URL) => {
      const url = String(input);
      calls.push(url);
      const path = url.replace(/^.*\/college-portal\/api\//, "").split("?")[0];
      if (path === "meta") return json(META);
      if (path === "plan") return json({ colleges: [{ college_id: "c3", p_level: "P1" }] });
      if (path === "colleges") return json(colleges);
      if (path === "people") return json([]);
      return json({ error: "not found" }, 404);
    }) as typeof fetch,
  });
}

function Loc() {
  const l = useLocation();
  return <output data-testid="loc">{`${l.pathname}${l.search}`}</output>;
}

function renderAt(url: string, node: ReactNode = <CollegeList />, over: Partial<PortalUi> = {}) {
  const ui: PortalUi = { overlayRoot: document.body, form: "desktop", coarse: false, canWrite: true, ...over };
  return render(
    <MemoryRouter initialEntries={[url]}>
      <PortalUiProvider value={ui}>
        <Routes>
          <Route path="/colleges/colleges" element={node} />
          <Route path="*" element={<div>other page</div>} />
        </Routes>
        <Loc />
        <FormsHost />
        <OverlayHost />
      </PortalUiProvider>
    </MemoryRouter>,
  );
}

const loc = () => screen.getByTestId("loc").textContent ?? "";

beforeEach(() => {
  localStorage.clear();
  resetScopeForTests();
  resetPortalApiForTests();
  clearPortalCacheForTests();
  install();
});
afterEach(() => {
  act(() => resetOverlaysForTests());
  vi.restoreAllMocks();
});

describe("Colleges list", () => {
  it("loads the scoped operational list, puts research priority first and links rows", async () => {
    colleges = [college(1, { name: "Bravo" }), college(2, { name: "Alpha", lead: { id: 7, name: "Ravi", phone: "9876543210" } }), college(3, { name: "Charlie" })];
    renderAt("/colleges/colleges");
    expect(await screen.findByText("3 colleges · operational")).toBeInTheDocument();
    const q = calls.find((u) => u.includes("/api/colleges?"))!;
    expect(q).toContain("op_status=operational");
    expect(q).toContain("districts=guntur");
    // P1 (from /plan) first, then by name
    await waitFor(() => expect(screen.getAllByRole("row")[1]).toHaveTextContent("Charlie"));
    const rows = screen.getAllByRole("row");
    expect(rows[1]).toHaveTextContent("Priority P1");
    expect(rows[2]).toHaveTextContent("Alpha");
    expect(within(rows[2]!).getByRole("link", { name: "Ravi" })).toHaveAttribute("href", "/colleges/person/7");
    expect(within(rows[3]!).getByText("No lead")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Alpha" })).toHaveAttribute("href", "/colleges/college/c2");
  });

  it("puts filters and sort in the URL and re-asks the server for server filters", async () => {
    colleges = [college(1, { name: "Bravo" }), college(2, { name: "Alpha" })];
    renderAt("/colleges/colleges");
    await screen.findByText("2 colleges · operational");
    fireEvent.change(screen.getByLabelText("Team"), { target: { value: "0" } }); // first option: No college lead
    await waitFor(() => expect(loc()).toContain("team=no_lead"));
    await waitFor(() => expect(calls.some((u) => u.includes("team=no_lead"))).toBe(true));
    fireEvent.change(screen.getByLabelText("Sort"), { target: { value: "0" } }); // Name
    await waitFor(() => expect(loc()).toContain("sort=name"));
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "0" } }); // Any status
    await waitFor(() => expect(loc()).toContain("op=all"));
    await waitFor(() => expect(calls.some((u) => u.includes("/api/colleges?") && !u.includes("op_status="))).toBe(true));
    // a "More filters" select (client filter) + its chip
    fireEvent.change(screen.getByLabelText("Follow-ups"), { target: { value: "overdue" } });
    await waitFor(() => expect(loc()).toContain("followup=overdue"));
    expect(await screen.findByText("No colleges match these filters")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove Follow-ups: Overdue follow-up" }));
    await waitFor(() => expect(loc()).not.toContain("followup="));
  });

  it("pages 25 at a time with the page in the URL", async () => {
    colleges = Array.from({ length: 30 }, (_, i) => college(i + 1));
    renderAt("/colleges/colleges?sort=sno");
    expect(await screen.findByText("1–25 of 30 colleges")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(loc()).toContain("page=2"));
    expect(await screen.findByText("26–30 of 30 colleges")).toBeInTheDocument();
    expect(screen.getAllByRole("row")[1]).toHaveTextContent("College 26");
  });

  it("shows the empty states (first college vs filtered) and opens the add dialog", async () => {
    colleges = [];
    renderAt("/colleges/colleges");
    expect(await screen.findByText("No colleges yet")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Add college" })[0]!);
    expect(await screen.findByRole("dialog", { name: "College form" })).toBeInTheDocument();
  });

  it("filtered empty state offers Clear filters", async () => {
    colleges = [];
    renderAt("/colleges/colleges?q=zzz");
    expect(await screen.findByText("No colleges match these filters")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Clear filters" }).at(-1)!);
    await waitFor(() => expect(loc()).toBe("/colleges/colleges"));
  });

  it("hides the add buttons for viewers", async () => {
    colleges = [college(1)];
    renderAt("/colleges/colleges", <CollegeList />, { canWrite: false });
    await screen.findByText("1 college · operational");
    expect(screen.queryByRole("button", { name: "Add college" })).toBeNull();
  });

  it("exports the visible rows as CSV with the formula guard", async () => {
    colleges = [college(1, { name: "=HYPERLINK(1)", target: 10, enrolled: 4, remaining: 6, pct: 0.4, on_track: true })];
    const blobs: Blob[] = [];
    const create = vi.fn((b: Blob) => {
      blobs.push(b);
      return "blob:x";
    });
    Object.assign(URL, { createObjectURL: create, revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    renderAt("/colleges/colleges");
    await screen.findByText("1 college · operational");
    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    expect(create).toHaveBeenCalled();
    expect(click).toHaveBeenCalled();
    const text = await new Promise<string>((res) => {
      const fr = new FileReader();
      fr.onload = () => res(String(fr.result));
      fr.readAsText(blobs[0]!);
    });
    expect(text).toContain("S.No,College,Short name,District");
    expect(text).toContain("'=HYPERLINK(1)");
    expect(text).toContain(",10,4,6,40,on track,");
    expect(await screen.findByText("Exported 1 college")).toBeInTheDocument();
  });
});

describe("csv", () => {
  it("quotes and neutralises formulas", () => {
    expect(csvCell("=1+1")).toBe("'=1+1");
    expect(csvCell("-5")).toBe("'-5");
    expect(csvCell(-5)).toBe("-5");
    expect(csvCell('a,"b"')).toBe('"a,""b"""');
    expect(csvCell(null)).toBe("");
    expect(csvText([["a", 1]])).toBe("﻿a,1");
  });
});

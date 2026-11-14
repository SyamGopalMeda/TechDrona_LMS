import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { resetDialogsForTests } from "../forms/host";
import { addDays } from "../forms/util";
import { configurePortalApi, resetPortalApiForTests } from "../lib/api";
import { clearPortalCacheForTests } from "../lib/cache";
import { today } from "../lib/fmt";
import { PortalUiProvider } from "../ui/context";
import { OverlayHost, resetOverlaysForTests } from "../ui/Overlay";
import { FormsHost } from "../forms/host";
import { AuditLog, changedFields } from "./AuditLog";
import { CallQueue } from "./CallQueue";
import { DataQuality } from "./DataQuality";
import { Followups } from "./Followups";
import { Settings } from "./Settings";

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
type Route = (method: string, path: string, url: URL, body: unknown) => Response | undefined;
function mockApi(route: Route) {
  const calls: { method: string; path: string; url: URL; body: unknown }[] = [];
  const fetchImpl = vi.fn(async (u: string, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const url = new URL(u, "http://x");
    const path = url.pathname.replace(/^\/college-portal\/api\//, "");
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, path, url, body });
    return route(method, path, url, body) ?? (method === "GET" ? json(200, []) : json(404, { error: "not found" }));
  });
  configurePortalApi({ fetchImpl: fetchImpl as unknown as typeof fetch, onSignedOut: () => undefined, onScopeRejected: () => undefined, onNetwork: () => undefined });
  return calls;
}
function mount(node: React.ReactNode, at = "/colleges", over: { canWrite?: boolean } = {}) {
  return render(
    <MemoryRouter initialEntries={[at]}>
      <PortalUiProvider value={{ overlayRoot: document.body, form: "desktop", coarse: false, canWrite: over.canWrite ?? true }}>
        {node}
        <FormsHost />
        <OverlayHost />
      </PortalUiProvider>
    </MemoryRouter>,
  );
}

afterEach(() => {
  act(() => {
    resetDialogsForTests();
    resetOverlaysForTests();
  });
  clearPortalCacheForTests();
  resetPortalApiForTests();
  try {
    sessionStorage.clear();
  } catch {
    /* ignore */
  }
});

const META = { districts: [{ id: "guntur", name: "Guntur" }], cities: [], courses: [{ id: 1, name: "Full-Stack", price_inr: 5000, active: 1 }], settings: { state_target_deadline: "2027-03-31", min_conversion: 0.05 }, counts: {}, demo: false };

/* ------------------------------------------------------------------ call queue */

const QROW = (id: string, extra: Record<string, unknown> = {}) => ({
  college_id: id,
  name: `College ${id}`,
  short_name: id.toUpperCase(),
  district_id: "guntur",
  district_name: "Guntur",
  call_status: "not_called",
  op_status: "operational",
  best_contact: { id: 1, name: "Dr Rao", role: "principal", phone: "+919876543210", status: "working", basis: "verified" },
  contact_counts: { total: 1 },
  priority: { score: 72, tier: "high", parts: [{ key: "potential", label: "Students", points: 30, max: 35, detail: "Many eligible students", estimated: true }] },
  ...extra,
});

describe("Call queue", () => {
  it("lists colleges, filters by chip and explains the priority", async () => {
    const calls = mockApi((m, path, url) => {
      if (path === "calls/queue") {
        const f = url.searchParams.get("filter");
        return json(200, { rows: f === "pending" ? [QROW("c2")] : [QROW("c1", { last_call: { outcome: "busy", called_at: "2026-11-10", caller: "Asha" }, calls_total: 2 }), QROW("c2")], counts: { all: 2, pending: 1 }, districts_filter: ["guntur"] });
      }
      if (path === "target-dashboard") return json(200, { calls: { today: 3, last_7d: 9 }, contacts: { working: 4, untested: 2, non_working: 1, invalid: 1 }, pending_calls: { callbacks_due: 1, callbacks_scheduled: 5, never_called: 7 } });
      return undefined;
    });
    mount(<CallQueue />, "/colleges/calls");
    expect(await screen.findByRole("link", { name: "C1" })).toBeInTheDocument();
    expect(screen.getByText("Colleges not called yet")).toBeInTheDocument();
    expect(screen.getByText("2 not tried yet · 2 not working")).toBeInTheDocument();
    expect(screen.getAllByText("Not called yet").length).toBeGreaterThan(0);
    expect(screen.getByText("Line busy")).toBeInTheDocument();
    expect(screen.getByText(/10 Nov 2026 · Asha · 2 calls/)).toBeInTheDocument();
    expect(screen.getAllByText("Students")[0]).toBeInTheDocument();
    expect(screen.getAllByText(/It only decides the order of this list/)[0]).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Log call" }).length).toBe(2);
    fireEvent.click(screen.getByRole("button", { name: "To call (1)" }));
    await waitFor(() => expect(screen.queryByRole("link", { name: "C1" })).toBeNull());
    expect(calls.some((c) => c.path === "calls/queue" && c.url.searchParams.get("filter") === "pending")).toBe(true);
  });

  it("hides Log call for view-only sessions", async () => {
    mockApi((m, path) => (path === "calls/queue" ? json(200, { rows: [QROW("c1")], counts: {} }) : undefined));
    mount(<CallQueue />, "/colleges/calls", { canWrite: false });
    expect(await screen.findByRole("link", { name: "C1" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Log call" })).toBeNull();
  });
});

/* ------------------------------------------------------------------ follow-ups */

const FU = (id: number, extra: Record<string, unknown>) => ({
  id,
  scope_type: "college",
  scope_id: "c1",
  college_id: "c1",
  district_id: "guntur",
  owner_person_id: null,
  owner_name: "Asha",
  status: "open",
  issue: "other",
  title: `Task ${id}`,
  notes: null,
  last_contact: null,
  created_at: "",
  created_by: "",
  done_at: null,
  ...extra,
});

describe("Follow-ups", () => {
  const routes: Route = (m, path) => {
    if (path === "followups")
      return json(200, [
        FU(1, { due_date: addDays(today(), -3), title: "Call back C1" }),
        FU(2, { due_date: today(), issue: "ambassador_gap" }),
        FU(3, { due_date: addDays(today(), 5), owner_name: null }),
        FU(4, { status: "done", due_date: addDays(today(), -9), done_at: `${today()}T10:00:00Z`, last_contact: today() }),
      ]);
    if (path === "colleges") return json(200, [{ id: "c1", name: "College One", short_name: "C1", district_id: "guntur", targeted: 1 }, { id: "c2", name: "College Two", short_name: "C2", district_id: "guntur", targeted: 1, next_followup: null }]);
    if (path === "people") return json(200, { items: [], total: 0 });
    if (path === "meta") return json(200, META);
    return undefined;
  };

  it("opens on Overdue, shows reasons, assigned-to and the unscheduled colleges", async () => {
    mockApi(routes);
    mount(<Followups />, "/colleges/followups");
    expect(await screen.findByText("Call back C1")).toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Which follow-ups" })).getByRole("button", { name: /Overdue/, pressed: true })).toBeInTheDocument();
    expect(screen.getAllByText("Call-back").some((e) => e.classList.contains("td-badge"))).toBe(true);
    expect(screen.getByText(/Overdue 3d/)).toBeInTheDocument();
    expect(screen.getByText("Last spoke to them")).toBeInTheDocument();
    expect(screen.getByText("Targeted colleges with nothing scheduled (1)")).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("group", { name: "Which follow-ups" })).getByRole("button", { name: /^Next 14 days/ }));
    expect(await screen.findByText("Task 3")).toBeInTheDocument();
    expect(screen.getAllByText("Not assigned").some((e) => e.tagName === "EM")).toBe(true);
    expect(screen.getAllByText("No ambassador").some((e) => e.classList.contains("td-badge"))).toBe(true);
  });

  it("filters by the Call-back reason from the URL and hides the duplicate column on Done", async () => {
    mockApi(routes);
    mount(<Followups />, "/colleges/followups?tab=open&issue=callback");
    expect(await screen.findByText("Call back C1")).toBeInTheDocument();
    expect(screen.queryByText("Task 2")).toBeNull();
  });

  it("Done tab: Reopen / Edit actions, no 'Last spoke to them' column", async () => {
    mockApi(routes);
    mount(<Followups />, "/colleges/followups?tab=done");
    expect(await screen.findByText("Task 4")).toBeInTheDocument();
    expect(screen.getByText("Done on")).toBeInTheDocument();
    expect(screen.queryByText("Last spoke to them")).toBeNull();
    expect(screen.getByRole("button", { name: "Reopen" })).toBeInTheDocument();
  });
});

/* ------------------------------------------------------------------ audit log */

const AUDIT = [
  { id: 9, at: "2026-11-12T09:30:00Z", actor: "Asha (asha@x.in)", action: "update", entity: "call", entity_id: "77", before: JSON.stringify({ outcome: "busy", next_action_at: null, college_id: "c1" }), after: JSON.stringify({ outcome: "connected_interested", next_action_at: "2026-11-15", college_id: "c1", updated_at: "x" }) },
  { id: 8, at: "2026-11-11T09:30:00Z", actor: "Ravi", action: "create", entity: "college", entity_id: "c6", before: null, after: { name: "New College" } },
];

describe("Audit log", () => {
  it("labels changed fields, opens the details and keeps raw data for ?dev=1", async () => {
    const calls = mockApi((m, path) => (path === "audit" ? json(200, AUDIT) : path === "audit/actors" ? json(200, ["Asha (asha@x.in)", "Ravi"]) : undefined));
    mount(<AuditLog />, "/colleges/audit?entity=calls");
    expect(await screen.findByText("What happened, Call back on")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New College" })).toHaveAttribute("href", "/colleges/college/c6");
    expect(calls.find((c) => c.path === "audit")!.url.searchParams.get("entity")).toBe("call");
    // record ids only show when a link set one
    expect(screen.queryByLabelText("Record reference")).toBeNull();
    fireEvent.click(screen.getByText("What happened, Call back on"));
    const drawer = await screen.findByRole("dialog", { name: "Change details" });
    expect(within(drawer).getByText("Only the 2 changed fields")).toBeInTheDocument();
    expect(within(drawer).getByText("15 Nov 2026")).toBeInTheDocument();
    expect(within(drawer).queryByText("Show raw data")).toBeNull();
    expect(changedFields({ before: { a: 1, updated_at: 1 }, after: { a: 2, updated_at: 2 } })).toEqual(["a"]);
  });

  it("shows the record box when set and the raw toggle in dev mode", async () => {
    sessionStorage.setItem("td.dev", "1");
    mockApi((m, path) => (path === "audit" ? json(200, AUDIT) : path === "audit/actors" ? json(200, []) : undefined));
    mount(<AuditLog />, "/colleges/audit?entity_id=77");
    expect(await screen.findByLabelText("Record reference")).toHaveValue("77");
    fireEvent.click(await screen.findByText("What happened, Call back on"));
    const drawer = await screen.findByRole("dialog", { name: "Change details" });
    expect(within(drawer).getByText("Show raw data")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeInTheDocument();
  });
});

/* ------------------------------------------------------------------ data quality */

describe("Data quality", () => {
  const routes: Route = (m, path, url) => {
    if (path === "quality") return json(200, { missing: [{ field: "phone", label: "Phone", count: 1, college_ids: ["c1"] }, { field: "op_status", count: 1, college_ids: ["c2"] }], basis_counts: { verified: 3, estimated: 1, pending: 0 } });
    if (path === "colleges") return json(200, [{ id: "c1", name: "College One", short_name: "C1", district_id: "guntur", targeted: 1, data_status: "unverified", lat: 1, lng: 2 }, { id: "c2", name: "College Two", district_id: "guntur", data_status: "verified", op_status: "possibly_closed", lat: null, lng: null }]);
    if (path === "meta") return json(200, META);
    if (path === "colleges/c1") return json(200, { college: { id: "c1", name: "College One", phone: "123", field_status: { name: "verified", phone: "unverified", email: "missing" }, verified_fields: { name: { verified_on: "2026-11-01", verified_by: "Asha" } } } });
    if (path === "colleges/c2") return json(200, { college: { id: "c2", op_status_note: "Website down" } });
    if (path === "contacts") return json(200, url.searchParams.get("basis") === "pending" ? [{ id: 5, college_id: "c1", college_label: "C1", district_id: "guntur", name: "Dr Rao", role: "principal", phone: "+919876543210", basis: "pending" }] : []);
    return undefined;
  };

  it("shows the verification queue with field chips and the renamed KPIs", async () => {
    mockApi(routes);
    mount(<DataQuality />, "/colleges/data");
    expect(await screen.findByText("Colleges fully verified")).toBeInTheDocument();
    expect(screen.getByText("Verified student figures")).toBeInTheDocument();
    expect(screen.getByText("Still open? To confirm")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /To verify/ })).toBeInTheDocument();
    expect(await screen.findByText("not verified")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Mark verified" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Contact numbers" }));
    expect(await screen.findByText("Dr Rao")).toBeInTheDocument();
    expect(screen.getByText("Principal")).toBeInTheDocument();
  });

  it("lists gaps and the downloads", async () => {
    mockApi(routes);
    mount(<DataQuality />, "/colleges/data?tab=gaps");
    expect(await screen.findByText("How reliable are our numbers?")).toBeInTheDocument();
    expect(screen.getByText("Is the college still operating? (1)")).toBeInTheDocument();
    expect(await screen.findByText("Website down")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "C1" }).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("tab", { name: "Download" }));
    expect(await screen.findByRole("button", { name: "Colleges in view (2)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download backup" })).toBeInTheDocument();
    expect(screen.queryByText(/Research data/)).toBeNull();
  });
});

/* ------------------------------------------------------------------ settings */

describe("Settings", () => {
  it("shows the LMS account (no passcode / sign-out) and saves the alert settings", async () => {
    const calls = mockApi((m, path) => {
      if (path === "meta") return json(200, META);
      if (path === "program") return json(200, { target: 500, deadline: "2027-03-31", target_district_groups: { Guntur: ["guntur"] }, target_district_ids: ["guntur"], districts: [{ id: "guntur", name: "Guntur" }] });
      if (path === "session") return json(200, { user: "Asha (asha@x.in)", role: "editor", sso: true, required: true, authenticated: true, expires_at: null });
      if (m === "PATCH" && path === "settings") return json(200, {});
      return undefined;
    });
    mount(<Settings />, "/colleges/settings");
    expect(await screen.findByRole("heading", { name: "Your account" })).toBeInTheDocument();
    expect(await screen.findByText("Asha (asha@x.in)")).toBeInTheDocument();
    expect(screen.queryByText(/passcode/i)).toBeNull();
    expect(screen.queryByRole("button", { name: "Sign out" })).toBeNull();
    expect(screen.queryByText("Organisation name")).toBeNull();
    expect(screen.getByLabelText('Unanswered calls before a number is "Not working"')).toHaveValue(6);
    expect(screen.getByLabelText("Low-conversion alert (%)")).toHaveValue(5);
    expect(screen.getByLabelText("Computer science")).toHaveValue(1);
    const alerts = screen.getByLabelText('Unanswered calls before a number is "Not working"').closest(".ad-stack") as HTMLElement;
    fireEvent.change(screen.getByLabelText('Unanswered calls before a number is "Not working"'), { target: { value: "8" } });
    fireEvent.click(within(alerts).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(calls.find((c) => c.method === "PATCH")!.body).toEqual({ state_target_deadline: "2027-03-31", min_conversion: 0.05, unreachable_after_attempts: 8 });
    fireEvent.change(screen.getByLabelText('Unanswered calls before a number is "Not working"'), { target: { value: "51" } });
    fireEvent.click(within(alerts).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Unanswered calls: use a whole number from 0 to 50.")).toBeInTheDocument();
  });
});

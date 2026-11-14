import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { csvSink } from "../lib/download";
import { CaseDetail as CaseDetailPage } from "./CaseDetail";
import { HistoryTab, NotesTab } from "./EvidenceTabs";
import { EngineControls } from "./EngineControls";
import { Incidents } from "./Incidents";
import { MyExports } from "./MyExports";
import { ExportRequest, ReportView } from "./Reports";
import { BulkLift, Restrictions } from "./Restrictions";
import { RuleVersions } from "./RuleVersions";
import { SecurityDashboard } from "./SecurityDashboard";
import { UserTimelinePage } from "./UserTimelinePage";
import type { CaseDetail } from "../lib/types";
import { istLocalToIso } from "@/lib/time";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

/** FE-24 pattern: paste instead of key-by-key typing. */
async function fill(el: HTMLElement, text: string) {
  await userEvent.click(el);
  await userEvent.paste(text);
}

const cleanups: (() => void)[] = [];
afterEach(() => {
  while (cleanups.length) cleanups.pop()!();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  sessionStorage.clear();
});

const inHours = (h: number) => new Date(Date.now() + h * 3_600_000).toISOString();
const UID = "0192f0a0-0000-7000-8000-000000000001";

// Shape of api_engine.py _export_out.
const job = (over: Record<string, unknown> = {}) => ({
  export_job_id: "e1",
  report_key: "blocked-accounts",
  report_id: "H5",
  status: "completed",
  contains_pii: true,
  row_count: 12,
  approval_request_id: "ap1",
  created_at: inHours(-2),
  completed_at: inHours(-1),
  download_expires_at: inHours(23),
  download_path: "/security/reports/exports/e1",
  ...over,
});

const catalogue = {
  data: [
    { report_key: "device-login-history", id: "H12", title: "Device and login history", per_user: true, accessible: true, export_approval: "security.export.per_user", filters: ["from", "to", "user_id"] },
    { report_key: "engine-health", id: "ENG", title: "Policy and engine health", per_user: false, accessible: true, export_approval: "step_up_only", filters: [] },
    { report_key: "false-positive-rate", id: "H8", title: "False-positive rate", per_user: false, accessible: true, export_approval: "step_up_only", filters: ["from", "to"] },
  ],
};

describe("My exports (ADM-05 / INV-11)", () => {
  it("lists the caller's exports and downloads a completed CSV through the same-origin api", async () => {
    const api = mockApi({
      "GET security/reports/exports": { body: { data: [job(), job({ export_job_id: "e2", status: "awaiting_approval", completed_at: null, download_expires_at: null, download_path: null })] } },
      "GET security/reports/exports/e1": { raw: "a,b\n1,2\n", headers: { "content-type": "text/csv", "content-disposition": 'attachment; filename="blocked-accounts-e1.csv"' } },
    });
    cleanups.push(api.restore);
    const save = vi.spyOn(csvSink, "save").mockImplementation(() => undefined);

    renderWithProviders(<MyExports tracked={[]} />);
    expect(await screen.findByText("#E1")).toBeInTheDocument();
    expect(screen.getByText("Awaiting approval")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Download export #E2" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Download export #E1" }));
    await waitFor(() => expect(save).toHaveBeenCalledWith("blocked-accounts-e1.csv", "a,b\n1,2\n"));
    expect(api.calls.find((c) => c.path === "security/reports/exports/e1")?.headers.accept).toContain("text/csv");
  });

  it("without a list endpoint keeps just-requested jobs visible and reports their state from the 409", async () => {
    const api = mockApi({
      "GET security/reports/exports": { status: 405, body: { type: "x", title: "Method not allowed", status: 405, detail: "", code: "method_not_allowed", request_id: "r" } },
      "GET security/reports/exports/e9": { status: 409, body: { type: "x", title: "Invalid state", status: 409, detail: "", code: "invalid_state_transition", request_id: "r", current_state: "awaiting_approval" } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<MyExports tracked={[{ export_job_id: "e9", report_key: "blocked-accounts" }]} />);
    expect(await screen.findByText(/export list is not available/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Download export #E9" }));
    expect(await screen.findByText("Awaiting approval")).toBeInTheDocument();
  });

  it("a completed (aggregate) export points at My exports, not at a notification", async () => {
    const api = mockApi({ "POST security/reports/engine-health/exports": { status: 202, body: { export_job_id: "e5", status: "completed", approval_request_id: null, contains_pii: false } } });
    cleanups.push(api.restore);
    const onRequested = vi.fn();
    renderWithProviders(<ExportRequest reportKey="engine-health" perUserAllowed={false} filters={{}} onRequested={onRequested} />);
    await userEvent.click(screen.getByRole("button", { name: "Request export" }));
    expect(await screen.findByText(/Download it from My exports below/)).toBeInTheDocument();
    expect(screen.queryByText(/You will be notified/)).not.toBeInTheDocument();
    expect(onRequested).toHaveBeenCalledWith({ export_job_id: "e5", report_key: "engine-health" });
  });
});

describe("Report filters and secondary data (ADM-06 / ADM-07)", () => {
  it("H12 waits for a user id, then sends user_id and the 'to' date", async () => {
    const api = mockApi({
      "GET security/reports": { body: catalogue },
      "GET security/reports/exports": { body: { data: [] } },
      "GET security/reports/device-login-history": {
        body: { report_key: "device-login-history", report_id: "H12", title: "Device and login history", generated_at: inHours(0), period: { from: inHours(-24), to: inHours(0), timezone: "Asia/Kolkata" }, rows: [{ at: inHours(-1), type: "login", outcome: "success" }], user_id: UID },
      },
    });
    cleanups.push(api.restore);
    renderWithProviders(<ReportView reportKey="device-login-history" />);
    expect(await screen.findByText(/Enter user id and apply the filters/)).toBeInTheDocument();
    expect(api.calls.some((c) => c.path === "security/reports/device-login-history")).toBe(false);

    await fill(screen.getByLabelText(/^User id/), UID);
    fireEvent.change(screen.getByLabelText(/^To/), { target: { value: "2026-11-02" } });
    await userEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    expect(await screen.findByText("success")).toBeInTheDocument();
    const call = api.calls.find((c) => c.path === "security/reports/device-login-history")!;
    const qs = new URL(call.url, "http://x").searchParams;
    expect(qs.get("user_id")).toBe(UID);
    expect(qs.get("to")).toBe("2026-11-02");
    expect(qs.get("reason_code")).toBe("case_review");
    expect(qs.get("from")).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("ENG renders its data although rows is empty; H8 shows breakers and alerts", async () => {
    const api = mockApi({
      "GET security/reports": { body: catalogue },
      "GET security/reports/exports": { body: { data: [] } },
      "GET security/reports/engine-health": {
        body: { report_key: "engine-health", report_id: "ENG", title: "Policy and engine health", generated_at: inHours(0), period: { from: inHours(-720), to: inHours(0), timezone: "Asia/Kolkata" }, rows: [], level_distribution: { "3": 7 }, hc: { shadow_matches: 4, enforced: 2 }, signal_volumes: { "SH-01": 31 }, login_failures_10min: 5 },
      },
    });
    cleanups.push(api.restore);
    renderWithProviders(<ReportView reportKey="engine-health" />);
    expect(await screen.findByText("Login failures 10min")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Signal volumes" })).toBeInTheDocument();
    expect(screen.getByText("SH 01")).toBeInTheDocument();
    expect(screen.getByText("31")).toBeInTheDocument();
    expect(screen.getByText("Shadow matches")).toBeInTheDocument();
  });

  it("H8 alerts and circuit breakers are visible", async () => {
    const api = mockApi({
      "GET security/reports": { body: catalogue },
      "GET security/reports/exports": { body: { data: [] } },
      "GET security/reports/false-positive-rate": {
        body: {
          report_key: "false-positive-rate",
          report_id: "H8",
          title: "False-positive rate",
          generated_at: inHours(0),
          period: { from: inHours(-720), to: inHours(0), timezone: "Asia/Kolkata" },
          rows: [],
          circuit_breakers: { "HC-01": "open", "HC-02": "closed" },
          alerts: [{ alert: "rule_fp_cases_per_week_above_3", key: "SH-01", week: "2026-W44", false_positives: 4 }],
        },
      },
    });
    cleanups.push(api.restore);
    renderWithProviders(<ReportView reportKey="false-positive-rate" />);
    expect(await screen.findByText("More than 3 false-positive cases for one rule in a week")).toBeInTheDocument();
    expect(screen.queryByText("rule_fp_cases_per_week_above_3")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Circuit breakers" })).toBeInTheDocument();
    expect(screen.getByText("open")).toBeInTheDocument();
  });
});

describe("Section H filters and secondary data (w3web: ADM-06/07)", () => {
  const envelope = (key: string, id: string, extra: Record<string, unknown>) => ({ report_key: key, report_id: id, title: key, generated_at: inHours(0), period: { from: inHours(-720), to: inHours(0), timezone: "Asia/Kolkata" }, rows: [], ...extra });

  it("My exports downloads from the job's download_path and hides expired jobs' download", async () => {
    const api = mockApi({
      "GET security/reports/exports": { body: { data: [job({ export_job_id: "e3", download_path: "/security/reports/exports/e3?part=1" }), job({ export_job_id: "e4", status: "expired", download_path: null })] } },
      "GET security/reports/exports/e3": { raw: "a,b", headers: { "content-type": "text/csv" } },
    });
    cleanups.push(api.restore);
    vi.spyOn(csvSink, "save").mockImplementation(() => undefined);
    renderWithProviders(<MyExports tracked={[]} />);
    await userEvent.click(await screen.findByRole("button", { name: "Download export #E3" }));
    await waitFor(() => expect(api.calls.some((c) => c.path === "security/reports/exports/e3")).toBe(true));
    expect(api.calls.find((c) => c.path === "security/reports/exports/e3")?.url).toBe("/api/v1/security/reports/exports/e3?part=1");
    expect(screen.queryByRole("button", { name: "Download export #E4" })).not.toBeInTheDocument();
  });

  it("H10 shows sessions per user (suppressed cells as <k) and the students at the cap", async () => {
    const api = mockApi({
      "GET security/reports": { body: { data: [{ report_key: "active-session-counts", id: "H10", title: "Active-session counts", per_user: false, accessible: true, export_approval: "step_up_only", filters: ["tier", "client_type"] }] } },
      "GET security/reports/exports": { body: { data: [] } },
      "GET security/reports/active-session-counts": { body: envelope("active-session-counts", "H10", { k_min: 5, student_sessions_per_user: { "1": 120, "2": null }, students_at_session_cap: null, student_session_cap: 2 }) },
    });
    cleanups.push(api.restore);
    renderWithProviders(<ReportView reportKey="active-session-counts" />);
    const table = await screen.findByRole("table", { name: "Active student sessions per user" });
    expect(within(table).getByText("120")).toBeInTheDocument();
    expect(within(table).getByText("Hidden (small group)")).toBeInTheDocument();
    expect(screen.getByText("Students at the session cap")).toBeInTheDocument();
    expect(screen.getByText("Student session cap")).toBeInTheDocument();
  });

  it("H11 shows its granularity and platform scope", async () => {
    const api = mockApi({
      "GET security/reports": { body: { data: [] } },
      "GET security/reports/exports": { body: { data: [] } },
      "GET security/reports/learning-activity": { body: envelope("learning-activity", "H11", { granularity: "week", scope: "platform", k_min: 5, available: true }) },
    });
    cleanups.push(api.restore);
    renderWithProviders(<ReportView reportKey="learning-activity" />);
    expect(await screen.findByText("Granularity")).toBeInTheDocument();
    const details = screen.getByText("Scope").closest("section, div[class*='rounded']") as HTMLElement;
    expect(within(details).getByText("Week")).toBeInTheDocument();
    expect(screen.getByText("Whole platform")).toBeInTheDocument();
  });

  it("H12 shows the api's 422 user_id error on the User id filter", async () => {
    const api = mockApi({
      "GET security/reports": { body: catalogue },
      "GET security/reports/exports": { body: { data: [] } },
      "GET security/reports/device-login-history": problem(422, "validation_failed", "Validation failed", { errors: [{ field: "user_id", code: "not_found", message: "No such user" }] }),
    });
    cleanups.push(api.restore);
    renderWithProviders(<ReportView reportKey="device-login-history" />);
    await screen.findByText(/Enter user id/);
    await fill(screen.getByLabelText(/^User id/), UID);
    await userEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    expect(await screen.findByText("No such user")).toBeInTheDocument();
  });
});

describe("Security dashboard (INV-11 / SEC-40)", () => {
  it("shows tiles from GET /security/dashboard and links incidents", async () => {
    const api = mockApi({
      "GET security/dashboard": { body: { queue: { open: 4, under_review: 2 }, restrictions: { L3: 5, L1: 1 }, pending_unblock_requests: 3, engine: {} } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<SecurityDashboard />);
    expect(await screen.findByText("Pending unblock requests")).toBeInTheDocument();
    expect(screen.getByText("Under review")).toBeInTheDocument();
    expect(screen.getByText("Temporarily restricted (L3)")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open\s*4/ })).toHaveAttribute("href", "/security/cases?status=open");
    expect(screen.getByRole("link", { name: "Incidents" })).toHaveAttribute("href", "/security/incidents");
  });

  it("shows an error state when the dashboard cannot load", async () => {
    const api = mockApi({ "GET security/dashboard": problem(500, "internal_error", "Server error") });
    cleanups.push(api.restore);
    renderWithProviders(<SecurityDashboard />);
    expect(await screen.findByText("Could not load the dashboard")).toBeInTheDocument();
  });
});

describe("Incidents and bulk-lift status (ADM-11)", () => {
  it("opens an incident and updates it with If-Match", async () => {
    const inc = { incident_id: "i1", incident_ref: "INC-1", title: "Leaked token", severity: "high", status: "detected", detected_at: inHours(-1), certin_due_at: inHours(5), certin_reported_at: null, dpb_report_due_at: null, version: 3 };
    const api = mockApi({
      "GET security/incidents": { body: { data: [inc] } },
      "POST security/incidents": { status: 201, body: { ...inc, incident_id: "i2", incident_ref: "INC-2" } },
      "PATCH security/incidents/i1": { body: { ...inc, status: "triaged", version: 4 } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<Incidents />);
    expect(await screen.findByText("INC-1")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Open incident" }));
    let dialog = await screen.findByRole("dialog");
    await fill(within(dialog).getByLabelText(/^Title/), "Credential stuffing");
    await userEvent.click(within(dialog).getByRole("checkbox", { name: /CERT-In reportable/ }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Open incident" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    expect(api.calls.find((c) => c.method === "POST")!.body).toMatchObject({ title: "Credential stuffing", severity: "medium", certin_reportable: true, is_personal_data_breach: false });

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "Update INC-1" }));
    dialog = await screen.findByRole("dialog");
    await userEvent.selectOptions(within(dialog).getByLabelText(/^Status/), "triaged");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "PATCH")).toBe(true));
    const patch = api.calls.find((c) => c.method === "PATCH")!;
    expect(patch.headers["if-match"]).toBe('"v3"');
    expect(patch.body).toEqual({ status: "triaged" });
  });

  it("shows the bulk-lift status after the dual-approval request", async () => {
    const api = mockApi({
      "POST security/restrictions/bulk-lift-requests": (c) =>
        (c.body as { dry_run: boolean }).dry_run
          ? { body: { matched: 2, excluded_by_reason: {}, sample: [] } }
          : { status: 202, body: { status: "approval_pending", approval_request_id: "bl-apr", action_type: "security.restriction.bulk_lift", required_approver_role: "security_reviewer", expires_at: inHours(72), bulk_lift_id: "bl1", matched: 2 } },
      "GET security/restrictions/bulk-lift-requests/bl1": { body: { bulk_lift_id: "bl1", status: "awaiting_approval", selector: { rule_key: "HC-01" }, matched: 2, progress: {}, approval_request_id: "bl-apr" } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<BulkLift />);
    await fill(screen.getByLabelText("Rule key"), "HC-01");
    await fill(screen.getByLabelText(/^Reason/), "HC-01 false-positive surge on 2 Nov");
    await userEvent.click(screen.getByRole("button", { name: "Check matches (dry run)" }));
    await userEvent.click(await screen.findByRole("button", { name: "Request bulk lift" }));
    expect(await screen.findByText("Awaiting approval")).toBeInTheDocument();
    expect(screen.getByLabelText("Bulk lift id")).toHaveValue("bl1");
  });
});

describe("Case history: previous incidents (ADM-11)", () => {
  it("lists the subject's other cases from the audited timeline instead of 'Not available yet'", async () => {
    const api = mockApi({
      "GET security/users/u1/timeline": {
        body: {
          subject: { user_id: "u1", is_minor: false },
          events: [
            { at: inHours(-2), type: "case", event: "opened", case_ref: "SEC-NOW", opened_reason: "engine" },
            { at: inHours(-500), type: "case", event: "decision", case_ref: "SEC-OLD", outcome: "uphold" },
            { at: inHours(-600), type: "case", event: "opened", case_ref: "SEC-OLD", opened_reason: "engine" },
          ],
          page: { next_cursor: null, has_more: false },
        },
      },
    });
    cleanups.push(api.restore);
    const detail = { case_ref: "SEC-NOW", repeat_count: 1, decisions: [] } as unknown as CaseDetail;
    renderWithProviders(<HistoryTab detail={detail} userId="u1" ctx={{ reasonCode: "case_review", caseRef: "SEC-NOW" }} />);
    expect(await screen.findByText("SEC-OLD")).toBeInTheDocument();
    expect(screen.queryByText("SEC-NOW")).not.toBeInTheDocument();
    expect(screen.queryByText(/Not available yet/)).not.toBeInTheDocument();
    const call = api.calls[0]!;
    expect(call.url).toContain("types=case");
    expect(call.url).not.toContain("case_ref=");
  });
});

describe("Confirmations before irreversible actions (audit 0.7)", () => {
  const draft = { version_id: "v1", rule_key: "SH-01", family: "sharing", ruleset_version: null, semver: "1.2.0", status: "draft", definition: {}, shadow_started_at: null, eligible_at: null, proposed_by: "u1", approved_by: null, status_change_reason: null };

  it("explains the 14-day shadow before starting it", async () => {
    const api = mockApi({
      "GET security/rule-versions": { body: { data: [draft], page: { next_cursor: null, has_more: false, limit: 25 } } },
      "POST security/rule-versions/v1/start-shadow": { body: { ...draft, status: "shadow" } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<RuleVersions />);
    await userEvent.click((await screen.findAllByRole("button", { name: "Start shadow" }))[0]!);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/14 days/)).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.click(within(dialog).getByRole("button", { name: "Start shadow" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.path === "security/rule-versions/v1/start-shadow")).toBe(true));
  });

  it("asks before posting a student-visible case note, but not an internal one", async () => {
    const api = mockApi({ "POST security/cases/c1/notes": { status: 201, body: {} } });
    cleanups.push(api.restore);
    const onAdded = vi.fn();
    renderWithProviders(<NotesTab caseId="c1" notes={[]} onAdded={onAdded} />);
    await userEvent.selectOptions(screen.getByLabelText("Visibility"), "student");
    await fill(screen.getByLabelText(/^Note/), "Please re-take the test on one device.");
    await userEvent.click(screen.getByRole("button", { name: "Add note for student" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Please re-take the test on one device.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.click(within(dialog).getByRole("button", { name: "Back to editing" }));
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Add note for student" }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Add visible note" }));
    await waitFor(() => expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ visibility: "student", body: "Please re-take the test on one device." }));
    expect(onAdded).toHaveBeenCalled();

    await userEvent.selectOptions(screen.getByLabelText("Visibility"), "internal");
    await fill(screen.getByLabelText(/^Note/), "Internal only");
    await userEvent.click(screen.getByRole("button", { name: "Add note" }));
    await waitFor(() => expect(api.calls.filter((c) => c.method === "POST")).toHaveLength(2));
  });
});

describe("Phase 2 readability (codes, ids, layout)", () => {
  const engine = { "risk.mode": "shadow", "risk.hc.auto_restrict_enabled": true, rules: [], rulesets: {}, pending_ratifications: [] };

  it("engine strip uses words instead of config keys and keeps the kill switch secondary", async () => {
    const api = mockApi({ "GET security/engine/state": { body: engine } });
    cleanups.push(api.restore);
    renderWithProviders(<EngineControls />);
    expect(await screen.findByText("Watching only (shadow)")).toBeInTheDocument();
    expect(screen.getByText("Automatic restrictions")).toBeInTheDocument();
    expect(screen.queryByText("risk.mode")).not.toBeInTheDocument();
    expect(screen.queryByText(/HC auto-restrict/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Emergency stop/ })).toBeInTheDocument();
  });

  it("reports index and report view show titles and breadcrumbs, no H-codes", async () => {
    const api = mockApi({
      "GET security/reports": { body: { data: [] } },
      "GET security/reports/blocked-accounts": { body: { report_key: "blocked-accounts", report_id: "H5", title: "Blocked accounts", generated_at: inHours(0), period: { from: inHours(-24), to: inHours(0) }, filters_applied: {}, rows: [{ user_id: UID, rule_key: "HC-01" }] } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<ReportView reportKey="blocked-accounts" />);
    expect(screen.getByRole("heading", { level: 1, name: "Blocked accounts" })).toBeInTheDocument();
    expect(within(screen.getByRole("navigation", { name: "Breadcrumb" })).getByRole("link", { name: "Reports" })).toHaveAttribute("href", "/security/reports");
    expect(await screen.findByRole("columnheader", { name: "Rule" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "User" })).toBeInTheDocument();
    expect(screen.queryByText("H5")).not.toBeInTheDocument();
    expect(screen.queryByText(/Report key/)).not.toBeInTheDocument();
  });

  it("restrictions name the account by short reference and say when a filter only covers this page", async () => {
    const api = mockApi({
      "GET security/restrictions": {
        body: { data: [{ restriction_id: "r1", user_id: UID, level: 2, family: "sharing", scope: "account", source: "hc_rule", hc_rule: "HC-01", starts_at: inHours(-5), ends_at: null, deferred_until: null, state: "active", case_id: null, case_ref: null, ended_at: null, end_reason: null }], page: { next_cursor: null, has_more: false } },
      },
    });
    cleanups.push(api.restore);
    renderWithProviders(<Restrictions />);
    expect(await screen.findByRole("link", { name: /Security timeline for user #00000001/ })).toHaveAttribute("href", `/security/users/${UID}/timeline`);
    expect(within(screen.getByRole("table")).getByText("High-confidence rule")).toBeInTheDocument();
    expect(screen.queryByText(UID)).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText(/^Family/), "takeover");
    expect(screen.getByText(/filter only the restrictions loaded on this page/)).toBeInTheDocument();
    expect(screen.getByText("No matches on this page")).toBeInTheDocument();
  });

  it("user timeline page never shows the raw user id", () => {
    renderWithProviders(<UserTimelinePage userId={UID} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("User #00000001");
    expect(screen.queryByText(new RegExp(UID))).not.toBeInTheDocument();
    expect(within(screen.getByRole("navigation", { name: "Breadcrumb" })).getByRole("link", { name: "Cases" })).toHaveAttribute("href", "/security/cases");
  });

  it("case gate shows where you are before the reason is chosen", () => {
    renderWithProviders(<CaseDetailPage caseId="c1" />);
    expect(screen.getByRole("heading", { level: 1, name: "Open case" })).toBeInTheDocument();
    expect(within(screen.getByRole("navigation", { name: "Breadcrumb" })).getByRole("link", { name: "Cases" })).toHaveAttribute("href", "/security/cases");
    expect(screen.getByRole("button", { name: "Open" })).toBeInTheDocument();
  });

  it("treats the rule activation time as IST", () => {
    expect(istLocalToIso("2026-11-10T09:30")).toBe("2026-11-10T04:00:00.000Z");
  });
});

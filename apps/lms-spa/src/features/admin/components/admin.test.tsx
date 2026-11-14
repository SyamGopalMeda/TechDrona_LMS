import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { formatINR } from "../lib/console";
import { actionTypeLabel, ApprovalsQueue, fallbackDecidePath } from "./ApprovalsQueue";
import { AdminDashboard, AuditLog, BreakGlass, FeatureFlags, parseIdList, RoleGrants, SystemStatus } from "./Governance";
import { UserDetail, UserDevices, UserSearch } from "./Users";
import { parseProposed, PolicySettings } from "./PolicySettings";
import { SECURITY_APPROVAL_TYPES } from "../lib/approval-types";
import { resetIntegrationsCache } from "@/components/shell/Integrations";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

const cleanups: (() => void)[] = [];
afterEach(() => {
  while (cleanups.length) cleanups.pop()!();
});
const page = { next_cursor: null, has_more: false, limit: 25 };
const inHours = (h: number) => new Date(Date.now() + h * 3_600_000).toISOString();

describe("ApprovalsQueue (ADM-010)", () => {
  const me = { user: { id: "me-id" } };
  const rows = [
    { approval_request_id: "a1", action_type: "policy.change", target_type: "policy_setting", target_id: null, status: "pending", requested_by: "u2", request_reason: "Exam season", required_approver_role: "super_admin", decided_by: null, decided_at: null, decision_note: null, expires_at: inHours(70), created_at: inHours(-2) },
    { approval_request_id: "a2", action_type: "export.bulk_pii", target_type: "user", target_id: "u7", status: "pending", requested_by: "me-id", request_reason: "Audit", required_approver_role: "super_admin", decided_by: null, decided_at: null, decision_note: null, expires_at: inHours(60), created_at: inHours(-1) },
  ];

  it("lets an approver approve (ADM-14 with Idempotency-Key) and hides decisions on own requests", async () => {
    const api = mockApi({ "GET admin/approvals": { body: { data: rows } }, "GET me": { body: me }, "POST admin/approvals/a1/approve": { body: { status: "executed" } } });
    cleanups.push(api.restore);
    renderWithProviders(<ApprovalsQueue />);
    expect(await screen.findByText("Exam season")).toBeInTheDocument();
    expect(await screen.findByText("You requested this, so another approver must decide.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Approve Bulk personal-data export/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Approve Change policy a1" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.path === "admin/approvals/a1/approve")).toBe(true));
    expect(api.calls.find((c) => c.method === "POST")!.headers["idempotency-key"]).toBeTruthy();
  });

  it("shows sod_violation inline", async () => {
    const api = mockApi({ "GET admin/approvals": { body: { data: rows } }, "GET me": { body: me }, "POST admin/approvals/a1/reject": problem(403, "sod_violation", "Not allowed", { detail: "You cannot decide this request." }) });
    cleanups.push(api.restore);
    renderWithProviders(<ApprovalsQueue />);
    await userEvent.click(await screen.findByRole("button", { name: "Send back Change policy a1" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Reason/), "Need more detail");
    await userEvent.click(within(dialog).getByRole("button", { name: "Send back" }));
    expect(await within(dialog).findByText("You cannot decide this request.")).toBeInTheDocument();
  });

  it("opens every decision dialog with an empty note, so a reason never carries to another action (audit 0.5)", async () => {
    const api = mockApi({ "GET admin/approvals": { body: { data: rows } }, "GET me": { body: me }, "POST admin/approvals/a1/approve": { body: { status: "executed" } } });
    cleanups.push(api.restore);
    renderWithProviders(<ApprovalsQueue />);
    await userEvent.click(await screen.findByRole("button", { name: "Send back Change policy a1" }));
    let dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Reason/), "Wrong numbers in the payload");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await userEvent.click(screen.getByRole("button", { name: "Approve Change policy a1" }));
    dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText(/Note/)).toHaveValue("");
    await userEvent.click(within(dialog).getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.path === "admin/approvals/a1/approve")).toBe(true));
    expect(JSON.stringify(api.calls.find((c) => c.method === "POST")!.body ?? {})).not.toContain("Wrong numbers");
  });

  it("labels the cancel-request dismiss button so it is not a second Cancel (audit 0.7)", async () => {
    const api = mockApi({ "GET admin/approvals": { body: { data: rows } }, "GET me": { body: me } });
    cleanups.push(api.restore);
    renderWithProviders(<ApprovalsQueue />);
    await userEvent.click(await screen.findByRole("button", { name: "Cancel request" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("button", { name: "Keep request" })).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  });

  it("shows rule-version activation and rollback requests in the security queue (audit 0.6)", async () => {
    expect(SECURITY_APPROVAL_TYPES).toEqual(expect.arrayContaining(["risk.ruleset.activate", "risk.ruleset.rollback"]));
    const sec = [
      { ...rows[0]!, approval_request_id: "r1", action_type: "risk.ruleset.activate", request_reason: "Shadow looks clean" },
      { ...rows[0]!, approval_request_id: "r2", action_type: "risk.ruleset.rollback", request_reason: "False positives spiked" },
      { ...rows[0]!, approval_request_id: "r3", action_type: "policy.change", request_reason: "Not a security type" },
    ];
    const api = mockApi({ "GET admin/approvals": { body: { data: sec } }, "GET me": { body: me } });
    cleanups.push(api.restore);
    renderWithProviders(<ApprovalsQueue title="Security approvals" actionTypes={[...SECURITY_APPROVAL_TYPES]} />);
    expect(await screen.findByText("Shadow looks clean")).toBeInTheDocument();
    expect(screen.getByText("False positives spiked")).toBeInTheDocument();
    expect(screen.queryByText("Not a security type")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve Activate rule version r1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve Roll back rule version r2" })).toBeInTheDocument();
  });
});

const settings = {
  data: [
    { setting_key: "devices.student.max_trusted", value: 3, default: 3, source: "default", version: 0, kind: "int", min_value: 1, max_value: 10, choices: null, plan_overridable: true, locked: false, pending_changes: [] },
    { setting_key: "devices.student.max_replacements_per_30d", value: 2, default: 2, source: "platform_row", version: 2, kind: "int", min_value: 0, max_value: 10, choices: null, plan_overridable: false, locked: false, pending_changes: ["p1"] },
    { setting_key: "risk.mode", value: "shadow", default: "shadow", source: "default", version: 0, kind: "enum", min_value: null, max_value: null, choices: ["off", "shadow", "enforce"], plan_overridable: false, locked: true, pending_changes: [] },
  ],
};

describe("PolicySettings (ADM-006)", () => {
  it("validates bounds client-side", () => {
    const s = settings.data[0] as never;
    expect(parseProposed(s, "11").error).toBe("Max 10");
    expect(parseProposed(s, "0").error).toBe("Min 1");
    expect(parseProposed(s, "2.5").error).toBe("Enter a whole number.");
    expect(parseProposed(s, "4").value).toBe(4);
    expect(parseProposed(settings.data[2] as never, "on").error).toMatch(/One of/);
  });

  it("shows pending/locked state, shadow mode and the ratification banner, and proposes a dual-approved change", async () => {
    const api = mockApi({
      "GET admin/policy-settings": { body: settings },
      "GET security/engine/state": { body: { "risk.mode": "shadow", pending_ratifications: [{ approval_request_id: "k1", due_at: inHours(10) }] } },
      "POST admin/policy-settings/devices.student.max_trusted/changes": { status: 202, body: { status: "approval_pending", approval_request_id: "pc1", action_type: "policy.change", required_approver_role: "super_admin", expires_at: inHours(72) } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<PolicySettings />);
    // Readable setting names, no raw keys, emoji or "∞" (Phase 2).
    expect(await screen.findByText("Trusted devices per student")).toBeInTheDocument();
    expect(screen.queryByText("devices.student.max_trusted")).not.toBeInTheDocument();
    expect(screen.getByText("Waiting for approval")).toBeInTheDocument();
    expect(await screen.findByText(/needs ratification/)).toBeInTheDocument();
    expect(screen.getByText(/Account security is watching only/)).toBeInTheDocument();
    expect(screen.queryByText(/risk\.mode/)).not.toBeInTheDocument();

    const input = screen.getByLabelText("Proposed value for Trusted devices per student");
    await userEvent.type(input, "11");
    expect(screen.getByText("Max 10")).toBeInTheDocument();
    const propose = screen.getByRole("button", { name: "Propose change to Trusted devices per student" });
    expect(propose).toBeDisabled();
    await userEvent.clear(input);
    await userEvent.type(input, "4");
    await userEvent.click(propose);
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Change reason/), "Exam season needs one more device");
    await userEvent.click(within(dialog).getByRole("button", { name: "Propose change" }));
    expect(await within(dialog).findByText("Waiting for a second approver")).toBeInTheDocument();
    const post = api.calls.find((c) => c.method === "POST")!;
    expect(post.body).toMatchObject({ scope_type: "platform", value: 4 });
    expect(post.headers["idempotency-key"]).toBeTruthy();
  });
});

const roles = [
  { role_key: "super_admin", name: "Super admin", session_tier: "privileged", mfa_required: true, allowed_scope_types: ["platform"], dual_control: true },
  // Folded into Admin (D2): hidden from the pickers even if the api still lists it.
  { role_key: "security_reviewer", name: "Security reviewer", session_tier: "privileged", mfa_required: true, allowed_scope_types: ["platform"], dual_control: true },
  { role_key: "trainer", name: "Trainer", session_tier: "staff", mfa_required: true, allowed_scope_types: ["batch", "course", "organization"], dual_control: false },
];

describe("Role grants and audit log", () => {
  it("privileged grants are requested for dual approval", async () => {
    const api = mockApi({
      "GET rbac/grants": { body: { data: [] } },
      "GET rbac/roles": { body: { data: roles } },
      "POST rbac/grants": { status: 202, body: { status: "approval_pending", approval_request_id: "g1", action_type: "rbac.grant.privileged", required_approver_role: "super_admin", expires_at: inHours(72) } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<RoleGrants />);
    await userEvent.click(await screen.findByRole("button", { name: "Grant role" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/User id/), "u9");
    await userEvent.selectOptions(within(dialog).getByLabelText(/^Role/), "super_admin");
    expect(within(dialog).getByText(/privileged role/)).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText(/Reason/), "New admin");
    await userEvent.click(within(dialog).getByRole("button", { name: "Request grant" }));
    expect(await within(dialog).findByText("Waiting for a second approver")).toBeInTheDocument();
  });

  it("simple authentication: granting Admin applies at once; only removal needs a second admin", async () => {
    const api = mockApi({
      "GET rbac/grants": { body: { data: [] } },
      "GET rbac/roles": { body: { data: roles } },
      "GET public/integrations": { body: { integrations: {}, simple_auth: true } },
    });
    resetIntegrationsCache();
    cleanups.push(api.restore, resetIntegrationsCache);
    renderWithProviders(<RoleGrants />);
    expect(await screen.findByText(/Removing an Admin role needs a second admin to approve/)).toBeInTheDocument();
    expect(screen.queryByText(/Admin roles need a second admin/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Grant role" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.selectOptions(within(dialog).getByLabelText(/^Role/), "super_admin");
    expect(within(dialog).queryByText(/privileged role/)).not.toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Grant" })).toBeInTheDocument();
  });

  it("simple authentication: the Approvals queue does not promise a second confirmation", async () => {
    const api = mockApi({ "GET admin/approvals": { body: { data: [] } }, "GET me": { body: { user: { id: "me" } } }, "GET public/integrations": { body: { integrations: {}, simple_auth: true } } });
    resetIntegrationsCache();
    cleanups.push(api.restore, resetIntegrationsCache);
    renderWithProviders(<ApprovalsQueue />);
    expect(await screen.findByText(/You can never approve your own request/)).toBeInTheDocument();
    expect(screen.queryByText(/confirm again/)).not.toBeInTheDocument();
  });

  it("flags a broken audit chain and filters by action", async () => {
    const api = mockApi({
      "GET audit/events": { body: { data: [{ seq: 1048577, occurred_at: "2026-11-03T10:00:00.000Z", id: "e1", actor_type: "user", actor_user_id: "r1", actor_session_id: null, actor_roles: ["security_reviewer"], action: "case.decide", target_type: "security_case", target_id: "c1", organization_id: null, subject_user_id: null, reason_code: "case_review", reason: null, request_id: "req-1", prev_hash: "00", row_hash: "11" }], page } },
      "GET audit/chain-status": { body: { verified: false, checked_rows: 1048577, last_seq: 1048577, last_row_hash: "11", first_bad_seq: 1048000, reason: null } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<AuditLog />);
    // Readable action and record; raw keys and ids stay out of the table (Phase 2, 1.11).
    expect(await screen.findByText("Case decide")).toBeInTheDocument();
    expect(screen.queryByText("case.decide")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "User #R1" })).toHaveAttribute("href", "/admin/users/r1");
    expect(await screen.findByRole("alert")).toHaveTextContent("Audit chain break detected at seq 1048000");
    await userEvent.type(screen.getByLabelText(/^Action/), "case.decide");
    await waitFor(() => expect(api.calls.some((c) => c.url.includes("action=case.decide"))).toBe(true));
    expect(screen.queryByRole("button", { name: /delete/i })).not.toBeInTheDocument();
  });
});

describe("formatINR", () => {
  it("uses Indian digit grouping", () => {
    expect(formatINR(184230000)).toBe("₹18,42,300.00");
    expect(formatINR(null)).toBe("—");
  });
});

describe("Admin dashboard (ADM-001)", () => {
  it("renders platform aggregates and the break-glass alert", async () => {
    const api = mockApi({
      "GET audit/chain-status": { body: { verified: true, checked_rows: 10, last_seq: 10, last_row_hash: "a", first_bad_seq: null, reason: null } },
      "GET admin/dashboard": {
        body: {
          generated_at: "2026-11-03T10:00:00.000Z",
          users: { total: 1200, active: 1000, pending_verification: 150, deactivated: 50, minors: 80, new_7d: 30, new_30d: 120 },
          sessions: { active: 300 },
          support: { open: 7, breached: 2, unassigned: 3 },
          security: { restricted_by_level: { "1": 4, "3": 1 }, open_cases: 2 },
          approvals: { pending: 1 },
          privacy: { open: 2, overdue: 0 },
          break_glass: { active: 1 },
          commerce: { paid_orders_30d: 42, revenue_paise_30d: 4200000 },
          learning: { learners: 1100, courses_published: 12, courses_draft: 3, batches_active: 5, batches_planned: 2 },
        },
      },
      "GET admin/admissions/overview": { body: { registered: 9, enrolled: 4, pending_claims: 2, pending_amount_paise: 300000, collected_paise: 4200000 } },
      "GET public/integrations": { body: { integrations: { payments: false }, simple_auth: true } },
    });
    resetIntegrationsCache();
    cleanups.push(api.restore, resetIntegrationsCache);
    renderWithProviders(<AdminDashboard />);
    // Headline tiles: students, registrations, payments, courses, batches, approvals.
    expect(await screen.findByRole("link", { name: /Students.*1,100.*1,200 accounts in all/ })).toHaveAttribute("href", "/admin/users?status=active");
    expect(screen.getByRole("link", { name: /New registrations.*120/ })).toBeInTheDocument();
    // Live audit M1: courses open the Admin course overview, not the Content studio.
    expect(screen.getByRole("link", { name: /Active courses.*12.*3 in draft/ })).toHaveAttribute("href", "/admin/courses");
    expect(screen.getByRole("link", { name: /^Courses/ })).toHaveAttribute("href", "/admin/courses");
    expect(screen.queryByRole("link", { name: /studio/i })).not.toBeInTheDocument();
    // M12: fees are verified under Admissions (UPI); gateway sales only once a gateway is connected.
    expect(await screen.findByRole("link", { name: /Payments to verify.*2.*₹3,000\.00 waiting/ })).toHaveAttribute("href", "/finance/admissions/verify");
    expect(screen.getByRole("link", { name: /Verified fees.*₹42,000\.00/ })).toHaveAttribute("href", "/finance/admissions");
    expect(screen.queryByText("Sales, last 30 days")).not.toBeInTheDocument();
    // M11: the Integrations card moved to Settings › System status.
    expect(screen.queryByText("Integrations")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Active batches.*5.*2 planned/ })).toHaveAttribute("href", "/admin/batches");
    // Colleges Data goes straight to the real portal page (full page load for its CSP).
    const colleges = screen.getAllByRole("link", { name: /Colleges Data/ });
    expect(colleges.every((a) => a.getAttribute("href") === "/college-portal/index.html")).toBe(true);
    expect(screen.getByRole("heading", { level: 1, name: "Dashboard" })).toBeInTheDocument();
    // Readable restriction levels instead of "Restricted L3".
    expect(screen.getByText("Temporarily restricted")).toBeInTheDocument();
    expect(screen.queryByText(/Restricted L\d/)).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Break-glass elevation active: 1");
    // "Needs your attention": only counts above zero, each a link to its queue, most urgent first.
    const attention = screen.getByRole("heading", { name: "Needs your attention" }).closest("section")!;
    const links = within(attention).getAllByRole("link");
    expect(links.map((l) => l.getAttribute("href"))).toEqual(["/admin/break-glass", "/desk", "/admin/approvals", "/security/cases", "/desk"]);
    expect(within(attention).getByText("1 request is waiting for your approval")).toBeInTheDocument();
    expect(within(attention).queryByText(/privacy requests are overdue/)).not.toBeInTheDocument();
    // Tiles link to their queues.
    expect(screen.getByRole("link", { name: /Pending approvals.*Waiting in Approvals/ })).toHaveAttribute("href", "/admin/approvals");
    expect(screen.getByRole("link", { name: /Audit log verified/ })).toHaveAttribute("href", "/admin/audit");
  });

  it("shows gateway sales once online payments are connected", async () => {
    const zero = { generated_at: "2026-11-03T10:00:00.000Z", users: { total: 1, active: 1, pending_verification: 0, deactivated: 0, minors: 0, new_7d: 0, new_30d: 0 }, sessions: { active: 0 }, support: { open: 0, breached: 0, unassigned: 0 }, security: { restricted_by_level: {}, open_cases: 0 }, approvals: { pending: 0 }, privacy: { open: 0, overdue: 0 }, break_glass: { active: 0 }, commerce: { paid_orders_30d: 3, revenue_paise_30d: 900000 } };
    const api = mockApi({ "GET admin/dashboard": { body: zero }, "GET public/integrations": { body: { integrations: { payments: true } } } });
    resetIntegrationsCache();
    cleanups.push(api.restore, resetIntegrationsCache);
    renderWithProviders(<AdminDashboard />);
    expect(await screen.findByText("Sales, last 30 days")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Paid orders.*3/ })).toHaveAttribute("href", "/finance/orders");
  });

  it("System status lists the outside services and the advanced tools that left the sidebar", async () => {
    const api = mockApi({ "GET public/integrations": { body: { integrations: { email: false, payments: false, ai: true } } } });
    resetIntegrationsCache();
    cleanups.push(api.restore, resetIntegrationsCache);
    renderWithProviders(<SystemStatus />);
    expect(await screen.findByText("Online payments")).toBeInTheDocument();
    expect(screen.getAllByText("Not integrated yet").length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "Feature flags" })).toHaveAttribute("href", "/admin/feature-flags");
    expect(screen.getByRole("link", { name: "Break-glass history" })).toHaveAttribute("href", "/admin/break-glass");
  });

  it("says when nothing needs attention", async () => {
    const zero = { generated_at: "2026-11-03T10:00:00.000Z", users: { total: 1, active: 1, pending_verification: 0, deactivated: 0, minors: 0, new_7d: 0, new_30d: 0 }, sessions: { active: 0 }, support: { open: 0, breached: 0, unassigned: 0 }, security: { restricted_by_level: {}, open_cases: 0 }, approvals: { pending: 0 }, privacy: { open: 0, overdue: 0 }, break_glass: { active: 0 }, commerce: { paid_orders_30d: 0, revenue_paise_30d: 0 } };
    const api = mockApi({ "GET audit/chain-status": { body: { verified: true, checked_rows: 1, last_seq: 1, last_row_hash: "a", first_bad_seq: null, reason: null } }, "GET admin/dashboard": { body: zero } });
    cleanups.push(api.restore);
    renderWithProviders(<AdminDashboard />);
    expect(await screen.findByText("Nothing needs your attention")).toBeInTheDocument();
  });
});

const account = {
  user_id: "u1",
  display_name: "Asha Rao",
  email: "asha@example.com",
  phone_masked: "+91******10",
  status: "active",
  privacy_tier: "adult",
  is_minor: false,
  email_verified_at: "2026-01-01T00:00:00.000Z",
  phone_verified_at: null,
  restriction_level: 0,
  account_origin: "self_signup",
  created_at: "2026-01-01T00:00:00.000Z",
  last_login_at: null,
  grants: [],
  mfa: { enrolled: true, factors: [{ factor_type: "totp", created_at: null, last_used_at: null }] },
  sessions: { active: 2 },
  pending_approvals: [],
  break_glass_active: false,
};

describe("Admin users (ADM-004)", () => {
  it("searches users", async () => {
    const api = mockApi({ "GET admin/users": { body: { data: [{ user_id: "u1", display_name: "Asha Rao", email: "asha@example.com", phone_masked: null, status: "active", is_minor: true, restriction_level: 2, roles: ["student"], created_at: "2026-01-01T00:00:00.000Z", last_login_at: null }], page } } });
    cleanups.push(api.restore);
    renderWithProviders(<UserSearch />);
    expect(await screen.findByText("Asha Rao")).toBeInTheDocument();
    expect(screen.getByText("Verification required")).toBeInTheDocument();
    expect(screen.queryByText("L2")).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/Search/), "asha");
    await waitFor(() => expect(api.calls.some((c) => c.url.includes("q=asha"))).toBe(true));
  });

  it("hides erased accounts by default and can show them", async () => {
    const api = mockApi({ "GET admin/users": { body: { data: [], page } } });
    cleanups.push(api.restore);
    renderWithProviders(<UserSearch />);
    await waitFor(() => expect(api.calls.some((c) => c.url.includes("status=current"))).toBe(true));
    await userEvent.selectOptions(screen.getByLabelText(/Status/), "any");
    await waitFor(() => expect(api.calls.at(-1)?.url.includes("status=")).toBe(false));
  });

  it("adds a user with a starting password and a batch-scoped Trainer role (ADM-06)", async () => {
    const api = mockApi({
      "GET admin/users": { body: { data: [], page } },
      "GET batches": { body: { data: [{ id: "b1", name: "March cohort", code: "MAR26", status: "active" }] } },
      "POST admin/users": { status: 201, body: { user_id: "n1", status: "active", role: { role_key: "trainer", status: "granted", grant_id: "g1" } } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<UserSearch />);
    await userEvent.click(await screen.findByRole("button", { name: "Add user" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Full name/), "Ravi Kumar");
    await userEvent.type(within(dialog).getByLabelText(/^Email/), "ravi@example.com");
    await userEvent.click(within(dialog).getByRole("button", { name: "Suggest" }));
    await userEvent.selectOptions(within(dialog).getByLabelText(/^Role/), "trainer");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create account" }));
    expect(await within(dialog).findByText("Choose the batch this trainer will teach.")).toBeInTheDocument();
    await userEvent.selectOptions(await within(dialog).findByLabelText(/^Batch/), "b1");
    await userEvent.type(within(dialog).getByLabelText(/Reason/), "New trainer for March");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create account" }));
    expect(await within(dialog).findByText("Confirm the person is 18 or older.")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByLabelText(/18 or older/));
    await userEvent.click(within(dialog).getByRole("button", { name: "Create account" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.path === "admin/users")).toBe(true));
    const post = api.calls.find((c) => c.method === "POST" && c.path === "admin/users")!;
    expect(post.headers["idempotency-key"]).toBeTruthy();
    expect(post.body).toMatchObject({ full_name: "Ravi Kumar", email: "ravi@example.com", role_key: "trainer", scope_type: "batch", scope_id: "b1", confirm_adult: true, must_change_password: false });
    expect((post.body as { password: string }).password.length).toBeGreaterThanOrEqual(8);
  });

  it("simple authentication: Add user can require a password change on first login; Admin is just 'Admin'", async () => {
    try { window.sessionStorage.clear(); } catch { /* ignore */ }
    resetIntegrationsCache();
    cleanups.push(resetIntegrationsCache);
    const api = mockApi({
      "GET public/integrations": { body: { integrations: { email: false }, simple_auth: true } },
      "GET admin/users": { body: { data: [], page } },
      "POST admin/users": { status: 201, body: { user_id: "n2", status: "active", role: null } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<UserSearch />);
    await userEvent.click(await screen.findByRole("button", { name: "Add user" }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByRole("option", { name: "Admin" })).toBeInTheDocument();
    const must = within(dialog).getByLabelText(/Must change password on first login/);
    expect(must).not.toBeChecked();
    await userEvent.type(within(dialog).getByLabelText(/Full name/), "Meena Iyer");
    await userEvent.type(within(dialog).getByLabelText(/^Email/), "meena@example.com");
    await userEvent.type(within(dialog).getByLabelText(/Starting password/), "start-123");
    await userEvent.click(must);
    await userEvent.type(within(dialog).getByLabelText(/Reason/), "New student");
    await userEvent.click(within(dialog).getByLabelText(/18 or older/));
    await userEvent.click(within(dialog).getByRole("button", { name: "Create account" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.path === "admin/users")).toBe(true));
    const post = api.calls.find((c) => c.method === "POST" && c.path === "admin/users")!;
    expect(post.body).toMatchObject({ email: "meena@example.com", password: "start-123", must_change_password: true });
  });

  it("keeps the Add user entries after closing the dialog, and Clear form empties them", async () => {
    try { window.sessionStorage.clear(); } catch { /* ignore */ }
    const api = mockApi({ "GET admin/users": { body: { data: [], page } } });
    cleanups.push(api.restore);
    renderWithProviders(<UserSearch />);
    await userEvent.click(await screen.findByRole("button", { name: "Add user" }));
    let dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Full name/), "Tirumala");
    await userEvent.type(within(dialog).getByLabelText(/^Email/), "t@example.com");
    await userEvent.type(within(dialog).getByLabelText(/Starting password/), "a-long-starting-password-1");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await userEvent.click(await screen.findByRole("button", { name: "Add user" }));
    dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText(/Full name/)).toHaveValue("Tirumala");
    expect(within(dialog).getByLabelText(/^Email/)).toHaveValue("t@example.com");
    expect(within(dialog).getByLabelText(/Starting password/)).toHaveValue("a-long-starting-password-1");
    // the password is never written to storage
    expect(window.sessionStorage.getItem("td-admin-add-user-draft") ?? "").not.toContain("a-long-starting-password-1");
    await userEvent.click(within(dialog).getByRole("button", { name: "Clear form" }));
    expect(within(dialog).getByLabelText(/Full name/)).toHaveValue("");
    expect(within(dialog).getByLabelText(/Starting password/)).toHaveValue("");
  });

  it("deactivates with a reason and requests a dual-control MFA reset", async () => {
    const api = mockApi({
      "GET admin/users/u1": { body: account },
      "POST admin/users/u1/deactivate": { body: { user_id: "u1", status: "deactivated", sessions_revoked: 2 } },
      "POST admin/users/u1/mfa-reset": { status: 202, body: { status: "approval_pending", approval_request_id: "m1", action_type: "user.mfa.reset", required_approver_role: "security_reviewer", expires_at: inHours(72) } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<UserDetail userId="u1" />);
    // Phase 2: the person's name is the h1, with breadcrumbs back to Users and no raw id as the subtitle.
    expect(await screen.findByRole("heading", { level: 1, name: "Asha Rao" })).toBeInTheDocument();
    expect(within(screen.getByRole("navigation", { name: "Breadcrumb" })).getByRole("link", { name: "Users" })).toHaveAttribute("href", "/admin/users");
    expect(screen.getByText("asha@example.com · Account #U1")).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Deactivate" }));
    let dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Deactivate" }));
    expect(await within(dialog).findByText(/Give a reason/)).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText(/Reason/), "Fraudulent account");
    await userEvent.click(within(dialog).getByRole("button", { name: "Deactivate" }));
    await waitFor(() => expect(api.calls.some((c) => c.path === "admin/users/u1/deactivate")).toBe(true));
    const post = api.calls.find((c) => c.path === "admin/users/u1/deactivate")!;
    expect(post.body).toEqual({ reason: "Fraudulent account" });
    expect(post.headers["idempotency-key"]).toBeTruthy();

    await userEvent.click(await screen.findByRole("button", { name: "Reset MFA" }));
    dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Reason/), "Verified on a video call");
    await userEvent.click(within(dialog).getByRole("button", { name: "Request reset" }));
    expect(await within(dialog).findByText("Waiting for a second approver")).toBeInTheDocument();
    expect(api.calls.find((c) => c.path === "admin/users/u1/mfa-reset")!.body).toEqual({ reason: "Verified on a video call", verification_method: "video_call" });
  });

  it("simple authentication: no MFA reset or device list; Set new password asks for a change by default", async () => {
    resetIntegrationsCache();
    cleanups.push(resetIntegrationsCache);
    const api = mockApi({
      "GET public/integrations": { body: { integrations: { email: false }, simple_auth: true } },
      "GET admin/users/u1": { body: account },
      "POST admin/users/u1/password": { body: { user_id: "u1" } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<UserDetail userId="u1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Set new password" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Reset MFA" })).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Show devices" })).not.toBeInTheDocument();
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText(/Must change password on first login/)).toBeChecked();
    await userEvent.type(within(dialog).getByLabelText(/^New password/), "temp-4567");
    await userEvent.type(within(dialog).getByLabelText(/Reason/), "Forgot password, email not connected");
    await userEvent.click(within(dialog).getByRole("button", { name: "Set password" }));
    await waitFor(() => expect(api.calls.some((c) => c.path === "admin/users/u1/password")).toBe(true));
    expect(api.calls.find((c) => c.path === "admin/users/u1/password")!.body).toEqual({ password: "temp-4567", reason: "Forgot password, email not connected", must_change_password: true });
  });
});

describe("Break-glass (ADM-012)", () => {
  it("shows history with review state and offers no activation (retired in single-company mode)", async () => {
    const ended = { break_glass_id: "b1", user_id: "11111111-aaaa", reason: "Investigating incident 42", elevated_role: "security_reviewer", status: "ended", started_at: inHours(-5), expires_at: inHours(-4), ended_at: inHours(-4.5), end_reason: "ended_early", ended_by: null, review_status: "pending", review_due_at: inHours(40), reviewed_by: null, reviewed_at: null, review_note: null };
    const api = mockApi({
      "GET admin/break-glass": { body: { data: [ended], active: null } },
      "POST admin/break-glass/b1/review": { body: { ...ended, review_status: "reviewed" } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<BreakGlass />);
    expect(await screen.findByText("Investigating incident 42")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Activate break-glass" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Review break-glass b1" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Review note/), "Checked the evidence trail");
    await userEvent.click(within(dialog).getByRole("button", { name: "Record review" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    const post = api.calls.find((c) => c.method === "POST")!;
    expect(post.url).toContain("admin/break-glass/b1/review");
    expect(post.headers["idempotency-key"]).toBeTruthy();
  });
});

describe("Approvals payload and decide routing (ADM-13, ADM-15, ADM-22, ADM-25)", () => {
  const grantRow = { approval_request_id: "g7", action_type: "rbac.grant.privileged", target_type: "user", target_id: "u9", status: "pending", requested_by: "u2", request_reason: "New admin", required_approver_role: "super_admin", decided_by: null, decided_at: null, decision_note: null, expires_at: inHours(70), created_at: inHours(-1) };

  it("labels real action types and maps fallbacks", () => {
    expect(actionTypeLabel("rbac.grant.privileged")).toBe("Privileged role grant");
    expect(actionTypeLabel("commerce.coupon.activate")).toBe("Activate coupon");
    expect(fallbackDecidePath("commerce.refund", "a", true)).toBe("finance/approval-requests/a/approve");
    expect(fallbackDecidePath("rbac.revoke.privileged", "a", false)).toBe("rbac/approval-requests/a/reject");
    expect(fallbackDecidePath("policy.change", "a", true)).toBeNull();
  });

  it("shows the payload from GET admin/approvals/{id} and falls back to RBAC-07 on 404", async () => {
    const api = mockApi({
      "GET admin/approvals": { body: { data: [grantRow] } },
      "GET me": { body: { user: { id: "me-id" } } },
      "GET admin/approvals/g7": { body: { ...grantRow, payload: { user_id: "u9", role_key: "security_reviewer", scope_type: "platform" }, payload_hash: "ab12" } },
      "POST admin/approvals/g7/approve": problem(404, "not_found", "Not found"),
      "POST rbac/approval-requests/g7/approve": { body: { status: "executed" } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<ApprovalsQueue />);
    expect(await screen.findByText("Privileged role grant")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show details" }));
    expect(await screen.findByText("security_reviewer")).toBeInTheDocument();
    // Ids in the payload read as short references; the exact JSON stays under "Raw data".
    expect(screen.getByText("User #U9")).toBeInTheDocument();
    expect(screen.getByText("Raw data")).toBeInTheDocument();
    expect(screen.getByText("Payload hash ab12")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Approve Privileged role grant g7" }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("security_reviewer")).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText(/Note/), "Checked");
    await userEvent.click(within(dialog).getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(api.calls.some((c) => c.path === "rbac/approval-requests/g7/approve")).toBe(true));
    expect(api.calls.find((c) => c.path === "rbac/approval-requests/g7/approve")!.body).toEqual({ note: "Checked" });
  });

  it("does not fall back for other errors", async () => {
    const api = mockApi({
      "GET admin/approvals": { body: { data: [{ ...grantRow, action_type: "commerce.refund" }] } },
      "GET me": { body: { user: { id: "me-id" } } },
      "GET admin/approvals/g7": { body: { ...grantRow, payload: {} } },
      "POST admin/approvals/g7/approve": problem(403, "sod_violation", "Not allowed", { detail: "You cannot decide your own request." }),
    });
    cleanups.push(api.restore);
    renderWithProviders(<ApprovalsQueue />);
    await userEvent.click(await screen.findByRole("button", { name: /Approve Refund/ }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Approve" }));
    expect(await within(dialog).findByText("You cannot decide your own request.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.path.startsWith("finance/approval-requests"))).toBe(false);
  });
});

describe("Role list and revoke reason (ADM-22)", () => {
  it("uses GET rbac/roles and keeps the revoke reason separate from the grant form", async () => {
    const grant = { grant_id: "gr1", user_id: "u5", role_key: "trainer", scope_type: "batch", scope_id: "b1", organization_id: null, granted_by: "u1", granted_at: inHours(-100), expires_at: null, reason: null };
    const api = mockApi({ "GET rbac/grants": { body: { data: [grant] } }, "GET rbac/roles": { body: { data: roles } }, "POST rbac/grants/gr1/revoke": { body: { revoked: true } } });
    cleanups.push(api.restore);
    renderWithProviders(<RoleGrants />);
    await userEvent.click(await screen.findByRole("button", { name: "Grant role" }));
    let dialog = await screen.findByRole("dialog");
    const roleSelect = within(dialog).getByLabelText(/^Role/);
    await waitFor(() => expect(within(roleSelect).getAllByRole("option").map((o) => o.textContent)).toEqual(["Choose a role", "Admin", "Trainer"]));
    await userEvent.type(within(dialog).getByLabelText(/Reason/), "Grant reason text");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("link", { name: "User #U5" })).toHaveAttribute("href", "/admin/users/u5");
    expect(screen.getByText("Batch #B1")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Revoke Trainer from user #U5" }));
    dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText(/Reason/)).toHaveValue("");
    await userEvent.type(within(dialog).getByLabelText(/Reason/), "Left the company");
    await userEvent.click(within(dialog).getByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    expect(api.calls.find((c) => c.method === "POST")!.body).toEqual({ reason: "Left the company" });
  });
});

describe("Feature flag allowlists (ADM-17)", () => {
  it("edits the user allowlist in the PATCH body (no org allowlist field)", async () => {
    const ORG = "0193a000-0000-7000-8000-0000000000aa";
    const api = mockApi({
      "GET admin/feature-flags": { body: { data: [{ flag_key: "payments.cashfree_enabled", description: null, is_enabled: false, rollout_percent: 0, user_allowlist: [] }] } },
      "PATCH admin/feature-flags/payments.cashfree_enabled": { body: {} },
    });
    cleanups.push(api.restore);
    renderWithProviders(<FeatureFlags />);
    await userEvent.click(await screen.findByRole("button", { name: "Edit payments.cashfree_enabled" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByLabelText(/Organization allowlist/)).not.toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText(/User allowlist/), "bad-id");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByText("Not a valid id: bad-id")).toBeInTheDocument();
    await userEvent.clear(within(dialog).getByLabelText(/User allowlist/));
    await userEvent.type(within(dialog).getByLabelText(/User allowlist/), ORG);
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(api.calls.find((c) => c.method === "PATCH")!.body).toEqual({ is_enabled: false, rollout_percent: 0, user_allowlist: [ORG] });
    expect(parseIdList(`${ORG}\n${ORG}, x`)).toEqual({ ids: [ORG, "x"], invalid: ["x"] });
  });
});

describe("Commerce approvals in the admin queue (ADM-25)", () => {
  it("shows Decide with readable labels for every registered commerce type and decides via ADM-14 (no fallback)", async () => {
    const types = ["commerce.refund", "commerce.coupon.activate", "commerce.price.create", "entitlements.grant.bulk"];
    const rows = types.map((t, i) => ({ approval_request_id: `c${i}`, action_type: t, target_type: "x", target_id: null, status: "pending", requested_by: "u2", request_reason: "r", required_approver_role: "finance_admin", decided_by: null, decided_at: null, decision_note: null, expires_at: inHours(70), created_at: inHours(-1) }));
    const api = mockApi({ "GET admin/approvals": { body: { data: rows } }, "GET me": { body: { user: { id: "me-id" } } }, "GET admin/approvals/c1": { body: { ...rows[1], payload: { coupon_id: "cp1" } } }, "POST admin/approvals/c1/approve": { body: { status: "executed" } } });
    cleanups.push(api.restore);
    renderWithProviders(<ApprovalsQueue />);
    for (const label of ["Refund (goodwill or above threshold)", "Activate coupon", "New price", "Bulk access grant"]) expect(await screen.findByRole("button", { name: new RegExp(`^Approve ${label.replace(/[()]/g, "\\$&")} `) })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Approve Activate coupon c1" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(api.calls.some((c) => c.path === "admin/approvals/c1/approve")).toBe(true));
    expect(api.calls.some((c) => c.path.startsWith("finance/approval-requests"))).toBe(false);
  });
});

describe("Phase 2 identity and copy helpers", () => {
  it("shortRef and personLabel never show a raw id", async () => {
    const { shortRef, personLabel, formatCountdown } = await import("../lib/console");
    expect(shortRef("9b2f6c1e-4d3a-4c1b-9f3c-21ab9f3c21ab")).toBe("#9F3C21AB");
    expect(shortRef(null)).toBe("—");
    expect(personLabel({ full_name: "Asha Rao", email: "a@x.in", id: "u1" })).toBe("Asha Rao");
    expect(personLabel({ email: "a@x.in", id: "u1" })).toBe("a@x.in");
    expect(personLabel({ id: "9b2f6c1e-4d3a-4c1b-9f3c-21ab9f3c21ab" })).toBe("User #9F3C21AB");
    expect(formatCountdown(new Date(Date.now() + 12 * 86_400_000).toISOString())).toBe("in 12 days");
  });

  it("policy labels and bounds read as words", async () => {
    const { settingLabel } = await import("../lib/policy-labels");
    const { boundsText, istLocalToIso } = await import("./PolicySettings");
    expect(settingLabel("otp.ttl_seconds")).toBe("Code expiry (seconds)");
    expect(settingLabel("grace.some_new_key")).toBe("Some new key");
    expect(boundsText({ kind: "int", choices: null, min_value: 1, max_value: null })).toBe("At least 1");
    expect(boundsText({ kind: "int", choices: null, min_value: 1, max_value: 10 })).toBe("1 to 10");
    expect(istLocalToIso("2026-11-12T09:30")).toBe("2026-11-12T04:00:00.000Z");
    expect(istLocalToIso("")).toBeNull();
  });

  it("flag names are readable", async () => {
    const { flagName } = await import("./Governance");
    expect(flagName("payments.cashfree_enabled")).toBe("Payments · Cashfree enabled");
  });
});

describe("UserDevices (admin, reason user_request)", () => {
  it("loads only when opened and resets a device with reason_code user_request", async () => {
    const api = mockApi({
      "GET users/u9/devices": { body: { data: [{ user_device_id: "d1", label: "Chrome on Windows", trust_status: "trusted", last_used_at: "2026-11-10T10:00:00Z" }], limits: {} } },
      "POST users/u9/devices/d1/reset": { body: { removed: true } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<UserDevices userId="u9" />);
    expect(api.calls.length).toBe(0); // viewing is audited, so nothing loads until asked
    await userEvent.click(screen.getByRole("button", { name: "Show devices" }));
    expect(await screen.findByText("Chrome on Windows")).toBeInTheDocument();
    expect(api.calls[0]!.url).toContain("reason_code=user_request");
    await userEvent.click(screen.getByRole("button", { name: "Reset Chrome on Windows" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/^Reason/), "Lost phone, asked by email");
    await userEvent.click(within(dialog).getByRole("button", { name: "Reset device" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    const post = api.calls.find((c) => c.method === "POST")!;
    expect(post.body).toEqual({ reason_code: "user_request", reason: "Lost phone, asked by email" });
    expect(post.headers["idempotency-key"]).toBeTruthy();
  });
});

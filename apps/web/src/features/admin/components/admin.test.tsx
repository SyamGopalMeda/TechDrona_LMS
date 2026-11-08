import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { formatINR } from "../lib/console";
import { actionTypeLabel, ApprovalsQueue, fallbackDecidePath } from "./ApprovalsQueue";
import { AdminDashboard, AuditLog, BreakGlass, FeatureFlags, parseIdList, RoleGrants } from "./Governance";
import { UserDetail, UserSearch } from "./Users";
import { parseProposed, PolicySettings } from "./PolicySettings";

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
    expect(await screen.findByText("devices.student.max_trusted")).toBeInTheDocument();
    expect(screen.getByText("⏳ Pending ⇄")).toBeInTheDocument();
    expect(await screen.findByText(/needs ratification/)).toBeInTheDocument();
    expect(screen.getByText(/risk.mode is SHADOW/)).toBeInTheDocument();

    const input = screen.getByLabelText("Proposed value for devices.student.max_trusted");
    await userEvent.type(input, "11");
    expect(screen.getByText("Max 10")).toBeInTheDocument();
    const propose = screen.getByRole("button", { name: "Propose change to devices.student.max_trusted" });
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

  it("flags a broken audit chain and filters by action", async () => {
    const api = mockApi({
      "GET audit/events": { body: { data: [{ seq: 1048577, occurred_at: "2026-11-03T10:00:00.000Z", id: "e1", actor_type: "user", actor_user_id: "r1", actor_session_id: null, actor_roles: ["security_reviewer"], action: "case.decide", target_type: "security_case", target_id: "c1", organization_id: null, subject_user_id: null, reason_code: "case_review", reason: null, request_id: "req-1", prev_hash: "00", row_hash: "11" }], page } },
      "GET audit/chain-status": { body: { verified: false, checked_rows: 1048577, last_seq: 1048577, last_row_hash: "11", first_bad_seq: 1048000, reason: null } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<AuditLog />);
    expect(await screen.findByText("case.decide")).toBeInTheDocument();
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
        },
      },
    });
    cleanups.push(api.restore);
    renderWithProviders(<AdminDashboard />);
    expect(await screen.findByText("1,200")).toBeInTheDocument();
    expect(screen.getByText("Restricted L3")).toBeInTheDocument();
    expect(screen.getByText("₹42,000.00")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Break-glass elevation active: 1");
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
    expect(screen.getByText("L2")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/Search/), "asha");
    await waitFor(() => expect(api.calls.some((c) => c.url.includes("q=asha"))).toBe(true));
  });

  it("deactivates with a reason and requests a dual-control MFA reset", async () => {
    const api = mockApi({
      "GET admin/users/u1": { body: account },
      "POST admin/users/u1/deactivate": { body: { user_id: "u1", status: "deactivated", sessions_revoked: 2 } },
      "POST admin/users/u1/mfa-reset": { status: 202, body: { status: "approval_pending", approval_request_id: "m1", action_type: "user.mfa.reset", required_approver_role: "security_reviewer", expires_at: inHours(72) } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<UserDetail userId="u1" />);
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
    await userEvent.click(screen.getByRole("button", { name: "Show payload" }));
    expect(await screen.findByText("security_reviewer")).toBeInTheDocument();
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
    await userEvent.click(screen.getByRole("button", { name: "Revoke trainer from u5" }));
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

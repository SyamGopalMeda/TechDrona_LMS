import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { configureApiClient } from "@/lib/api/client";
import { CaseQueue } from "./CaseQueue";
import { CaseView } from "./CaseDetail";
import { DecisionPanel, PendingApprovalPanel } from "./DecisionPanel";
import { RatificationBanner } from "./EngineControls";
import { ExportRequest } from "./Reports";
import { BulkLift } from "./Restrictions";
import { RiskBadge } from "./RiskLevel";

/**
 * FE-24: typing long strings key-by-key re-renders the decision form per character and made
 * these tests exceed the 5 s default under parallel load. Pasting fires one input event per
 * field, which is all these tests need (no per-keystroke behaviour is under test).
 */
async function fill(el: HTMLElement, text: string) {
  await userEvent.click(el);
  await userEvent.paste(text);
}

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

const cleanups: (() => void)[] = [];
afterEach(() => {
  while (cleanups.length) cleanups.pop()!();
});

const page = { next_cursor: null, has_more: false, limit: 50 };
const inHours = (h: number) => new Date(Date.now() + h * 3_600_000).toISOString();

describe("RiskBadge (design-system §3.3: label + icon + 4-pip meter)", () => {
  it("never relies on colour alone", () => {
    const { container } = render(<RiskBadge level={3} />);
    expect(screen.getByText("L3 · Temporary restriction")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Level 3 of 4" })).toBeInTheDocument();
    expect(container.querySelectorAll("[data-filled]")).toHaveLength(3);
    expect(container.querySelector("svg")).not.toBeNull();
    expect(container.innerHTML).not.toMatch(/danger|red-/);
  });

  it("compact form keeps the full label for screen readers; unknown level is a dash", () => {
    render(
      <>
        <RiskBadge level={4} compact />
        <RiskBadge level={null} />
      </>,
    );
    expect(screen.getByText("L4")).toBeInTheDocument();
    expect(screen.getByText("Suspended")).toHaveClass("sr-only");
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

// Shape of app/modules/security/cases.py case_out.
const caseRow = {
  case_id: "c1",
  case_ref: "SEC-2611-7KQ4MZ",
  user_id: "u1",
  family: "sharing",
  level: 3,
  recommended_level: 4,
  priority: "high",
  status: "under_review",
  opened_reason: "engine",
  hc_rule: null,
  score: 82.4,
  age_hours: 19,
  sla_first_response_due: null,
  sla_decision_due: inHours(40),
  sla_state: "on_track",
  assignee_id: null,
  is_high_risk: true,
  high_risk_reasons: [],
  repeat_count: 1,
  organization_id: "org-1",
  unblock_request: null,
  version: 7,
};

describe("CaseQueue (SEC-002 / H1)", () => {
  it("lists cases with staff risk badge, counts, filters and a conflict-checked claim", async () => {
    const api = mockApi({
      "GET security/cases": { body: { data: [caseRow], counts: { open: 14, decided: 2 }, page } },
      "POST security/cases/c1/claim": problem(409, "conflict_of_interest", "Conflict of interest"),
    });
    cleanups.push(api.restore);
    renderWithProviders(<CaseQueue />);
    const link = await screen.findByRole("link", { name: "SEC-2611-7KQ4MZ" });
    expect(link).toHaveAttribute("href", "/security/cases/c1");
    expect(screen.getByRole("img", { name: "Level 3 of 4" })).toBeInTheDocument();
    expect(screen.getByText("⚑ High-risk")).toBeInTheDocument();
    expect(screen.getByText("Decided")).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Level"), "3,4");
    await waitFor(() => expect(api.calls.some((c) => c.url.includes("level=3%2C4"))).toBe(true));

    await userEvent.click(screen.getByRole("button", { name: "Claim SEC-2611-7KQ4MZ" }));
    expect(await screen.findByText("You can't take this case")).toBeInTheDocument();
    const claim = api.calls.find((c) => c.method === "POST")!;
    expect(claim.headers["if-match"]).toBe('"v7"');
  });
});

// Shape of api_review.py get_case.
const detail = {
  ...caseRow,
  level: 4,
  assignee_id: "r1",
  subject: { user_id: "u1", name: "Asha", is_minor: false },
  restriction: { restriction_id: "r-1", user_id: "u1", level: 4, family: "sharing", scope: "account", source: "reviewer", hc_rule: null, starts_at: "2026-11-03T04:45:00.000Z", ends_at: null, deferred_until: null, state: "active", case_id: "c1", case_ref: "SEC-2611-7KQ4MZ", ended_at: null, end_reason: null },
  unblock_request: { reference: "APL-2611-3HX9RB", state: "under_review" },
  decisions: [],
  notes: [],
};

// Shape of api_review.py explanation (evaluation_out).
const explanation = {
  case_ref: "SEC-2611-7KQ4MZ",
  hc_rule: null,
  evaluation: {
    id: "ev1",
    family: "sharing",
    mode: "enforce",
    ruleset_version: "7.0.0",
    evaluated_at: "2026-11-02T13:58:40.000Z",
    signals: [{ signal_id: "s1", rule: "SH-01", rule_version: "1.0.0", category: "C", occurred_at: "2026-11-02T13:58:40.000Z", base_points: 18, decayed_points: 16.2, evidence: { separation_class: "S3" } }],
    subtotals: { C: 54 },
    repeat_multiplier: 1,
    score: 82.4,
    previous_score: null,
    level_before: 2,
    level_after: 3,
    action: "restrict",
    explanation_keys: ["sh01"],
  },
  student_explanation_preview: ["Your account was active on two devices."],
};

const timeline = {
  subject: { user_id: "u1", is_minor: false },
  events: [{ at: "2026-11-02T13:58:40.000Z", type: "login", outcome: "success", device_label: "Chrome on Windows", net: "49.36.112.0/24", evidence_ref: "la_1" }],
  page,
};

async function openEvidence() {
  expect(await screen.findByText("SH-01")).toBeInTheDocument();
  expect(screen.getByText("v1.0.0")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("tab", { name: /^Timeline/ }));
  expect(await screen.findByText(/Chrome on Windows/)).toBeInTheDocument();
}

describe("Case detail decision panel (SEC-003)", () => {
  it("is disabled until Explanation and Timeline were opened, then a high-risk L4 lift goes to second approval", async () => {
    let proposed = false;
    const api = mockApi({
      "GET security/cases/c1": () => ({
        body: proposed
          ? {
              ...detail,
              status: "escalated",
              pending_approval: {
                approval_request_id: "apr1",
                status: "pending",
                requested_by: "me",
                requested_at: new Date().toISOString(),
                expires_at: inHours(72),
                is_requester: true,
                can_decide: false,
                can_withdraw: true,
                payload: { outcome: "lift_false_positive", resulting_level: 0, student_summary: "We reviewed your request.", rationale: "Both devices belong to the student." },
              },
            }
          : detail,
        headers: { etag: '"v7"' },
      }),
      "GET security/cases/c1/explanation": { body: explanation },
      "GET security/users/u1/timeline": { body: timeline },
      "POST security/cases/c1/decisions": () => {
        proposed = true;
        return { status: 202, body: { requires_second_approval: true, approval_request_id: "apr1", expires_at: inHours(72), unblock_request: { state: "escalated" } } };
      },
    });
    cleanups.push(api.restore);
    renderWithProviders(<CaseView caseId="c1" reason={{ reason_code: "case_review" }} />);

    expect((await screen.findAllByText("L4 · Suspended")).length).toBeGreaterThan(0);
    expect(api.calls[0]!.url).toContain("reason_code=case_review");
    const submit = await screen.findByRole("button", { name: "Submit for approval" });
    expect(screen.getByRole("checkbox", { name: /Requires second approval/ })).toBeChecked();
    await openEvidence();
    await waitFor(() => expect(screen.queryByText("Open Explanation and Timeline before deciding.")).not.toBeInTheDocument());

    await userEvent.selectOptions(screen.getByLabelText(/^Outcome/), "lift_false_positive");
    await fill(screen.getByLabelText(/Rationale \(internal\)/), "Both devices belong to the student.");
    await fill(screen.getByLabelText(/^Student summary/), "short");
    await userEvent.click(submit);
    expect(await screen.findByText(/Write at least 50 characters/)).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);

    await fill(screen.getByLabelText(/^Student summary/), " — we reviewed your request and found the activity was yours, access returns soon.");
    await userEvent.click(screen.getByRole("button", { name: "Submit for approval" }));

    expect(await screen.findByText("Waiting for a second approver")).toBeInTheDocument();
    const post = api.calls.find((c) => c.method === "POST")!;
    expect(post.headers["if-match"]).toBe('"v7"');
    expect(post.headers["idempotency-key"]).toBeTruthy();
    expect(post.body).toMatchObject({ outcome: "lift_false_positive", resulting_level: 0 });
    expect(post.body).not.toHaveProperty("requires_second_approval");
    expect(post.body).not.toHaveProperty("unblock_request_id");
    // SEC-04 now returns the pending proposal: the requester sees it and may only withdraw (SEC-11a).
    expect(screen.getByText(/Proposed by You/)).toBeInTheDocument();
    expect(screen.getByText("Both devices belong to the student.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Withdraw proposal" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Not available yet/)).not.toBeInTheDocument();
  });

  it("retries the decision once with the same Idempotency-Key after step-up", async () => {
    let attempts = 0;
    const api = mockApi({
      "GET security/cases/c1": { body: { ...detail, level: 3, is_high_risk: false, restriction: { ...detail.restriction, level: 3 } }, headers: { etag: '"v7"' } },
      "GET security/cases/c1/explanation": { body: explanation },
      "GET security/users/u1/timeline": { body: timeline },
      "POST security/cases/c1/decisions": () => {
        attempts += 1;
        if (attempts === 1) return problem(401, "step_up_required", "Please confirm it's you", { step_up: { max_age_seconds: 300, allowed_methods: ["totp"], options_url: "/api/v1/auth/step-up/options" } });
        return { status: 201, body: { decision_id: "d1", requires_second_approval: false } };
      },
    });
    cleanups.push(api.restore);
    const stepUp = vi.fn(async () => true);
    cleanups.push(configureApiClient({ requestStepUp: stepUp }));
    renderWithProviders(<CaseView caseId="c1" reason={{ reason_code: "case_review" }} />);
    await openEvidence();
    await fill(screen.getByLabelText(/Rationale \(internal\)/), "Owner verified.");
    await fill(screen.getByLabelText(/^Student summary/), "We reviewed your request and found the activity was yours. Access is back.");
    await userEvent.click(screen.getByRole("button", { name: "Record decision" }));
    expect(await screen.findByText("Decision recorded")).toBeInTheDocument();
    expect(stepUp).toHaveBeenCalledTimes(1);
    const posts = api.calls.filter((c) => c.method === "POST");
    expect(posts).toHaveLength(2);
    expect(posts[0]!.headers["idempotency-key"]).toBe(posts[1]!.headers["idempotency-key"]);
  });
});

describe("DecisionPanel close_no_action (security_0004)", () => {
  const manual = { ...detail, level: 0, restriction: null, unblock_request: null, opened_reason: "manual" };
  const viewed = { explanation: true, timeline: true };

  it("offers only Close / Convert to L4 when nothing is restricted and closes without a summary", async () => {
    const onChanged = vi.fn();
    const api = mockApi({ "POST security/cases/c1/decisions": { status: 201, body: { decision_id: "d1", outcome: "close_no_action" } } });
    cleanups.push(api.restore);
    renderWithProviders(<DecisionPanel detail={manual as never} ifMatch={'"v2"'} viewed={viewed} onChanged={onChanged} />);
    const select = screen.getByLabelText(/^Outcome/) as HTMLSelectElement;
    expect([...select.options].map((o) => o.value)).toEqual(["convert_L4", "close_no_action"]);
    expect(select.value).toBe("close_no_action");
    await userEvent.click(screen.getByRole("button", { name: "Record decision" }));
    expect(await screen.findByText("Add the internal rationale.")).toBeInTheDocument();
    await fill(screen.getByLabelText(/^Rationale/), "Support escalation checked: sign-ins are the learner's own.");
    await userEvent.click(screen.getByRole("button", { name: "Record decision" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    const post = api.calls.find((c) => c.method === "POST")!;
    expect(post.body).toEqual({ outcome: "close_no_action", rationale: "Support escalation checked: sign-ins are the learner's own.", student_summary: "" });
    expect(post.headers["if-match"]).toBe('"v2"');
  });

  it("does not offer close_no_action while a restriction is active", () => {
    renderWithProviders(<DecisionPanel detail={detail as never} ifMatch={'"v2"'} viewed={viewed} onChanged={vi.fn()} />);
    const select = screen.getByLabelText(/^Outcome/) as HTMLSelectElement;
    expect([...select.options].map((o) => o.value)).not.toContain("close_no_action");
  });
});

describe("PendingApprovalPanel (second approver)", () => {
  const approval = { approval_request_id: "apr1", status: "pending", can_decide: true, is_requester: false, requested_by: "r1", requested_at: null, expires_at: inHours(70), payload: { outcome: "lift_false_positive", resulting_level: 0, extension_days: 2, student_summary: "We found the activity was yours." } };

  it("approves through SEC-10 with If-Match and an Idempotency-Key", async () => {
    const onChanged = vi.fn();
    const api = mockApi({ "POST security/cases/c1/approval-requests/apr1/approve": { body: { decision_id: "d1" } } });
    cleanups.push(api.restore);
    renderWithProviders(<PendingApprovalPanel detail={detail as never} approval={approval} ifMatch={'"v9"'} onChanged={onChanged} />);
    expect(screen.getByText(/Proposed by r1/)).toBeInTheDocument();
    expect(screen.getByText("2 days")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    const dialog = await screen.findByRole("dialog", { name: "Approve this decision?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    const call = api.calls[0]!;
    expect(call.headers["if-match"]).toBe('"v9"');
    expect(call.headers["idempotency-key"]).toBeTruthy();
  });

  it("send back requires a reason", async () => {
    const api = mockApi({ "POST security/cases/c1/approval-requests/apr1/send-back": { body: { status: "rejected" } } });
    cleanups.push(api.restore);
    renderWithProviders(<PendingApprovalPanel detail={detail as never} approval={approval} ifMatch={undefined} onChanged={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Send back" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Send back" }));
    expect(within(dialog).getByText("A reason is required.")).toBeInTheDocument();
    expect(api.calls).toHaveLength(0);
  });

  it("withdraws through SEC-11a; an expired proposal offers no actions", async () => {
    const onChanged = vi.fn();
    const api = mockApi({ "POST security/cases/c1/approval-requests/apr1/withdraw": { body: { approval_request_id: "apr1", status: "cancelled" } } });
    cleanups.push(api.restore);
    const mine = { ...approval, is_requester: true, can_decide: false, can_withdraw: true };
    const { unmount } = renderWithProviders(<PendingApprovalPanel detail={detail as never} approval={mine} ifMatch={'"v9"'} onChanged={onChanged} />);
    await userEvent.click(screen.getByRole("button", { name: "Withdraw proposal" }));
    const dialog = await screen.findByRole("dialog", { name: "Withdraw your proposal?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Withdraw" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(api.calls[0]!.headers["if-match"]).toBe('"v9"');
    unmount();
    renderWithProviders(<PendingApprovalPanel detail={detail as never} approval={{ ...approval, status: "expired", can_decide: false }} ifMatch={undefined} onChanged={() => {}} />);
    expect(screen.getByText("Proposal expired")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("an escalated case without an open proposal lets a reviewer propose again", async () => {
    const api = mockApi({
      "GET security/cases/c1": { body: { ...detail, status: "escalated", pending_approval: null }, headers: { etag: '"v8"' } },
      "GET security/cases/c1/explanation": { body: explanation },
      "GET security/users/u1/timeline": { body: timeline },
    });
    cleanups.push(api.restore);
    renderWithProviders(<CaseView caseId="c1" reason={{ reason_code: "case_review" }} />);
    expect(await screen.findByText(/No proposal is waiting for a second approver/)).toBeInTheDocument();
    expect(screen.queryByText(/Not available yet/)).not.toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Submit for approval" })).toBeInTheDocument();
  });

  it("tells a conflicted reviewer they cannot decide", () => {
    renderWithProviders(<PendingApprovalPanel detail={detail as never} approval={{ ...approval, can_decide: false }} ifMatch={undefined} onChanged={() => {}} />);
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.getByText(/Another reviewer must decide/)).toBeInTheDocument();
  });
});

describe("Kill switch ratification and exports", () => {
  it("shows the 24 h ratification banner while a flip is unratified", () => {
    // Shape of controls.py engine_state (pending_ratifications = admin approval_out rows).
    const state = {
      "risk.mode": "shadow",
      "risk.hc.auto_restrict_enabled": false,
      rules: [],
      rulesets: {},
      pending_ratifications: [{ approval_request_id: "k1", action_type: "risk.kill_switch.ratify", requested_by: "a1", request_reason: "FP surge", required_approver_role: "security_reviewer|super_admin", status: "pending", expires_at: inHours(68), created_at: inHours(-4) }],
    };
    render(<RatificationBanner state={state} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/Kill switch needs ratification in 20 h/);
    expect(screen.getByRole("alert")).toHaveTextContent(/FP surge/);
    expect(screen.getByRole("alert")).toHaveTextContent(/not reverted automatically/);
  });

  it("per-user export waits for a second security reviewer", async () => {
    const api = mockApi({ "POST security/reports/blocked-accounts/exports": { status: 202, body: { export_job_id: "e1", status: "awaiting_approval", approval_request_id: "ap9", contains_pii: true } } });
    cleanups.push(api.restore);
    renderWithProviders(<ExportRequest reportKey="blocked-accounts" perUserAllowed filters={{ level: "3" }} />);
    // ADM-01: per-user reports always need approval, so there is no opt-in checkbox any more.
    expect(screen.queryByRole("checkbox", { name: /Include per-user rows/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Request export" }));
    expect(await screen.findByText("Export waiting for a second security reviewer")).toBeInTheDocument();
    expect(api.calls[0]!.body).toMatchObject({ include_per_user_rows: true, reason_code: "qa_sample", filters: { level: "3" } });
    // ADM-05: no false "you will be notified" claim; the requester is emailed on approval (controls.py _notify_export).
    expect(screen.queryByText(/You will be notified/)).not.toBeInTheDocument();
  });

  it("bulk lift: dry run first, then a dual-approval request", async () => {
    const api = mockApi({
      "POST security/restrictions/bulk-lift-requests": (c) =>
        (c.body as { dry_run: boolean }).dry_run
          ? { body: { matched: 214, excluded_by_reason: { l4: 3, high_risk: 5 }, sample: [] } }
          : { status: 202, body: { status: "approval_pending", approval_request_id: "bl1", action_type: "security.restriction.bulk_lift", required_approver_role: "security_reviewer", expires_at: inHours(72) } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<BulkLift />);
    expect(screen.getByRole("button", { name: "Request bulk lift" })).toBeDisabled();
    await fill(screen.getByLabelText("Rule key"), "HC-01");
    await fill(screen.getByLabelText(/^Reason/), "HC-01 false-positive surge on 2 Nov");
    await userEvent.click(screen.getByRole("button", { name: "Check matches (dry run)" }));
    expect(await screen.findByText("214")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Request bulk lift" }));
    expect(await screen.findByText("Waiting for a second approver")).toBeInTheDocument();
    expect(api.calls.map((c) => (c.body as { dry_run: boolean }).dry_run)).toEqual([true, false]);
  });
});

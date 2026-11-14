import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { DRAFT_TTL_MS, loadDraft, saveDraft } from "../lib/draft";
import { AccountStatus } from "./AccountStatus";
import { RestrictedStatus } from "./RestrictedStatus";
import { UnblockRequestForm } from "./UnblockRequestForm";
import { UnblockLookup } from "./UnblockStatus";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

let restore: (() => void) | undefined;
afterEach(() => restore?.());


/**
 * FE-24: key-by-key typing of long text re-renders the form (and its draft autosave) per
 * character, which exceeded the 5 s default under a full parallel run. Paste fires one input.
 */
async function fill(el: HTMLElement, text: string) {
  await userEvent.click(el);
  await userEvent.paste(text);
}

const l3Status = {
  level: 3,
  family: "sharing",
  scope: "learning_access",
  // Far future: an L3 whose end has passed renders different copy (see "pause period ended").
  starts_at: "2099-11-03T04:45:00.000Z",
  until: "2099-11-04T04:45:00.000Z",
  case_ref: "SEC-2611-7KQ4MZ",
  reasons: [{ explanation_key: "sh01.overlap_two_devices", text: "Video and tests were used at the same time on 2 devices on 4 different days." }],
  available_actions: ["request_review", "manage_devices", "contact_support"],
  unblock_request: { reference: null, state: null },
  policy: { max_trusted_devices: 3, max_concurrent_sessions: 2, max_concurrent_streams: 1 },
};
const me = {
  user: { id: "u1", email: "ananya@example.com", email_verified: true, mobile_masked: "+91 98xxxxxx21", mobile_verified: false },
  profile: { full_name: "Ananya Reddy" },
  organizations: [],
};
const devices = {
  data: [
    { user_device_id: "d1", label: "Chrome on Windows", trust_status: "trusted", last_used_at: "2026-11-03T10:12:40.000Z", approx_region: "Telangana" },
    { user_device_id: "d2", label: "Android · Redmi 12", trust_status: "trusted", approx_region: "Karnataka" },
  ],
};

describe("RestrictedStatus (PUB-021 / L3 / L4)", () => {
  it("renders the verbatim L3 copy and links the review form with the case", async () => {
    restore = mockApi({ "GET me/security/status": { body: l3Status } }).restore;
    renderWithProviders(<RestrictedStatus />);
    expect(await screen.findByRole("heading", { name: /Learning access paused until/ })).toBeInTheDocument();
    expect(screen.getByText("SEC-2611-7KQ4MZ")).toBeInTheDocument();
    expect(screen.getByText(/paused video lessons, tests and practice on your account for 24 hours/)).toBeInTheDocument();
    expect(screen.getByText(/A person, not a computer, will look at it, usually within 24 hours/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Request a review" })).toHaveAttribute("href", "/unblock-request?case_ref=SEC-2611-7KQ4MZ");
    expect(screen.getByRole("img", { name: "Level 3 of 4" })).toBeInTheDocument();
  });

  it("renders the L4 suspension copy", async () => {
    restore = mockApi({ "GET me/security/status": { body: { ...l3Status, level: 4, reasons: [{ explanation_key: "sharing.multi_person", text: "Your login was shared with several people" }] } } }).restore;
    renderWithProviders(<RestrictedStatus />);
    expect(await screen.findByRole("heading", { name: "Your account is suspended pending review" })).toBeInTheDocument();
    expect(screen.getByText(/Reason: Your login was shared with several people\./)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Contact support" })).toBeInTheDocument();
  });

  it("offers re-verification after a lift (AUTH-21/22) and sends the student to sign in again", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const api = mockApi({
      "GET me/security/status": { body: { ...l3Status, lift_pending: true, available_actions: ["reverify", "request_review", "manage_devices", "contact_support"], unblock_request: { reference: "APL-2611-0HH73B", state: "approved" } } },
      "GET security/unblock-requests/by-reference/APL-2611-0HH73B": { body: { request_id: "r1", reference: "APL-2611-0HH73B", case_ref: "SEC-2611-7KQ4MZ", state: "approved", timeline: [] } },
      "POST auth/reverify/start": { body: { sent_to: "an****@example.com", expires_in_seconds: 300 } },
      "POST auth/reverify/complete": { body: { result: "reverified", restriction_ended: true, sessions_revoked: 1, next: "login" } },
    });
    restore = api.restore;
    try {
      renderWithProviders(<RestrictedStatus />);
      await userEvent.click(await screen.findByRole("button", { name: "Email me a code" }));
      expect(await screen.findByText("Code sent to an****@example.com.")).toBeInTheDocument();
      await userEvent.type(screen.getByLabelText(/6-digit code/), "582014");
      await userEvent.click(screen.getByRole("button", { name: "Confirm and restore access" }));
      await waitFor(() => expect(assign).toHaveBeenCalledWith("/login?reason=reverified"));
      expect(api.calls.find((c) => c.path === "auth/reverify/start")?.body).toEqual({ channel: "email" });
      const done = api.calls.find((c) => c.path === "auth/reverify/complete")!;
      expect(done.body).toEqual({ otp_code: "582014" });
      expect(done.headers["idempotency-key"]).toBeTruthy();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("does not claim 'paused until <past date>' once the L3 end has passed (still enforced until re-verified)", async () => {
    restore = mockApi({
      "GET me/security/status": { body: { ...l3Status, starts_at: "2026-01-01T04:45:00.000Z", until: "2026-01-02T04:45:00.000Z", available_actions: ["reverify", "request_review", "manage_devices", "contact_support"] } },
    }).restore;
    renderWithProviders(<RestrictedStatus />);
    expect(await screen.findByRole("heading", { name: "Learning access is still paused" })).toBeInTheDocument();
    expect(screen.getByText(/The pause period ended on .*Confirm it.s you above to get your access back\./)).toBeInTheDocument();
  });

  it("offers SMS only with a verified mobile and sends the reviewed device list", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const api = mockApi({
      "GET me/security/status": { body: { ...l3Status, lift_pending: true, available_actions: ["reverify", "request_review", "manage_devices", "contact_support"] } },
      "GET me": { body: me },
      "GET me/devices": { body: { data: [{ ...devices.data[0], is_current: true }, devices.data[1]] } },
      "POST auth/reverify/start": { body: { sent_to: "an****@example.com", expires_in_seconds: 300 } },
      "POST auth/reverify/complete": { body: { result: "reverified", restriction_ended: true, sessions_revoked: 1, next: "login" } },
    });
    restore = api.restore;
    try {
      renderWithProviders(<RestrictedStatus />);
      await userEvent.click(await screen.findByRole("button", { name: "Email me a code" }));
      // me.user.mobile_verified is false: no SMS option.
      expect(screen.queryByRole("button", { name: "Text me a code" })).not.toBeInTheDocument();
      await userEvent.type(await screen.findByLabelText(/6-digit code/), "582014");
      expect(await screen.findByRole("checkbox", { name: "Chrome on Windows (this device)" })).toBeChecked();
      const other = screen.getByRole("checkbox", { name: "Android · Redmi 12" });
      expect(other).not.toBeChecked();
      await userEvent.click(screen.getByRole("button", { name: "Confirm and restore access" }));
      await waitFor(() => expect(assign).toHaveBeenCalledWith("/login?reason=reverified"));
      expect(api.calls.find((c) => c.path === "auth/reverify/complete")!.body).toEqual({
        otp_code: "582014",
        devices: [
          { user_device_id: "d1", keep: true },
          { user_device_id: "d2", keep: false },
        ],
      });
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("asks for a new password when re-verification requires one (422 password_reset_required)", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    let n = 0;
    const api = mockApi({
      "GET me/security/status": { body: { ...l3Status, lift_pending: true, available_actions: ["reverify", "request_review", "manage_devices", "contact_support"] } },
      "POST auth/reverify/start": { body: { sent_to: "an****@example.com", expires_in_seconds: 300 } },
      "POST auth/reverify/complete": () =>
        ++n === 1
          ? problem(422, "validation_failed", "Some fields need attention", { errors: [{ field: "new_password", code: "password_reset_required", message: "Choose a new password" }] })
          : { body: { result: "reverified", restriction_ended: true, sessions_revoked: 1, next: "login" } },
    });
    restore = api.restore;
    try {
      renderWithProviders(<RestrictedStatus />);
      await userEvent.click(await screen.findByRole("button", { name: "Email me a code" }));
      await userEvent.type(await screen.findByLabelText(/6-digit code/), "582014");
      await userEvent.click(screen.getByRole("button", { name: "Confirm and restore access" }));
      expect(await screen.findByText(/needs a new password before access returns/)).toBeInTheDocument();
      await userEvent.type(screen.getByLabelText(/New password/), "a-much-longer-passphrase");
      await userEvent.click(screen.getByRole("button", { name: "Confirm and restore access" }));
      await waitFor(() => expect(assign).toHaveBeenCalledWith("/login?reason=reverified"));
      const calls = api.calls.filter((c) => c.path === "auth/reverify/complete");
      expect(calls[1]!.body).toEqual({ otp_code: "582014", new_password: "a-much-longer-passphrase" });
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("shows the account-protection lock from takeover.protect_locked", async () => {
    restore = mockApi({ "GET me/security/status": { body: { ...l3Status, level: 0, family: null, case_ref: null, takeover: { protect_locked: true, step_up_required: false, since: "2026-11-03T10:00:00Z" } } } }).restore;
    renderWithProviders(<RestrictedStatus />);
    expect(await screen.findByRole("heading", { name: "We've secured your account" })).toBeInTheDocument();
  });

  it("shows an error with the request id and keeps the fallback case reference", async () => {
    restore = mockApi({ "GET me/security/status": problem(503, "service_unavailable", "Service unavailable") }).restore;
    renderWithProviders(<RestrictedStatus fallbackCaseRef="SEC-2611-7KQ4MZ" fallbackLevel={4} />);
    expect(await screen.findByText("We couldn't load your account status")).toBeInTheDocument();
    expect(screen.getByText("req-123")).toBeInTheDocument();
    expect(screen.getByText("SEC-2611-7KQ4MZ")).toBeInTheDocument();
  });
});

describe("UnblockRequestForm (UNB-01)", () => {
  const routes = {
    "GET me/security/status": { body: l3Status },
    "GET me": { body: me },
    "GET me/devices": { body: devices },
  };

  it("validates every required field and blocks codes in the explanation", async () => {
    const api = mockApi(routes);
    restore = api.restore;
    renderWithProviders(<UnblockRequestForm caseRef="SEC-2611-7KQ4MZ" />);
    await userEvent.click(await screen.findByRole("button", { name: "Send request" }));
    expect(screen.getByText(/Please fix these 4 problems/)).toBeInTheDocument();
    await fill(screen.getByLabelText(/Your explanation/), "Here is my OTP 482913 so you can check my account quickly");
    await userEvent.click(screen.getByRole("button", { name: "Send request" }));
    expect(screen.getAllByText("Please don't include passwords or codes.").length).toBeGreaterThan(1);
    expect(api.calls.filter((c) => c.method === "POST")).toHaveLength(0);
    // SMS is not verified, so it cannot be chosen
    expect(screen.getByRole("radio", { name: /SMS/ })).toBeDisabled();
  });

  it("submits with an Idempotency-Key and shows the APL reference and status", async () => {
    const api = mockApi({
      ...routes,
      "POST security/unblock-requests": { status: 201, body: { request_id: "r1", reference: "APL-2611-3HX9RB", case_ref: "SEC-2611-7KQ4MZ", state: "submitted", devices_revoked: [{ user_device_id: "d2", label: "Android · Redmi 12" }], sla: { first_response_due: "2026-11-04T10:15:02.000Z" }, acknowledgement_sent_via: ["in_app", "email"] } },
      "GET security/unblock-requests/r1": { body: { request_id: "r1", reference: "APL-2611-3HX9RB", case_ref: "SEC-2611-7KQ4MZ", state: "submitted", timeline: [{ at: "2026-11-03T10:15:02.123Z", state: "submitted" }], appeal: { allowed: false, deadline: null } } },
    });
    restore = api.restore;
    renderWithProviders(<UnblockRequestForm />);
    await userEvent.click(await screen.findByRole("checkbox", { name: "All devices are mine" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "I was travelling / using VPN" }));
    await fill(screen.getByLabelText(/Your explanation/), "I use my laptop for lectures and my phone for notes at the same time.");
    await userEvent.click(screen.getByRole("checkbox", { name: "Chrome on Windows" }));
    await userEvent.click(screen.getByRole("radio", { name: /Email/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: /The information I've given is true/ }));
    await userEvent.click(screen.getByRole("button", { name: "Send request" }));
    expect(await screen.findByText("Request sent")).toBeInTheDocument();
    expect(window.localStorage.getItem("td.unblock.draft.SEC-2611-7KQ4MZ")).toBeNull();
    expect(screen.getAllByText("APL-2611-3HX9RB").length).toBeGreaterThan(0);
    expect(screen.getByText(/We signed out the devices you didn't recognise: Android · Redmi 12/)).toBeInTheDocument();
    const post = api.calls.find((c) => c.method === "POST")!;
    expect(post.headers["idempotency-key"]).toMatch(/^[0-9a-f-]{36}$/);
    expect(post.body).toMatchObject({
      case_ref: "SEC-2611-7KQ4MZ",
      submit: true,
      what_happened: ["all_devices_mine", "travelling_or_vpn"],
      recognised_user_device_ids: ["d1"],
      none_recognised: false,
      preferred_contact: "email",
      declaration: true,
    });
    expect(JSON.stringify(post.body)).not.toMatch(/password|otp/i);
  });

  it("replaces the form with the status when a request is already open", async () => {
    const api = mockApi({
      ...routes,
      "GET me/security/status": { body: { ...l3Status, unblock_request: { reference: "APL-2611-3HX9RB", state: "escalated" } } },
      "GET security/unblock-requests/by-reference/APL-2611-3HX9RB": { body: { request_id: "r1", reference: "APL-2611-3HX9RB", case_ref: "SEC-2611-7KQ4MZ", state: "escalated", timeline: [] } },
    });
    restore = api.restore;
    renderWithProviders(<UnblockRequestForm />);
    expect(await screen.findByText("With senior reviewer")).toBeInTheDocument();
    expect(screen.getByText(/Your case is with a senior reviewer for a second check/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send request" })).not.toBeInTheDocument();
  });
});

describe("UnblockLookup (UNB-05/06)", () => {
  it("validates the reference format, then shows info-requested state and sends a reply", async () => {
    const api = mockApi({
      "GET security/unblock-requests/by-reference/APL-2611-3HX9RB": {
        body: {
          request_id: "r1",
          reference: "APL-2611-3HX9RB",
          case_ref: "SEC-2611-7KQ4MZ",
          state: "info_requested",
          timeline: [{ at: "2026-11-03T15:40:00.000Z", state: "info_requested", message: "Please tell us which city you were in on 30–31 October." }],
          info_requested_due: "2026-11-10T15:40:00.000Z",
        },
      },
      "POST security/unblock-requests/r1/responses": { body: { state: "under_review" } },
    });
    restore = api.restore;
    renderWithProviders(<UnblockLookup />);
    await userEvent.type(screen.getByLabelText(/Request reference/), "nope");
    await userEvent.click(screen.getByRole("button", { name: "Check status" }));
    expect(screen.getByText(/like APL-2611-3HX9RB/)).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText(/Request reference/));
    await userEvent.type(screen.getByLabelText(/Request reference/), "apl-2611-3hx9rb");
    await userEvent.click(screen.getByRole("button", { name: "Check status" }));
    expect(await screen.findByText("We need more information")).toBeInTheDocument();
    expect(screen.getByText(/Please tell us which city you were in/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reply" }));
    await fill(screen.getByLabelText(/Your reply/), "I was in Pune on 30 and 31 October, at my family home.");
    await userEvent.click(screen.getByRole("button", { name: "Send reply" }));
    await waitFor(() => expect(api.calls.some((c) => c.path === "security/unblock-requests/r1/responses")).toBe(true));
    expect(api.calls.some((c) => c.path === "security/unblock-requests/by-reference/APL-2611-3HX9RB" && c.method === "GET")).toBe(true);
  });

  it("does not reveal other people's requests", async () => {
    restore = mockApi({ "GET security/unblock-requests/by-reference/APL-2611-3HX9RB": problem(404, "not_found", "Not found") }).restore;
    renderWithProviders(<UnblockLookup initialReference="APL-2611-3HX9RB" />);
    expect(await screen.findByText(/We couldn't find request APL-2611-3HX9RB on your account/)).toBeInTheDocument();
  });
});

describe("AccountStatus (STU-026, FE-04/INV-02)", () => {
  it("shows the L3 panel, case details, limits and history from SEC-01/SEC-02", async () => {
    const api = mockApi({
      "GET me/security/status": { body: { ...l3Status, history: [{ level: 2, starts_at: "2026-09-01T00:00:00Z", ended_at: "2026-09-02T00:00:00Z", end_reason: "deescalated" }] } },
      "GET me/security/cases/SEC-2611-7KQ4MZ": {
        body: { case_ref: "SEC-2611-7KQ4MZ", family: "sharing", level: 3, status: "open", restriction: { level: 3, until: null, state: "active" }, notes: [{ at: "2026-11-03T06:00:00Z", body: "We are looking at it." }], decision: null },
      },
    });
    restore = api.restore;
    renderWithProviders(<AccountStatus />);
    expect(await screen.findByRole("heading", { name: /Learning access paused until/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Request a review" })).toHaveAttribute("href", "/unblock-request?case_ref=SEC-2611-7KQ4MZ");
    expect(await screen.findByText("We are looking at it.")).toBeInTheDocument();
    expect(screen.getByText("Lowered automatically")).toBeInTheDocument();
    expect(screen.getByText("Signed-in devices at once").nextSibling).toHaveTextContent("2");
    expect(api.calls.filter((c) => c.path === "me/security/status")).toHaveLength(1);
  });
});

describe("AccountStatus for staff (live audit staff-portals.md F4, admin.md F8)", () => {
  const clear = { level: 0, case_ref: null, reasons: [], available_actions: [], history: [], policy: { max_trusted_devices: 3, max_concurrent_sessions: 2, max_concurrent_streams: 1 } };

  it("students keep the student links", async () => {
    restore = mockApi({ "GET me/security/status": { body: clear }, "GET me/grants": { body: { portals: ["/app"] } } }).restore;
    renderWithProviders(<AccountStatus />);
    expect(await screen.findByRole("link", { name: "Go to my dashboard" })).toHaveAttribute("href", "/app");
    expect(screen.getByRole("link", { name: "Contact support" })).toHaveAttribute("href", "/app/support/new");
    expect(screen.getByRole("link", { name: "Check a review request" })).toBeInTheDocument();
    expect(screen.getByText("Videos playing at once")).toBeInTheDocument();
  });

  it("staff go to their own portal, without the student support / review links or video limit", async () => {
    restore = mockApi({ "GET me/security/status": { body: clear }, "GET me/grants": { body: { portals: ["/trainer"], data: [{ role_key: "trainer" }] } } }).restore;
    renderWithProviders(<AccountStatus />);
    expect(await screen.findByRole("link", { name: "Go to the Trainer portal" })).toHaveAttribute("href", "/trainer");
    expect(screen.getByRole("link", { name: "Back to the Trainer portal" })).toHaveAttribute("href", "/trainer");
    expect(screen.queryByRole("link", { name: "Go to my dashboard" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Contact support" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Check a review request" })).not.toBeInTheDocument();
    expect(screen.queryByText("Videos playing at once")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Privacy requests" })).toHaveAttribute("href", "/app/settings/privacy");
    expect(screen.queryByRole("link", { name: /\/app\/support/ })).not.toBeInTheDocument();
    expect(document.querySelector('a[href^="/app/support"]')).toBeNull();
  });
});

describe("Unblock request draft autosave (FE-15 / UNB-02)", () => {
  const routes = {
    "GET me/security/status": { body: l3Status },
    "GET me": { body: me },
    "GET me/devices": { body: devices },
  };
  afterEach(() => window.localStorage.clear());

  it("restores a saved draft on this device, without the declaration", async () => {
    window.localStorage.setItem(
      "td.unblock.draft.SEC-2611-7KQ4MZ",
      JSON.stringify({ what_happened: ["all_devices_mine"], explanation: "Saved explanation text from before", recognised: ["d1", "gone"], none_recognised: false, contact: "email", saved_at: Date.now() }),
    );
    restore = mockApi(routes).restore;
    renderWithProviders(<UnblockRequestForm />);
    expect(await screen.findByLabelText(/Your explanation/)).toHaveValue("Saved explanation text from before");
    expect(screen.getByRole("checkbox", { name: "All devices are mine" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Chrome on Windows" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /The information I've given is true/ })).not.toBeChecked();
    expect(screen.getByText(/Draft saved on this device/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Discard draft" }));
    expect(screen.getByLabelText(/Your explanation/)).toHaveValue("");
    expect(window.localStorage.getItem("td.unblock.draft.SEC-2611-7KQ4MZ")).toBeNull();
  });

  it("saves while typing and drops expired drafts", async () => {
    expect(loadDraft("SEC-X", Date.now())).toBeNull();
    saveDraft("SEC-X", { what_happened: [], explanation: "abc", recognised: [], none_recognised: false, contact: "in_app" }, 1000);
    expect(loadDraft("SEC-X", 1000 + DRAFT_TTL_MS - 1)?.explanation).toBe("abc");
    expect(loadDraft("SEC-X", 1000 + DRAFT_TTL_MS + 1)).toBeNull();
    expect(window.localStorage.getItem("td.unblock.draft.SEC-X")).toBeNull();

    restore = mockApi(routes).restore;
    renderWithProviders(<UnblockRequestForm />);
    await userEvent.type(await screen.findByLabelText(/Your explanation/), "typed text");
    await waitFor(() => expect(loadDraft("SEC-2611-7KQ4MZ")?.explanation).toBe("typed text"), { timeout: 3000 });
  });
});

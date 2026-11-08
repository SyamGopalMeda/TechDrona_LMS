import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "../test/mock-api";
import { readPendingLogin, writePendingLogin } from "../lib/pending-login";
import { LoginForm } from "./LoginForm";
import { SessionChoice } from "./SessionChoice";
import { GuardianConsent } from "./GuardianConsent";
import { SignupForm } from "./SignupForm";

/**
 * FE-24: typing long strings key-by-key re-renders the whole form per character and made these
 * tests exceed the 5 s default under parallel load. Pasting fires one input event per field,
 * which is all these tests need (no per-keystroke behaviour is under test).
 */
async function fill(el: HTMLElement, text: string) {
  await userEvent.click(el);
  await userEvent.paste(text);
}

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: push, back: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }) }));

let restore: (() => void) | undefined;
beforeEach(() => {
  push.mockReset();
  sessionStorage.clear();
});
afterEach(() => restore?.());

describe("LoginForm (AUTH-06)", () => {
  it("signs in and goes to the safe next path, sending CSRF + idempotency headers", async () => {
    const api = mockApi({ "POST auth/login": { body: { result: "authenticated", session: { scope: "full" }, redirect: "/app" } } });
    restore = api.restore;
    renderWithProviders(<LoginForm next="/app/learning" />);
    await fill(screen.getByLabelText(/Email or mobile/), "ananya@example.com");
    await fill(screen.getByLabelText(/^Password/), "correct-horse-battery-staple");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/app/learning"));
    const call = api.calls[0]!;
    expect(call.body).toEqual({ identifier: "ananya@example.com", password: "correct-horse-battery-staple", remember_device: false });
    expect(call.headers["x-csrf-token"]).toBe("test-csrf-token");
    expect(call.headers["idempotency-key"]).toBeTruthy();
  });

  it("routes a new device to OTP without storing the password", async () => {
    const api = mockApi({
      "POST auth/login": { body: { result: "device_verification_required", channels: [{ channel: "sms", destination_masked: "+91 98xxxxxx21" }], alternatives: ["totp"] } },
    });
    restore = api.restore;
    renderWithProviders(<LoginForm />);
    await fill(screen.getByLabelText(/Email or mobile/), "ananya@example.com");
    await fill(screen.getByLabelText(/^Password/), "correct-horse-battery-staple");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/login/verify-device"));
    expect(readPendingLogin()?.channels?.[0]?.destination_masked).toBe("+91 98xxxxxx21");
    expect(JSON.stringify(sessionStorage)).not.toContain("correct-horse");
  });

  it("shows the non-enumerating invalid-credentials copy with the request id", async () => {
    const api = mockApi({ "POST auth/login": problem(401, "invalid_credentials", "Sign-in failed") });
    restore = api.restore;
    renderWithProviders(<LoginForm />);
    await fill(screen.getByLabelText(/Email or mobile/), "x@example.com");
    await fill(screen.getByLabelText(/^Password/), "wrong-password-123456");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("That email/mobile and password don't match. Check them and try again.")).toBeInTheDocument();
    expect(screen.getByText("req-123")).toBeInTheDocument();
    expect(screen.getByLabelText(/^Password/)).toHaveValue("");
    expect(api.navigate).not.toHaveBeenCalled();
  });

  it("sends a session-cap problem to the chooser", async () => {
    const api = mockApi({
      "POST auth/login": problem(409, "session_cap_reached", "You're signed in on 2 devices", {
        max_concurrent: 2,
        sessions: [{ session_id: "s1", device_label: "Chrome on Windows", last_active_at: "2026-11-03T09:58:11.000Z", has_active_attempt: false }],
      }),
    });
    restore = api.restore;
    renderWithProviders(<LoginForm />);
    await fill(screen.getByLabelText(/Email or mobile/), "x@example.com");
    await fill(screen.getByLabelText(/^Password/), "correct-horse-battery-staple");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/login/session-choice"));
    expect(readPendingLogin()?.capSessions).toHaveLength(1);
  });

  it("validates required fields without calling the API", async () => {
    const api = mockApi({});
    restore = api.restore;
    renderWithProviders(<LoginForm />);
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(screen.getByText("Enter your email or mobile number.")).toBeInTheDocument();
    expect(api.calls).toHaveLength(0);
  });
});

describe("SessionChoice (AUTH-14)", () => {
  it("pre-selects the oldest session without a test and warns about active attempts", async () => {
    writePendingLogin({
      next: "/app",
      capSessions: [
        { session_id: "old", device_label: "Chrome on Windows", approx_region: "Telangana", last_active_at: "2026-11-03T08:00:00Z" },
        { session_id: "busy", device_label: "Android phone", last_active_at: "2026-11-03T07:00:00Z", has_active_attempt: true },
      ],
    });
    const api = mockApi({ "POST auth/session-choice": { body: { result: "authenticated", redirect: "/app" } } });
    restore = api.restore;
    renderWithProviders(<SessionChoice />);
    const old = await screen.findByRole("radio", { name: /Chrome on Windows/ });
    expect(old).toBeChecked();
    expect(screen.getByText(/Signing out this device would interrupt your test/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Sign out selected and continue" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/app"));
    expect(api.calls[0]!.body).toEqual({ end_session_id: "old", cancel: false, confirm_attempt_session: false });
  });

  it("requires explicit confirmation to end a session with a test in progress", async () => {
    writePendingLogin({
      capSessions: [
        { session_id: "a", device_label: "Laptop", last_active_at: "2026-11-03T08:00:00Z" },
        { session_id: "busy", device_label: "Android phone", last_active_at: "2026-11-03T07:00:00Z", has_active_attempt: true },
      ],
    });
    const api = mockApi({ "POST auth/session-choice": { body: { result: "authenticated" } } });
    restore = api.restore;
    renderWithProviders(<SessionChoice />);
    await userEvent.click(await screen.findByRole("radio", { name: /Android phone/ }));
    await userEvent.click(screen.getByRole("button", { name: "Sign out selected and continue" }));
    expect(api.calls).toHaveLength(0);
    await userEvent.click(screen.getByRole("checkbox", { name: /will be interrupted/ }));
    await userEvent.click(screen.getByRole("button", { name: "Sign out selected and continue" }));
    await waitFor(() => expect(api.calls[0]?.body).toEqual({ end_session_id: "busy", cancel: false, confirm_attempt_session: true }));
  });

  it("shows the expired state when nothing is pending", async () => {
    restore = mockApi({}).restore;
    renderWithProviders(<SessionChoice />);
    expect(await screen.findByText("This sign-in has expired")).toBeInTheDocument();
  });
});

async function fillDob(day: string, month: string, year: string) {
  await userEvent.selectOptions(screen.getByLabelText("Day"), day);
  await userEvent.selectOptions(screen.getByLabelText("Month"), month);
  await userEvent.selectOptions(screen.getByLabelText("Year"), year);
}

describe("SignupForm (AUTH-01)", () => {
  it("shows an error summary and does not submit an empty form", async () => {
    const api = mockApi({});
    restore = api.restore;
    renderWithProviders(<SignupForm />);
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(screen.getByText(/Please fix these/)).toBeInTheDocument();
    expect(screen.getAllByText("Enter your full name.").length).toBeGreaterThan(0);
    expect(api.calls).toHaveLength(0);
  });

  it("applies the under-18 gate: guardian notice, no optional consents, adult-only purposes not granted", async () => {
    const api = mockApi({ "POST auth/signup": { status: 201, body: { user_id: "u1", status: "pending_guardian_consent", is_minor: true, next_steps: ["guardian_consent"] } } });
    restore = api.restore;
    renderWithProviders(<SignupForm />);
    await fill(screen.getByLabelText(/Full name/), "Ravi Kumar");
    await fill(screen.getByLabelText(/^Email/), "ravi@example.com");
    const year = String(new Date().getFullYear() - 15);
    await fillDob("5", "June", year);
    expect(screen.getByText("A parent or guardian needs to agree")).toBeInTheDocument();
    expect(screen.queryByText(/Product news and offers by email/)).not.toBeInTheDocument();
    await fill(screen.getByLabelText(/Their name/), "Sunita Kumar");
    await fill(screen.getByLabelText(/Their email/), "sunita@example.com");
    await fill(screen.getByLabelText(/^Password/), "a-long-enough-password");
    await userEvent.click(screen.getByRole("checkbox", { name: /I agree to the/ }));
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    await screen.findByText("Almost there");
    const body = api.calls[0]!.body as { consents: { purpose: string; granted: boolean }[]; date_of_birth: string; guardian: unknown };
    expect(body.date_of_birth).toBe(`${year}-06-05`);
    expect(body.guardian).toEqual({ name: "Sunita Kumar", email: "sunita@example.com", phone: null, relationship: "parent" });
    expect(body.consents.filter((c) => c.granted).map((c) => c.purpose).sort()).toEqual(["core_service", "privacy_notice", "terms"]);
  });

  it("offers unticked optional consents to adults and maps server field errors", async () => {
    const api = mockApi({
      "POST auth/signup": problem(400, "validation_failed", "Check your details", { errors: [{ field: "password", code: "password_breached", message: "This password appears in a data breach. Choose another." }] }),
    });
    restore = api.restore;
    renderWithProviders(<SignupForm />);
    await fill(screen.getByLabelText(/Full name/), "Ananya Reddy");
    await fill(screen.getByLabelText(/^Email/), "ananya@example.com");
    await fillDob("12", "April", "2000");
    const marketing = screen.getByRole("checkbox", { name: /Product news and offers by email/ });
    expect(marketing).not.toBeChecked();
    await fill(screen.getByLabelText(/^Password/), "password-password-1");
    await userEvent.click(screen.getByRole("checkbox", { name: /I agree to the/ }));
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect((await screen.findAllByText("This password appears in a data breach. Choose another.")).length).toBeGreaterThan(0);
  });
});

describe("GuardianConsent (AUTH-25/26/27)", () => {
  it("renders the real view, requires the declaration and sends it with the decision", async () => {
    const tok = "tok-0123456789abcdef";
    const api = mockApi({
      [`GET auth/guardian-consent/${tok}`]: {
        body: {
          child_first_name: "Ravi",
          status: "pending",
          relationship: "parent",
          notice_version: "2026-11-01",
          items: [
            { purpose: "core_service", item: "A", required: true },
            { purpose: "assessment_integrity", item: "G", required: false },
          ],
          unavailable_for_minors: ["marketing_email"],
          contact_masked: "s****@example.com",
        },
      },
      [`POST auth/guardian-consent/${tok}/verify-contact`]: { body: { sent_to: "s****@example.com" } },
      [`POST auth/guardian-consent/${tok}/decision`]: { body: { status: "verified", child_status: "active" } },
    });
    restore = api.restore;
    renderWithProviders(<GuardianConsent token={tok} />);
    expect(await screen.findByText(/Ravi wants to use Tech Drona/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Send code" }));
    await screen.findByText(/We sent a code to s\*\*\*\*@example.com/);
    await userEvent.type(screen.getByLabelText(/6-digit code/), "123456");
    await userEvent.click(screen.getByRole("button", { name: "I agree" }));
    expect(await screen.findByText("Please confirm you are the parent or legal guardian.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox", { name: /parent or legal guardian/ }));
    await userEvent.click(screen.getByRole("button", { name: "I agree" }));
    expect(await screen.findByText(/consent recorded/)).toBeInTheDocument();
    expect(api.calls.find((c) => c.path.endsWith("/decision"))?.body).toEqual({ decision: "consent", otp_code: "123456", declaration: true });
  });
});

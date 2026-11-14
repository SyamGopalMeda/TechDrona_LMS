import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "../test/mock-api";
import { readPendingLogin, writePendingLogin } from "../lib/pending-login";
import { MfaForm } from "./MfaForm";
import { LoginForm } from "./LoginForm";
import { ForgotPasswordForm, ResetPasswordForm, isPlausibleResetToken } from "./PasswordRecovery";
import { AuthCard, OrDivider } from "./shared";
import { resetIntegrationsCache } from "@/components/shell/Integrations";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

let restore: (() => void) | undefined;
beforeEach(() => sessionStorage.clear());
afterEach(() => {
  restore?.();
  restore = undefined;
  push.mockReset();
});

describe("MfaForm (PUB-012 MFA step)", () => {
  it("hands a device-cap result over to device verification instead of dead-ending", async () => {
    writePendingLogin({ next: "/app", mfaMethods: ["totp", "recovery_code"] });
    restore = mockApi({
      "POST auth/mfa/verify": problem(409, "device_cap_reached", "Device limit reached", {
        detail: "You've reached your trusted-device limit. Remove a device to continue here.",
        devices: [{ user_device_id: "d1", label: "Chrome on Windows", last_used_at: "2026-10-20T10:00:00Z" }],
        max_trusted: 3,
      }),
    }).restore;
    renderWithProviders(<MfaForm />);
    await userEvent.type(await screen.findByLabelText(/Authenticator code/), "123456");
    await userEvent.click(screen.getByRole("button", { name: "Verify" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/login/verify-device"));
    expect(readPendingLogin()?.channels?.[0]?.channel).toBe("email");
  });

  it("says the log-in has expired up front when there is no sign-in in progress", async () => {
    renderWithProviders(<MfaForm />);
    expect(await screen.findByText("This log-in has expired")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Log in again" })).toHaveAttribute("href", "/login");
    expect(screen.queryByLabelText(/Authenticator code/)).not.toBeInTheDocument();
  });
});

describe("Reset password link (PUB-013)", () => {
  it("recognises link tokens by shape", () => {
    expect(isPlausibleResetToken("Abc_def-1234567890XYZ")).toBe(true);
    expect(isPlausibleResetToken("invalid-token")).toBe(false);
    expect(isPlausibleResetToken("a".repeat(129))).toBe(false);
    expect(isPlausibleResetToken("has spaces in it 123456")).toBe(false);
  });

  it("shows the expired card instead of the form for a malformed token", () => {
    renderWithProviders(<ResetPasswordForm token="invalid-token" />);
    expect(screen.getByText("This reset link doesn't work")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Request a new link" })).toHaveAttribute("href", "/forgot-password");
    expect(screen.queryByLabelText(/New password/)).not.toBeInTheDocument();
  });

  it("shows the full-width form for a well-formed token", () => {
    renderWithProviders(<ResetPasswordForm token="Abc_def-1234567890XYZ" />);
    expect(screen.getByLabelText(/^New password/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Set new password" })).toHaveClass("w-full");
  });
});

describe("Auth consistency (UI audit: one verb, full-width submit)", () => {
  it("uses 'Log in' and a full-width submit, with a text keyboard for email or mobile", () => {
    renderWithProviders(<LoginForm />);
    const submit = screen.getByRole("button", { name: "Log in" });
    expect(submit).toHaveClass("w-full");
    expect(screen.getByLabelText(/Email or mobile/)).not.toHaveAttribute("inputmode");
    expect(screen.getByRole("link", { name: "Forgot password?" })).toHaveAttribute("href", "/forgot-password");
  });

  it("links back to 'log in' from password recovery", () => {
    renderWithProviders(<ForgotPasswordForm />);
    expect(screen.getByRole("link", { name: "Back to log in" })).toHaveAttribute("href", "/login");
    expect(screen.getByRole("button", { name: "Send reset instructions" })).toHaveClass("w-full");
  });

  it("says reset links can't be sent while email isn't connected, instead of pretending", async () => {
    resetIntegrationsCache();
    const api = mockApi({ "GET public/integrations": { body: { integrations: { email: false, sms: false }, simple_auth: true } } });
    restore = () => {
      api.restore();
      resetIntegrationsCache();
    };
    renderWithProviders(<ForgotPasswordForm />);
    expect(await screen.findByText(/reset links can.t be sent\. Ask your Tech Drona admin to set a new password for you\./)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send reset instructions" })).not.toBeInTheDocument();
    expect(api.calls.some((c) => c.path === "auth/password/forgot")).toBe(false);
  });

  it("renders the auth card heading at page level and a decorative divider", () => {
    render(
      <AuthCard title="Log in">
        <OrDivider />
      </AuthCard>,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Log in" })).toHaveClass("font-extrabold");
    expect(screen.getByText("or")).toHaveAttribute("aria-hidden", "true");
  });
});

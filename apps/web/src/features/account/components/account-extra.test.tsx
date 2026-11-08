import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { GuardianPending } from "./GuardianPending";
import { DevicePolicyCard, LoginHistoryCard } from "./SecurityActivity";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

let restore: (() => void) | undefined;
afterEach(() => restore?.());

describe("Security activity (INV-19: device policy + login history)", () => {
  it("shows the published limits from me/device-policy", async () => {
    restore = mockApi({
      "GET me/device-policy": {
        body: { devices: { max_trusted: 3, max_replacements_per_30d: 2, trusted_inactivity_expiry_days: 90 }, sessions: { max_concurrent: 2, idle_minutes: 30, absolute_hours: 24 }, streams: { max_concurrent: 1 } },
      },
    }).restore;
    renderWithProviders(<DevicePolicyCard />);
    expect((await screen.findByText("Trusted devices")).nextSibling).toHaveTextContent("3");
    expect(screen.getByText("Signed out after inactivity (minutes)").nextSibling).toHaveTextContent("30");
  });

  it("labels sign-in attempts from me/login-history", async () => {
    restore = mockApi({
      "GET me/login-history": {
        body: {
          attempts: [
            { at: "2026-11-03T10:00:00Z", method: "password", mfa_method: "totp", result: "success", ip: "49.36.112.18" },
            { at: "2026-11-02T10:00:00Z", method: "password", mfa_method: null, result: "bad_credentials", ip: null },
          ],
          ended_sessions: [],
        },
      },
    }).restore;
    renderWithProviders(<LoginHistoryCard />);
    expect(await screen.findByText("Signed in")).toBeInTheDocument();
    expect(screen.getByText("Wrong password")).toBeInTheDocument();
    expect(screen.getByText(/Password \+ Authenticator app/)).toBeInTheDocument();
  });
});

describe("GuardianPending (/app/guardian-consent, INV-10)", () => {
  it("explains the pending guardian decision", async () => {
    restore = mockApi({ "GET me": { body: { user: { id: "u1", status: "pending_guardian_consent", is_minor: true } } } }).restore;
    renderWithProviders(<GuardianPending />);
    expect(await screen.findByText("Waiting for your parent or guardian")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "contact support" })).toHaveAttribute("href", "/app/support/new");
  });

  it("says nothing is pending for active accounts", async () => {
    restore = mockApi({ "GET me": { body: { user: { id: "u1", status: "active" } } } }).restore;
    renderWithProviders(<GuardianPending />);
    expect(await screen.findByText("Your parent or guardian has already responded")).toBeInTheDocument();
  });
});

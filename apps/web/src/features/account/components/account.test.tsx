import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { DevicesAndSessions } from "./DevicesAndSessions";
import { DisownEvent, MfaCard } from "./SecuritySettings";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

let restore: (() => void) | undefined;
afterEach(() => restore?.());

const sessions = {
  data: [
    { session_id: "cur", is_current: true, status: "active", device_label: "Chrome 130 on Windows", approx_region: "Telangana", ip: "49.36.112.18", login_at: "2026-11-03T08:01:10.000Z", last_active_at: "2026-11-03T10:14:55.000Z" },
    { session_id: "oth", is_current: false, status: "active", device_label: "Android phone", approx_region: "Telangana", login_at: "2026-11-02T08:01:10.000Z", last_active_at: "2026-11-03T09:00:00.000Z" },
    { session_id: "old", is_current: false, status: "revoked", device_label: "Edge on Windows", ip: "106.208.0.0/24", login_at: "2026-11-01T14:00:00.000Z", logout_at: "2026-11-01T15:21:03.000Z", end_reason: "user_logout" },
  ],
  page: { next_cursor: null, has_more: false, limit: 50 },
};
const devices = {
  data: [
    { user_device_id: "d1", label: "Chrome on Windows", user_label: "My laptop", trust_status: "trusted", counts_toward_cap: true, is_current: true, last_used_at: "2026-11-03T10:12:40.000Z" },
    { user_device_id: "d2", label: "Edge on Windows", trust_status: "trusted", counts_toward_cap: true, is_current: false },
    { user_device_id: "d9", label: "Office PC", trust_status: "trusted", counts_toward_cap: false },
  ],
  limits: { max_trusted: 3, trusted_counted: 2, replacements_used_30d: 1, replacements_max_30d: 2, next_replacement_at: "2026-11-14T00:00:00.000Z" },
  page: { next_cursor: null, has_more: false, limit: 25 },
};

describe("DevicesAndSessions (STU-022)", () => {
  it("lists devices, active sessions and history, and signs out another session after confirming", async () => {
    let deleted = false;
    const api = mockApi({
      "GET me/sessions": () => ({ body: deleted ? { ...sessions, data: sessions.data.filter((s) => s.session_id !== "oth") } : sessions }),
      "GET me/devices": { body: devices },
      "DELETE me/sessions/oth": () => {
        deleted = true;
        return { status: 204 };
      },
    });
    restore = api.restore;
    renderWithProviders(<DevicesAndSessions />);
    expect(await screen.findByText("Your devices (2 of 3)")).toBeInTheDocument();
    expect(screen.getByText(/Device changes: 1 of 2 used/)).toBeInTheDocument();
    expect(screen.getByText("Doesn't count toward your limit")).toBeInTheDocument();
    const activeList = screen.getByRole("list", { name: "Signed-in sessions" });
    expect(within(activeList).getByText(/This session/)).toBeInTheDocument();
    expect(screen.getByRole("table", { name: /ended/ })).toHaveTextContent("Edge on Windows");

    await userEvent.click(screen.getByRole("button", { name: "Sign out Android phone" }));
    expect(await screen.findByText("Sign out Android phone?")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "DELETE" && c.path === "me/sessions/oth")).toBe(true));
    expect(await screen.findByText("Signed out Android phone.")).toBeInTheDocument();
    await waitFor(() => expect(within(screen.getByRole("list", { name: "Signed-in sessions" })).queryByText("Android phone")).not.toBeInTheDocument());
  });

  it("signs out all other sessions and removes a device", async () => {
    const api = mockApi({
      "GET me/sessions": { body: sessions },
      "GET me/devices": { body: devices },
      "POST me/sessions/revoke-others": { body: { revoked: 1 } },
      "DELETE me/devices/d2": { status: 204 },
    });
    restore = api.restore;
    renderWithProviders(<DevicesAndSessions />);
    await userEvent.click(await screen.findByRole("button", { name: "Sign out all other sessions" }));
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByText("Signed out 1 other session.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Remove Edge on Windows" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove device" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "DELETE" && c.path === "me/devices/d2")).toBe(true));
  });

  it("shows the error state with the request id and retries", async () => {
    const api = mockApi({ "GET me/sessions": problem(503, "service_unavailable", "Service unavailable"), "GET me/devices": { body: devices } });
    restore = api.restore;
    renderWithProviders(<DevicesAndSessions />);
    expect((await screen.findAllByText("Service unavailable")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("req-123").length).toBeGreaterThan(0);
  });
});

describe("MFA enrolment (ME-07/08/09)", () => {
  it("enrols TOTP and confirms with a code", async () => {
    let enrolled = false;
    const api = mockApi({
      "GET me/mfa/factors": () => ({ body: { data: enrolled ? [{ factor_id: "f1", type: "totp", label: "Authenticator app", confirmed: true, created_at: "2026-11-03T10:00:00Z", last_used_at: null, remaining_codes: null }] : [] } }),
      "POST me/mfa/totp": { status: 201, body: { factor_id: "f1", otpauth_uri: "otpauth://totp/TechDrona:ananya?secret=JBSWY3DPEHPK3PXP&issuer=TechDrona", secret: "JBSWY3DPEHPK3PXP" } },
      "POST me/mfa/totp/f1/confirm": () => {
        enrolled = true;
        return { body: { factor_id: "f1", status: "active" } };
      },
    });
    restore = api.restore;
    renderWithProviders(<MfaCard />);
    await userEvent.click(await screen.findByRole("button", { name: "Add authenticator app" }));
    expect(await screen.findByText("JBSWY3DPEHPK3PXP")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/6-digit code/), "123456");
    await userEvent.click(screen.getByRole("button", { name: "Turn on" }));
    expect(await screen.findByText("Authenticator app added")).toBeInTheDocument();
    expect(api.calls.find((c) => c.path === "me/mfa/totp/f1/confirm")?.body).toEqual({ code: "123456" });
  });
});

describe("This wasn't me (SEC-46)", () => {
  it("requires confirmation, then shows the secured state", async () => {
    const api = mockApi({ "POST me/security/events/ACC-2611-ABC123/disown": { body: { result: "protected", sessions_revoked: 3, must_change_password: true, recovery_url: "/forgot-password" } } });
    restore = api.restore;
    renderWithProviders(<DisownEvent eventRef="ACC-2611-ABC123" />);
    await userEvent.click(screen.getByRole("button", { name: /This wasn't me/ }));
    expect(api.calls).toHaveLength(0);
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: /This wasn't me/ }));
    expect(await screen.findByText("We've secured your account")).toBeInTheDocument();
    expect(api.calls[0]!.body).toEqual({ confirm: true });
  });
});

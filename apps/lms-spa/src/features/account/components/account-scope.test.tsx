import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { accountScope, STUDENT_SCOPE } from "../lib/account-scope";
import { ProfileSettings } from "./ProfileSettings";
import { DevicePolicyCard } from "./SecurityActivity";
import { clearIdentityCache } from "@/lib/api/session-cache";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

let restore: (() => void) | undefined;
afterEach(() => restore?.());

const STUDENT_GRANTS = { portals: ["/app"], data: [{ role_key: "student" }] };
const TRAINER_GRANTS = { portals: ["/trainer"], data: [{ role_key: "trainer" }] };
const ADMIN_GRANTS = { portals: ["/admin"], data: [{ role_key: "super_admin" }] };

const me = {
  user: { id: "u1", email: "a@example.com", email_verified: true, mobile_masked: null },
  profile: { full_name: "Ananya Reddy", graduation_year: 2026, branch: "CSE" },
};

describe("accountScope (shared account pages: who is looking)", () => {
  it("students, unknown grants and staff who are also students get the student scope", () => {
    expect(accountScope(STUDENT_GRANTS)).toEqual(STUDENT_SCOPE);
    expect(accountScope(null)).toEqual(STUDENT_SCOPE);
    expect(accountScope({ portals: [] })).toEqual(STUDENT_SCOPE);
    expect(accountScope({ portals: ["/trainer", "/app"] }, "trainer").student).toBe(true);
  });

  it("staff-only accounts get their own portal as home (the shell they came from first)", () => {
    expect(accountScope(TRAINER_GRANTS)).toEqual({ student: false, home: "/trainer", homeTitle: "the Trainer portal" });
    expect(accountScope(ADMIN_GRANTS)).toEqual({ student: false, home: "/admin", homeTitle: "the Admin portal" });
    // an Admin section (finance) is reached through the Admin portal
    expect(accountScope(ADMIN_GRANTS, "finance")).toMatchObject({ home: "/admin" });
    expect(accountScope({ portals: ["/admin", "/studio"] }, "studio")).toMatchObject({ home: "/studio", homeTitle: "the Content studio portal" });
    // a remembered shell the account can't open is ignored
    expect(accountScope(TRAINER_GRANTS, "studio")).toMatchObject({ home: "/trainer" });
  });
});

describe("ProfileSettings: student-only fields (live audit admin.md F8 / M13)", () => {
  it("asks students for graduation year and branch", async () => {
    restore = mockApi({ "GET me": { body: me }, "GET me/grants": { body: STUDENT_GRANTS } }).restore;
    renderWithProviders(<ProfileSettings />);
    // the fields are filled by an effect after the form first renders
    expect(await screen.findByDisplayValue("2026")).toBe(screen.getByLabelText("Graduation year"));
    expect(screen.getByLabelText(/Branch/)).toHaveValue("CSE");
    expect(screen.getByText(/Contact support if you need to change it/)).toBeInTheDocument();
  });

  it("doesn't ask staff for them, and doesn't overwrite them on save", async () => {
    const api = mockApi({ "GET me": { body: me }, "GET me/grants": { body: TRAINER_GRANTS }, "PATCH me/profile": { body: {} } });
    restore = api.restore;
    renderWithProviders(<ProfileSettings />);
    const name = await screen.findByDisplayValue("Ananya Reddy");
    expect(screen.queryByLabelText("Graduation year")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Branch/)).not.toBeInTheDocument();
    expect(screen.getByText(/Ask an administrator if you need to change it/)).toBeInTheDocument();
    await userEvent.clear(name);
    await userEvent.type(name, "Ravi Kumar");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(api.calls.find((c) => c.method === "PATCH")!.body).toEqual({ full_name: "Ravi Kumar" });
  });

  it("keeps Save changes above the phone tab bar (sticky save bar)", async () => {
    restore = mockApi({ "GET me": { body: me }, "GET me/grants": { body: STUDENT_GRANTS } }).restore;
    renderWithProviders(<ProfileSettings />);
    await screen.findByLabelText("Graduation year");
    const bar = screen.getByTestId("profile-save-bar");
    expect(bar).toContainElement(screen.getByRole("button", { name: "Save changes" }));
    expect(bar.className).toMatch(/\bsticky\b/);
    expect(bar.className).toContain("bottom-[calc(4.5rem+env(safe-area-inset-bottom))]");
  });

  it("falls back to the student form when the grants can't be read", async () => {
    restore = mockApi({ "GET me": { body: me } }).restore; // me/grants -> 404
    renderWithProviders(<ProfileSettings />);
    expect(await screen.findByLabelText("Graduation year")).toBeInTheDocument();
  });
});

describe("DevicePolicyCard on the shared Devices page", () => {
  const policy = { devices: { max_trusted: 3 }, sessions: { max_concurrent: 2 }, streams: { max_concurrent: 1 } };

  it("shows the video limit to students only", async () => {
    const r = mockApi({ "GET me/device-policy": { body: policy }, "GET me/grants": { body: STUDENT_GRANTS } });
    const { unmount } = renderWithProviders(<DevicePolicyCard />);
    expect(await screen.findByText("Videos playing at once")).toBeInTheDocument();
    unmount();
    r.restore();
    // Another account: in the app that is a sign-out + sign-in, which clears the session cache.
    clearIdentityCache();

    restore = mockApi({ "GET me/device-policy": { body: policy }, "GET me/grants": { body: ADMIN_GRANTS } }).restore;
    renderWithProviders(<DevicePolicyCard />);
    expect(await screen.findByText("Trusted devices")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("Videos playing at once")).not.toBeInTheDocument());
  });
});

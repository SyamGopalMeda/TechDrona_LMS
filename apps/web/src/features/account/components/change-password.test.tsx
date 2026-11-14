import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { resetIntegrationsCache } from "@/components/shell/Integrations";
import { RequiredPasswordChange } from "./ChangePasswordForm";
import { SecuritySettings } from "./SecuritySettings";
import { AcceptTerms } from "./AcceptTerms";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace, back: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }) }));

let restore: (() => void) | undefined;
beforeEach(() => {
  replace.mockReset();
  resetIntegrationsCache();
});
afterEach(() => {
  restore?.();
  restore = undefined;
  resetIntegrationsCache();
});

const SIMPLE = { "GET public/integrations": { body: { integrations: { email: false }, simple_auth: true } } };

async function fill(label: RegExp, text: string) {
  await userEvent.click(screen.getByLabelText(label));
  await userEvent.paste(text);
}

describe("RequiredPasswordChange (/change-password)", () => {
  it("saves the new password and continues to next", async () => {
    const api = mockApi({ ...SIMPLE, "POST auth/password/change": { body: { changed: true } } });
    restore = api.restore;
    renderWithProviders(<RequiredPasswordChange next="/admin/users" />);
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
    await fill(/^Current password/, "given-by-admin");
    await fill(/^New password/, "my-own-1");
    await fill(/^Confirm new password/, "my-own-1");
    await userEvent.click(screen.getByRole("button", { name: "Save new password" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/admin/users"));
    const post = api.calls.find((c) => c.method === "POST" && c.path === "auth/password/change")!;
    expect(post.body).toEqual({ current_password: "given-by-admin", new_password: "my-own-1", revoke_other_sessions: true });
  });

  it("shows a mismatch error and does not call the api", async () => {
    const api = mockApi(SIMPLE);
    restore = api.restore;
    renderWithProviders(<RequiredPasswordChange next="/continue" />);
    await fill(/^Current password/, "given-by-admin");
    await fill(/^New password/, "my-own-1");
    await fill(/^Confirm new password/, "my-own-2");
    await userEvent.click(screen.getByRole("button", { name: "Save new password" }));
    expect(await screen.findByText("The passwords don't match.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.path === "auth/password/change")).toBe(false);
    expect(replace).not.toHaveBeenCalled();
  });

  it("says when the current password is wrong", async () => {
    const api = mockApi({ ...SIMPLE, "POST auth/password/change": problem(401, "invalid_credentials", "Wrong password") });
    restore = api.restore;
    renderWithProviders(<RequiredPasswordChange next="/continue" />);
    await fill(/^Current password/, "wrong-one");
    await fill(/^New password/, "my-own-1");
    await fill(/^Confirm new password/, "my-own-1");
    await userEvent.click(screen.getByRole("button", { name: "Save new password" }));
    expect(await screen.findByText("That password isn't right.")).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });
});

describe("required terms after the password change", () => {
  const consents = (granted: string[]) => ({
    body: { notice_version: "2026-11-01", data: ["terms", "privacy_notice", "core_service"].map((p) => ({ purpose: p, state: granted.includes(p) ? "granted" : "not_granted" })) },
  });

  it("a new account that hasn't agreed to the terms goes to /accept-terms next", async () => {
    const api = mockApi({ ...SIMPLE, "POST auth/password/change": { body: { result: "password_changed", other_sessions_revoked: 0 } }, "GET me/consents": consents([]) });
    restore = api.restore;
    renderWithProviders(<RequiredPasswordChange next="/app" />);
    await fill(/^Current password/, "given-by-admin");
    await fill(/^New password/, "my-own-1");
    await fill(/^Confirm new password/, "my-own-1");
    await userEvent.click(screen.getByRole("button", { name: "Save new password" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/accept-terms?next=%2Fapp"));
  });

  it("AcceptTerms grants the missing required purposes, then continues", async () => {
    const api = mockApi({ "GET me/consents": consents(["core_service"]), "POST me/consents": { status: 201, body: {} } });
    restore = api.restore;
    renderWithProviders(<AcceptTerms next="/app" />);
    await userEvent.click(await screen.findByRole("button", { name: "Continue" }));
    expect(await screen.findByText("Tick the box to agree before you continue.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/app"));
    expect(api.calls.filter((c) => c.method === "POST").map((c) => c.body)).toEqual([
      { purpose: "terms", action: "granted", notice_version: "2026-11-01" },
      { purpose: "privacy_notice", action: "granted", notice_version: "2026-11-01" },
    ]);
  });

  it("AcceptTerms skips straight to next when nothing is missing", async () => {
    const api = mockApi({ "GET me/consents": consents(["terms", "privacy_notice", "core_service"]) });
    restore = api.restore;
    renderWithProviders(<AcceptTerms next="/admin" />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/admin"));
  });
});

describe("SecuritySettings in simple authentication", () => {
  it("shows Change password but no 2-step verification section", async () => {
    const api = mockApi({ ...SIMPLE, "GET me/mfa/factors": { body: { data: [] } } });
    restore = api.restore;
    renderWithProviders(<SecuritySettings />);
    expect(await screen.findByRole("button", { name: "Change password" })).toBeInTheDocument();
    await waitFor(() => expect(api.calls.some((c) => c.path === "public/integrations")).toBe(true));
    await waitFor(() => expect(screen.queryByText("2-step verification")).not.toBeInTheDocument());
  });
});

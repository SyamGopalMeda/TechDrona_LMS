import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { SignOutButton } from "./SignOutButton";

const device = vi.hoisted(() => ({ unsynced: 0, clear: vi.fn(async () => undefined) }));
vi.mock("@/features/assessment/lib/device-cleanup", () => ({
  inspectDeviceAttemptData: async () => ({ unsyncedAttempts: device.unsynced }),
  clearDeviceAttemptData: device.clear,
}));

const assign = vi.fn();
let restore: (() => void) | undefined;
beforeEach(() => {
  device.clear.mockClear();
  assign.mockReset();
  vi.stubGlobal("location", { ...window.location, assign });
});
afterEach(() => {
  restore?.();
  vi.unstubAllGlobals();
});

describe("SignOutButton (FE-17)", () => {
  it("clears local test data after logout when nothing is unsynced", async () => {
    device.unsynced = 0;
    const api = mockApi({ "POST auth/logout": { status: 204 } });
    restore = api.restore;
    renderWithProviders(<SignOutButton />);
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/login"));
    expect(device.clear).toHaveBeenCalledTimes(1);
  });

  it("warns about unsynced answers first; 'Stay signed in' keeps the session and the data", async () => {
    device.unsynced = 2;
    const api = mockApi({ "POST auth/logout": { status: 204 } });
    restore = api.restore;
    renderWithProviders(<SignOutButton />);
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    const dialog = await screen.findByRole("dialog", { name: "Some test answers haven't synced yet" });
    expect(within(dialog).getByText(/2 tests have answers saved only on this device/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Stay signed in" }));
    expect(api.calls.some((c) => c.path === "auth/logout")).toBe(false);
    expect(device.clear).not.toHaveBeenCalled();
  });

  it("'Sign out anyway' logs out and clears the device", async () => {
    device.unsynced = 1;
    const api = mockApi({ "POST auth/logout": { status: 204 } });
    restore = api.restore;
    renderWithProviders(<SignOutButton />);
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await userEvent.click(await screen.findByRole("button", { name: "Sign out anyway" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/login"));
    expect(device.clear).toHaveBeenCalledTimes(1);
  });
});

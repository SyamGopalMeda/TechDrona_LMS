import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "../test/mock-api";
import { readPendingLogin } from "../lib/pending-login";
import { MfaForm } from "./MfaForm";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

let restore: (() => void) | undefined;
afterEach(() => {
  restore?.();
  push.mockReset();
});

describe("MfaForm (PUB-012 MFA step)", () => {
  it("hands a device-cap result over to device verification instead of dead-ending", async () => {
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
});

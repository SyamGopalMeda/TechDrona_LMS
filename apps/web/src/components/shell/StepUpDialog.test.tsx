import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { StepUpDialog, type StepUpRequest } from "./StepUpDialog";

let restore: (() => void) | undefined;
afterEach(() => restore?.());

function request(methods: string[]): StepUpRequest & { resolve: ReturnType<typeof vi.fn> } {
  return { challenge: { max_age_seconds: 900, allowed_methods: methods, options_url: "/api/v1/auth/step-up/options" }, resolve: vi.fn() };
}

describe("StepUpDialog (SEC-09: student email/SMS OTP step-up)", () => {
  it("sends an email code through AUTH-19 and confirms with AUTH-20 {method, code}", async () => {
    const api = mockApi({
      "POST auth/step-up/options": (call) =>
        (call.body as { send_otp_via?: string }).send_otp_via
          ? { body: { allowed_methods: ["email_otp", "sms_otp"], sent_to: "s***@example.com" } }
          : { body: { allowed_methods: ["email_otp", "sms_otp"], purpose: null } },
      "POST auth/step-up": { body: { last_step_up_at: "2026-11-03T10:00:00Z" } },
    });
    restore = api.restore;
    const req = request(["totp", "sms_otp", "email_otp"]);
    const onDone = vi.fn();
    renderWithProviders(<StepUpDialog request={req} onDone={onDone} />);

    // The API's real list (no TOTP enrolled) replaces the challenge's generic list.
    expect(await screen.findByRole("radio", { name: "Code by email" })).toBeChecked();
    expect(screen.queryByRole("radio", { name: "Authenticator app" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Send code" }));
    expect(await screen.findByText(/sent to s\*\*\*@example.com/)).toBeInTheDocument();
    expect(api.calls.find((c) => c.path === "auth/step-up/options" && (c.body as { send_otp_via?: string }).send_otp_via)?.body).toEqual({ send_otp_via: "email" });

    await userEvent.type(screen.getByRole("textbox", { name: /Confirmation code/ }), "123456");
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(req.resolve).toHaveBeenCalledWith(true));
    expect(api.calls.find((c) => c.path === "auth/step-up")?.body).toEqual({ method: "email_otp", code: "123456" });
    expect(onDone).toHaveBeenCalled();
  });

  it("SMS sends via sms; a wrong code keeps the dialog open with a plain message", async () => {
    const api = mockApi({
      "POST auth/step-up/options": { body: { allowed_methods: ["sms_otp"], sent_to: "+91******3210" } },
      "POST auth/step-up": problem(400, "otp_invalid", "Incorrect code"),
    });
    restore = api.restore;
    const req = request(["totp", "sms_otp", "email_otp"]);
    renderWithProviders(<StepUpDialog request={req} onDone={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Send code" }));
    await userEvent.type(await screen.findByRole("textbox", { name: /Confirmation code/ }), "000000");
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(await screen.findByText("That code is not correct. Check it and try again.")).toBeInTheDocument();
    expect(req.resolve).not.toHaveBeenCalled();
    expect(api.calls.find((c) => c.path === "auth/step-up")?.body).toEqual({ method: "sms_otp", code: "000000" });
  });

  it("E2E-12: a reused TOTP code says to wait for the next code", async () => {
    const api = mockApi({
      "POST auth/step-up/options": { body: { allowed_methods: ["totp"] } },
      "POST auth/step-up": problem(400, "otp_invalid", "Incorrect code", { reason: "code_already_used" }),
    });
    restore = api.restore;
    renderWithProviders(<StepUpDialog request={request(["totp"])} onDone={vi.fn()} />);
    await userEvent.type(await screen.findByRole("textbox", { name: /Authenticator code/ }), "654321");
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(await screen.findByText(/Wait for the next code/)).toBeInTheDocument();
  });

  it("offers password only when the API lists it (student with no other method)", async () => {
    const api = mockApi({
      "POST auth/step-up/options": { body: { allowed_methods: ["password"] } },
      "POST auth/step-up": { body: {} },
    });
    restore = api.restore;
    const req = request(["totp", "sms_otp", "email_otp"]);
    renderWithProviders(<StepUpDialog request={req} onDone={vi.fn()} />);
    await userEvent.type(await screen.findByLabelText(/Password/), "correct horse");
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(req.resolve).toHaveBeenCalledWith(true));
    expect(api.calls.find((c) => c.path === "auth/step-up")?.body).toEqual({ method: "password", password: "correct horse" });
  });
});

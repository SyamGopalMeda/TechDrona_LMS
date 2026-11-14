import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { PrivacyRequests } from "./components/PrivacyRequests";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

let restore: (() => void) | undefined;
afterEach(() => restore?.());

const base = { received_at: "2026-11-01T00:00:00Z", due_at: "2026-12-01T00:00:00Z", completed_at: null, response_summary: null, cooling_off_until: null, export_available: false };
const exportDone = { ...base, request_id: "p1", request_ref: "PRV-1", request_type: "access_export", status: "completed", completed_at: "2026-11-02T00:00:00Z", export_available: true };
const erasure = { ...base, request_id: "p2", request_ref: "PRV-2", request_type: "erasure", status: "cooling_off", cooling_off_until: "2026-11-15T00:00:00Z", retained_by_law: ["invoices (72 months)"] };

describe("PrivacyRequests (STU-023, FE-29/INV-08)", () => {
  it("creates an export request with an Idempotency-Key", async () => {
    const api = mockApi({
      "GET me/privacy-requests": { body: { data: [] } },
      "POST me/privacy-requests": { status: 201, body: { ...base, request_id: "p9", request_ref: "PRV-9", request_type: "access_export", status: "in_progress" } },
    });
    restore = api.restore;
    renderWithProviders(<PrivacyRequests />);
    await userEvent.click(await screen.findByRole("button", { name: "Request a copy of my data" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    const post = api.calls.find((c) => c.method === "POST")!;
    expect(post.body).toEqual({ request_type: "access_export", details: null, confirm: false });
    expect(post.headers["idempotency-key"]).toBeTruthy();
  });

  it("requires an explicit acknowledgement before requesting deletion, then sends confirm=true", async () => {
    const api = mockApi({
      "GET me/privacy-requests": { body: { data: [] } },
      "POST me/privacy-requests": { status: 201, body: { ...erasure } },
    });
    restore = api.restore;
    renderWithProviders(<PrivacyRequests />);
    const del = await screen.findByRole("button", { name: "Delete my account" });
    // Outline danger on the page; the filled danger button lives only inside the confirm dialog.
    expect(del.className).toContain("border-danger-border");
    await userEvent.click(del);
    const submit = await screen.findByRole("button", { name: "Request deletion" });
    expect(submit).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: /I understand/ }));
    await userEvent.click(submit);
    await waitFor(() => expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ request_type: "erasure", details: null, confirm: true }));
  });

  it("lists requests, downloads a completed export and cancels a pending deletion", async () => {
    const createObjectURL = vi.fn(() => "blob:x");
    const revokeObjectURL = vi.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    // jsdom cannot navigate; observe the download click instead of letting it try.
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const api = mockApi({
      "GET me/privacy-requests": { body: { data: [exportDone, erasure] } },
      "GET me/privacy-requests/p1/export": { body: { profile: { name: "A" } } },
      "POST me/privacy-requests/p2/withdraw": { body: { ...erasure, status: "withdrawn" } },
    });
    restore = api.restore;
    renderWithProviders(<PrivacyRequests />);
    expect(await screen.findByText(/Kept by law: invoices \(72 months\)/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Deletion requested" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Download" }));
    await waitFor(() => expect(createObjectURL).toHaveBeenCalled());
    expect(click).toHaveBeenCalled();
    click.mockRestore();
    await userEvent.click(screen.getByRole("button", { name: "Cancel deletion" }));
    await waitFor(() => expect(api.calls.some((c) => c.path === "me/privacy-requests/p2/withdraw")).toBe(true));
  });
});

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { EnquiryDetail, EnquiryQueue } from "./Enquiries";

vi.setConfig({ testTimeout: 20000 });
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }), usePathname: () => "/desk/enquiries" }));

const cleanups: (() => void)[] = [];
afterEach(() => {
  while (cleanups.length) cleanups.pop()!();
});

const base = {
  enquiry_id: "e1",
  reference: "ENQ-2026-0001",
  name: "Priya Nair",
  company: "Acme Systems",
  email: "priya@acme.example",
  phone: null,
  status: "new" as const,
  assigned_to: null,
  created_at: "2026-11-07T05:00:00Z",
  updated_at: "2026-11-07T05:00:00Z",
  closed_at: null,
};
const full = { ...base, message: "We would like to train 40 engineers.", staff_note: null, consent_at: "2026-11-07T05:00:00Z", notice_version: "2026-11" };

describe("Corporate enquiry queue (D8)", () => {
  it("lists new enquiries with a link to the detail and the new count", async () => {
    const api = mockApi({ "GET support/enquiries": { body: { data: [{ ...base, message_preview: "We would like to train" }], page: { next_cursor: null, has_more: false }, counts: { new: 1 } } } });
    cleanups.push(api.restore);
    renderWithProviders(<EnquiryQueue />);
    const link = await screen.findByRole("link", { name: "ENQ-2026-0001" });
    expect(link).toHaveAttribute("href", "/desk/enquiries/e1");
    expect(screen.getByText("New enquiries")).toBeInTheDocument();
    expect(api.calls[0]!.url).toContain("support/enquiries?status=new");
  });

  it("shows the full enquiry and PATCHes status and assignment", async () => {
    const api = mockApi({
      "GET support/enquiries/e1": { body: full },
      "PATCH support/enquiries/e1": (c) => ({ body: { ...full, ...(c.body as object), assigned_to: "u-admin-1" } }),
    });
    cleanups.push(api.restore);
    renderWithProviders(<EnquiryDetail enquiryId="e1" />);
    expect(await screen.findByText("We would like to train 40 engineers.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Assign to me" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(api.calls.find((c) => c.method === "PATCH")!.body).toEqual({ assign_to_me: true, status: "in_progress" });
    expect(await screen.findByText("Assigned to you.")).toBeInTheDocument();
  });
});

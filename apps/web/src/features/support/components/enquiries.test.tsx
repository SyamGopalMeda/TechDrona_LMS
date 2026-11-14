import { screen, waitFor, within } from "@testing-library/react";
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

  it("asks before marking as spam or closing (audit 0.7)", async () => {
    const api = mockApi({
      "GET support/enquiries/e1": { body: full },
      "PATCH support/enquiries/e1": (c) => ({ body: { ...full, ...(c.body as object) } }),
    });
    cleanups.push(api.restore);
    renderWithProviders(<EnquiryDetail enquiryId="e1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Mark as spam" }));
    let dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Mark this enquiry as spam?")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Keep open" }));
    expect(api.calls.some((c) => c.method === "PATCH")).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Close enquiry" }));
    await waitFor(() => expect(api.calls.find((c) => c.method === "PATCH")?.body).toEqual({ status: "closed" }));
    expect(await screen.findByText("Enquiry closed.")).toBeInTheDocument();
  });
});

describe("Corporate enquiry detail layout (Phase 2)", () => {
  it("has breadcrumbs back to the queue, the company as h1 and staff-only note wording", async () => {
    const api = mockApi({ "GET support/enquiries/e1": { body: { ...full, assigned_to: "0b1c2d3e-4f50-6172-8394-a5b6c7d8e9f0" } } });
    cleanups.push(api.restore);
    renderWithProviders(<EnquiryDetail enquiryId="e1" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Acme Systems" })).toBeInTheDocument();
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "Corporate enquiries" })).toHaveAttribute("href", "/desk/enquiries");
    expect(screen.getByText(/Only staff can see this note/)).toBeInTheDocument();
    expect(screen.queryByText(/Only Admin can see this/)).not.toBeInTheDocument();
    expect(screen.getByText("Agent #C7D8E9F0")).toBeInTheDocument();
  });
});

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { AdminCertificates, reasonLabel } from "./components/AdminCertificates";

vi.setConfig({ testTimeout: 20000 });
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }), usePathname: () => "/admin/certificates" }));

const cleanups: (() => void)[] = [];
afterEach(() => {
  while (cleanups.length) cleanups.pop()!();
});

const cert = {
  id: "c1",
  public_code: "ABCDEFGH2345",
  user_id: "u1",
  name_on_certificate: "Ananya Reddy",
  email: "ananya@example.test",
  course_id: "k1",
  course_title: "Data Structures",
  enrolment_id: "e1",
  issue_source: "rule",
  issued_at: "2026-11-10T10:00:00Z",
  status: "valid",
  revoked_at: null,
  revoke_reason: null,
  pdf_available: true,
  content_sha256: "ab",
  template_version: "cert-v2",
  verify_url: "/verify/ABCDEFGH2345",
  email_status: "awaiting",
  outbox: null,
};
const summary = { issued: 1, valid: 1, revoked: 0, without_pdf: 0, due: 2, due_eligible: 1, outbox: { awaiting: 1, pending: 0, sent: 0, failed: 0, cancelled: 0 }, auto_send: false };
const page = (data: unknown[]) => ({ data, page: { next_cursor: null, has_more: false, limit: 25 } });
const due = [
  { enrolment_id: "e2", user_id: "u2", name: "Rahul Varma", email: "rahul@example.test", course_id: "k1", course_title: "Data Structures", batch_id: "b1", batch_name: "CSE 2027", batch_ends_on: "2026-11-01", enrolment_status: "active", progress_pct: 100, completed_at: null, due_because: "batch_ended", eligible: true, reason: null },
  { enrolment_id: "e3", user_id: "u3", name: "Meera Iyer", email: "meera@example.test", course_id: "k1", course_title: "Data Structures", batch_id: "b1", batch_name: "CSE 2027", batch_ends_on: "2026-11-01", enrolment_status: "active", progress_pct: 40, completed_at: null, due_because: "batch_ended", eligible: false, reason: "lessons_incomplete" },
];

function routes(extra: Record<string, unknown> = {}) {
  return {
    "GET admin/certificates/summary": { body: summary },
    "GET admin/certificates": { body: page([cert]) },
    "GET admin/certificates/due": { body: { data: due, eligible: 1 } },
    "GET admin/certificates/outbox": { body: { ...page([{ id: "o1", status: "awaiting", origin: "rule", attempts: 0, last_error: null, approved_at: null, sent_at: null, cancelled_at: null, created_at: "2026-11-10T10:00:00Z", certificate: cert }]), counts: summary.outbox } },
    "GET admin/certificates/settings": { body: { auto_send: false, flag_key: "certificates.auto_send" } },
    ...extra,
  } as Parameters<typeof mockApi>[0];
}

describe("Admin certificates (ADM-017)", () => {
  it("shows KPI tiles and the issued register with verify link and course filter from ?course=", async () => {
    const api = mockApi(routes());
    cleanups.push(api.restore);
    renderWithProviders(<AdminCertificates initialCourse="k1" />);
    expect(screen.getByRole("heading", { level: 1, name: "Certificates & documents" })).toBeInTheDocument();
    expect(await screen.findByText("Ananya Reddy")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "ABCDEFGH2345" })).toHaveAttribute("href", "/verify/ABCDEFGH2345");
    expect(screen.getAllByText("Awaiting approval").length).toBeGreaterThan(0);
    await waitFor(() => expect(api.calls.some((c) => c.path === "admin/certificates" && c.url.includes("course_id=k1"))).toBe(true));
    expect(api.calls.some((c) => c.path === "admin/certificates/summary" && c.url.includes("course_id=k1"))).toBe(true);
  });

  it("issues one due certificate and explains ineligible rows", async () => {
    const api = mockApi(routes({ "POST admin/certificates/due/issue": { body: { issued: 1, certificate_ids: ["c9"], skipped: [] } } }));
    cleanups.push(api.restore);
    renderWithProviders(<AdminCertificates />);
    await userEvent.click(await screen.findByRole("tab", { name: /Due/ }));
    expect(await screen.findByText("Rahul Varma")).toBeInTheDocument();
    expect(screen.getByText("Required lessons not complete")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Issue certificate to Rahul Varma" }));
    await waitFor(() => expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ enrolment_ids: ["e2"] }));
    expect(api.calls.find((c) => c.method === "POST")?.headers["idempotency-key"]).toBeTruthy();
  });

  it("approves and sends from the approval queue, and toggles auto-send", async () => {
    const api = mockApi(
      routes({
        "POST admin/certificates/outbox/approve": { body: { approved: 1, sent: 1, failed: 0, pending: 0, skipped: [] } },
        "PUT admin/certificates/settings": { body: { auto_send: true, flag_key: "certificates.auto_send" } },
      }),
    );
    cleanups.push(api.restore);
    renderWithProviders(<AdminCertificates />);
    await userEvent.click(await screen.findByRole("tab", { name: /Approval queue/ }));
    const btn = await screen.findByRole("button", { name: "Approve and send to Ananya Reddy" });
    await userEvent.click(btn);
    await waitFor(() => expect(api.calls.find((c) => c.path === "admin/certificates/outbox/approve")?.body).toEqual({ ids: ["o1"] }));

    await userEvent.click(screen.getByRole("tab", { name: "Settings" }));
    const box = await screen.findByRole("checkbox", { name: /Send certificate emails automatically/ });
    await waitFor(() => expect(box).not.toBeDisabled());
    await userEvent.click(box);
    await waitFor(() => expect(api.calls.find((c) => c.method === "PUT")?.body).toEqual({ auto_send: true }));
  });

  it("revokes with a reason through the existing revoke endpoint", async () => {
    const api = mockApi(routes({ "POST certificates/c1/revoke": { body: { ...cert, status: "revoked" } } }));
    cleanups.push(api.restore);
    renderWithProviders(<AdminCertificates />);
    await userEvent.click(await screen.findByRole("button", { name: "Revoke ABCDEFGH2345" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/Reason/), "Issued to the wrong learner");
    await userEvent.click(within(dialog).getByRole("button", { name: "Revoke certificate" }));
    await waitFor(() => expect(api.calls.find((c) => c.path === "certificates/c1/revoke")?.body).toEqual({ reason: "Issued to the wrong learner" }));
  });

  it("labels rule reasons", () => {
    expect(reasonLabel("final_test_pending")).toBe("Final test not passed yet");
    expect(reasonLabel("something_new")).toBe("something new");
    expect(reasonLabel(null)).toBe("");
  });
});

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderWithProviders } from "@/features/auth/test/mock-api";
import { resetIntegrationsCache } from "@/components/shell/Integrations";
import { issueLettersInBulk, letterEmailMode, letterMessage, runInChunks, switchLetterFields, type IssuedLetter, type LetterDraft, type LetterStep } from "../lib/letters";
import { RegistrationsList, RegistrationView, VerifyQueue } from "./Admissions";

vi.setConfig({ testTimeout: 20000 });
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }), usePathname: () => "/finance/admissions", useSearchParams: () => new URLSearchParams(window.location.search) }));

const cleanups: (() => void)[] = [];
afterEach(() => {
  while (cleanups.length) cleanups.pop()!();
  resetIntegrationsCache();
});

const reg = {
  registration_id: "r1",
  reg_no: "TDR-AB12CD34",
  name: "Priya Sharma",
  email: "priya@example.com",
  phone: "+919848012345",
  college: "VRSEC",
  course_slug: "java",
  course_title: "Full Stack Java",
  fee_paise: 300000,
  access_min_paise: 150000,
  verified_total_paise: 0,
  balance_paise: 300000,
  payment_state: "unpaid",
  status: "pending_verification",
  open_claims: 1,
  enrolled_at: null,
  user_id: null,
  created_at: "2026-11-11T05:00:00Z",
  updated_at: "2026-11-11T05:00:00Z",
};
const claim = {
  claim_id: "c1",
  registration_id: "r1",
  provider: "manual_upi",
  method: "upi",
  amount_paise: 150000,
  utr: "123456789012",
  paid_on: "2026-11-10",
  note: null,
  has_proof: false,
  proof_name: null,
  proof_type: null,
  status: "pending",
  verified_amount_paise: 0,
  locks_released: false,
  reviewed_by: null,
  reviewed_at: null,
  review_note: null,
  submitted_at: "2026-11-11T05:00:00Z",
  registration: { ...reg, has_account: false },
};
const field = (key: string, label: string, kind = "text", required = false, options?: string[]) => ({ key, label, kind, required, options });
const types = {
  types: [
    {
      key: "offer_course",
      label: "Course admission letter",
      short: "Admission letter",
      layout: "letter",
      prefix: "AL",
      fields: [
        field("program", "Program / course", "text", true),
        field("batch_start", "Batch start date", "date", true),
        field("duration", "Duration", "text", true),
        field("mode", "Mode", "select", true, ["Online", "On-site", "Hybrid"]),
        field("fee_total", "Total course fee", "money"),
        field("fee_paid", "Fee received", "money"),
        field("fee_balance", "Balance due", "money"),
      ],
      paragraphs: [],
      sections: null,
      email_key: "offer_course",
    },
    {
      key: "offer_internship",
      label: "Internship offer letter",
      short: "Internship offer",
      layout: "letter",
      prefix: "OL",
      fields: [field("role", "Internship role / track", "text", true), field("start_date", "Start date", "date", true), field("duration", "Duration", "text", true), field("mode", "Mode", "select", true, ["Online", "On-site", "Hybrid"]), field("intern_stipend", "Stipend", "money", true)],
      paragraphs: [],
      sections: null,
      email_key: "offer_internship",
    },
  ],
  emails: [],
  settings_problem: null,
};
const draft = {
  doc_type: "offer_course",
  recipient: { name: "Priya Sharma", email: "priya@example.com", college: "VRSEC", reg_no: "TDR-AB12CD34" },
  fields: { program: "Full Stack Java", batch_start: "2026-12-01", duration: "12 weeks", mode: "Online", fee_total: "Rs 3,000", fee_paid: "Rs 1,500", fee_balance: "Rs 1,500" },
  issue_date: "2026-11-14",
  user_id: "u1",
  enrolment_id: "e1",
  batch_id: "b1",
  course_id: "c9",
};
const issued = {
  id: "d1",
  doc_type: "offer_course",
  label: "Course admission letter",
  short: "Admission letter",
  layout: "letter",
  ref_no: "TD-AL-2026-ABC123",
  recipient: draft.recipient,
  title: "Full Stack Java",
  user_id: "u1",
  enrolment_id: "e1",
  course_id: "c9",
  fields: draft.fields,
  subject: "Admission confirmed: Full Stack Java",
  issue_date: "2026-11-14",
  status: "valid",
  origin: "manual",
  replaces_id: null,
  superseded_by_id: null,
  revoked_at: null,
  revoke_reason: null,
  pdf_available: true,
  content_sha256: null,
  template_version: "1",
  verify_url: "/verify/TD-AL-2026-ABC123",
  verify_link: "https://lms.techdrona.in/verify/TD-AL-2026-ABC123",
  created_at: "2026-11-14T05:00:00Z",
  email_status: null,
} as unknown as IssuedLetter;
const step = (over: Partial<LetterStep> = {}): LetterStep =>
  ({
    registration_id: "r1",
    reg_no: "TDR-AB12CD34",
    name: "Priya Sharma",
    phone: "+919848012345",
    course_title: "Full Stack Java",
    enrolled_at: "2026-11-14T05:00:00Z",
    ready: true,
    reason: null,
    draft,
    letter: null,
    letters: [],
    email: { connected: false, auto_send: false },
    settings_problem: null,
    auto_open: true,
    ...over,
  }) as LetterStep;

function fakeTab() {
  const tab = { opener: {} as unknown, location: { href: "" }, close: vi.fn() };
  const open = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
  const create = URL.createObjectURL;
  const revoke = URL.revokeObjectURL;
  URL.createObjectURL = vi.fn(() => "blob:letter-preview") as unknown as typeof URL.createObjectURL;
  URL.revokeObjectURL = vi.fn();
  cleanups.push(() => {
    open.mockRestore();
    URL.createObjectURL = create;
    URL.revokeObjectURL = revoke;
  });
  return tab;
}

describe("Admission / offer letter step", () => {
  it("builds the WhatsApp message, the email mode and carries details between letter types", async () => {
    expect(letterMessage({ name: "Priya", course_title: "Java" }, { ref_no: "TD-AL-1", short: "Admission letter", verify_link: "https://x/verify/TD-AL-1" })).toContain("View and verify it here: https://x/verify/TD-AL-1");
    expect(letterEmailMode({ connected: false, auto_send: true })).toBe("none");
    expect(letterEmailMode({ connected: true, auto_send: true })).toBe("send");
    expect(letterEmailMode({ connected: true, auto_send: false })).toBe("queue");
    expect(switchLetterFields({ program: "Java", batch_start: "2026-12-01" }, "offer_internship")).toMatchObject({ role: "Java", start_date: "2026-12-01", intern_stipend: "Unpaid" });
    const progress: number[] = [];
    const out = await runInChunks([1, 2, 3], 2, async (n) => {
      if (n === 2) throw new Error("no");
      return n * 10;
    }, (d) => progress.push(d));
    expect(out.map((o) => (o.ok ? o.value : "x"))).toEqual([10, "x", 30]);
    expect(progress).toEqual([1, 2, 3]);
  });

  it("issues drafts through the documents bulk endpoint per letter type, sending deferred rows again", async () => {
    const intern = { ...draft, doc_type: "offer_internship", fields: { role: "AI Intern" } } as LetterDraft;
    const drafts = [draft as LetterDraft, intern, { ...(draft as LetterDraft), recipient: { ...draft.recipient, name: "Ravi" } }];
    const calls: { type: string; rows: number[] }[] = [];
    let first = true;
    const out = await issueLettersInBulk(drafts, async (type, rows) => {
      calls.push({ type, rows: rows.map((r) => r.row) });
      if (type === "offer_course" && first) {
        first = false;
        return { results: [{ row: 1, status: "issued", ref_no: "TD-AL-1" }, { row: 3, status: "deferred" }] };
      }
      return { results: rows.map((r) => (r.row === 2 ? { row: 2, status: "failed" as const, error: "Fill in: Duration." } : { row: r.row, status: "issued" as const, ref_no: `TD-X-${r.row}` })) };
    });
    expect(calls).toEqual([
      { type: "offer_course", rows: [1, 3] },
      { type: "offer_course", rows: [3] },
      { type: "offer_internship", rows: [2] },
    ]);
    expect(out.get(0)).toEqual({ ref_no: "TD-AL-1" });
    expect(out.get(2)).toEqual({ ref_no: "TD-X-3" });
    expect(out.get(1)).toEqual({ error: "Fill in: Duration." });
  });

  it("opens by itself after Verify & add to batch, previews the prefilled letter, issues it and offers download + WhatsApp", async () => {
    const tab = fakeTab();
    let letterReads = 0;
    let lists = 0;
    const api = mockApi({
      "GET public/integrations": { body: { integrations: { email: false } } },
      "GET admin/admissions/claims": () => ({ body: { data: lists++ === 0 ? [claim] : [], page: { next_cursor: null, has_more: false } } }),
      "GET admin/admissions/plans": { body: { data: [], pay: {}, batches: [] } },
      "POST admin/admissions/claims/c1/verify-and-enrol": {
        body: {
          registration_id: "r1",
          status: "enrolled",
          batch: { batch_id: "b1", name: "Java Jan" },
          account: { user_id: "u1", username: "priya.k7m2", email: "priya@example.com", created: true, temporary_password: "Tq7-mpx4-Lr9", must_change_password: true },
          email: { attempted: false, sent: false, reason: "email_not_connected" },
          login_url: "https://lms.techdrona.in/login",
          letter_step_auto: true,
        },
      },
      // 1: the step opens, 2: the check right before issuing, 3: the reload after issuing
      "GET admin/admissions/registrations/r1/letter": () => ({ body: ++letterReads < 3 ? step() : step({ letter: issued, letters: [issued] }) }),
      "GET admin/documents/types": { body: types },
      "POST admin/documents/preview": { body: { pdf_base64: btoa("%PDF-1.4"), missing: [], leftovers: [], settings_problem: null, subject: "Admission confirmed" } },
      "POST admin/documents": { status: 201, body: { ...issued, email_status: null } },
      "GET admin/documents/d1/pdf": { body: { url: "https://files.example/TD-AL-2026-ABC123.pdf?sig=1", expires_at: "2026-11-14T05:05:00Z" } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<VerifyQueue />);
    await userEvent.click(await screen.findByRole("button", { name: "Verify & add to batch" }));
    const verify = await screen.findByRole("dialog", { name: "Verify & add to batch" });
    await userEvent.click(within(verify).getByLabelText(/I found this payment in PhonePe/));
    await userEvent.click(within(verify).getByRole("button", { name: "Verify & add to batch" }));
    const login = await screen.findByRole("dialog", { name: "Login details" });
    expect(within(login).getByRole("button", { name: "Next: admission letter" })).toBeInTheDocument();
    await userEvent.click(within(login).getByRole("button", { name: "Done" }));

    // the letter step opens by itself (setting on), prefilled from the registration
    const dialog = await screen.findByRole("dialog", { name: "Admission / offer letter" });
    await waitFor(() => expect(within(dialog).getByLabelText(/Program \/ course/)).toHaveValue("Full Stack Java"));
    expect(within(dialog).getByLabelText(/Student name/)).toHaveValue("Priya Sharma");
    expect(within(dialog).getByLabelText("Registration no.")).toHaveValue("TDR-AB12CD34");
    expect(within(dialog).getByLabelText("Total course fee")).toHaveValue("Rs 3,000");
    expect(within(dialog).getByLabelText("Fee received")).toHaveValue("Rs 1,500");
    expect(within(dialog).getByText(/Email isn't connected yet: after issuing, download the PDF/)).toBeInTheDocument();

    // edit, preview (the PDF opens in a new tab), then issue
    const duration = within(dialog).getByLabelText(/^Duration/);
    await userEvent.clear(duration);
    await userEvent.type(duration, "3 months");
    await userEvent.click(within(dialog).getByRole("button", { name: "Preview letter" }));
    await waitFor(() => expect(tab.location.href).toBe("blob:letter-preview"));
    const prev = api.calls.find((c) => c.method === "POST" && c.path === "admin/documents/preview")!;
    expect(prev.body).toMatchObject({ doc_type: "offer_course", recipient: { name: "Priya Sharma", reg_no: "TDR-AB12CD34" }, fields: { duration: "3 months", program: "Full Stack Java" } });

    await userEvent.click(within(dialog).getByRole("button", { name: "Issue letter" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.path === "admin/documents")).toBe(true));
    const post = api.calls.find((c) => c.method === "POST" && c.path === "admin/documents")!;
    expect(post.body).toMatchObject({
      doc_type: "offer_course",
      recipient: { name: "Priya Sharma", email: "priya@example.com", college: "VRSEC", reg_no: "TDR-AB12CD34" },
      fields: { duration: "3 months", fee_total: "Rs 3,000" },
      issue_date: "2026-11-14",
      user_id: "u1",
      enrolment_id: "e1",
      batch_id: "b1",
      course_id: "c9",
      email: "none",
    });
    expect(post.headers["Idempotency-Key"] ?? post.headers["idempotency-key"]).toBeTruthy();

    // issued: the line, download and WhatsApp share (verify link)
    expect(await within(dialog).findByText("Letter issued: TD-AL-2026-ABC123 (14 Nov 2026)")).toBeInTheDocument();
    const wa = within(dialog).getByRole("link", { name: "Share on WhatsApp" }).getAttribute("href")!;
    expect(wa.startsWith("https://wa.me/919848012345?text=")).toBe(true);
    expect(decodeURIComponent(wa.split("text=")[1]!)).toContain("https://lms.techdrona.in/verify/TD-AL-2026-ABC123");
    await userEvent.click(within(dialog).getByRole("button", { name: "Download PDF" }));
    await waitFor(() => expect(tab.location.href).toBe("https://files.example/TD-AL-2026-ABC123.pdf?sig=1"));
    expect(within(dialog).getByRole("button", { name: "Re-issue / correct" })).toBeInTheDocument();
  });

  it("never issues a second letter: one issued meanwhile is shown instead", async () => {
    let letterReads = 0;
    const api = mockApi({
      "GET public/integrations": { body: { integrations: { email: true } } },
      "GET admin/admissions/registrations/r1": { body: { ...reg, status: "enrolled", enrolled_at: "2026-11-14T05:00:00Z", user_id: "u1", branch: "CSE", year: "3", schedule: [], claims: [], events: [], letter: null, letter_step_auto: true, eligible: true } },
      "GET admin/admissions/registrations/r1/letter": () => ({ body: ++letterReads < 2 ? step({ email: { connected: true, auto_send: false } }) : step({ letter: { ...issued, origin: "enrolment", email_status: "awaiting" }, letters: [issued], email: { connected: true, auto_send: false } }) }),
      "GET admin/documents/types": { body: types },
      "PUT admin/admissions/letter-settings": (c) => ({ body: c.body }),
    });
    cleanups.push(api.restore);
    renderWithProviders(<RegistrationView registrationId="r1" />);
    expect(await screen.findByText("Letter not issued")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Preview & issue letter" }));
    const dialog = await screen.findByRole("dialog", { name: "Admission / offer letter" });
    const issue = await within(dialog).findByRole("button", { name: "Issue & queue email" });
    await waitFor(() => expect(issue).toBeEnabled());
    await userEvent.click(issue);
    expect(await within(dialog).findByText("Letter issued: TD-AL-2026-ABC123 (14 Nov 2026)")).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "POST" && c.path === "admin/documents")).toBe(false);
    expect(within(dialog).getByText(/issued automatically on enrolment/)).toBeInTheDocument();
    expect(within(dialog).getByText(/Email waiting for approval/)).toBeInTheDocument();

    // the setting: switch off "open the step automatically"
    const auto = within(dialog).getByLabelText("After enrolling, open the offer-letter step automatically");
    expect(auto).toBeChecked();
    await userEvent.click(auto);
    await waitFor(() => expect(api.calls.some((c) => c.method === "PUT")).toBe(true));
    expect(api.calls.find((c) => c.method === "PUT")!.body).toEqual({ auto_open: false });
  });

  it("corrects an issued letter through the re-issue (supersede) flow", async () => {
    const api = mockApi({
      "GET public/integrations": { body: { integrations: { email: false } } },
      "GET admin/admissions/registrations/r1": { body: { ...reg, status: "enrolled", enrolled_at: "2026-11-14T05:00:00Z", user_id: "u1", branch: "CSE", year: "3", schedule: [], claims: [], events: [], letter: { id: "d1", doc_type: "offer_course", short: "Admission letter", ref_no: "TD-AL-2026-ABC123", issue_date: "2026-11-14", status: "valid", origin: "manual" }, eligible: true } },
      "GET admin/admissions/registrations/r1/letter": { body: step({ letter: issued, letters: [issued] }) },
      "GET admin/documents/types": { body: types },
      "POST admin/documents/d1/reissue": { status: 201, body: { ...issued, id: "d2", ref_no: "TD-AL-2026-NEW999", replaced: "TD-AL-2026-ABC123" } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<RegistrationView registrationId="r1" />);
    expect(await screen.findByText("Letter issued: TD-AL-2026-ABC123 (14 Nov 2026)")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Open letter" }));
    const dialog = await screen.findByRole("dialog", { name: "Admission / offer letter" });
    await userEvent.click(await within(dialog).findByRole("button", { name: "Re-issue / correct" }));
    const program = await within(dialog).findByLabelText(/Program \/ course/);
    await userEvent.clear(program);
    await userEvent.type(program, "Full Stack Java (Weekend)");
    await userEvent.click(within(dialog).getByRole("button", { name: "Issue corrected letter" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.path === "admin/documents/d1/reissue")).toBe(true));
    expect(api.calls.find((c) => c.path === "admin/documents/d1/reissue")!.body).toMatchObject({ fields: { program: "Full Stack Java (Weekend)" }, email: "none", recipient: { reg_no: "TDR-AB12CD34" } });
  });

  it("selects enrolled registrations and previews & issues their letters in bulk with progress", async () => {
    const enrolled = { ...reg, status: "enrolled", enrolled_at: "2026-11-14T05:00:00Z", user_id: "u1", verified_total_paise: 300000, balance_paise: 0 };
    const tab = fakeTab();
    const api = mockApi({
      "GET admin/admissions/registrations": {
        body: {
          data: [
            { ...enrolled, letter: null },
            { ...enrolled, registration_id: "r2", reg_no: "TDR-XY", name: "Ravi Kumar", user_id: "u2", letter: { id: "d9", doc_type: "offer_course", short: "Admission letter", ref_no: "TD-AL-2026-OLD111", issue_date: "2026-11-13", status: "valid", origin: "enrolment" } },
            { ...reg, registration_id: "r3", name: "Not Yet" },
          ],
          page: { next_cursor: null, has_more: false },
        },
      },
      "GET admin/documents/types": { body: types },
      "POST admin/admissions/letters/drafts": (c) => ({ body: { data: (c.body as { registration_ids: string[] }).registration_ids.map((id) => step({ registration_id: id, email: { connected: true, auto_send: true } })) } }),
      "POST admin/documents/preview": { body: { pdf_base64: btoa("%PDF-1.4"), missing: [], leftovers: [], settings_problem: null, subject: "x" } },
      "POST admin/documents": { status: 201, body: { ...issued, ref_no: "TD-AL-2026-BULK01", email_status: "sent" } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<RegistrationsList />);
    expect((await screen.findAllByText("Letter issued: TD-AL-2026-OLD111 (13 Nov 2026)")).length).toBeGreaterThan(0);
    expect(screen.queryByLabelText("Select Not Yet")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Select enrolled without a letter" }));
    expect(screen.getAllByLabelText("Select Priya Sharma")[0]).toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: "Preview & issue letters (1)" }));
    const dialog = await screen.findByRole("dialog", { name: "Preview & issue letters" });
    expect(api.calls.find((c) => c.path === "admin/admissions/letters/drafts")!.body).toEqual({ registration_ids: ["r1"] });
    await userEvent.click(await within(dialog).findByRole("button", { name: "Preview letter for Priya Sharma" }));
    await waitFor(() => expect(tab.location.href).toBe("blob:letter-preview"));
    const go = within(dialog).getByRole("button", { name: "Issue & send (1)" });
    await waitFor(() => expect(go).toBeEnabled());
    await userEvent.click(go);
    expect(await within(dialog).findByText("Issued TD-AL-2026-BULK01")).toBeInTheDocument();
    expect(within(dialog).getByText("1 of 1 done")).toBeInTheDocument();
    const post = api.calls.find((c) => c.method === "POST" && c.path === "admin/documents")!;
    expect(post.body).toMatchObject({ doc_type: "offer_course", user_id: "u1", enrolment_id: "e1", email: "send", recipient: { reg_no: "TDR-AB12CD34" } });
  });

  it("uses the documents bulk endpoint when it is there (email through the outbox)", async () => {
    const enrolled = { ...reg, status: "enrolled", enrolled_at: "2026-11-14T05:00:00Z", user_id: "u1", letter: null };
    const api = mockApi({
      "GET admin/admissions/registrations": { body: { data: [enrolled, { ...enrolled, registration_id: "r2", name: "Ravi Kumar", user_id: "u2" }], page: { next_cursor: null, has_more: false } } },
      "GET admin/documents/types": { body: types },
      "POST admin/admissions/letters/drafts": (c) => ({ body: { data: (c.body as { registration_ids: string[] }).registration_ids.map((id) => step({ registration_id: id, name: id === "r2" ? "Ravi Kumar" : "Priya Sharma", email: { connected: true, auto_send: false } })) } }),
      "POST admin/documents/bulk/issue": (c) => ({ body: { results: (c.body as { rows: { row: number }[] }).rows.map((r) => ({ row: r.row, status: "issued", ref_no: `TD-AL-2026-B${r.row}` })) } }),
    });
    cleanups.push(api.restore);
    renderWithProviders(<RegistrationsList />);
    await userEvent.click(await screen.findByRole("button", { name: "Select enrolled without a letter" }));
    await userEvent.click(screen.getByRole("button", { name: "Preview & issue letters (2)" }));
    const dialog = await screen.findByRole("dialog", { name: "Preview & issue letters" });
    const go = await within(dialog).findByRole("button", { name: "Issue & queue email (2)" });
    await waitFor(() => expect(go).toBeEnabled());
    await userEvent.click(go);
    expect(await within(dialog).findByText("Issued TD-AL-2026-B2")).toBeInTheDocument();
    const call = api.calls.find((c) => c.path === "admin/documents/bulk/issue")!;
    expect(call.body).toMatchObject({ doc_type: "offer_course", label: "Admission letters", email: "outbox", rows: [{ row: 1, name: "Priya Sharma", reg_no: "TDR-AB12CD34", user_id: "u1", enrolment_id: "e1" }, { row: 2 }] });
    expect(call.headers["idempotency-key"]).toBeTruthy();
    expect(api.calls.some((c) => c.method === "POST" && c.path === "admin/documents")).toBe(false);
  });
});

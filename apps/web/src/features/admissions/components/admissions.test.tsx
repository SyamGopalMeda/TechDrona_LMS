import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { resetIntegrationsCache } from "@/components/shell/Integrations";
import { approvalEnrols, loginMessage, toPaise, upiLink, whatsappLink } from "../lib/admissions";
import { AdmissionsOverview, FeePlans, RegistrationsList, RegistrationView, VerifyQueue } from "./Admissions";

vi.setConfig({ testTimeout: 20000 });
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }), usePathname: () => "/finance/admissions" }));

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
  has_proof: true,
  proof_name: "pay.jpg",
  proof_type: "image/jpeg",
  status: "pending",
  verified_amount_paise: 0,
  locks_released: false,
  reviewed_by: null,
  reviewed_at: null,
  review_note: null,
  submitted_at: "2026-11-11T05:00:00Z",
  registration: reg,
  flags: ["Proof is a PDF (check it's a genuine bank/app receipt)"],
};
const detail = {
  ...reg,
  branch: "CSE",
  year: "3rd year",
  current_status: "Student",
  preferred_mode: "Online",
  message: null,
  policy: "instalments",
  allow_instalments: true,
  schedule: [
    { label: "First", amount_paise: 150000, due: "", covered_paise: 0, done: false },
    { label: "Second", amount_paise: 150000, due: "", covered_paise: 0, done: false },
  ],
  next_due: { label: "First", amount_paise: 150000, due: "" },
  status_note: null,
  has_resume: true,
  resume_name: "cv.pdf",
  consent_text: "I agree",
  consent_at: "2026-11-11T05:00:00Z",
  show_public: false,
  marketing_consent: false,
  source: "website",
  entitlement_id: null,
  enrolment_id: null,
  enrolled_course_id: null,
  enrolled_batch_id: null,
  eligible: false,
  claims: [{ ...claim, registration: undefined, flags: undefined }],
  events: [{ event_id: "e1", registration_id: "r1", claim_id: "c1", action: "payment.submitted", amount_paise: 150000, actor: "student <priya@example.com>", detail: "Rs 1,500 · ref 123456789012", at: "2026-11-11T05:00:00Z" }],
};

describe("Admissions (website registrations + manual UPI verification)", () => {
  it("parses rupee amounts like the website", () => {
    expect(toPaise("2,500")).toBe(250000);
    expect(toPaise("2500.5")).toBe(250050);
    expect(Number.isNaN(toPaise("abc"))).toBe(true);
  });

  it("knows when an approval enrols and builds the UPI link", () => {
    const r = { verified_total_paise: 0, access_min_paise: 500000, fee_paise: 500000, enrolled_at: null, status: "pending_verification" as const };
    expect(approvalEnrols(r, 500000)).toBe(true);
    expect(approvalEnrols(r, 400000)).toBe(false);
    expect(approvalEnrols({ ...r, enrolled_at: "2026-11-12T00:00:00Z" }, 500000)).toBe(false);
    expect(upiLink("techdrona@ybl", "Tech Drona", 500000)).toBe("upi://pay?pa=techdrona%40ybl&pn=Tech+Drona&cu=INR&am=5000.00");
  });

  it("builds the WhatsApp login message", () => {
    expect(whatsappLink("98480 12345", "hi")).toBe("https://wa.me/919848012345?text=hi");
    expect(whatsappLink("", "hi")).toBe("https://wa.me/?text=hi");
    const base = { registration_id: "r1", name: "Priya", phone: "", course_title: "Java", batch_name: null, email: { attempted: false, sent: false, reason: null }, login_url: "https://lms/login" };
    expect(loginMessage({ ...base, account: { user_id: "u", username: "priya.k7", email: "p@x", temporary_password: null, must_change_password: false } })).toContain("Use your existing password");
    expect(loginMessage({ ...base, account: { user_id: "u", username: "priya.k7", email: "p@x", temporary_password: "abc", must_change_password: true } })).toContain("choose your own password");
  });

  it("shows website-style KPI cards on the overview", async () => {
    const api = mockApi({
      "GET admin/admissions/overview": {
        body: { registered: 4, enrolled: 1, pending_claims: 2, pending_amount_paise: 300000, needs_info_claims: 0, rejected_claims: 1, closed_registrations: 0, collected_paise: 150000, expected_paise: 1200000, outstanding_paise: 1050000, courses: [], recent: [] },
      },
    });
    cleanups.push(api.restore);
    renderWithProviders(<AdmissionsOverview />);
    expect(await screen.findByText("Waiting for verification")).toBeInTheDocument();
    expect(screen.getByText("Verified revenue")).toBeInTheDocument();
  });

  it("shows each waiting payment and verifies + adds the student to the batch, then shows the login details once", async () => {
    const origCreate = URL.createObjectURL;
    const origRevoke = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn(() => "blob:receipt-1") as unknown as typeof URL.createObjectURL;
    URL.revokeObjectURL = vi.fn();
    cleanups.push(() => {
      URL.createObjectURL = origCreate;
      URL.revokeObjectURL = origRevoke;
    });
    let lists = 0;
    const waiting = { ...claim, registration: { ...reg, has_account: false } };
    const api = mockApi({
      "GET public/integrations": { body: { integrations: { email: true } } },
      "GET admin/admissions/claims": () => ({ body: { data: lists++ === 0 ? [waiting] : [], page: { next_cursor: null, has_more: false } } }),
      "GET admin/admissions/claims/c1/proof/file": { raw: "jpeg-bytes", headers: { "content-type": "image/jpeg" } },
      "GET admin/admissions/plans": { body: { data: [{ slug: "java", title: "Full Stack Java", batch_id: "b1", course_id: "c9" }], pay: {}, batches: [{ batch_id: "b2", name: "Java Weekend", code: "JW1", course_id: "c9", website_course_slug: null }, { batch_id: "b1", name: "Java Jan", code: "JJ1", course_id: "c9", website_course_slug: "java" }] } },
      "POST admin/admissions/claims/c1/verify-and-enrol": {
        body: {
          registration_id: "r1",
          status: "enrolled",
          batch: { batch_id: "b1", name: "Java Jan" },
          account: { user_id: "u1", username: "priya.k7m2", email: "priya@example.com", created: true, temporary_password: "Tq7-mpx4-Lr9", must_change_password: true },
          email: { attempted: true, sent: true, reason: null },
          login_url: "https://lms.techdrona.in/login",
        },
      },
    });
    cleanups.push(api.restore);
    renderWithProviders(<VerifyQueue />);
    expect(await screen.findByRole("link", { name: "Priya Sharma" })).toHaveAttribute("href", "/finance/admissions/registrations/r1");
    expect(api.calls.find((c) => c.path === "admin/admissions/claims")!.url).toContain("admin/admissions/claims?status=open");
    expect(screen.getByRole("link", { name: "priya@example.com" })).toHaveAttribute("href", "mailto:priya@example.com");
    expect(screen.getByText("123456789012")).toBeInTheDocument();
    expect(screen.getByText(/No LMS account with this email yet/)).toBeInTheDocument();
    // the receipt is fetched through the session and shown inline; tapping it opens it full size
    const thumb = await screen.findByRole("button", { name: /Open the receipt of Priya Sharma/ });
    expect(within(thumb).getByRole("img")).toHaveAttribute("src", "blob:receipt-1");
    await userEvent.click(thumb);
    const full = await screen.findByRole("dialog", { name: "Payment receipt" });
    expect(within(full).getByRole("img", { name: /full size/ })).toBeInTheDocument();
    await userEvent.click(within(full).getByRole("button", { name: /close/i }));

    expect(screen.queryByRole("button", { name: /^Approve/ })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Verify & add to batch" }));
    const dialog = await screen.findByRole("dialog", { name: "Verify & add to batch" });
    expect(within(dialog).getByText("+919848012345")).toBeInTheDocument();
    // the batch defaults to the course plan's batch; both boxes start ticked
    await waitFor(() => expect(within(dialog).getByLabelText("Add to batch")).toHaveValue("b1"));
    expect(within(dialog).getByLabelText("Ask the student to change this password on first login")).toBeChecked();
    expect(within(dialog).getByLabelText("Email the login details to the student")).toBeChecked();
    await userEvent.click(within(dialog).getByRole("button", { name: "Verify & add to batch" }));
    expect(await within(dialog).findByText(/Confirm that you found this payment in PhonePe/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByLabelText(/I found this payment in PhonePe/));
    await userEvent.selectOptions(within(dialog).getByLabelText("Add to batch"), "b2");
    await userEvent.click(within(dialog).getByLabelText("Ask the student to change this password on first login"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Verify & add to batch" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    expect(api.calls.find((c) => c.method === "POST")!.body).toEqual({ amount_paise: 150000, batch_id: "b2", must_change_password: false, send_email: true, note: null });

    // the login details: username, temporary password (shown once), email status, WhatsApp
    const result = await screen.findByRole("dialog", { name: "Login details" });
    expect(within(result).getByText("priya.k7m2")).toBeInTheDocument();
    expect(within(result).getByText("Tq7-mpx4-Lr9")).toBeInTheDocument();
    expect(within(result).getByText(/shown only once/)).toBeInTheDocument();
    expect(within(result).getByText("Login email sent to priya@example.com.")).toBeInTheDocument();
    const wa = within(result).getByRole("link", { name: "Share on WhatsApp" });
    const href = wa.getAttribute("href")!;
    expect(href.startsWith("https://wa.me/919848012345?text=")).toBe(true);
    const text = decodeURIComponent(href.split("text=")[1]!);
    expect(text).toContain("Full Stack Java (Java Jan)");
    expect(text).toContain("https://lms.techdrona.in/login");
    expect(text).toContain("Username: priya.k7m2");
    expect(text).toContain("Temporary password: Tq7-mpx4-Lr9");
    expect(within(result).getByRole("button", { name: "Resend login email (new password)" })).toBeInTheDocument();
    await userEvent.click(within(result).getByRole("button", { name: "Done" }));
    // the item leaves the queue and the decision stays visible, with the login details to reopen
    expect(await screen.findByText("Nothing waiting")).toBeInTheDocument();
    const decided = screen.getByRole("heading", { name: "Just decided" }).closest("section")!;
    expect(within(decided).getByText(/Verified and added to Java Jan\. Username priya\.k7m2\. Login email sent\./)).toBeInTheDocument();
    expect(within(decided).getByRole("button", { name: "Login details" })).toBeInTheDocument();
  });

  it("without email, unticks the email box and says to share the login details yourself", async () => {
    const api = mockApi({
      "GET public/integrations": { body: { integrations: { email: false } } },
      "GET admin/admissions/claims": { body: { data: [{ ...claim, has_proof: false }], page: { next_cursor: null, has_more: false } } },
      "GET admin/admissions/plans": { body: { data: [], pay: {}, batches: [] } },
      "POST admin/admissions/claims/c1/verify-and-enrol": {
        body: {
          registration_id: "r1",
          status: "enrolled",
          batch: { batch_id: "b1", name: "Java Jan" },
          account: { user_id: "u1", username: "priya.k7m2", email: "priya@example.com", created: true, temporary_password: "Tq7-mpx4-Lr9", must_change_password: true },
          email: { attempted: false, sent: false, reason: "email_not_connected" },
          login_url: "https://lms.techdrona.in/login",
        },
      },
    });
    cleanups.push(api.restore);
    renderWithProviders(<VerifyQueue />);
    await userEvent.click(await screen.findByRole("button", { name: "Verify & add to batch" }));
    const dialog = await screen.findByRole("dialog", { name: "Verify & add to batch" });
    await waitFor(() => expect(within(dialog).getByLabelText("Email the login details to the student")).not.toBeChecked());
    expect(within(dialog).getByText(/Email isn't connected yet — you'll get the login details to share yourself/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByLabelText(/I found this payment in PhonePe/));
    await userEvent.click(within(dialog).getByRole("button", { name: "Verify & add to batch" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    expect(api.calls.find((c) => c.method === "POST")!.body).toMatchObject({ send_email: false, must_change_password: true, batch_id: null });
    const result = await screen.findByRole("dialog", { name: "Login details" });
    expect(within(result).getByText(/Email isn't connected yet — share these details with the student yourself/)).toBeInTheDocument();
  });

  it("approves a part payment (below the access amount) without enrolling, and reports a warning", async () => {
    const api = mockApi({
      "GET admin/admissions/claims": { body: { data: [{ ...claim, amount_paise: 100000, has_proof: false }], page: { next_cursor: null, has_more: false } } },
      "POST admin/admissions/claims/c1/verify": { body: { registration: { ...detail, status: "partially_paid" }, enrolled: false, warning: "Payment saved, but enrolment didn't finish: not linked" } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<VerifyQueue />);
    await userEvent.click(await screen.findByRole("button", { name: "Approve part payment" }));
    const dialog = await screen.findByRole("dialog", { name: "Approve payment" });
    await userEvent.click(within(dialog).getByRole("checkbox"));
    await userEvent.click(within(dialog).getByRole("button", { name: /^Approve/ }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    expect(api.calls.find((c) => c.method === "POST")!.body).toEqual({ amount_paise: 100000, checked: true, note: null });
    expect((await screen.findAllByText(/enrolment didn't finish/)).length).toBeGreaterThan(0);
  });

  it("switches a course's registration status at once, and links to the fee plan when it has no fee", async () => {
    const api = mockApi({
      "GET admin/admissions/overview": {
        body: { registered: 0, enrolled: 0, pending_claims: 0, pending_amount_paise: 0, needs_info_claims: 0, rejected_claims: 0, closed_registrations: 0, collected_paise: 0, expected_paise: 0, outstanding_paise: 0, courses: [], recent: [] },
      },
      "GET admin/courses/status": {
        body: {
          data: [
            { course_slug: "java", status: "coming_soon", updated_at: "2026-11-11T05:00:00Z", fee_paise: 500000, plan_active: true, batch: { batch_id: "b1", name: "Java Jan" } },
            { course_slug: "python", status: "closed", updated_at: null, fee_paise: null, plan_active: false, batch: null },
          ],
        },
      },
      "PUT admin/courses/java/status": (c) => ({ body: { course_slug: "java", status: (c.body as { status: string }).status, updated_at: "2026-11-12T05:00:00Z", fee_paise: 500000, plan_active: true, batch: { batch_id: "b1", name: "Java Jan" } } }),
      "PUT admin/courses/python/status": problem(409, "no_fee_plan", "No fee plan", { detail: "Set a fee for this course before opening registration." }),
    });
    cleanups.push(api.restore);
    renderWithProviders(<AdmissionsOverview titles={{ java: "Full Stack Java" }} />);
    expect(await screen.findByText(/Changes show on the website and in the LMS within a minute/)).toBeInTheDocument();
    const java = (await screen.findByRole("group", { name: "Registration for Full Stack Java" }));
    expect(within(java).getByLabelText("Coming soon")).toBeChecked();
    await userEvent.click(within(java).getByLabelText("Open for registration"));
    await waitFor(() => expect(api.calls.some((c) => c.method === "PUT" && c.path === "admin/courses/java/status")).toBe(true));
    expect(api.calls.find((c) => c.method === "PUT" && c.path === "admin/courses/java/status")!.body).toEqual({ status: "open" });
    expect(within(java).getByLabelText("Open for registration")).toBeChecked();
    expect(await screen.findByText(/Full Stack Java: open for registration\./)).toBeInTheDocument();

    // the slug is shown when the website has no title; opening without a fee says what to do
    const python = screen.getByRole("group", { name: "Registration for python" });
    await userEvent.click(within(python).getByLabelText("Open for registration"));
    expect(await screen.findByText("Set a fee for this course before opening registration.")).toBeInTheDocument();
    expect(within(python).getByLabelText("Closed")).toBeChecked();
    expect(screen.getByRole("link", { name: "Set the fee" })).toHaveAttribute("href", "/finance/admissions/plans?edit=python");
  });

  it("opens a PDF receipt in a new tab", async () => {
    const tab = { opener: {} as unknown, location: { href: "" }, close: vi.fn() };
    const open = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    cleanups.push(() => open.mockRestore());
    const api = mockApi({
      "GET admin/admissions/claims": { body: { data: [{ ...claim, proof_type: "application/pdf" }], page: { next_cursor: null, has_more: false } } },
      "GET admin/admissions/claims/c1/proof": { body: { url: "https://files.example/r.pdf?sig=1", expires_at: "2026-11-12T05:02:00Z", content_type: "application/pdf", filename: "r.pdf" } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<VerifyQueue />);
    await userEvent.click(await screen.findByRole("button", { name: "Open receipt (PDF)" }));
    await waitFor(() => expect(tab.location.href).toBe("https://files.example/r.pdf?sig=1"));
    expect(tab.opener).toBeNull();
  });

  it("asks for a reason the student will see before rejecting", async () => {
    const api = mockApi({
      "GET admin/admissions/claims": { body: { data: [{ ...claim, has_proof: false }], page: { next_cursor: null, has_more: false } } },
      "POST admin/admissions/claims/c1/reject": (c) => ({ body: { claim: { ...claim, status: "rejected" }, registration: detail, echo: c.body } }),
    });
    cleanups.push(api.restore);
    renderWithProviders(<VerifyQueue />);
    await userEvent.click(await screen.findByRole("button", { name: "Reject" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText(/Reason \(the student sees this\)/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Reject" }));
    expect(await within(dialog).findByText("Write a short reason.")).toBeInTheDocument();
    await userEvent.type(within(dialog).getByRole("textbox"), "No such payment in PhonePe");
    await userEvent.click(within(dialog).getByRole("button", { name: "Reject" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    expect(api.calls.find((c) => c.method === "POST")!.body).toEqual({ reason: "No such payment in PhonePe", release_locks: false });
  });

  it("lists registrations with email, fee, paid, balance, status and the last payment reference", async () => {
    const api = mockApi({
      "GET admin/admissions/registrations": {
        body: { data: [{ ...reg, status: "enrolled", verified_total_paise: 300000, balance_paise: 0, last_utr: "998877665544", last_paid_on: "2026-11-10", last_claim_status: "verified" }], page: { next_cursor: null, has_more: false } },
      },
    });
    cleanups.push(api.restore);
    renderWithProviders(<RegistrationsList />);
    expect((await screen.findAllByText("998877665544")).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/priya@example\.com/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Enrolled").length).toBeGreaterThan(0);
    await userEvent.type(screen.getByLabelText("Search"), "priya@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(api.calls.some((c) => c.url.includes("q=priya%40example.com"))).toBe(true));
  });

  it("shows a registration with its payments, instalments and history", async () => {
    const api = mockApi({ "GET admin/admissions/registrations/r1": { body: detail } });
    cleanups.push(api.restore);
    renderWithProviders(<RegistrationView registrationId="r1" />);
    expect(await screen.findByRole("heading", { name: "Priya Sharma" })).toBeInTheDocument();
    expect(screen.getByText("Instalments")).toBeInTheDocument();
    expect(screen.getByText("Payment submitted")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "View resume" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Enrol now" })).toBeNull();
  });

  it("shows the LMS username and whether the login email went out on the registrations list", async () => {
    const api = mockApi({
      "GET admin/admissions/registrations": {
        body: { data: [{ ...reg, status: "enrolled", user_id: "u1", account_username: "priya.k7m2", login_email_sent_at: null }], page: { next_cursor: null, has_more: false } },
      },
    });
    cleanups.push(api.restore);
    renderWithProviders(<RegistrationsList />);
    expect((await screen.findAllByText("priya.k7m2")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Login email: not sent").length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: "Send login email" }).length).toBeGreaterThan(0);
  });

  it("resends the login email with a new temporary password after a clear confirm", async () => {
    const api = mockApi({
      "GET public/integrations": { body: { integrations: { email: true } } },
      "GET admin/admissions/registrations/r1": { body: { ...detail, status: "enrolled", enrolled_at: "2026-11-12T05:00:00Z", user_id: "u1", account_username: "priya.k7m2", login_email_sent_at: "2026-11-12T05:00:00Z" } },
      "POST admin/admissions/registrations/r1/login-email": {
        body: {
          account: { user_id: "u1", username: "priya.k7m2", email: "priya@example.com", temporary_password: "Nw4-zzk2-Pq8", must_change_password: true },
          email: { attempted: true, sent: false, reason: "send_failed" },
          login_url: "https://lms.techdrona.in/login",
        },
      },
    });
    cleanups.push(api.restore);
    renderWithProviders(<RegistrationView registrationId="r1" />);
    expect(await screen.findByText(/^Sent /)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Resend login email" }));
    const dialog = await screen.findByRole("dialog", { name: "Resend login email" });
    expect(within(dialog).getByText(/The old password stops working/)).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Ask the student to change this password on first login")).toBeChecked();
    await userEvent.click(within(dialog).getByRole("button", { name: "Resend login email" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    expect(api.calls.find((c) => c.method === "POST")!.body).toEqual({ reset_password: true, must_change_password: true });
    const result = await screen.findByRole("dialog", { name: "Login details" });
    expect(within(result).getByText("Nw4-zzk2-Pq8")).toBeInTheDocument();
    expect(within(result).getByText(/didn't go out/)).toBeInTheDocument();
    expect(within(result).getByRole("link", { name: "Share on WhatsApp" }).getAttribute("href")).toContain("Nw4-zzk2-Pq8");
  });

  it("saves the pay-to settings and a new fee plan with instalments in paise", async () => {
    const api = mockApi({
      "GET admin/admissions/plans": { body: { data: [], pay: { phone: "", preferred_app: "PhonePe", upi_id: "", payee_name: "", instructions: "" }, batches: [{ batch_id: "b1", name: "Java Jan", code: "JJ1", course_id: "c9", website_course_slug: "java" }] } },
      "PUT admin/admissions/pay-settings": (c) => ({ body: c.body }),
      "PUT admin/admissions/plans": (c) => ({ body: c.body }),
    });
    cleanups.push(api.restore);
    renderWithProviders(<FeePlans />);
    await userEvent.type(await screen.findByLabelText("Payment number (10 digits)"), "9502524924");
    await userEvent.type(screen.getByLabelText(/UPI ID \(students scan/), "techdrona@ybl");
    expect(await screen.findByRole("img", { name: "UPI QR code for techdrona@ybl" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save payment details" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "PUT" && c.path.endsWith("pay-settings"))).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: "Add fee plan" }));
    await userEvent.type(screen.getByLabelText("Website course slug"), "java");
    await userEvent.type(screen.getByLabelText("Course title"), "Full Stack Java");
    await userEvent.selectOptions(screen.getByLabelText("LMS batch"), "b1");
    await userEvent.type(screen.getByLabelText("Course fee (₹)"), "3000");
    await userEvent.click(screen.getByLabelText("Allow instalments"));
    await userEvent.type(screen.getByLabelText("Amount (₹)"), "3000");
    await userEvent.click(screen.getByRole("button", { name: "Save fee plan" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "PUT" && c.path.endsWith("plans"))).toBe(true));
    const body = api.calls.find((c) => c.method === "PUT" && c.path.endsWith("plans"))!.body as Record<string, unknown>;
    expect(body).toMatchObject({ slug: "java", batch_id: "b1", fee_paise: 300000, allow_instalments: true, schedule: [{ label: "First instalment", amount_paise: 300000, due: "" }] });
  });
});

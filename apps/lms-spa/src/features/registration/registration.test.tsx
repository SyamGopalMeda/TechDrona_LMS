import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { CourseRegister } from "./components/CourseRegister";
import { MyRegistrations } from "./components/MyRegistrations";
import { sniff } from "./lib/proof-file";
import { inr, newRegNo, refProblem, upiLink, type MyPlanView, type MyRegistration } from "./lib/registration";

vi.setConfig({ testTimeout: 20000 });
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }), usePathname: () => "/app/courses/java/register" }));

const cleanups: (() => void)[] = [];
afterEach(() => {
  while (cleanups.length) cleanups.pop()!();
});

const FEE = 500000;
const plan: MyPlanView = {
  course_slug: "java",
  plan: {
    slug: "java",
    title: "Full Stack Java",
    fee_paise: FEE,
    allow_instalments: false,
    schedule: [{ label: "Full fee", amount_paise: FEE, due: "" }],
    policy: "full",
    min_first_paise: FEE,
    access_min_paise: FEE,
    instructions: "",
    active: true,
    amount_options: [{ label: "Full fee", amount_paise: FEE }],
  },
  pay_configured: true,
  payment: { upi_id: "techdrona@ybl", payee_name: "Tech Drona", phone: "", preferred_app: "PhonePe", bank_details: "", instructions: [] },
  consent_text: "I agree that Tech Drona may store and use my details.",
  prefill: { name: "Ravi Kumar", email: "ravi@example.com", phone: "9848012345", college: "VRSEC", branch: "CSE", year: "3rd year" },
  registration: null,
  past: [],
};

const reg = (over: Partial<MyRegistration> = {}): MyRegistration => ({
  registration_id: "r1",
  reg_no: "TDR-AB12CD34",
  course_slug: "java",
  course_title: "Full Stack Java",
  status: "pending_verification",
  state: "pending",
  reason: null,
  fee_paise: FEE,
  verified_total_paise: 0,
  balance_paise: FEE,
  open_claims: 1,
  next_due: { label: "Full fee", amount_paise: FEE, due: "" },
  can_pay: false,
  pay_options: [],
  enrolled: false,
  enrolled_at: null,
  course_href: null,
  created_at: "2026-11-12T05:00:00Z",
  claims: [
    { claim_id: "c1", amount_paise: FEE, method: "upi", utr: "123456789012", paid_on: "2026-11-12", status: "pending", reason: null, proof_name: "pay.pdf", submitted_at: "2026-11-12T05:00:00Z", reviewed_at: null },
  ],
  ...over,
});

const pdf = () => new File([new TextEncoder().encode(`%PDF-1.4\n${"receipt ".repeat(40)}`)], "receipt.pdf", { type: "application/pdf" });

describe("registration lib", () => {
  it("builds the UPI pay link like the website (UPI ID unencoded, amount in rupees)", () => {
    expect(upiLink("techdrona@ybl", "Tech Drona", FEE, "TDR-AB12CD34")).toBe("upi://pay?pa=techdrona@ybl&pn=Tech%20Drona&am=5000.00&cu=INR&tn=TDR-AB12CD34");
    expect(inr(FEE)).toBe("₹5,000");
  });
  it("checks references, sniffs files, makes registration numbers", () => {
    expect(refProblem("123456789012", "upi")).toBeNull();
    expect(refProblem("T2311121234", "upi")).toMatch(/app's own transaction ID/);
    expect(sniff(new TextEncoder().encode("%PDF-1.4"))).toBe("application/pdf");
    expect(newRegNo(() => new Uint8Array(8))).toBe("TDR-AAAAAAAA");
    expect(newRegNo()).toMatch(/^TDR-[A-Z2-9]{8}$/);
  });
});

describe("CourseRegister", () => {
  it("shows the fee and a scannable UPI QR with the correct upi:// link, then registers with the proof", async () => {
    let sent: Record<string, unknown> | undefined;
    const api = mockApi({
      "GET me/admissions/plans/java": { body: plan },
      "POST me/admissions/registrations": (c) => {
        sent = c.body as Record<string, unknown>;
        return { status: 201, body: reg({ reg_no: String(sent.reg_no) }) };
      },
    });
    cleanups.push(api.restore);
    renderWithProviders(<CourseRegister slug="java" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Full Stack Java" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Pay ₹5,000/ })).toBeInTheDocument();
    const regNo = screen.getAllByText(/^TDR-[A-Z2-9]{8}$/)[0]!.textContent!;
    const link = `upi://pay?pa=techdrona@ybl&pn=Tech%20Drona&am=5000.00&cu=INR&tn=${regNo}`;
    expect(screen.getByRole("link", { name: /Open UPI app/ })).toHaveAttribute("href", link);
    expect(document.querySelector(`[data-upi="${link}"]`)).not.toBeNull();
    expect(await screen.findByRole("img", { name: /UPI QR code to pay ₹5,000/ })).toHaveAttribute("src", expect.stringMatching(/^data:image\/png;base64,/));
    expect(screen.getByText("techdrona@ybl")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy UPI ID" })).toBeInTheDocument();
    // prefilled from the account
    expect(screen.getByRole("textbox", { name: /Full name/ })).toHaveValue("Ravi Kumar");

    // client checks first: nothing is sent without the UTR, proof and consent
    await userEvent.click(screen.getByRole("button", { name: "Register and submit payment" }));
    expect(await screen.findByText(/Enter the transaction reference/)).toBeInTheDocument();
    expect(screen.getByText("Upload the payment screenshot or receipt.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);

    await userEvent.type(screen.getByRole("textbox", { name: /UPI reference/ }), "123456789012");
    await userEvent.upload(screen.getByLabelText(/Payment screenshot or receipt/), pdf());
    expect(await screen.findByText(/ready to upload/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: "Register and submit payment" }));

    expect(await screen.findByText(/Payment submitted. We'll verify it and enrol you — usually within a day./)).toBeInTheDocument();
    expect(sent).toMatchObject({ course_slug: "java", reg_no: regNo, name: "Ravi Kumar", phone: "9848012345", consent: true, claim: { amount_paise: FEE, method: "upi", utr: "123456789012" } });
    const proof = sent!.proof as { filename: string; data_b64: string; original_sha256: string };
    expect(proof.filename).toBe("receipt.pdf");
    expect(atob(proof.data_b64).startsWith("%PDF-")).toBe(true);
    expect(proof.original_sha256).toMatch(/^[0-9a-f]{64}$/);
    expect(screen.getByText("Payment under verification")).toBeInTheDocument();
  });

  it("maps api field errors back to the form", async () => {
    const api = mockApi({
      "GET me/admissions/plans/java": { body: plan },
      "POST me/admissions/registrations": problem(409, "conflict", "Conflict", { errors: [{ field: "utr", code: "utr_taken", message: "This transaction reference was already submitted." }] }),
    });
    cleanups.push(api.restore);
    renderWithProviders(<CourseRegister slug="java" />);
    await userEvent.type(await screen.findByRole("textbox", { name: /UPI reference/ }), "123456789012");
    await userEvent.upload(screen.getByLabelText(/Payment screenshot or receipt/), pdf());
    await screen.findByText(/ready to upload/);
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: "Register and submit payment" }));
    expect(await screen.findByText("This transaction reference was already submitted.")).toBeInTheDocument();
  });

  it("no fee plan: registration opens soon (no error)", async () => {
    const api = mockApi({ "GET me/admissions/plans/ai": { body: { ...plan, course_slug: "ai", plan: null, payment: null, pay_configured: false } } });
    cleanups.push(api.restore);
    renderWithProviders(<CourseRegister slug="ai" courseTitle="AI Engineering" />);
    expect(await screen.findByText("Registration for this course opens soon")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "AI Engineering" })).toBeInTheDocument();
  });

  it("payment details missing: a clear message instead of a broken QR", async () => {
    const api = mockApi({ "GET me/admissions/plans/java": { body: { ...plan, pay_configured: false, payment: { ...plan.payment!, upi_id: "" } } } });
    cleanups.push(api.restore);
    renderWithProviders(<CourseRegister slug="java" />);
    expect(await screen.findByText(/Online payment details aren't set up yet — contact Tech Drona/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Open UPI app/ })).not.toBeInTheDocument();
  });

  it("needs info: shows the reason and uploads the proof again on the same registration", async () => {
    let sent: Record<string, unknown> | undefined;
    const needs = reg({ state: "needs_info", reason: "Screenshot is cut off", can_pay: true, pay_options: [{ label: "Full fee", amount_paise: FEE }] });
    const api = mockApi({
      "GET me/admissions/plans/java": { body: { ...plan, registration: needs } },
      "POST me/admissions/claims": (c) => {
        sent = c.body as Record<string, unknown>;
        return { status: 201, body: reg({ open_claims: 2 }) };
      },
    });
    cleanups.push(api.restore);
    renderWithProviders(<CourseRegister slug="java" />);
    expect(await screen.findByText("Screenshot is cut off")).toBeInTheDocument();
    expect(screen.getByText("More information needed")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open UPI app/ })).toHaveAttribute("href", "upi://pay?pa=techdrona@ybl&pn=Tech%20Drona&am=5000.00&cu=INR&tn=TDR-AB12CD34");
    await userEvent.type(screen.getByRole("textbox", { name: /UPI reference/ }), "123456789099");
    await userEvent.upload(screen.getByLabelText(/Payment screenshot or receipt/), pdf());
    await screen.findByText(/ready to upload/);
    await userEvent.click(screen.getByRole("button", { name: "Submit payment proof" }));
    expect(await screen.findByText(/Payment submitted/)).toBeInTheDocument();
    expect(sent).toMatchObject({ registration_id: "r1", claim: { amount_paise: FEE, utr: "123456789099" } });
  });
});

describe("MyRegistrations", () => {
  it("lists each state with its next step", async () => {
    const api = mockApi({
      "GET me/admissions": {
        body: {
          data: [
            reg({ registration_id: "r1", state: "enrolled", status: "enrolled", enrolled: true, course_href: "/app/courses/full-stack-java", balance_paise: 0, verified_total_paise: FEE }),
            reg({ registration_id: "r2", course_slug: "python", course_title: "Python", state: "payment_rejected", reason: "No such payment", can_pay: true, pay_options: [{ label: "Full fee", amount_paise: FEE }] }),
            reg({ registration_id: "r3", course_slug: "devops", course_title: "DevOps" }),
          ],
        },
      },
    });
    cleanups.push(api.restore);
    renderWithProviders(<MyRegistrations />);
    const enrolled = (await screen.findByRole("heading", { name: "Full Stack Java" })).closest("article")!;
    expect(within(enrolled).getByText("Enrolled")).toBeInTheDocument();
    expect(within(enrolled).getByRole("link", { name: /Open course/ })).toHaveAttribute("href", "/app/courses/full-stack-java");
    const rejected = screen.getByRole("heading", { name: "Python" }).closest("article")!;
    expect(within(rejected).getByText("No such payment")).toBeInTheDocument();
    expect(within(rejected).getByRole("link", { name: "Upload proof again" })).toHaveAttribute("href", "/app/courses/python/register");
    const pending = screen.getByRole("heading", { name: "DevOps" }).closest("article")!;
    expect(within(pending).getByText("Payment under verification")).toBeInTheDocument();
    await waitFor(() => expect(within(pending).queryByRole("link")).toBeNull());
  });

  it("empty: points to the courses", async () => {
    const api = mockApi({ "GET me/admissions": { body: { data: [] } } });
    cleanups.push(api.restore);
    renderWithProviders(<MyRegistrations />);
    expect(await screen.findByText("You haven't registered for a course yet")).toBeInTheDocument();
  });
});

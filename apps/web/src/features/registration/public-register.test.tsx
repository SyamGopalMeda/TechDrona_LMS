import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import type { MyBatchClasses } from "@/features/batches/lib/delivery";
import { CourseRegister } from "./components/CourseRegister";
import { MyCoursesCard, myCourseItems } from "./components/MyCoursesCard";
import { PublicStatusCheck, normaliseRegNo } from "./components/PublicStatusCheck";
import { firstOptions, publicPlanToView, publicState, type MyPlanView, type MyRegistration, type PublicPlan } from "./lib/registration";

vi.setConfig({ testTimeout: 20000 });
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }), usePathname: () => "/register/java" }));

const cleanups: (() => void)[] = [];
afterEach(() => {
  while (cleanups.length) cleanups.pop()!();
});

const FEE = 500000;
const pubPlan: PublicPlan = {
  slug: "java",
  title: "Full Stack Java",
  fee_paise: FEE,
  allow_instalments: true,
  schedule: [
    { label: "First instalment", amount_paise: 200000, due: "" },
    { label: "Second instalment", amount_paise: 300000, due: "" },
  ],
  policy: "instalments",
  min_first_paise: 250000,
  access_min_paise: 250000,
  upi_id: "",
  payee_name: "",
  bank_details: "",
  instructions: "Mention the registration number.",
  active: true,
  course_status: "open",
  pay: { phone: "", preferred_app: "PhonePe", upi_id: "techdrona@ybl", payee_name: "Tech Drona", instructions: "" },
  pay_configured: true,
  consent_text: "I agree that Tech Drona may store and use my details.",
};

const pdf = () => new File([new TextEncoder().encode(`%PDF-1.4\n${"receipt ".repeat(40)}`)], "receipt.pdf", { type: "application/pdf" });

async function fillPublicForm() {
  await userEvent.type(await screen.findByRole("textbox", { name: /Full name/ }), "Asha Rao");
  await userEvent.type(screen.getByRole("textbox", { name: /^Email/ }), "asha@example.com");
  await userEvent.type(screen.getByRole("textbox", { name: /Mobile number/ }), "9848012345");
  await userEvent.type(screen.getByRole("textbox", { name: /College/ }), "VRSEC");
  await userEvent.type(screen.getByRole("textbox", { name: /Branch/ }), "CSE");
  await userEvent.type(screen.getByRole("textbox", { name: /Year of study/ }), "3rd year");
  await userEvent.type(screen.getByRole("textbox", { name: /UPI reference/ }), "123456789012");
  await userEvent.upload(screen.getByLabelText(/Payment screenshot or receipt/), pdf());
  await screen.findByText(/ready to upload/);
  await userEvent.click(screen.getByRole("checkbox"));
}

describe("public registration lib", () => {
  it("maps the public plan to the form's view (amount options, payment resolved like the api)", () => {
    expect(firstOptions(pubPlan)).toEqual([
      { label: "Full fee", amount_paise: FEE },
      { label: "First instalment", amount_paise: 250000 },
    ]);
    const v = publicPlanToView(pubPlan);
    expect(v.course_status).toBe("open");
    expect(v.payment).toMatchObject({ upi_id: "techdrona@ybl", payee_name: "Tech Drona", instructions: ["Mention the registration number."] });
    expect(publicPlanToView({ ...pubPlan, active: false }).plan).toBeNull();
  });
  it("reads a public status in student terms and normalises registration numbers", () => {
    expect(publicState({ status: "pending_verification", enrolled: false, open_claims: 1 })).toBe("pending");
    expect(publicState({ status: "enrolled", enrolled: true, open_claims: 0 })).toBe("enrolled");
    expect(publicState({ status: "registered", enrolled: false, open_claims: 0 })).toBe("awaiting_payment");
    expect(normaliseRegNo("tdr-ab12 cd34")).toBe("TDR-AB12CD34");
    expect(normaliseRegNo("AB12CD34")).toBe("TDR-AB12CD34");
  });
});

describe("CourseRegister (public, no account)", () => {
  it("details -> pay -> upload, posts to the public endpoint and shows the registration number", async () => {
    let sent: Record<string, unknown> | undefined;
    const api = mockApi({
      "GET public/admissions/plans/java": { body: pubPlan },
      "POST public/admissions/registrations": (c) => {
        sent = c.body as Record<string, unknown>;
        return { status: 201, body: { reg_no: String(sent.reg_no), email: "asha@example.com", status: "pending_verification", course_title: "Full Stack Java" } };
      },
    });
    cleanups.push(api.restore);
    renderWithProviders(<CourseRegister mode="public" slug="java" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Full Stack Java" })).toBeInTheDocument();
    expect(screen.getByText(/No account needed/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open UPI app/ })).toHaveAttribute("href", expect.stringContaining("upi://pay?pa=techdrona@ybl"));
    expect(screen.getByRole("button", { name: "Copy UPI ID" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Courses" })).toHaveAttribute("href", "/register");

    // email is required for a visitor
    await userEvent.click(screen.getByRole("button", { name: "Submit registration" }));
    expect(await screen.findByText("Enter a valid email address. We send your LMS login here.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);

    await fillPublicForm();
    await userEvent.click(screen.getByRole("button", { name: "Submit registration" }));

    const done = await screen.findByRole("status");
    expect(api.calls.find((c) => c.method === "POST")?.path).toBe("public/admissions/registrations");
    expect(sent).toMatchObject({ course_slug: "java", name: "Asha Rao", email: "asha@example.com", phone: "9848012345", college: "VRSEC", consent: true, claim: { amount_paise: FEE, method: "upi", utr: "123456789012" } });
    expect((sent!.proof as { data_b64: string }).data_b64.length).toBeGreaterThan(100);
    const regNo = String(sent!.reg_no);
    expect(regNo).toMatch(/^TDR-[A-Z2-9]{8}$/);
    expect(done).toHaveTextContent(`Thanks! Your registration number is ${regNo}.`);
    expect(done).toHaveTextContent("We'll verify your payment and send your LMS login details to asha@example.com. Keep this number.");
    expect(within(done).getByRole("link", { name: "Check my registration" })).toHaveAttribute("href", `/register/status?reg_no=${regNo}`);
  });

  it("409 registration_closed: switches to the closed notice", async () => {
    const api = mockApi({
      "GET public/admissions/plans/java": { body: pubPlan },
      "POST public/admissions/registrations": problem(409, "registration_closed", "Registration isn't open", { course_status: "closed" }),
    });
    cleanups.push(api.restore);
    renderWithProviders(<CourseRegister mode="public" slug="java" />);
    await fillPublicForm();
    await userEvent.click(screen.getByRole("button", { name: "Submit registration" }));
    expect(await screen.findByText("Registration is closed")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See all courses" })).toHaveAttribute("href", "/register");
    expect(screen.queryByRole("button", { name: "Submit registration" })).not.toBeInTheDocument();
  });

  it("course coming soon / closed: no form, a clear notice with a link back to courses", async () => {
    const api = mockApi({ "GET public/admissions/plans/java": { body: { ...pubPlan, course_status: "coming_soon" } } });
    cleanups.push(api.restore);
    const { unmount } = renderWithProviders(<CourseRegister mode="public" slug="java" />);
    expect(await screen.findByText("Registration is coming soon")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /Full name/ })).not.toBeInTheDocument();
    unmount();

    // no fee plan (404) but the server page knows the course is closed
    const api2 = mockApi({});
    cleanups.push(api2.restore);
    renderWithProviders(<CourseRegister mode="public" slug="ai" courseTitle="AI Engineering" courseStatus="closed" />);
    expect(await screen.findByText("Registration is closed")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "AI Engineering" })).toBeInTheDocument();
  });
});

describe("CourseRegister (signed in) respects the course status", () => {
  const meView: MyPlanView = { ...publicPlanToView(pubPlan), prefill: { name: "Ravi Kumar", email: "ravi@example.com", phone: "9848012345", college: "VRSEC", branch: "CSE", year: "3rd year" } };
  it("closed course: no form", async () => {
    const api = mockApi({ "GET me/admissions/plans/java": { body: { ...meView, course_status: "closed" } } });
    cleanups.push(api.restore);
    renderWithProviders(<CourseRegister slug="java" />);
    expect(await screen.findByText("Registration is closed")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See all courses" })).toHaveAttribute("href", "/app/courses");
  });
  it("open course: prefilled from the account, no email field", async () => {
    const api = mockApi({ "GET me/admissions/plans/java": { body: meView } });
    cleanups.push(api.restore);
    renderWithProviders(<CourseRegister slug="java" />);
    expect(await screen.findByRole("textbox", { name: /Full name/ })).toHaveValue("Ravi Kumar");
    expect(screen.queryByRole("textbox", { name: /^Email/ })).not.toBeInTheDocument();
  });
});

describe("PublicStatusCheck", () => {
  it("looks up reg no + email through the public endpoint and shows the state", async () => {
    let sent: unknown;
    const api = mockApi({
      "POST public/admissions/status": (c) => {
        sent = c.body;
        return {
          body: { reg_no: "TDR-AB12CD34", email: "asha@example.com", course_slug: "java", course_title: "Full Stack Java", status: "pending_verification", fee_paise: FEE, verified_total_paise: 0, balance_paise: FEE, open_claims: 1, next_due: null, enrolled: false },
        };
      },
    });
    cleanups.push(api.restore);
    renderWithProviders(<PublicStatusCheck initialRegNo="tdr-ab12cd34" />);
    await userEvent.type(screen.getByRole("textbox", { name: /^Email/ }), "asha@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Check status" }));
    expect(await screen.findByText("Payment under verification")).toBeInTheDocument();
    expect(sent).toEqual({ reg_no: "TDR-AB12CD34", email: "asha@example.com" });
  });
  it("not found: shows the api message", async () => {
    const api = mockApi({ "POST public/admissions/status": problem(404, "not_found", "Not found", { detail: "We couldn't find a registration with that number and email." }) });
    cleanups.push(api.restore);
    renderWithProviders(<PublicStatusCheck initialRegNo="TDR-AB12CD34" initialEmail="x@example.com" />);
    await userEvent.click(screen.getByRole("button", { name: "Check status" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("We couldn't find a registration with that number and email.");
  });
});

const enrolledReg = (over: Partial<MyRegistration> = {}): MyRegistration => ({
  registration_id: "r1",
  reg_no: "TDR-AB12CD34",
  course_slug: "java",
  course_title: "Full Stack Java",
  status: "enrolled",
  state: "enrolled",
  reason: null,
  fee_paise: FEE,
  verified_total_paise: FEE,
  balance_paise: 0,
  open_claims: 0,
  next_due: null,
  can_pay: false,
  pay_options: [],
  enrolled: true,
  enrolled_at: "2026-11-12T05:00:00Z",
  course_href: "/app/classes",
  batch: { batch_id: "b1", name: "Java Nov 2026" },
  created_at: "2026-11-10T05:00:00Z",
  claims: [],
  ...over,
});

const batch = (id: string, name: string, slug: string | null, upcoming: MyBatchClasses["upcoming"] = []): MyBatchClasses => ({
  batch: { id, name, code: id, status: "active", starts_on: null, ends_on: null, course_id: null, website_course_slug: slug },
  class_time: null,
  meet_url: null,
  current_week: 1,
  weeks_count: 10,
  end_date: null,
  current_week_title: null,
  min_attendance_percent: null,
  attendance: {} as MyBatchClasses["attendance"],
  upcoming,
  recent: [],
});

describe("MyCoursesCard (student dashboard)", () => {
  it("merges registrations with batches (next class) and keeps batch-only memberships", () => {
    const cls = { id: "s1", batch_id: "b1", session_date: "2026-11-16", starts_at: "18:00", duration_minutes: 120, topic: "Arrays", meet_url: null, recording_url: null, cancelled: false };
    const items = myCourseItems([enrolledReg()], [batch("b1", "Java Nov 2026", "java", [cls]), batch("b2", "Aptitude", null)]);
    expect(items).toHaveLength(2);
    expect(items[0]).toMatchObject({ title: "Full Stack Java", batchName: "Java Nov 2026", href: "/app/classes" });
    expect(items[0]!.nextClass).toMatch(/18:00 IST · Arrays$/);
    expect(items[1]).toMatchObject({ title: "Aptitude", href: "/app/classes" });
  });

  it("shows enrolled courses with Open course, and pending registrations as under review", async () => {
    const api = mockApi({
      "GET me/admissions": {
        body: { data: [enrolledReg(), enrolledReg({ registration_id: "r2", reg_no: "TDR-ZZ12CD34", course_slug: "ai", course_title: "AI Engineering", state: "pending", status: "pending_verification", enrolled: false, enrolled_at: null, batch: null, course_href: null, open_claims: 1 })] },
      },
      "GET me/classes": { body: { today: "2026-11-12", batches: [batch("b1", "Java Nov 2026", "java")] } },
    });
    cleanups.push(api.restore);
    render(<MyCoursesCard />);
    const list = await screen.findByRole("list", { name: "My courses" });
    expect(within(list).getByText("Full Stack Java")).toBeInTheDocument();
    expect(within(list).getByText("Batch: Java Nov 2026")).toBeInTheDocument();
    expect(within(list).getByText("Enrolled")).toBeInTheDocument();
    expect(within(list).getByRole("link", { name: "Open course: Full Stack Java" })).toHaveAttribute("href", "/app/classes");
    expect(within(list).getByText("Payment under review")).toBeInTheDocument();
    expect(within(list).getByRole("link", { name: "My registrations" })).toHaveAttribute("href", "/app/registrations");
  });

  it("renders nothing for a learner with no registrations or batches", async () => {
    const api = mockApi({ "GET me/admissions": { body: { data: [] } }, "GET me/classes": { body: { today: "2026-11-12", batches: [] } } });
    cleanups.push(api.restore);
    const { container } = render(<MyCoursesCard />);
    await vi.waitFor(() => expect(api.calls).toHaveLength(2));
    await new Promise((r) => setTimeout(r, 20));
    expect(container).toBeEmptyDOMElement();
  });
});

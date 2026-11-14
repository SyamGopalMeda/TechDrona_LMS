import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { AdmissionsOverview } from "./Admissions";
import { FeePlans, formToBody, planToForm, validatePlan, emptyPlan } from "./FeePlans";

vi.setConfig({ testTimeout: 20000 });
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }), usePathname: () => "/finance/admissions/plans", useSearchParams: () => new URLSearchParams(window.location.search) }));

const cleanups: (() => void)[] = [];
afterEach(() => {
  while (cleanups.length) cleanups.pop()!();
  window.history.replaceState(null, "", "/");
});

const plan = {
  fee_plan_id: "p1",
  slug: "nextgen-career-accelerator-2026",
  title: "NextGen Career Accelerator 2026",
  course_id: null,
  batch_id: "b1",
  fee_paise: 500000,
  allow_instalments: false,
  schedule: [{ label: "Full fee", amount_paise: 500000, due: "" }],
  policy: "full",
  min_first_paise: 500000,
  access_min_paise: 500000,
  upi_id: "",
  payee_name: "",
  bank_details: "",
  instructions: "",
  active: false,
  updated_at: "2026-11-13T05:00:00Z",
  problems: [],
};
const pay = { phone: "9502524924", preferred_app: "PhonePe", upi_id: "techdrona@ybl", payee_name: "Tech Drona", instructions: "" };
const batches = [{ batch_id: "b1", name: "NextGen Jan", code: "NG1", course_id: "0193a000-0000-7000-8000-000000000001", website_course_slug: "nextgen-career-accelerator-2026" }];
const titles = { "nextgen-career-accelerator-2026": "NextGen Career Accelerator 2026", "python-basics": "Python Basics" };
const statuses = {
  data: [
    { course_slug: "nextgen-career-accelerator-2026", title: "NextGen Career Accelerator 2026", status: "open", effective_status: "closed", updated_at: null, fee_paise: 500000, plan_active: false, batch: { batch_id: "b1", name: "NextGen Jan" } },
  ],
};

function routes(extra: Record<string, Parameters<typeof mockApi>[0][string]> = {}, plans = [plan]) {
  return mockApi({
    "GET admin/admissions/plans": { body: { data: plans, pay, batches } },
    "GET admin/courses/status": { body: statuses },
    ...extra,
  });
}

const rowOf = async (name: string) => screen.findByRole("listitem", { name });

describe("Fee plans (Admin › Payments › Admissions › Fee plans)", () => {
  it("lists every website course first, including one with no plan, then the default payment details", async () => {
    const api = routes();
    cleanups.push(api.restore);
    renderWithProviders(<FeePlans titles={titles} />);

    const list = await screen.findByRole("list", { name: "Courses and fee plans" });
    const ng = within(list).getByRole("listitem", { name: "NextGen Career Accelerator 2026" });
    expect(within(ng).getByText("₹5,000.00")).toBeInTheDocument();
    expect(within(ng).getByText("No (full fee)")).toBeInTheDocument();
    expect(within(ng).getByText("Batch: NextGen Jan (NG1)")).toBeInTheDocument();
    expect(within(ng).getByText("Plan inactive")).toBeInTheDocument();
    // set to open, but students see Closed while the plan is inactive
    expect(within(ng).getByText("Registration: Closed")).toBeInTheDocument();
    expect(within(ng).getByText(/students see it as closed because the fee plan is inactive/)).toBeInTheDocument();
    expect(within(ng).getByRole("button", { name: "Edit fee plan: NextGen Career Accelerator 2026" })).toBeInTheDocument();
    expect(within(ng).getByRole("button", { name: "Activate fee plan: NextGen Career Accelerator 2026" })).toBeInTheDocument();
    expect(within(ng).getByRole("link", { name: /Open registration \(Courses\)/ })).toHaveAttribute("href", "/finance/admissions#course-status");

    const py = within(list).getByRole("listitem", { name: "Python Basics" });
    expect(within(py).getByText("No fee plan")).toBeInTheDocument();
    expect(within(py).getByText("Registration: Coming soon")).toBeInTheDocument();
    expect(within(py).getByRole("button", { name: "Set up fee plan: Python Basics" })).toBeInTheDocument();
    expect(within(py).queryByRole("button", { name: /Activate/ })).not.toBeInTheDocument();

    // the defaults card comes after the list
    const defaults = screen.getByRole("heading", { name: "Default payment details (used when a course has none)" });
    expect(list.compareDocumentPosition(defaults) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("Edit opens the plan form in a dialog with the plan's values, grouped; Cancel closes it without saving", async () => {
    const api = routes();
    cleanups.push(api.restore);
    renderWithProviders(<FeePlans titles={titles} />);
    await userEvent.click(within(await rowOf("NextGen Career Accelerator 2026")).getByRole("button", { name: /^Edit fee plan/ }));

    const dialog = await screen.findByRole("dialog", { name: "Edit fee plan: NextGen Career Accelerator 2026" });
    for (const g of ["Course & batch", "Fee", "Where students pay", "Status"]) expect(within(dialog).getByRole("group", { name: g })).toBeInTheDocument();
    const course = within(dialog).getByLabelText("Website course");
    expect(course).toHaveValue("nextgen-career-accelerator-2026");
    expect(course).toHaveAttribute("readonly");
    expect(within(dialog).getByLabelText(/Course title/)).toHaveValue("NextGen Career Accelerator 2026");
    expect(within(dialog).getByLabelText("LMS batch")).toHaveValue("b1");
    expect(within(dialog).getByLabelText(/Course fee/)).toHaveValue("5000");
    expect(within(dialog).getByLabelText("Allow instalments")).not.toBeChecked();
    expect(within(dialog).getByLabelText("Fee plan active")).not.toBeChecked();
    expect(within(dialog).getByText(/Leave these empty to use the default payment details/)).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(api.calls.some((c) => c.method === "PUT")).toBe(false);
  });

  it("saves an edited plan, shows a toast and reloads the list", async () => {
    let saved = plan;
    const api = mockApi({
      "GET admin/admissions/plans": () => ({ body: { data: [saved], pay, batches } }),
      "GET admin/courses/status": { body: statuses },
      "PUT admin/admissions/plans": (c) => {
        saved = { ...plan, fee_paise: (c.body as { fee_paise: number }).fee_paise, active: (c.body as { active: boolean }).active };
        return { body: saved };
      },
    });
    cleanups.push(api.restore);
    renderWithProviders(<FeePlans titles={titles} />);
    await userEvent.click(within(await rowOf("NextGen Career Accelerator 2026")).getByRole("button", { name: /^Edit fee plan/ }));
    const dialog = await screen.findByRole("dialog", { name: /Edit fee plan/ });
    const fee = within(dialog).getByLabelText(/Course fee/);
    await userEvent.clear(fee);
    await userEvent.type(fee, "6000");
    await userEvent.click(within(dialog).getByLabelText("Fee plan active"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Save fee plan" }));

    await waitFor(() => expect(api.calls.some((c) => c.method === "PUT")).toBe(true));
    expect(api.calls.find((c) => c.method === "PUT")!.body).toEqual({
      slug: "nextgen-career-accelerator-2026",
      title: "NextGen Career Accelerator 2026",
      course_id: null,
      batch_id: "b1",
      fee_paise: 600000,
      allow_instalments: false,
      schedule: [],
      min_first_paise: null,
      access_min_paise: null,
      upi_id: null,
      payee_name: null,
      bank_details: null,
      instructions: null,
      active: true,
      fee_plan_id: "p1", // editing a saved plan locks its slug server-side (409 slug_locked)
    });
    expect(await screen.findByText("Fee plan saved: NextGen Career Accelerator 2026.")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const row = await rowOf("NextGen Career Accelerator 2026");
    await waitFor(() => expect(within(row).getByText("₹6,000.00")).toBeInTheDocument());
    expect(within(row).getByText("Plan active")).toBeInTheDocument();
    expect(api.calls.filter((c) => c.method === "GET" && c.path === "admin/admissions/plans").length).toBeGreaterThanOrEqual(2);
  });

  it("sets up a plan for a website course with no plan: checks fields next to them, then saves with instalments in paise", async () => {
    const api = routes({ "PUT admin/admissions/plans": (c) => ({ body: { ...plan, ...(c.body as object) } }) });
    cleanups.push(api.restore);
    renderWithProviders(<FeePlans titles={titles} />);
    await userEvent.click(within(await rowOf("Python Basics")).getByRole("button", { name: "Set up fee plan: Python Basics" }));
    const dialog = await screen.findByRole("dialog", { name: "Set up fee plan: Python Basics" });
    expect(within(dialog).getByLabelText("Website course")).toHaveValue("python-basics");
    expect(within(dialog).getByLabelText(/Course title/)).toHaveValue("Python Basics");

    await userEvent.click(within(dialog).getByRole("button", { name: "Save fee plan" }));
    expect(await within(dialog).findByText("Enter the course fee.")).toBeInTheDocument();
    expect(within(dialog).getByLabelText(/Course fee/)).toHaveAttribute("aria-invalid", "true");
    expect(api.calls.some((c) => c.method === "PUT")).toBe(false);

    await userEvent.type(within(dialog).getByLabelText(/Course fee/), "3000");
    await userEvent.click(within(dialog).getByLabelText("Allow instalments"));
    await userEvent.type(within(dialog).getByLabelText("Instalment 1 amount (₹)"), "1000");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save fee plan" }));
    expect(await within(dialog).findByText("The instalments add up to ₹1,000.00, but the fee is ₹3,000.00.")).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("button", { name: "Add instalment" }));
    await userEvent.type(within(dialog).getByLabelText("Instalment 2 amount (₹)"), "2000");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save fee plan" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "PUT")).toBe(true));
    expect(api.calls.find((c) => c.method === "PUT")!.body).toMatchObject({
      slug: "python-basics",
      title: "Python Basics",
      fee_paise: 300000,
      allow_instalments: true,
      schedule: [
        { label: "First instalment", amount_paise: 100000, due: "" },
        { label: "Instalment 2", amount_paise: 200000, due: "" },
      ],
      active: false,
    });
    expect(await screen.findByText("It's inactive: activate it before opening registration.")).toBeInTheDocument();
  });

  it("shows an api field error next to its field and keeps the dialog open", async () => {
    const api = routes({
      "PUT admin/admissions/plans": problem(422, "validation_failed", "Check the fields", {
        errors: [{ field: "active", code: "pay_to_missing", message: "Set the payment number in Payment details before opening online registration." }],
      }),
    });
    cleanups.push(api.restore);
    renderWithProviders(<FeePlans titles={titles} />);
    await userEvent.click(within(await rowOf("NextGen Career Accelerator 2026")).getByRole("button", { name: /^Edit fee plan/ }));
    const dialog = await screen.findByRole("dialog", { name: /Edit fee plan/ });
    await userEvent.click(within(dialog).getByLabelText("Fee plan active"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Save fee plan" }));
    const status = within(dialog).getByRole("group", { name: "Status" });
    expect(await within(status).findByText(/Set the payment number in Payment details/)).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: /Edit fee plan/ })).toBeInTheDocument();
  });

  it("Activate/Deactivate use the on/off endpoint (only active changes); Deactivate asks first", async () => {
    let current = plan;
    const api = mockApi({
      "GET admin/admissions/plans": () => ({ body: { data: [current], pay, batches } }),
      "GET admin/courses/status": { body: statuses },
      "POST admin/admissions/plans/nextgen-career-accelerator-2026/active": (c) => {
        current = { ...current, active: (c.body as { active: boolean }).active };
        return { body: current };
      },
    });
    cleanups.push(api.restore);
    renderWithProviders(<FeePlans titles={titles} />);
    await userEvent.click(within(await rowOf("NextGen Career Accelerator 2026")).getByRole("button", { name: /^Activate fee plan/ }));
    const onOff = () => api.calls.filter((c) => c.method === "POST" && c.path.endsWith("/active"));
    await waitFor(() => expect(onOff().length).toBe(1));
    expect(onOff()[0]!.body).toEqual({ active: true });
    expect(api.calls.some((c) => c.method === "PUT")).toBe(false);
    expect(await screen.findByText("NextGen Career Accelerator 2026: fee plan active.")).toBeInTheDocument();
    const row = await rowOf("NextGen Career Accelerator 2026");
    await waitFor(() => expect(within(row).getByText("Plan active")).toBeInTheDocument());

    await userEvent.click(within(row).getByRole("button", { name: /^Deactivate fee plan/ }));
    const confirm = await screen.findByRole("dialog", { name: "Deactivate this fee plan?" });
    await userEvent.click(within(confirm).getByRole("button", { name: "Deactivate plan" }));
    await waitFor(() => expect(onOff().length).toBe(2));
    expect(onOff()[1]!.body).toEqual({ active: false });
    await waitFor(() => expect(within(row).getByText("Plan inactive")).toBeInTheDocument());
  });

  it("reports a failed Activate next to the course", async () => {
    const api = routes({
      "POST admin/admissions/plans/nextgen-career-accelerator-2026/active": problem(422, "validation_failed", "Check the fields", { errors: [{ field: "active", code: "pay_to_missing", message: "Set the payment number first." }] }),
    });
    cleanups.push(api.restore);
    renderWithProviders(<FeePlans titles={titles} />);
    const row = await rowOf("NextGen Career Accelerator 2026");
    await userEvent.click(within(row).getByRole("button", { name: /^Activate fee plan/ }));
    expect(await within(row).findByRole("alert")).toHaveTextContent("Set the payment number first.");
  });

  it("?edit=<slug> (from Courses › Set the fee) opens that course's plan", async () => {
    window.history.replaceState(null, "", "/finance/admissions/plans?edit=python-basics");
    const api = routes();
    cleanups.push(api.restore);
    renderWithProviders(<FeePlans titles={titles} />);
    expect(await screen.findByRole("dialog", { name: "Set up fee plan: Python Basics" })).toBeInTheDocument();
  });

  it("saves the default payment details from their own card", async () => {
    const api = routes({ "PUT admin/admissions/pay-settings": (c) => ({ body: c.body }) });
    cleanups.push(api.restore);
    renderWithProviders(<FeePlans titles={titles} />);
    const card = (await screen.findByRole("heading", { name: "Default payment details (used when a course has none)" })).closest("section")!;
    const upi = within(card).getByLabelText(/UPI ID \(students scan/);
    expect(upi).toHaveValue("techdrona@ybl");
    await userEvent.clear(upi);
    await userEvent.type(upi, "drona@okaxis");
    expect(await within(card).findByRole("img", { name: "UPI QR code for drona@okaxis" })).toBeInTheDocument();
    await userEvent.click(within(card).getByRole("button", { name: "Save payment details" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "PUT" && c.path.endsWith("pay-settings"))).toBe(true));
    expect(api.calls.find((c) => c.method === "PUT")!.body).toEqual({ ...pay, upi_id: "drona@okaxis" });
    expect(await screen.findByText("Default payment details saved.")).toBeInTheDocument();
  });

  it("shows a pay-settings field error next to the field", async () => {
    const api = routes({ "PUT admin/admissions/pay-settings": problem(422, "validation_failed", "Check the fields", { errors: [{ field: "phone", code: "invalid_mobile", message: "Enter a 10-digit Indian mobile number." }] }) });
    cleanups.push(api.restore);
    renderWithProviders(<FeePlans titles={titles} />);
    await userEvent.click(await screen.findByRole("button", { name: "Save payment details" }));
    expect(await screen.findByText("Enter a 10-digit Indian mobile number.")).toBeInTheDocument();
    expect(screen.getByLabelText("Payment number (10 digits)")).toHaveAttribute("aria-invalid", "true");
  });

  it("maps plans to the form and back without turning a full-fee plan into a 'first payment = whole fee' instalment plan", () => {
    const f = planToForm(plan as never);
    expect(f.min_first).toBe("");
    expect(f.schedule).toEqual([{ label: "First instalment", amount: "", due: "" }]);
    expect(formToBody(f)).toMatchObject({ fee_paise: 500000, schedule: [], min_first_paise: null, access_min_paise: null });
    expect(validatePlan({ ...emptyPlan(), slug: "Bad Slug", title: "", fee: "abc", course_id: "nope", upi_id: "x" })).toMatchObject({
      slug: expect.any(String),
      title: expect.any(String),
      fee: expect.any(String),
      course_id: expect.any(String),
      upi_id: expect.any(String),
    });
  });
});

describe("Courses switch (Admissions overview)", () => {
  it("lists website courses the api doesn't know yet and warns when an open course reads Closed", async () => {
    const api = mockApi({
      "GET admin/admissions/overview": {
        body: { registered: 0, enrolled: 0, pending_claims: 0, pending_amount_paise: 0, needs_info_claims: 0, rejected_claims: 0, closed_registrations: 0, collected_paise: 0, expected_paise: 0, outstanding_paise: 0, courses: [], recent: [] },
      },
      "GET admin/courses/status": { body: statuses },
    });
    cleanups.push(api.restore);
    renderWithProviders(<AdmissionsOverview titles={titles} />);
    expect(await screen.findByRole("group", { name: "Registration for Python Basics" })).toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Registration for Python Basics" })).getByLabelText("Coming soon")).toBeChecked();
    expect(screen.getByText(/Students see this course as Closed: its fee plan is inactive/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Set up the fee plan" })).toHaveAttribute("href", "/finance/admissions/plans?edit=python-basics");
  });
});

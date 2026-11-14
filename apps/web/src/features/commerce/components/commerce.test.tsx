import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PLANS_HREF } from "@/lib/site/website";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { downloadSink } from "../lib/download";
import { isTestMode, providerFor, razorpayProvider, testGatewayProvider } from "../lib/payment-provider";
import { AccessList, accessTitle } from "./AccessList";
import { Billing } from "./Billing";
import { Checkout, cadenceLabel, checkoutItem } from "./Checkout";
import { OrderStatus } from "./OrderStatus";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

let restore: (() => void) | undefined;
afterEach(() => {
  restore?.();
  push.mockReset();
});

const page = { next_cursor: null, has_more: false, limit: 25 };
const quote = {
  price_id: "p1",
  product: { sku: "PP-TCS-NQT-180", name: "TCS NQT Placement Package (180 days)", product_kind: "placement_package" },
  list_amount_paise: 349900,
  discount_paise: 0,
  taxable_paise: 296525,
  cgst_paise: 26687,
  sgst_paise: 26688,
  igst_paise: 0,
  total_paise: 349900,
  coupon: null,
  warnings: [],
  blocking: [],
  refund_rule: "Full refund within 7 days of purchase if less than 20% of the content is used and no certificate is issued.",
  access_ends_at: "2027-05-02T10:15:00.000Z",
};
const order = {
  order_id: "o1",
  order_number: "TD-O-2026-00001234",
  status: "pending_payment",
  total_paise: 349900,
  currency: "INR",
  expires_at: "2026-11-03T10:45:02.000Z",
  gateway: "fake",
  checkout: { key_id: "fake_test", gateway_order_id: "order_fake_1", amount: 349900, currency: "INR", name: "Tech Drona", test_payment: { payment_id: "pay_fake_1", signature: "sig_fake_1" } },
};

describe("payment provider", () => {
  it("picks the test gateway for the dev fake provider and Razorpay otherwise", () => {
    expect(providerFor(order)).toBe(testGatewayProvider);
    expect(providerFor({ gateway: "razorpay", checkout: { ...order.checkout, key_id: "rzp_live_x", test_payment: null } })).toBe(razorpayProvider);
    expect(isTestMode({ gateway: "razorpay", checkout: { ...order.checkout, key_id: "rzp_test_x", test_payment: null } })).toBe(true);
    expect(isTestMode({ gateway: "razorpay", checkout: { ...order.checkout, key_id: "rzp_live_x", test_payment: null } })).toBe(false);
  });
});

describe("Checkout (STU-016)", () => {
  it("quotes with GST, creates the order, pays in test mode and confirms server-side", async () => {
    const api = mockApi({
      "POST commerce/checkout/quote": { body: quote },
      "POST commerce/orders": { status: 201, body: order },
      "POST commerce/orders/o1/confirm": { body: { order_id: "o1", status: "paid" } },
    });
    restore = api.restore;
    renderWithProviders(<Checkout priceId="p1" returnTo="/pricing" />);
    expect(screen.getByText(/Choose your state to see/)).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText(/Name on invoice/), "Ananya Reddy");
    await userEvent.selectOptions(screen.getByLabelText(/^State/), "36");
    const summary = await screen.findByRole("complementary", { name: "Order summary" });
    expect(await within(summary).findByText("CGST (9%)")).toBeInTheDocument();
    expect(within(summary).getByText("Total (incl. GST)").nextSibling).toHaveTextContent("₹3,499");
    expect(within(summary).getByText(/Full refund within 7 days/)).toBeInTheDocument();
    const quoteCall = api.calls.find((c) => c.path === "commerce/checkout/quote")!;
    expect(quoteCall.body).toEqual({ price_id: "p1", coupon_code: null, billing: { state_code: "36" } });

    await userEvent.click(screen.getByRole("button", { name: "Continue to payment" }));
    expect(await screen.findByText("Test mode — no real money is charged")).toBeInTheDocument();
    const orderCall = api.calls.find((c) => c.path === "commerce/orders")!;
    expect(orderCall.body).toEqual({ price_id: "p1", coupon_code: null, billing: { name: "Ananya Reddy", state_code: "36", gstin: null }, quote_total_paise: 349900 });
    expect(orderCall.headers["idempotency-key"]).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "Pay ₹3,499" }));
    await userEvent.click(await screen.findByRole("button", { name: "Simulate a successful payment" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/app/orders/o1"));
    const confirm = api.calls.find((c) => c.path === "commerce/orders/o1/confirm")!;
    expect(confirm.body).toEqual({ razorpay_order_id: "order_fake_1", razorpay_payment_id: "pay_fake_1", razorpay_signature: "sig_fake_1" });
    expect(confirm.headers["idempotency-key"]).toBeTruthy();
  });

  it("reports a simulated failure without confirming and lets the learner retry", async () => {
    const api = mockApi({ "POST commerce/checkout/quote": { body: quote }, "POST commerce/orders": { status: 201, body: order } });
    restore = api.restore;
    renderWithProviders(<Checkout priceId="p1" />);
    await userEvent.type(screen.getByLabelText(/Name on invoice/), "Ananya");
    await userEvent.selectOptions(screen.getByLabelText(/^State/), "29");
    await screen.findByText("CGST (9%)");
    await userEvent.click(screen.getByRole("button", { name: "Continue to payment" }));
    await userEvent.click(await screen.findByRole("button", { name: "Pay ₹3,499" }));
    await userEvent.click(await screen.findByRole("button", { name: "Simulate a failed payment" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Test payment declined");
    expect(api.calls.some((c) => c.path.endsWith("/confirm"))).toBe(false);
    expect(screen.getByRole("button", { name: "Pay ₹3,499" })).toBeEnabled();
  });

  it("blocks payment when the plan is already owned and shows coupon feedback", async () => {
    const api = mockApi({
      "POST commerce/checkout/quote": (c) => ({
        body: {
          ...quote,
          coupon: (c.body as { coupon_code: string | null }).coupon_code ? { code: "OLD", status: "expired" } : null,
          blocking: [{ code: "already_owned" }],
        },
      }),
    });
    restore = api.restore;
    renderWithProviders(<Checkout priceId="p1" />);
    await userEvent.selectOptions(screen.getByLabelText(/^State/), "36");
    expect(await screen.findByText(/already have access/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue to payment" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Coupon code/), "old");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(await screen.findByText("This coupon has expired.")).toBeInTheDocument();
  });

  it("explains a refused order with a link to fix it", async () => {
    const api = mockApi({ "POST commerce/checkout/quote": { body: quote }, "POST commerce/orders": problem(403, "contact_not_verified", "Verify your contact details first") });
    restore = api.restore;
    renderWithProviders(<Checkout priceId="p1" />);
    await userEvent.type(screen.getByLabelText(/Name on invoice/), "Ananya");
    await userEvent.selectOptions(screen.getByLabelText(/^State/), "36");
    await screen.findByText("CGST (9%)");
    await userEvent.click(screen.getByRole("button", { name: "Continue to payment" }));
    expect((await screen.findAllByText("Verify your contact details first"))[0]).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Verify your email and mobile" })).toHaveAttribute("href", "/app/settings/profile");
  });

  it("asks for a plan when no price is given", () => {
    renderWithProviders(<Checkout priceId={null} />);
    expect(screen.getByText("Choose a plan first")).toBeInTheDocument();
  });
});

describe("OrderStatus (STU-017)", () => {
  it("shows a paid order with its access and invoice", async () => {
    const api = mockApi({
      "GET commerce/orders/o1": {
        body: { ...order, status: "paid", paid_at: "2026-11-03T10:17:40.000Z", checkout: null, gateway: "razorpay", entitlements: [{ entitlement_id: "e1", title: "TCS NQT Placement Package", ends_at: "2027-05-02T10:17:40.000Z" }], invoice: { invoice_number: "TD/2627/000123", pdf_ready: false } },
      },
    });
    restore = api.restore;
    renderWithProviders(<OrderStatus orderId="o1" />);
    expect(await screen.findByText("Payment confirmed. Your access is active.")).toBeInTheDocument();
    expect(screen.getByText(/TCS NQT Placement Package/)).toBeInTheDocument();
    expect(screen.getByText(/TD\/2627\/000123/)).toBeInTheDocument();
    expect(screen.queryByText(/Test mode/)).not.toBeInTheDocument();
  });

  it("polls while the payment is being confirmed", async () => {
    let n = 0;
    const api = mockApi({ "GET commerce/orders/o1": () => ({ body: ++n < 2 ? { ...order, message: "Payment received by bank, confirming…" } : { ...order, status: "paid", checkout: null } }) });
    restore = api.restore;
    renderWithProviders(<OrderStatus orderId="o1" />);
    expect(await screen.findByText("Payment received by bank, confirming…")).toBeInTheDocument();
    expect(screen.getByText("Test mode — no real money is charged")).toBeInTheDocument();
    expect(await screen.findByText("Payment confirmed. Your access is active.", {}, { timeout: 6000 })).toBeInTheDocument();
  }, 10_000);
});

describe("Billing (STU-018)", () => {
  it("requests a refund after showing the rule evaluation", async () => {
    const api = mockApi({
      "GET me/orders": { body: { data: [{ ...order, status: "paid", paid_at: "2026-11-01T10:00:00.000Z" }], page } },
      "GET me/orders/o1/refund-eligibility": {
        body: { order_id: "o1", refund_rule: "7 days", eligible: true, reasons: [], days_since_purchase: 2, consumption_pct: 6.5, certificate_issued: false, refundable_paise: 349900 },
      },
      "POST me/refund-requests": { status: 201, body: { refund_id: "r1", order_id: "o1", status: "requested", decision_due: "2026-11-10" } },
    });
    restore = api.restore;
    renderWithProviders(<Billing />);
    await userEvent.click(await screen.findByRole("button", { name: "Request a refund for TD-O-2026-00001234" }));
    expect(await screen.findByText("This order meets the refund rule.")).toBeInTheDocument();
    expect(screen.getByText("7% of the content used")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Request refund" }));
    await waitFor(() => expect(api.calls.some((c) => c.path === "me/refund-requests")).toBe(true));
    const call = api.calls.find((c) => c.path === "me/refund-requests")!;
    expect(call.body).toEqual({ order_id: "o1", reason_code: "within_policy_window", note: null });
    expect(call.headers["idempotency-key"]).toBeTruthy();
    expect(await screen.findByText(/Refund requested/)).toBeInTheDocument();
  });

  it("cancels a subscription in one click", async () => {
    let cancelled = false;
    const api = mockApi({
      "GET me/orders": { body: { data: [], page } },
      "GET me/subscriptions": () => ({
        body: {
          data: [
            {
              subscription_id: "s1",
              plan_id: "pl1",
              price_id: "p1",
              status: "active",
              current_period_start: "2026-11-01T18:30:00.000Z",
              current_period_end: "2026-12-01T18:29:59.000Z",
              next_charge_at: "2026-12-01T18:29:59.000Z",
              cancel_at_period_end: cancelled,
              grace_until: null,
            },
          ],
          page,
        },
      }),
      "POST me/subscriptions/s1/cancel": () => {
        cancelled = true;
        return { body: { subscription_id: "s1", status: "active", cancel_at_period_end: true, access_until: "2026-12-01T18:29:59.000Z", confirmation_sent: true } };
      },
    });
    restore = api.restore;
    renderWithProviders(<Billing />);
    await userEvent.click(screen.getByRole("tab", { name: "Subscriptions" }));
    await userEvent.click(await screen.findByRole("button", { name: /Cancel subscription started/ }));
    const call = api.calls.find((c) => c.path === "me/subscriptions/s1/cancel")!;
    expect(call.body).toEqual({ reason: null, feedback: null });
    expect(await screen.findByText(/You keep access until 1 Dec 2026/)).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /Resume subscription started/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Change plan/ })).not.toBeInTheDocument();
  });

  it("downloads an invoice PDF from a fresh signed URL on every click", async () => {
    const open = vi.spyOn(downloadSink, "open").mockImplementation(() => {});
    let n = 0;
    const api = mockApi({
      "GET me/orders": { body: { data: [], page } },
      "GET me/invoices": {
        body: {
          data: [
            { invoice_id: "i1", invoice_number: "TD/2627/000123", invoice_type: "tax_invoice", order_id: "o1", issue_date: "2026-11-03", total_paise: 349900, status: "issued", pdf_ready: true, description: null, due_on: null },
            { invoice_id: "c1", invoice_number: "TDCN/2627/000001", invoice_type: "credit_note", order_id: "o1", issue_date: "2026-11-04", total_paise: 349900, status: "issued", pdf_ready: true },
          ],
          page,
        },
      },
      "GET me/invoices/i1/pdf": () => ({ body: { url: `https://files.example/i1.pdf?sig=${++n}`, expires_at: "2026-11-03T10:05:00Z", filename: "TD-2627-000123.pdf" } }),
      "GET me/invoices/c1/pdf": problem(409, "invalid_state_transition", "The PDF is still being prepared"),
    });
    restore = api.restore;
    renderWithProviders(<Billing />);
    await userEvent.click(screen.getByRole("tab", { name: "Invoices" }));
    const btn = await screen.findByRole("button", { name: "Download PDF for invoice TD/2627/000123" });
    await userEvent.click(btn);
    await waitFor(() => expect(open).toHaveBeenCalledWith({ url: "https://files.example/i1.pdf?sig=1", expires_at: "2026-11-03T10:05:00Z", filename: "TD-2627-000123.pdf" }));
    await userEvent.click(btn);
    await waitFor(() => expect(open).toHaveBeenCalledTimes(2));
    expect(open.mock.calls[1]![0].url).toContain("sig=2");
    expect(api.calls.filter((c) => c.path === "me/invoices/i1/pdf")).toHaveLength(2);

    await userEvent.click(screen.getByRole("button", { name: "Download PDF for credit note TDCN/2627/000001" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The PDF is still being prepared");
    expect(open).toHaveBeenCalledTimes(2);
    open.mockRestore();
  });
});

const sub = {
  subscription_id: "s1",
  plan_id: "pl1",
  price_id: "pm",
  status: "active",
  current_period_start: "2026-11-01T18:30:00.000Z",
  current_period_end: "2026-12-01T18:29:59.000Z",
  next_charge_at: "2026-12-01T18:29:59.000Z",
  cancel_at_period_end: false,
  grace_until: null,
  scheduled_price_id: null,
  scheduled_change_at: null,
  pending_addon_paise: 0,
};
const recurringPlan = (plan_id: string, prices: { price_id: string; amount_paise: number }[]) => ({
  plan_id,
  code: plan_id,
  billing_type: "recurring",
  interval_unit: "month",
  interval_count: 1,
  access_duration_days: null,
  prices: prices.map((p) => ({ ...p, currency: "INR", tax_inclusive: true, is_recurring: true, valid_from: "2026-01-01", valid_until: null, is_active: true })),
});
const products = {
  data: [
    { product_id: "pr1", sku: "SUB-MONTHLY", name: "All-access Monthly", product_kind: "subscription", plans: [recurringPlan("pl1", [{ price_id: "pm", amount_paise: 49900 }])] },
    { product_id: "pr2", sku: "SUB-PRO", name: "Pro Monthly", product_kind: "subscription", plans: [recurringPlan("pl2", [{ price_id: "pp", amount_paise: 99900 }])] },
    { product_id: "pr3", sku: "SUB-LITE", name: "Lite Monthly", product_kind: "subscription", plans: [recurringPlan("pl3", [{ price_id: "pl", amount_paise: 19900 }])] },
    {
      product_id: "pr4",
      sku: "PP-1",
      name: "Placement Package",
      product_kind: "placement_package",
      plans: [{ ...recurringPlan("pl4", [{ price_id: "one", amount_paise: 349900 }]), billing_type: "one_time" }],
    },
  ],
  page,
};
const upgrade = {
  subscription_id: "s1",
  direction: "upgrade",
  effective: "now",
  effective_at: "2026-11-16T10:00:00Z",
  from_price_id: "pm",
  to_price_id: "pp",
  from_amount_paise: 49900,
  to_amount_paise: 99900,
  remaining_days: 15,
  period_days: 30,
  proration_paise: 25000,
  next_debit_paise: 124900,
  preview: true,
  subscription: sub,
};

describe("Billing subscriptions: resume and change plan (STU-018)", () => {
  it("resumes a subscription scheduled to cancel", async () => {
    let cancelAtEnd = true;
    const api = mockApi({
      "GET me/orders": { body: { data: [], page } },
      "GET me/subscriptions": () => ({ body: { data: [{ ...sub, cancel_at_period_end: cancelAtEnd }], page } }),
      "POST me/subscriptions/s1/resume": () => {
        cancelAtEnd = false;
        return { body: { ...sub, cancel_at_period_end: false } };
      },
    });
    restore = api.restore;
    renderWithProviders(<Billing />);
    await userEvent.click(screen.getByRole("tab", { name: "Subscriptions" }));
    expect(await screen.findByText("Cancels at period end")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Resume subscription started/ }));
    expect(await screen.findByText(/Subscription resumed. It renews on 1 Dec 2026/)).toBeInTheDocument();
    const call = api.calls.find((c) => c.path === "me/subscriptions/s1/resume")!;
    expect(call.method).toBe("POST");
    expect(call.headers["idempotency-key"]).toBeTruthy();
    expect(await screen.findByRole("button", { name: /Cancel subscription started/ })).toBeInTheDocument();
  });

  it("previews an upgrade with proration, then confirms with a fresh Idempotency-Key", async () => {
    const api = mockApi({
      "GET me/orders": { body: { data: [], page } },
      "GET me/subscriptions": { body: { data: [sub], page } },
      "GET commerce/products": { body: products },
      "POST me/subscriptions/s1/change-plan": (c) => ({ body: { ...upgrade, preview: (c.body as { preview: boolean }).preview } }),
    });
    restore = api.restore;
    renderWithProviders(<Billing />);
    await userEvent.click(screen.getByRole("tab", { name: "Subscriptions" }));
    await userEvent.click(await screen.findByRole("button", { name: /Change plan for subscription started/ }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Upgrades/).parentElement).toHaveTextContent(/added to your next renewal debit/);
    expect(within(dialog).getByText(/Downgrades/).parentElement).toHaveTextContent(/no refund for the current period/);
    const select = await within(dialog).findByLabelText(/New plan/);
    // Current price and one-time plans are not offered.
    const labels = within(select).getAllByRole("option").map((o) => o.textContent);
    expect(labels).toEqual(["Choose a plan", "Pro Monthly · ₹999 /month", "Lite Monthly · ₹199 /month"]);
    await userEvent.selectOptions(select, "pp");
    await userEvent.click(within(dialog).getByRole("button", { name: "Preview change" }));

    const preview = await within(dialog).findByRole("region", { name: "Change preview" });
    expect(preview).toHaveTextContent("Upgrade to Pro Monthly: takes effect now");
    expect(preview).toHaveTextContent("Prorated difference (15 of 30 days left)₹250");
    expect(preview).toHaveTextContent("Next renewal debit₹1,249");
    await userEvent.click(within(dialog).getByRole("button", { name: "Confirm upgrade" }));
    expect(await screen.findByText(/Plan upgraded. ₹250 will be added to your next renewal./)).toBeInTheDocument();

    const posts = api.calls.filter((c) => c.path === "me/subscriptions/s1/change-plan");
    expect(posts.map((c) => c.body)).toEqual([
      { price_id: "pp", preview: true },
      { price_id: "pp", preview: false },
    ]);
    expect(posts[0]!.headers["idempotency-key"]).toBeTruthy();
    expect(posts[1]!.headers["idempotency-key"]).toBeTruthy();
    expect(posts[0]!.headers["idempotency-key"]).not.toBe(posts[1]!.headers["idempotency-key"]);
  });

  it("explains the ₹15,000 mandate cap when an upgrade would exceed it", async () => {
    const api = mockApi({
      "GET me/orders": { body: { data: [], page } },
      "GET me/subscriptions": { body: { data: [sub], page } },
      "GET commerce/products": { body: products },
      "POST me/subscriptions/s1/change-plan": problem(422, "recurring_amount_exceeds_mandate_limit", "Recurring amount exceeds mandate limit", { max_paise: 1500000 }),
    });
    restore = api.restore;
    renderWithProviders(<Billing />);
    await userEvent.click(screen.getByRole("tab", { name: "Subscriptions" }));
    await userEvent.click(await screen.findByRole("button", { name: /Change plan for/ }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.selectOptions(await within(dialog).findByLabelText(/New plan/), "pp");
    await userEvent.click(within(dialog).getByRole("button", { name: "Preview change" }));
    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent("This change would exceed the auto-debit limit");
    expect(alert).toHaveTextContent("can't be more than ₹15,000");
    expect(within(dialog).queryByRole("button", { name: /Confirm/ })).not.toBeInTheDocument();
  });

  it("previews a downgrade for the next renewal and shows the scheduled change", async () => {
    let scheduled = false;
    const downgrade = { ...upgrade, direction: "downgrade", effective: "renewal", effective_at: "2026-12-01T18:30:00Z", to_price_id: "pl", to_amount_paise: 19900, proration_paise: 0, next_debit_paise: 19900 };
    const api = mockApi({
      "GET me/orders": { body: { data: [], page } },
      "GET me/subscriptions": () => ({ body: { data: [scheduled ? { ...sub, scheduled_price_id: "pl", scheduled_change_at: "2026-12-01T18:30:00Z" } : sub], page } }),
      "GET commerce/products": { body: products },
      "POST me/subscriptions/s1/change-plan": (c) => {
        const preview = (c.body as { preview: boolean }).preview;
        if (!preview) scheduled = true;
        return { body: { ...downgrade, preview } };
      },
    });
    restore = api.restore;
    renderWithProviders(<Billing />);
    await userEvent.click(screen.getByRole("tab", { name: "Subscriptions" }));
    await userEvent.click(await screen.findByRole("button", { name: /Change plan for/ }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.selectOptions(await within(dialog).findByLabelText(/New plan/), "pl");
    await userEvent.click(within(dialog).getByRole("button", { name: "Preview change" }));
    const preview = await within(dialog).findByRole("region", { name: "Change preview" });
    expect(preview).toHaveTextContent("Downgrade to Lite Monthly: takes effect on 2 Dec 2026");
    expect(preview).toHaveTextContent("No refund is due for the current period");
    expect(preview).not.toHaveTextContent("Prorated difference");
    await userEvent.click(within(dialog).getByRole("button", { name: "Confirm downgrade" }));
    expect(await screen.findByText("Your plan changes on 2 Dec 2026.")).toBeInTheDocument();
    expect(await screen.findByText("Changes to Lite Monthly on 2 Dec 2026")).toBeInTheDocument();
  });

  it("reports an invalid state transition", async () => {
    const api = mockApi({
      "GET me/orders": { body: { data: [], page } },
      "GET me/subscriptions": { body: { data: [sub], page } },
      "GET commerce/products": { body: products },
      "POST me/subscriptions/s1/change-plan": problem(409, "invalid_state_transition", "Invalid state transition", { detail: "A plan change is already scheduled." }),
    });
    restore = api.restore;
    renderWithProviders(<Billing />);
    await userEvent.click(screen.getByRole("tab", { name: "Subscriptions" }));
    await userEvent.click(await screen.findByRole("button", { name: /Change plan for/ }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.selectOptions(await within(dialog).findByLabelText(/New plan/), "pp");
    await userEvent.click(within(dialog).getByRole("button", { name: "Preview change" }));
    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent("This subscription can't change plan right now");
    expect(alert).toHaveTextContent("A plan change is already scheduled.");
  });
});

describe("AccessList (STU-019)", () => {
  it("lists entitlements with source, dates, grace and quotas", async () => {
    const api = mockApi({
      "GET me/entitlements": {
        body: {
          data: [
            {
              entitlement_id: "e1",
              title: "TCS NQT Placement Package",
              source_type: "placement_package",
              source_ref: "0192f0aa-0000-7000-8000-000000000001",
              status: "active",
              effective_status: "active",
              ends_at: "2027-05-02T10:17:40.000Z",
              quotas: { mentor_sessions_remaining: 2, mocks_remaining: null, resume_reviews_remaining: null },
            },
            {
              entitlement_id: "e3",
              title: "All-access monthly",
              source_type: "subscription",
              status: "active",
              effective_status: "grace",
              ends_at: "2026-11-01T18:29:59.000Z",
              grace_ends_at: "2026-11-06T18:29:59.000Z",
              quotas: { mentor_sessions_remaining: null, mocks_remaining: null, resume_reviews_remaining: null },
            },
          ],
          restriction_gate: { active: false },
          page: { next_cursor: null, has_more: false },
        },
      },
    });
    restore = api.restore;
    renderWithProviders(<AccessList />);
    expect(await screen.findByText("TCS NQT Placement Package")).toBeInTheDocument();
    expect(screen.getByText("Mentor sessions: 2 left")).toBeInTheDocument();
    expect(screen.getByText("Payment due")).toBeInTheDocument();
    expect(screen.getByText(/Update your payment method by 6 Nov 2026/)).toBeInTheDocument();
  });

  it("never shows a raw access key as the title", () => {
    expect(accessTitle("all_practice", "subscription")).toBe("All practice questions");
    expect(accessTitle("mock_tests_pack", "purchase")).toBe("Mock tests pack");
    expect(accessTitle("TCS NQT Placement Package", "placement_package")).toBe("TCS NQT Placement Package");
    expect(accessTitle(null, "free_enrolment")).toBe("Free enrolment");
  });
});

describe("Checkout summary first (UI audit: checkout)", () => {
  it("names the product and price before a state is chosen, and the summary comes before the form", async () => {
    restore = mockApi({ "GET commerce/products": { body: products } }).restore;
    renderWithProviders(<Checkout priceId="one" returnTo="/pricing" />);
    const summary = screen.getByRole("complementary", { name: "Order summary" });
    expect(await within(summary).findByText("Placement Package")).toBeInTheDocument();
    expect(within(summary).getByText("₹3,499")).toBeInTheDocument();
    expect(within(summary).getByText(/Choose your state to see/)).toBeInTheDocument();
    const form = screen.getByRole("form", { name: "Billing details" });
    // Reading order: summary, then the billing form (phones see what they're buying first).
    expect(summary.compareDocumentPosition(form) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("link", { name: /Back/ })).toHaveAttribute("href", "/pricing");
  });

  it("finds the plan behind a price id and describes its cadence", () => {
    const item = checkoutItem(products.data as never, "pm");
    expect(item?.productName).toBe("All-access Monthly");
    expect(cadenceLabel(item!.plan)).toBe("per month");
    expect(checkoutItem(products.data as never, "missing")).toBeNull();
  });

  it("gives the no-plan state a page heading and a real button", () => {
    renderWithProviders(<Checkout priceId={null} />);
    expect(screen.getByRole("heading", { level: 1, name: "Checkout" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See plans" })).toHaveAttribute("href", PLANS_HREF);
  });
});

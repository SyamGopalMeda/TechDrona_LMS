// Regressions: FE-26 (resume a pending order), FE-27 (URL becomes the order), FE-28 (never-paid
// copy), INV-15 (recurring plans start a subscription, not a one-time order).
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { Checkout } from "./Checkout";
import { OrderStatus } from "./OrderStatus";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

let restore: (() => void) | undefined;
afterEach(() => {
  restore?.();
  push.mockReset();
  vi.restoreAllMocks();
});

const quote = {
  price_id: "p1",
  product: { sku: "S", name: "Plan", product_kind: "subscription_plan" },
  list_amount_paise: 49900,
  discount_paise: 0,
  taxable_paise: 42288,
  cgst_paise: 3806,
  sgst_paise: 3806,
  igst_paise: 0,
  total_paise: 49900,
  coupon: null,
  warnings: [],
  blocking: [],
  refund_rule: "rule",
  access_ends_at: null,
};
const checkout = { key_id: "rzp_test_FAKE", gateway_order_id: "order_fake_1", amount: 49900, currency: "INR", test_payment: null };
const order = { order_id: "o-9", order_number: "TD-O-1", status: "pending_payment", total_paise: 49900, currency: "INR", expires_at: "2026-11-03T10:45:02.000Z", gateway: "razorpay", checkout };

async function fillAndSubmit() {
  await userEvent.type(screen.getByLabelText(/Name on invoice/), "Ananya");
  await userEvent.selectOptions(screen.getByLabelText(/^State/), "29");
  await screen.findByText("CGST (9%)");
  await userEvent.click(screen.getByRole("button", { name: "Continue to payment" }));
}

describe("Checkout URL (FE-27)", () => {
  it("replaces /app/checkout/new with the order id so a reload resumes instead of re-ordering", async () => {
    const replace = vi.spyOn(window.history, "replaceState");
    const api = mockApi({ "POST commerce/checkout/quote": { body: quote }, "POST commerce/orders": { status: 201, body: order } });
    restore = api.restore;
    renderWithProviders(<Checkout priceId="p1" />);
    await fillAndSubmit();
    expect(await screen.findByRole("button", { name: "Pay ₹499" })).toBeInTheDocument();
    expect(replace).toHaveBeenCalledWith(window.history.state, "", "/app/checkout/o-9");
    expect(api.calls.filter((c) => c.path === "commerce/orders")).toHaveLength(1);
  });
});

const subCreated = {
  status: 201,
  body: { subscription_id: "s1", plan_id: "pl", price_id: "p1", status: "created", mandate_max_amount_paise: 49900, checkout: { key_id: "rzp_test_FAKE", subscription_id: "sub_fake" } },
};

describe("Recurring plans (INV-15)", () => {
  it("routes a recurring price (quote answers not_one_time) to COM-09 without posting an order", async () => {
    const api = mockApi({
      "POST commerce/checkout/quote": problem(422, "validation_failed", "Invalid", { errors: [{ field: "price_id", code: "not_one_time", message: "Use subscriptions for recurring plans" }] }),
      "POST commerce/subscriptions": subCreated,
    });
    restore = api.restore;
    renderWithProviders(<Checkout priceId="p1" />);
    await userEvent.type(screen.getByLabelText(/Name on invoice/), "Ananya");
    await userEvent.selectOptions(screen.getByLabelText(/^State/), "29");
    expect(await screen.findByText(/renews automatically\. The amount per renewal/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Continue to autopay set-up" }));
    expect(await screen.findByText(/not available with the test gateway/)).toBeInTheDocument();
    const sub = api.calls.find((c) => c.path === "commerce/subscriptions")!;
    expect(sub.body).toEqual({ price_id: "p1", billing: { name: "Ananya", state_code: "29", gstin: null } });
    expect(sub.headers["idempotency-key"]).toBeTruthy();
    expect(api.calls.some((c) => c.path === "commerce/orders")).toBe(false);
  });

  it("also switches when the order endpoint answers recurring_price", async () => {
    const api = mockApi({
      "POST commerce/checkout/quote": { body: quote },
      "POST commerce/orders": problem(422, "validation_failed", "Invalid", { errors: [{ field: "price_id", code: "recurring_price", message: "renews" }] }),
      "POST commerce/subscriptions": subCreated,
    });
    restore = api.restore;
    renderWithProviders(<Checkout priceId="p1" />);
    await fillAndSubmit();
    expect(await screen.findByText(/not available with the test gateway/)).toBeInTheDocument();
    expect(api.calls.filter((c) => c.path === "commerce/subscriptions")).toHaveLength(1);
  });
});

describe("Missing purchase consent (E2E-04)", () => {
  it("offers an inline toggle that grants the named consent and retries the order", async () => {
    let orders = 0;
    const api = mockApi({
      "POST commerce/checkout/quote": { body: quote },
      "POST commerce/orders": () =>
        ++orders === 1
          ? problem(403, "consent_required", "Turn on account protection to buy a paid plan", {
              detail: "Paid plans need 'Account protection and single-user licence checks'. Turn it on to continue to payment.",
              purposes: ["security_monitoring"],
              grant: { method: "POST", path: "/me/consents", body: { purpose: "security_monitoring", action: "granted" }, also_required: ["notice_version"] },
            })
          : { status: 201, body: order },
      "POST me/consents": { body: { purpose: "security_monitoring", state: "granted" } },
    });
    restore = api.restore;
    renderWithProviders(<Checkout priceId="p1" />);
    await fillAndSubmit();
    expect(await screen.findByText("Turn on account protection to buy a paid plan")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Review consents" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Turn on and continue" }));
    expect(await screen.findByRole("button", { name: "Pay ₹499" })).toBeInTheDocument();
    const consent = api.calls.find((c) => c.path === "me/consents")!;
    expect(consent.body).toMatchObject({ purpose: "security_monitoring", action: "granted" });
    expect((consent.body as { notice_version?: string }).notice_version).toBeTruthy();
    expect(orders).toBe(2);
  });
});

describe("Resumed order (FE-27 backend)", () => {
  it("treats resumed: true as success and says the earlier order was picked up", async () => {
    const api = mockApi({ "POST commerce/checkout/quote": { body: quote }, "POST commerce/orders": { status: 201, body: { ...order, resumed: true } } });
    restore = api.restore;
    renderWithProviders(<Checkout priceId="p1" />);
    await fillAndSubmit();
    expect(await screen.findByText(/picked it up instead of creating a new one/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pay ₹499" })).toBeInTheDocument();
  });
});

describe("Resume and never-paid orders (FE-26, FE-28)", () => {
  it("offers payment on /app/checkout/{id} when COM-05 returns checkout", async () => {
    const api = mockApi({ "GET commerce/orders/o-9": { body: order } });
    restore = api.restore;
    renderWithProviders(<OrderStatus orderId="o-9" mode="resume" />);
    expect(await screen.findByRole("button", { name: "Pay ₹499" })).toBeInTheDocument();
    expect(screen.queryByText(/not available yet/)).not.toBeInTheDocument();
  });

  it("says 'Awaiting payment' (not 'Confirming') for a never-paid order and links to resume", async () => {
    const api = mockApi({ "GET commerce/orders/o-9": { body: { ...order, message: null } } });
    restore = api.restore;
    renderWithProviders(<OrderStatus orderId="o-9" />);
    expect(await screen.findByText(/Awaiting payment\. If you’ve just paid/)).toBeInTheDocument();
    expect(screen.queryByText(/Confirming your payment/)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Complete payment" })).toHaveAttribute("href", "/app/checkout/o-9");
  });

  it("does not offer a second payment when the bank is confirming one", async () => {
    const api = mockApi({ "GET commerce/orders/o-9": { body: { ...order, checkout: null, message: "Payment received by bank, confirming…" } } });
    restore = api.restore;
    renderWithProviders(<OrderStatus orderId="o-9" mode="resume" />);
    expect(await screen.findByText(/You don’t need to pay again/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Pay/ })).not.toBeInTheDocument();
  });
});

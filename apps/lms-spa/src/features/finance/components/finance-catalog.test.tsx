import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { Coupons, couponNeedsDual, Products, Subscriptions, validateItems } from "./FinanceCatalog";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));
// Long multi-dialog user-event flows: keep them stable on a loaded machine.
vi.setConfig({ testTimeout: 20_000 });

const cleanups: (() => void)[] = [];
afterEach(() => {
  while (cleanups.length) cleanups.pop()!();
});
const page = { next_cursor: null, has_more: false, limit: 200 };
const inHours = (h: number) => new Date(Date.now() + h * 3_600_000).toISOString();

const PRODUCT_ID = "0193a000-0000-7000-8000-000000000001";
const product = {
  product_id: PRODUCT_ID,
  sku: "DSA-PRO",
  name: "DSA Pro",
  product_kind: "course",
  description_md: null,
  sac_code: "9992",
  gst_rate: "18.00",
  refund_policy_key: "standard_7d_20pct",
  status: "active",
  unlocks: [{ item_type: "course", ref_id: "c1", feature_key: null, quantity: null }],
  plans: [
    {
      plan_id: "pl1",
      code: "dsa-1y",
      billing_type: "one_time",
      interval_unit: null,
      interval_count: null,
      access_duration_days: 365,
      status: "active",
      prices: [{ price_id: "pr1", amount_paise: 499900, valid_from: "2026-01-01T00:00:00+00:00", valid_until: null, is_active: true }],
    },
  ],
};

describe("Products and prices (FIN-002, ADM-28/INV-04)", () => {
  it("lists products with plans and current GST-inclusive prices", async () => {
    const api = mockApi({ "GET finance/products": { body: { data: [product], page } } });
    cleanups.push(api.restore);
    renderWithProviders(<Products />);
    expect(screen.queryByText(/not yet implemented/i)).not.toBeInTheDocument();
    expect(await screen.findByText("DSA Pro")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Manage DSA-PRO" }));
    const plans = screen.getByRole("table", { name: "Plans of DSA-PRO" });
    expect(within(plans).getByText("365 days access")).toBeInTheDocument();
    expect(within(plans).getAllByText(/₹4,999.00/).length).toBeGreaterThan(0);
  });

  it("a price cut over 20 % goes to a second finance admin (202 approval_pending)", async () => {
    const api = mockApi({
      "GET finance/products": { body: { data: [product], page } },
      "POST finance/plans/pl1/prices": { status: 202, body: { status: "approval_pending", approval_request_id: "ap-price", action_type: "commerce.price.create", required_approver_role: "finance_admin", expires_at: inHours(72) } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<Products />);
    await userEvent.click(await screen.findByRole("button", { name: "Manage DSA-PRO" }));
    await userEvent.click(screen.getByRole("button", { name: "Add price to dsa-1y" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/^Price/), "2999");
    expect(within(dialog).getByText(/more than 20 %/)).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText(/^Reason/), "Diwali sale");
    await userEvent.click(within(dialog).getByRole("button", { name: "Submit for approval" }));
    expect(await within(dialog).findByText("Waiting for a second approver")).toBeInTheDocument();
    expect(within(dialog).getByText(/Another finance admin must approve/)).toBeInTheDocument();
    const post = api.calls.find((c) => c.method === "POST")!;
    expect(post.body).toEqual({ amount_paise: 299900, valid_from: null, valid_until: null, reason: "Diwali sale" });
    expect(post.headers["idempotency-key"]).toBeTruthy();
  });

  it("creates a product with what it unlocks, adds a plan and edits the product", async () => {
    const api = mockApi({
      "GET finance/products": { body: { data: [product], page } },
      "POST finance/products": { status: 201, body: { ...product, product_id: "p2" } },
      ["POST finance/products/" + PRODUCT_ID + "/plans"]: { status: 201, body: product.plans[0] },
      ["PATCH finance/products/" + PRODUCT_ID]: { body: { ...product, status: "retired" } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<Products />);
    await userEvent.click(await screen.findByRole("button", { name: "New product" }));
    let dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/^SKU/), "MOCK-PACK");
    await userEvent.type(within(dialog).getByLabelText(/^Name/), "Mock pack");
    await userEvent.selectOptions(within(dialog).getByLabelText(/^Kind/), "mock_pack");
    await userEvent.click(within(dialog).getByRole("button", { name: "Add unlock" }));
    await userEvent.selectOptions(within(dialog).getByLabelText("Unlock 1 type"), "feature");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create product" }));
    expect(within(dialog).getByText(/enter a feature key/)).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText("Unlock 1 feature key"), "mock_interview");
    await userEvent.type(within(dialog).getByLabelText("Unlock 1 quantity"), "5");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create product" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.path === "finance/products")).toBe(true));
    expect(api.calls.find((c) => c.path === "finance/products" && c.method === "POST")!.body).toEqual({
      sku: "MOCK-PACK",
      name: "Mock pack",
      product_kind: "mock_pack",
      description_md: null,
      sac_code: "9992",
      gst_rate: "18",
      refund_policy_key: "standard_7d_20pct",
      status: "draft",
      items: [{ item_type: "feature", ref_id: null, feature_key: "mock_interview", quantity: 5 }],
    });

    await userEvent.click(await screen.findByRole("button", { name: "Manage DSA-PRO" }));
    await userEvent.click(screen.getByRole("button", { name: "Add plan" }));
    dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/^Plan code/), "dsa-monthly");
    await userEvent.selectOptions(within(dialog).getByLabelText(/^Billing/), "recurring");
    await userEvent.click(within(dialog).getByRole("button", { name: "Add plan" }));
    await waitFor(() => expect(api.calls.some((c) => c.path.endsWith("/plans"))).toBe(true));
    expect(api.calls.find((c) => c.path.endsWith("/plans"))!.body).toEqual({ code: "dsa-monthly", billing_type: "recurring", access_duration_days: null, interval_unit: "month", interval_count: 1 });

    await userEvent.click(await screen.findByRole("button", { name: "Edit product" }));
    dialog = await screen.findByRole("dialog");
    await userEvent.selectOptions(within(dialog).getByLabelText(/^Status/), "retired");
    // Retiring needs an explicit confirmation (audit 0.7).
    await userEvent.click(within(dialog).getByRole("button", { name: "Retire product" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent(/Confirm that you want to retire/);
    expect(api.calls.some((c) => c.method === "PATCH")).toBe(false);
    await userEvent.click(within(dialog).getByLabelText(/I understand/));
    await userEvent.click(within(dialog).getByRole("button", { name: "Retire product" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(api.calls.find((c) => c.method === "PATCH")!.body).toEqual({ name: "DSA Pro", description_md: null, status: "retired" });
  });

  it("validates unlock rows like ProductItemIn", () => {
    expect(validateItems([{ item_type: "course", ref: "abc", quantity: "" }])).toMatch(/full course id/);
    expect(validateItems([{ item_type: "course", ref: PRODUCT_ID, quantity: "0" }])).toMatch(/quantity/);
    expect(validateItems([{ item_type: "feature", ref: "resume_review", quantity: "" }])).toBeNull();
  });
});

const coupon = { coupon_id: "cp1", code: "WELCOME10", discount_type: "percent", percent_off: 10, amount_off_paise: null, applicable_product_ids: [], min_order_paise: null, max_redemptions: 500, per_user_limit: 1, redeemed_count: 12, valid_from: "2026-10-01T00:00:00+05:30", valid_until: null, first_time_only: true, status: "active" };

describe("Coupons (FIN-003, ADM-28)", () => {
  it("a big coupon is created paused (202) and shown as waiting for the second finance admin", async () => {
    let rows: unknown[] = [coupon];
    const paused = { ...coupon, coupon_id: "cp2", code: "DIWALI60", percent_off: 60, max_redemptions: 100, first_time_only: false, redeemed_count: 0, status: "paused" };
    const api = mockApi({
      "GET finance/coupons": () => ({ body: { data: rows, page } }),
      "GET finance/products": { body: { data: [product], page } },
      "POST finance/coupons": () => {
        rows = [paused, coupon];
        return { status: 202, body: { ...paused, approval_request_id: "ap-cp2", approval_status: "approval_pending", action_type: "commerce.coupon.activate", required_approver_role: "finance_admin", expires_at: inHours(72) } };
      },
    });
    cleanups.push(api.restore);
    renderWithProviders(<Coupons />);
    expect(await screen.findByText("WELCOME10")).toBeInTheDocument();
    expect(screen.getByText("12 / 500")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "New coupon" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/^Code/), "DIWALI60");
    await userEvent.type(within(dialog).getByLabelText(/^Percent off/), "60");
    await userEvent.type(within(dialog).getByLabelText(/^Max redemptions/), "100");
    await userEvent.type(within(dialog).getByLabelText(/^Valid from/), "2026-11-01");
    await userEvent.click(await within(dialog).findByRole("checkbox", { name: "DSA Pro (DSA-PRO)" }));
    await userEvent.type(within(dialog).getByLabelText(/^Reason/), "Festive campaign");
    expect(within(dialog).getByText(/created paused/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Create and request approval" }));
    // Before the fix the 202 `status: "paused"` body was treated as a plain success.
    expect(await within(dialog).findByText("Waiting for a second approver")).toBeInTheDocument();
    expect(within(dialog).getByText(/ap-cp2/)).toBeInTheDocument();
    // w2a R4: the 202 envelope's approver role and expiry are shown, not a generic 72 h note.
    expect(within(dialog).getByText(/Another finance admin must approve this/)).toBeInTheDocument();
    expect(within(dialog).queryByText(/Requests expire after 72 h/)).not.toBeInTheDocument();
    const post = api.calls.find((c) => c.method === "POST")!;
    expect(post.body).toMatchObject({ code: "DIWALI60", discount_type: "percent", percent_off: 60, amount_off_paise: null, max_redemptions: 100, applicable_product_ids: [PRODUCT_ID], valid_from: "2026-11-01T00:00:00+05:30", reason: "Festive campaign" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(await screen.findByText("DIWALI60")).toBeInTheDocument();
    expect(screen.getByText("⇄ Awaiting second approver")).toBeInTheDocument();
  });

  it("shows second_approval_required when a PATCH would loosen a big coupon", async () => {
    const api = mockApi({
      "GET finance/coupons": { body: { data: [{ ...coupon, status: "paused", percent_off: 60 }], page } },
      "PATCH finance/coupons/cp1": problem(409, "second_approval_required", "Second approval required", { detail: "Re-create the coupon to route it through approval." }),
    });
    cleanups.push(api.restore);
    renderWithProviders(<Coupons />);
    await userEvent.click(await screen.findByRole("button", { name: "Edit coupon WELCOME10" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.selectOptions(within(dialog).getByLabelText(/^Status/), "active");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await within(dialog).findByText("Re-create the coupon to route it through approval.")).toBeInTheDocument();
    expect(api.calls.find((c) => c.method === "PATCH")!.body).toEqual({ status: "active" });
  });

  it("filters coupons by status on the server and marks a coupon with a pending approval (webstaff R6)", async () => {
    const api = mockApi({
      "GET finance/coupons": (c) => ({ body: { data: c.url.includes("status=paused") ? [{ ...coupon, coupon_id: "cp3", code: "BIG70", status: "paused", approval_request_id: "ap9" }] : [coupon], page } }),
    });
    cleanups.push(api.restore);
    renderWithProviders(<Coupons />);
    expect(await screen.findByText("WELCOME10")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Status"), "paused");
    expect(await screen.findByText("BIG70")).toBeInTheDocument();
    expect(screen.getByText(/Awaiting second approver/)).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "GET" && c.url.includes("finance/coupons") && c.url.includes("status=paused"))).toBe(true);
  });

  it("mirrors coupon_needs_dual (unlimited counts as big)", () => {
    expect(couponNeedsDual("percent", 10, 500)).toBe(false);
    expect(couponNeedsDual("percent", 10, null)).toBe(true);
    expect(couponNeedsDual("percent", 51, 10)).toBe(true);
    expect(couponNeedsDual("flat", null, 1001)).toBe(true);
    expect(couponNeedsDual("free_access", null, 1)).toBe(true);
  });
});

describe("Subscriptions (FIN-006, ADM-28)", () => {
  const sub = { subscription_id: "s1", user_id: "u1", plan_id: "pl2", price_id: "pr2", status: "active", gateway_subscription_id: "sub_RZP1", mandate_max_amount_paise: 99900, current_period_start: "2026-10-01T00:00:00Z", current_period_end: "2026-11-01T00:00:00Z", next_charge_at: "2026-11-01T00:00:00Z", cancel_at_period_end: false, grace_until: null, paid_count: 3 };

  it("filters by status and cancels with a reason and an Idempotency-Key", async () => {
    const api = mockApi({
      "GET finance/subscriptions": { body: { data: [sub, { ...sub, subscription_id: "s2", gateway_subscription_id: "sub_RZP2", status: "cancelled" }], page } },
      "POST finance/subscriptions/s1/cancel": { body: { ...sub, cancel_at_period_end: true } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<Subscriptions />);
    expect(await screen.findByText("sub_RZP1")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel subscription sub_RZP2" })).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText(/^Status/), "active");
    await waitFor(() => expect(api.calls.some((c) => c.url.includes("status=active"))).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: "Cancel subscription sub_RZP1" }));
    const dialog = await screen.findByRole("dialog");
    // The dismiss button must not also read "Cancel" (audit 0.7).
    expect(within(dialog).getByRole("button", { name: "Keep subscription" })).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel subscription" }));
    expect(within(dialog).getByText(/Give a reason/)).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText(/^Reason/), "Duplicate mandate");
    await userEvent.type(within(dialog).getByLabelText(/^Support ticket/), "TD-T-42");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel subscription" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    const post = api.calls.find((c) => c.method === "POST")!;
    expect(post.body).toEqual({ reason: "Duplicate mandate", ticket_ref: "TD-T-42", immediate: false });
    expect(post.headers["idempotency-key"]).toBeTruthy();
  });
});

describe("Finance catalogue copy (Phase 2)", () => {
  it("says Unlimited instead of ∞ and offers no Edit on an expired coupon", async () => {
    const api = mockApi({ "GET finance/coupons": { body: { data: [{ ...coupon, max_redemptions: null }, { ...coupon, coupon_id: "cp9", code: "OLD5", status: "expired" }], page } } });
    cleanups.push(api.restore);
    renderWithProviders(<Coupons />);
    expect(await screen.findByText("12 / Unlimited")).toBeInTheDocument();
    expect(screen.queryByText(/∞/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit coupon WELCOME10" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit coupon OLD5" })).not.toBeInTheDocument();
  });

  it("shows the subscriber as a short reference and the cap as Max per debit", async () => {
    const api = mockApi({ "GET finance/subscriptions": { body: { data: [{ subscription_id: "s1", user_id: "0b1c2d3e-4f50-6172-8394-a5b6c7d8e9f0", plan_id: "pl", price_id: "pr", status: "active", gateway_subscription_id: null, mandate_max_amount_paise: 99900, current_period_start: null, current_period_end: null, next_charge_at: null, cancel_at_period_end: false, grace_until: null, paid_count: 0 }], page } } });
    cleanups.push(api.restore);
    renderWithProviders(<Subscriptions />);
    expect(await screen.findByText("User #C7D8E9F0")).toBeInTheDocument();
    expect(screen.getByText("Max per debit")).toBeInTheDocument();
    expect(screen.queryByText("Mandate cap")).not.toBeInTheDocument();
  });
});

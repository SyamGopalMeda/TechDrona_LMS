import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, problem, renderWithProviders } from "@/features/auth/test/mock-api";
import { downloadSink } from "@/features/commerce/lib/download";
import { FinanceHome, Invoices, MismatchList, Orders, Reconciliation, Refunds, RevenueSummary, istToday, orderRef, reconciliationRange } from "./Finance";
import { inclusiveDays } from "./FinanceDocuments";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

const cleanups: (() => void)[] = [];
afterEach(() => {
  while (cleanups.length) cleanups.pop()!();
});
const page = { next_cursor: null, has_more: false, limit: 50 };

const refunds = {
  data: [
    { refund_id: "rf1", order_id: "TD-O-1", status: "requested", amount_paise: 262425, reason_code: "changed_mind", approval_request_id: null, created_at: "2026-10-01T10:00:00Z", eligibility: { eligible: true, reasons: [], days_since_purchase: 2, consumption_pct: 6.5, certificate_issued: false, refundable_paise: 262425 } },
    { refund_id: "rf2", order_id: "TD-O-2", status: "requested", amount_paise: 499900, reason_code: "other", approval_request_id: null, created_at: "2026-09-01T10:00:00Z", eligibility: { eligible: false, days_since_purchase: 20, reasons: ["window_passed"], refundable_paise: 499900 } },
  ],
  page,
};

describe("Refunds (FIN-005)", () => {
  it("approves an eligible refund in INR with an Idempotency-Key", async () => {
    const api = mockApi({ "GET finance/refunds": { body: refunds }, "POST finance/refunds/rf1/decision": { body: { status: "processing" } } });
    cleanups.push(api.restore);
    renderWithProviders(<Refunds />);
    expect(await screen.findByText("₹2,624.25", { selector: "td" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Review refund for order #TDO1" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/^Note/), "Within 7 days");
    await userEvent.click(within(dialog).getByRole("button", { name: "Approve refund" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    const post = api.calls.find((c) => c.method === "POST")!;
    expect(post.body).toMatchObject({ decision: "approve", amount_paise: 262425, goodwill: false });
    expect(post.headers["idempotency-key"]).toBeTruthy();
  });

  it("outside the rule is goodwill only and goes to a second finance admin", async () => {
    const api = mockApi({
      "GET finance/refunds": { body: refunds },
      "POST finance/refunds/rf2/decision": { status: 202, body: { status: "approval_pending", approval_request_id: "ap1", action_type: "refund.goodwill", required_approver_role: "finance_admin", expires_at: new Date(Date.now() + 72 * 3_600_000).toISOString() } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<Refunds />);
    await userEvent.click(await screen.findByRole("button", { name: "Review refund for order #TDO2" }));
    const dialog = await screen.findByRole("dialog");
    const goodwill = within(dialog).getByRole("checkbox", { name: /Goodwill/ });
    expect(goodwill).toBeChecked();
    expect(within(dialog).getByText(/A second admin must approve/)).toBeInTheDocument();
    await userEvent.click(goodwill);
    await userEvent.type(within(dialog).getByLabelText(/^Note/), "Service outage");
    await userEvent.click(within(dialog).getByRole("button", { name: "Approve refund" }));
    expect(within(dialog).getByText(/approve only as goodwill/)).toBeInTheDocument();
    await userEvent.click(goodwill);
    await userEvent.click(within(dialog).getByRole("button", { name: "Submit for approval" }));
    expect(await within(dialog).findByText("Waiting for a second approver")).toBeInTheDocument();
    expect(within(dialog).getByText(/Another finance admin must approve/)).toBeInTheDocument();
  });
});

const signed = (name: string) => ({ url: `https://files.example/${name}?sig=1`, expires_at: "2026-11-03T10:05:00Z", filename: name });
const invoice = { invoice_id: "i1", invoice_number: "TD/2627/000123", invoice_type: "tax_invoice", order_id: "o1", issue_date: "2026-11-03", buyer_name: "Ananya", total_paise: 349900, cgst_paise: 26687, sgst_paise: 26688, igst_paise: 0, status: "issued", pdf_ready: true, description: null, due_on: null };
const ready = { gst_export_id: "g1", period_from: "2026-10-01", period_to: "2026-10-31", status: "ready", row_count: 812, approval_request_id: null, requested_by: "u-fin-1", created_at: "2026-11-01T10:00:00Z", completed_at: "2026-11-01T10:00:05Z", download_expires_at: "2026-11-08T10:00:05Z" };

describe("Invoices (FIN-007)", () => {
  it("downloads an invoice PDF via a signed URL", async () => {
    const open = vi.spyOn(downloadSink, "open").mockImplementation(() => {});
    const api = mockApi({ "GET finance/invoices": { body: { data: [invoice], page } }, "GET finance/gst-exports": { body: { data: [] } }, "GET finance/invoices/i1/pdf": { body: signed("TD-2627-000123.pdf") } });
    cleanups.push(api.restore, () => open.mockRestore());
    renderWithProviders(<Invoices />);
    await userEvent.click(await screen.findByRole("button", { name: "Download PDF for TD/2627/000123" }));
    await waitFor(() => expect(open).toHaveBeenCalledWith(signed("TD-2627-000123.pdf")));
    expect(screen.queryByText(/not available yet/)).not.toBeInTheDocument();
  });

  it("validates the GST export period before requesting", async () => {
    const api = mockApi({ "GET finance/invoices": { body: { data: [], page } }, "GET finance/gst-exports": { body: { data: [] } } });
    cleanups.push(api.restore);
    renderWithProviders(<Invoices />);
    const form = await screen.findByRole("form", { name: "Request GST register export" });
    expect(screen.getByText(/over 10,000 rows wait for a super admin/)).toBeInTheDocument();
    await userEvent.click(within(form).getByRole("button", { name: "Request export" }));
    expect(within(form).getByRole("alert")).toHaveTextContent("Choose the period.");
    await userEvent.type(within(form).getByLabelText(/Period from/), "2025-01-01");
    await userEvent.type(within(form).getByLabelText(/Period to/), "2026-01-02");
    await userEvent.click(within(form).getByRole("button", { name: "Request export" }));
    expect(within(form).getByRole("alert")).toHaveTextContent("at most 366 days");
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
    expect(inclusiveDays("2024-01-01", "2024-12-31")).toBe(366);
  });

  it("requests a GST export that needs approval, then downloads a ready one", async () => {
    const open = vi.spyOn(downloadSink, "open").mockImplementation(() => {});
    const pending = { ...ready, gst_export_id: "g2", period_from: "2026-04-01", period_to: "2026-09-30", status: "awaiting_approval", row_count: 14250, approval_request_id: "ap1", completed_at: null, download_expires_at: null };
    let rows: unknown[] = [ready];
    const api = mockApi({
      "GET finance/invoices": { body: { data: [], page } },
      "GET finance/gst-exports": () => ({ body: { data: rows } }),
      "POST finance/gst-exports": () => {
        rows = [pending, ready];
        return { status: 202, body: pending };
      },
      "GET finance/gst-exports/g1/download": { body: signed("gst-register-2026-10.csv") },
    });
    cleanups.push(api.restore, () => open.mockRestore());
    renderWithProviders(<Invoices />);
    const form = await screen.findByRole("form", { name: "Request GST register export" });
    await userEvent.type(within(form).getByLabelText(/Period from/), "2026-04-01");
    await userEvent.type(within(form).getByLabelText(/Period to/), "2026-09-30");
    await userEvent.type(within(form).getByLabelText(/Reason/), "Half-yearly GSTR-1 check");
    await userEvent.click(within(form).getByRole("button", { name: "Request export" }));
    expect(await screen.findByText(/needs a super admin's approval/)).toBeInTheDocument();
    const post = api.calls.find((c) => c.method === "POST")!;
    expect(post.body).toEqual({ period_from: "2026-04-01", period_to: "2026-09-30", reason: "Half-yearly GSTR-1 check" });
    expect(post.headers["idempotency-key"]).toBeTruthy();
    expect(await screen.findByText("Awaiting approval")).toBeInTheDocument();
    expect(screen.getByText("14,250")).toBeInTheDocument();
    expect(screen.getByText("Ready")).toBeInTheDocument();
    // Only ready exports offer a download.
    expect(screen.getAllByRole("button", { name: /Download GST register/ })).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: "Download GST register 1 Oct 2026 to 31 Oct 2026" }));
    await waitFor(() => expect(open).toHaveBeenCalledWith(signed("gst-register-2026-10.csv")));

    const gets = () => api.calls.filter((c) => c.path === "finance/gst-exports" && c.method === "GET").length;
    const before = gets();
    await userEvent.click(screen.getByRole("button", { name: "Refresh GST exports" }));
    await waitFor(() => expect(gets()).toBe(before + 1));
  });
});

describe("Revenue dashboard (FIN-001, ADM-31)", () => {
  it("renders gross, GST, refunds and net from finance/reports/revenue", async () => {
    const api = mockApi({ "GET finance/reports/revenue": { body: { range_from: "2026-10-04T00:00:00+00:00", range_to: "2026-11-03T00:00:00+00:00", orders_paid: 42, gross_paise: 18423000, gst_paise: 2810288, discount_pre_tax_paise: 0, refunds_processed: 2, refunded_paise: 499900, net_paise: 17923100, by_product_kind: [{ product_kind: "course", items: 40, total_paise: 18000000 }], non_purchase_grants: {}, currency: "INR" } } });
    cleanups.push(api.restore);
    renderWithProviders(<RevenueSummary />);
    expect(await screen.findByText("₹1,84,230.00")).toBeInTheDocument();
    expect(screen.getByText("₹28,102.88")).toBeInTheDocument();
    expect(screen.getByText("₹4,999.00")).toBeInTheDocument();
    expect(screen.getByText("₹1,79,231.00")).toBeInTheDocument();
    expect(api.calls[0]!.url).toContain("range_from=");
    await userEvent.selectOptions(screen.getByLabelText(/^Period/), "7");
    await waitFor(() => expect(api.calls.filter((c) => c.path === "finance/reports/revenue").length).toBe(2));
  });
});

describe("Refund second approval (FIN-005, ADM-25)", () => {
  it("offers Decide on a refund awaiting the second approver and falls back to the finance approval route", async () => {
    const waiting = { ...refunds.data[1]!, refund_id: "rf3", order_id: "TD-O-3", approval_request_id: "ap9" };
    const api = mockApi({
      "GET finance/refunds": { body: { data: [waiting], page } },
      "POST admin/approvals/ap9/approve": problem(404, "not_found", "Not found"),
      "POST finance/approval-requests/ap9/approve": { body: { approval_request_id: "ap9", status: "executed" } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<Refunds />);
    expect(await screen.findByText("⇄ Awaiting second approver")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Second approval for refund on order #TDO3" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Approve refund" }));
    await waitFor(() => expect(api.calls.some((c) => c.path === "finance/approval-requests/ap9/approve")).toBe(true));
    const fin = api.calls.find((c) => c.path === "finance/approval-requests/ap9/approve")!;
    expect(fin.body).toEqual({});
    expect(fin.headers["idempotency-key"]).toBeTruthy();
  });
});

describe("Order detail (FIN-004, ADM-37)", () => {
  it("shows a structured order instead of raw JSON", async () => {
    const order = { order_id: "o1", order_number: "TD-O-9", status: "paid", total_paise: 349900, subtotal_paise: 296525, discount_paise: 0, tax_paise: 53375, gateway: "razorpay", created_at: "2026-11-01T10:00:00Z", paid_at: "2026-11-01T10:01:00Z", expires_at: "2026-11-01T10:30:00Z" };
    const api = mockApi({
      "GET finance/orders": { body: { data: [order], page } },
      "GET finance/orders/o1": { body: { ...order, items: [{ order_item_id: "oi1", product_id: "p1", price_id: "pr1", unit_amount_paise: 349900, taxable_paise: 296525, cgst_paise: 26687, sgst_paise: 26688, igst_paise: 0, total_paise: 349900, gst_rate: "18.00", sac_code: "9992" }], payments: [{ payment_id: "pay1", gateway_payment_id: "pay_RZP1", status: "captured", method: "card", amount_paise: 349900, card_last4: "4242", vpa_masked: null, error_code: null }], webhook_events: [], entitlements: [], invoices: [invoice] } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<Orders />);
    await userEvent.click(await screen.findByRole("button", { name: "Details for order TD-O-9" }));
    expect(await screen.findByRole("table", { name: "Items" })).toBeInTheDocument();
    expect(screen.getByText("Card ···· 4242")).toBeInTheDocument();
    expect(screen.getByText("TD/2627/000123")).toBeInTheDocument();
    expect(document.querySelector("pre")).toBeNull();
  });
});

describe("Reconciliation (FIN-009, ADM-40)", () => {
  it("says the online gateway is not integrated yet when the API reports the fake adapter", async () => {
    const api = mockApi({ "GET finance/reconciliation": { body: { data: [], gateway: { provider: "fake", integrated: false } } } });
    cleanups.push(api.restore);
    renderWithProviders(<Reconciliation />);
    expect(await screen.findByText("Online payment gateway: not integrated yet")).toBeInTheDocument();
  });

  it("shows no gateway notice when the gateway is integrated", async () => {
    const api = mockApi({ "GET finance/reconciliation": { body: { data: [], gateway: { provider: "razorpay", integrated: true } } } });
    cleanups.push(api.restore);
    renderWithProviders(<Reconciliation />);
    expect(await screen.findByText("No reconciliation runs yet")).toBeInTheDocument();
    expect(screen.queryByText(/not integrated yet/)).not.toBeInTheDocument();
  });

  it("sends the To day inclusively (next day 00:00 IST)", async () => {
    expect(reconciliationRange("2026-10-01", "2026-10-31")).toEqual({ body: { range_from: "2026-10-01T00:00:00+05:30", range_to: "2026-11-01T00:00:00+05:30" } });
    expect(reconciliationRange("2026-10-05", "2026-10-05")).toEqual({ body: { range_from: "2026-10-05T00:00:00+05:30", range_to: "2026-10-06T00:00:00+05:30" } });
    expect(reconciliationRange("2026-10-01", "2026-11-01")).toEqual({ error: "The range can be at most 31 days." });
    const api = mockApi({ "GET finance/reconciliation": { body: { data: [] } }, "POST finance/reconciliation/runs": { status: 201, body: { run_id: "r1" } } });
    cleanups.push(api.restore);
    renderWithProviders(<Reconciliation />);
    await userEvent.click(await screen.findByRole("button", { name: "Run reconciliation" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/^From/), "2026-10-05");
    await userEvent.type(within(dialog).getByLabelText(/^To/), "2026-10-05");
    await userEvent.click(within(dialog).getByRole("button", { name: "Run" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    expect(api.calls.find((c) => c.method === "POST")!.body).toEqual({ range_from: "2026-10-05T00:00:00+05:30", range_to: "2026-10-06T00:00:00+05:30" });
  });
});

describe("Finance paging and server filters (ADM-32)", () => {
  it("filters invoices by type on the server and follows the next cursor", async () => {
    const api = mockApi({
      "GET finance/invoices": (c) => ({ body: c.url.includes("cursor=c2") ? { data: [{ ...invoice, invoice_id: "i2", invoice_number: "TD/2627/000124" }], page: { next_cursor: null, has_more: false, limit: 100 } } : { data: [invoice], page: { next_cursor: "c2", has_more: true, limit: 100 } } }),
      "GET finance/gst-exports": { body: { data: [] } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<Invoices />);
    expect(await screen.findByText("TD/2627/000123")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText(/^Type/), "credit_note");
    await waitFor(() => expect(api.calls.some((c) => c.path === "finance/invoices" && c.url.includes("invoice_type=credit_note"))).toBe(true));
    await userEvent.click(await screen.findByRole("button", { name: /Next/ }));
    expect(await screen.findByText("TD/2627/000124")).toBeInTheDocument();
    expect(api.calls.some((c) => c.url.includes("cursor=c2") && c.url.includes("invoice_type=credit_note"))).toBe(true);
  });
});

describe("Finance-initiated refund (COM-01 price_adjustment)", () => {
  it("issues a price-adjustment refund that keeps access", async () => {
    const order = { order_id: "o1", order_number: "TD-O-9", status: "paid", total_paise: 349900, created_at: "2026-11-01T10:00:00Z", paid_at: "2026-11-01T10:01:00Z" };
    const api = mockApi({
      "GET finance/orders": { body: { data: [order], page } },
      "GET finance/orders/o1": { body: { ...order, items: [], webhook_events: [], entitlements: [], invoices: [] } },
      "POST finance/refunds": { status: 201, body: { refund_id: "rf9", status: "processing" } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<Orders />);
    await userEvent.click(await screen.findByRole("button", { name: "Details for order TD-O-9" }));
    await userEvent.click(await screen.findByRole("button", { name: "Issue refund" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText(/^Reason/)).toHaveValue("price_adjustment");
    expect(within(dialog).getByText("The buyer keeps access: only money is returned.")).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText(/^Amount/), "500");
    await userEvent.type(within(dialog).getByLabelText(/^Note/), "Price dropped after purchase");
    await userEvent.click(within(dialog).getByRole("button", { name: "Issue refund" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST")).toBe(true));
    const post = api.calls.find((c) => c.method === "POST")!;
    expect(post.body).toEqual({ order_id: "o1", reason_code: "price_adjustment", amount_paise: 50000, note: "Price dropped after purchase" });
    expect(post.headers["idempotency-key"]).toBeTruthy();
  });
});

describe("Finance Phase 2 presentation (audit 1.11)", () => {
  it("home: the refund tile links to its queue, warns when work waits and says 50+ for a full page", async () => {
    const api = mockApi({
      "GET finance/refunds": { body: { data: refunds.data, page: { ...page, has_more: true, next_cursor: "c2" } } },
      "GET finance/reconciliation": { body: { data: [{ run_id: "r1", gateway: "razorpay", range_from: "2026-10-01T00:00:00Z", range_to: "2026-10-02T00:00:00Z", status: "completed", mismatches: [{ type: "amount_mismatch" }], created_at: "2026-10-02T00:00:00Z" }] } },
      "GET finance/reports/revenue": { body: { range_from: "2026-10-01T00:00:00Z", range_to: "2026-10-31T00:00:00Z", orders_paid: 0, gross_paise: 0, gst_paise: 0, discount_pre_tax_paise: 0, refunds_processed: 0, refunded_paise: 0, net_paise: 0, by_product_kind: [] } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<FinanceHome />);
    expect(screen.getByRole("heading", { level: 1, name: "Revenue" })).toBeInTheDocument();
    const refundTile = await screen.findByRole("link", { name: /Refunds waiting for a decision/ });
    expect(refundTile).toHaveAttribute("href", "/finance/refunds");
    expect(refundTile).toHaveTextContent("2+");
    expect(screen.getByRole("link", { name: /Mismatches in the last reconciliation/ })).toHaveAttribute("href", "/finance/reconciliation");
    expect(screen.queryByText(/Indian grouping/)).not.toBeInTheDocument();
  });

  it("orders: a readable reference when there is no order number, and details in a dialog with product names", async () => {
    expect(orderRef({ order_id: "0b1c2d3e-4f50-6172-8394-a5b6c7d8e9f0", order_number: "" })).toBe("#C7D8E9F0");
    const order = { order_id: "o1", order_number: "TD-O-9", status: "paid", total_paise: 349900, created_at: "2026-11-01T10:00:00Z" };
    const api = mockApi({
      "GET finance/orders": { body: { data: [order], page } },
      "GET finance/orders/o1": { body: { ...order, items: [{ order_item_id: "oi1", product_id: "p1", price_id: null, unit_amount_paise: 349900, taxable_paise: 296525, cgst_paise: 0, sgst_paise: 0, igst_paise: 53375, total_paise: 349900, gst_rate: "18.00", sac_code: "9992" }], webhook_events: [{ event_type: "payment.captured", status: "processed", is_stale: false, refetch_status: null, received_at: "2026-11-01T10:01:00Z" }], entitlements: [], invoices: [] } },
      "GET finance/products": { body: { data: [{ product_id: "p1", name: "DSA Pro", sku: "DSA-PRO" }], page } },
    });
    cleanups.push(api.restore);
    renderWithProviders(<Orders />);
    await userEvent.click(await screen.findByRole("button", { name: "Details for order TD-O-9" }));
    const dialog = await screen.findByRole("dialog", { name: "Order TD-O-9" });
    expect(await within(dialog).findByText("DSA Pro")).toBeInTheDocument();
    expect(within(dialog).getByText("Payment captured")).toBeInTheDocument();
  });

  it("orders: a partial user id is not sent and says how to fix it", async () => {
    const api = mockApi({ "GET finance/orders": { body: { data: [], page } } });
    cleanups.push(api.restore);
    renderWithProviders(<Orders />);
    await userEvent.type(await screen.findByLabelText(/Buyer's user id/), "abc");
    expect(screen.getByText(/Paste the full user id/)).toBeInTheDocument();
    expect(api.calls.some((c) => c.url.includes("user_id="))).toBe(false);
  });

  it("refunds: order short refs instead of UUIDs and day counts in words", async () => {
    const api = mockApi({ "GET finance/refunds": { body: { data: [{ ...refunds.data[0]!, order_id: "0b1c2d3e-4f50-6172-8394-a5b6c7d8e9f0", eligibility: { ...refunds.data[0]!.eligibility, days_since_purchase: 12 } }], page } } });
    cleanups.push(api.restore);
    renderWithProviders(<Refunds />);
    expect(await screen.findByText("#C7D8E9F0")).toBeInTheDocument();
    expect(screen.queryByText(/0b1c2d3e-4f50/)).not.toBeInTheDocument();
    expect(screen.getByText(/12 days since purchase/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review refund for order #C7D8E9F0" })).toHaveTextContent("Review");
  });

  it("reconciliation: mismatches as a readable table, raw JSON only under a disclosure", () => {
    render(<MismatchList mismatches={[{ type: "amount_mismatch", payment_id: "pay_1", ours: 349900, provider: 300000 }]} />);
    expect(screen.getByText("Amount does not match")).toBeInTheDocument();
    expect(screen.getByText("₹3,499.00")).toBeInTheDocument();
    expect(screen.getByText("Raw data")).toBeInTheDocument();
    expect(screen.getByText("Raw data").closest("details")).not.toHaveAttribute("open");
  });

  it("reconciliation: dates cannot be in the future (IST)", () => {
    expect(istToday(Date.parse("2026-11-10T20:00:00Z"))).toBe("2026-11-11");
  });
});

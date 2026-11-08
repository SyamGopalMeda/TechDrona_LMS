"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge, Button, Card, Checkbox, FormField, Input, PageHeader, Pagination, Select, Skeleton, StatTile, Table, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import { ApprovalsQueue, decideApproval } from "@/features/admin/components/ApprovalsQueue";
import { ActionDialog, FilterBar, InlineProblem, JsonBlock, KeyValueList, StateBadge, TextArea, textLink } from "@/features/admin/components/console-ui";
import type { Schema } from "@/lib/api-types";
import { GstExports, InvoicePdfButton } from "./FinanceDocuments";
import type { InvoiceRow } from "../lib/types";
import { cleanQuery, formatDate, formatDateTime, formatINR, humanize, toOutcome, useCursorList, useVersioned } from "@/features/admin/lib/console";

/** Default above which a refund needs a second finance_admin (commerce.refund.dual_approval_above_paise). */
export const REFUND_DUAL_ABOVE_PAISE = 2_500_000;

/** Commerce Dual approvals (verified: app/modules/commerce/admin.py COMMERCE_ACTIONS). */
const FINANCE_ACTIONS = ["commerce.refund", "commerce.coupon.activate", "commerce.price.create"];

/* -------------------------------------------------------------- Dashboard */

/** verified: app/modules/commerce/admin.py revenue_report (GET finance/reports/revenue; paid_at in [range_from, range_to)). */
interface RevenueReport {
  range_from: string;
  range_to: string;
  orders_paid: number;
  /** Sum of paid order totals (GST-inclusive). */
  gross_paise: number;
  gst_paise: number;
  discount_pre_tax_paise: number;
  refunds_processed: number;
  refunded_paise: number;
  /** gross − processed refunds. */
  net_paise: number;
  by_product_kind: { product_kind: string; items: number; total_paise: number }[];
  non_purchase_grants?: Record<string, number>;
  currency?: string;
}

const REVENUE_PERIODS = [
  { value: "1", label: "Last 24 hours" },
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
];

export const revenueRange = (days: number, now: number = Date.now()) => ({ range_from: new Date(now - days * 86_400_000).toISOString(), range_to: new Date(now).toISOString() });

/** COM-47 revenue tiles: gross, GST, refunds and net for a rolling period. */
export function RevenueSummary() {
  const [days, setDays] = useState("30");
  const [range, setRange] = useState(() => revenueRange(30));
  const report = useVersioned<RevenueReport>("finance/reports/revenue", range);
  const r = report.data;
  return (
    <Card title="Revenue">
      <div className="mb-4 max-w-xs">
        <FormField label="Period">
          {(f) => (
            <Select
              {...f}
              value={days}
              onChange={(e) => {
                setDays(e.target.value);
                setRange(revenueRange(Number(e.target.value)));
              }}
              options={REVENUE_PERIODS}
            />
          )}
        </FormField>
      </div>
      {report.error ? (
        <InlineProblem error={report.error} />
      ) : !r ? (
        <Skeleton className="h-24 w-full" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile label="Gross sales" value={formatINR(r.gross_paise)} hint={`${r.orders_paid} paid orders, incl. GST`} />
            <StatTile label="GST" value={formatINR(r.gst_paise)} />
            <StatTile label="Refunds" value={formatINR(r.refunded_paise)} hint={`${r.refunds_processed} processed`} />
            <StatTile label="Net" value={formatINR(r.net_paise)} hint="Gross − refunds" />
          </div>
          {r.by_product_kind.length ? (
            <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-fg-secondary" aria-label="Sales by product kind">
              {r.by_product_kind.map((k) => (
                <li key={k.product_kind}>
                  {humanize(k.product_kind)}: {formatINR(k.total_paise)} ({k.items})
                </li>
              ))}
            </ul>
          ) : null}
          <p className="mt-2 text-xs text-fg-muted">
            {formatDateTime(r.range_from)} – {formatDateTime(r.range_to)}
          </p>
        </>
      )}
    </Card>
  );
}

/** FIN-001: revenue (COM-47), the work queues and pending approvals. */
export function FinanceHome() {
  const refunds = useCursorList<RefundRow>("finance/refunds", { status: "requested" });
  const recon = useCursorList<ReconRunRow>("finance/reconciliation");
  const latest = recon.rows?.[0];
  return (
    <div>
      <PageHeader eyebrow="FIN-001" title="Finance" description="Revenue, work queues and approvals. Amounts in ₹ with Indian grouping." />
      <div className="mb-6">
        <RevenueSummary />
      </div>
      <div className="mb-6 grid gap-4 md:grid-cols-2">
        <Card title="Refund queue" actions={<Link className={textLink} href="/finance/refunds">Open →</Link>}>
          {refunds.rows ? (
            <p className="text-sm text-fg-secondary">{refunds.rows.length === 0 ? "No refunds waiting." : `${refunds.rows.length} waiting · oldest ${formatDateTime(refunds.rows[0]?.created_at)}`}</p>
          ) : refunds.error ? (
            <InlineProblem error={refunds.error} />
          ) : (
            <p className="text-sm text-fg-muted">Loading…</p>
          )}
        </Card>
        <Card title="Reconciliation" actions={<Link className={textLink} href="/finance/reconciliation">Resolve →</Link>}>
          {recon.rows ? <p className="text-sm text-fg-secondary">{!latest ? "No reconciliation runs yet." : `Last run ${formatDateTime(latest.created_at)} · ${latest.mismatches?.length ?? 0} mismatches`}</p> : recon.error ? <InlineProblem error={recon.error} /> : <p className="text-sm text-fg-muted">Loading…</p>}
        </Card>
      </div>
      <h2 className="mb-2 font-display text-base font-semibold text-fg">Pending approvals I can decide</h2>
      <ApprovalsQueue embedded actionTypes={FINANCE_ACTIONS} />
    </div>
  );
}

/* ----------------------------------------------------------------- Orders */

/** verified: app/modules/commerce/service.py order_json (via router.py fin_orders). */
interface OrderRow {
  order_id: string;
  order_number: string;
  status: string;
  currency?: string;
  subtotal_paise?: number;
  discount_paise?: number;
  tax_paise?: number;
  total_paise?: number;
  gateway?: string | null;
  expires_at?: string;
  created_at?: string | null;
  paid_at?: string | null;
}

/** verified: commerce/router.py fin_order (order_json with items; `payments` only with payment.read; webhook_events; entitlements; invoices). */
interface OrderDetailOut extends OrderRow {
  items?: { order_item_id: string; product_id: string; price_id: string | null; unit_amount_paise: number; taxable_paise: number; cgst_paise: number; sgst_paise: number; igst_paise: number; total_paise: number; gst_rate: string; sac_code: string }[];
  payments?: { payment_id: string; gateway_payment_id: string | null; status: string; method: string | null; amount_paise: number; card_last4: string | null; vpa_masked: string | null; error_code: string | null }[];
  webhook_events?: { event_type: string; status: string; is_stale: boolean; refetch_status: string | null; received_at: string }[];
  entitlements?: { entitlement_id: string; product_id: string | null; course_id: string | null; feature_key: string | null; source_type: string; status: string; starts_at: string | null; ends_at: string | null }[];
  invoices?: InvoiceRow[];
}

type Detail<K extends keyof OrderDetailOut> = NonNullable<OrderDetailOut[K]> extends (infer R)[] ? R : never;

/** Structured order view (ADM-37): totals, GST lines, masked payments, webhooks, entitlements, invoices. */
export function OrderDetail({ order: o }: { order: OrderDetailOut }) {
  const itemCols: Column<Detail<"items">>[] = [
    { key: "product", header: "Product", cell: (i) => <span className="font-mono text-xs">{i.product_id}</span> },
    { key: "sac", header: "SAC · GST", cell: (i) => `${i.sac_code} · ${Number(i.gst_rate)}%` },
    { key: "taxable", header: "Taxable", align: "right", cell: (i) => formatINR(i.taxable_paise) },
    { key: "gst", header: "CGST / SGST / IGST", align: "right", cell: (i) => `${formatINR(i.cgst_paise)} / ${formatINR(i.sgst_paise)} / ${formatINR(i.igst_paise)}` },
    { key: "total", header: "Total", align: "right", cell: (i) => formatINR(i.total_paise) },
  ];
  const payCols: Column<Detail<"payments">>[] = [
    { key: "gw", header: "Gateway payment", cell: (p) => <span className="font-mono text-xs">{p.gateway_payment_id ?? "—"}</span> },
    { key: "status", header: "Status", cell: (p) => <StateBadge state={p.status} /> },
    { key: "method", header: "Method", cell: (p) => `${humanize(p.method)}${p.card_last4 ? ` ···· ${p.card_last4}` : ""}${p.vpa_masked ? ` ${p.vpa_masked}` : ""}` },
    { key: "amount", header: "Amount", align: "right", cell: (p) => formatINR(p.amount_paise) },
    { key: "err", header: "Error", cell: (p) => p.error_code ?? "—" },
  ];
  const hookCols: Column<Detail<"webhook_events">>[] = [
    { key: "at", header: "Received", cell: (e) => formatDateTime(e.received_at) },
    { key: "type", header: "Event", cell: (e) => <span className="font-mono text-xs">{e.event_type}</span> },
    { key: "status", header: "Status", cell: (e) => <StateBadge state={e.status} /> },
    { key: "stale", header: "Stale", cell: (e) => (e.is_stale ? `Yes${e.refetch_status ? ` (refetch ${humanize(e.refetch_status).toLowerCase()})` : ""}` : "No") },
  ];
  const entCols: Column<Detail<"entitlements">>[] = [
    { key: "what", header: "Access", cell: (e) => <span className="font-mono text-xs">{e.feature_key ?? e.course_id ?? e.product_id ?? "—"}</span> },
    { key: "src", header: "Source", cell: (e) => humanize(e.source_type) },
    { key: "status", header: "Status", cell: (e) => <StateBadge state={e.status} /> },
    { key: "window", header: "Window", cell: (e) => `${formatDate(e.starts_at)} – ${e.ends_at ? formatDate(e.ends_at) : "open"}` },
  ];
  const invCols: Column<InvoiceRow>[] = [
    { key: "no", header: "Number", cell: (i) => <span className="font-mono text-xs">{i.invoice_number}</span> },
    { key: "kind", header: "Type", cell: (i) => humanize(i.invoice_type) },
    { key: "total", header: "Total", align: "right", cell: (i) => formatINR(i.total_paise) },
    { key: "pdf", header: <span className="sr-only">PDF</span>, cell: (i) => <InvoicePdfButton invoice={i} /> },
  ];
  return (
    <div className="space-y-5">
      <KeyValueList
        items={[
          { label: "Order", value: <span className="font-mono text-xs">{o.order_number}</span> },
          { label: "Status", value: <StateBadge state={o.status} /> },
          { label: "Subtotal", value: formatINR(o.subtotal_paise) },
          { label: "Discount", value: formatINR(o.discount_paise) },
          { label: "GST", value: formatINR(o.tax_paise) },
          { label: "Total", value: formatINR(o.total_paise) },
          { label: "Gateway", value: humanize(o.gateway) },
          { label: "Created", value: formatDateTime(o.created_at) },
          { label: "Paid", value: formatDateTime(o.paid_at) },
          { label: "Payment window ends", value: formatDateTime(o.expires_at) },
        ]}
      />
      <Table caption="Items" showCaption columns={itemCols} rows={o.items ?? []} rowKey={(i) => i.order_item_id} empty={{ title: "No items" }} />
      {o.payments ? (
        <Table caption="Payments" showCaption columns={payCols} rows={o.payments} rowKey={(p) => p.payment_id} empty={{ title: "No payment attempts" }} />
      ) : (
        <p className="text-sm text-fg-muted">Payment attempts need the payment.read permission.</p>
      )}
      <Table caption="Gateway webhook events" showCaption columns={hookCols} rows={o.webhook_events ?? []} rowKey={(e) => `${e.event_type}-${e.received_at}`} empty={{ title: "No webhook events" }} />
      <Table caption="Access granted" showCaption columns={entCols} rows={o.entitlements ?? []} rowKey={(e) => e.entitlement_id} empty={{ title: "No access granted" }} />
      <Table caption="Invoices" showCaption columns={invCols} rows={o.invoices ?? []} rowKey={(i) => i.invoice_id} empty={{ title: "No invoices" }} />
    </div>
  );
}

/** FIN-004 orders & payments (COM-28/29). Payment rows are masked (gateway ids, method, last4 only). */
export function Orders() {
  const [status, setStatus] = useState("");
  const [userId, setUserId] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  // fin_orders filters: status, user_id, limit (no search / date range).
  const list = useCursorList<OrderRow>("finance/orders", cleanQuery({ status, user_id: userId.trim(), limit: 50 }));
  const detail = useVersioned<OrderDetailOut>(open ? `finance/orders/${open}` : null);
  const [refundFor, setRefundFor] = useState<OrderDetailOut | null>(null);
  const cols: Column<OrderRow>[] = [
    { key: "ref", header: "Order", cell: (o) => <span className="font-mono text-xs">{o.order_number ?? o.order_id}</span> },
    { key: "status", header: "Status", cell: (o) => <StateBadge state={o.status} /> },
    { key: "total", header: "Total", align: "right", cell: (o) => formatINR(o.total_paise) },
    { key: "gateway", header: "Gateway", cell: (o) => humanize(o.gateway) },
    { key: "created", header: "Created", cell: (o) => formatDateTime(o.created_at) },
    { key: "paid", header: "Paid", cell: (o) => formatDateTime(o.paid_at) },
    { key: "act", header: <span className="sr-only">Details</span>, cell: (o) => <Button size="sm" variant="ghost" onClick={() => setOpen(o.order_id)} aria-label={`Details for order ${o.order_number ?? o.order_id}`}>Details</Button> },
  ];
  return (
    <div>
      <PageHeader eyebrow="FIN-004" title="Orders & payments" />
      <FilterBar label="Order filters">
        <FormField label="User id">{(f) => <Input {...f} value={userId} onChange={(e) => setUserId(e.target.value)} />}</FormField>
        <FormField label="Status">{(f) => <Select {...f} value={status} onChange={(e) => setStatus(e.target.value)} options={[{ value: "", label: "Any" }, ...["created", "pending_payment", "paid", "failed", "expired", "cancelled", "refunded", "partially_refunded"].map((s) => ({ value: s, label: humanize(s) }))]} />}</FormField>
      </FilterBar>
      <Table caption="Orders" columns={cols} rows={list.rows} rowKey={(o) => o.order_id} loading={list.loading} error={list.error} onRetry={() => void list.reload()} empty={{ title: "No orders match" }} footer={<Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} />} />
      {open ? (
        <Card
          title="Order detail"
          className="mt-4"
          actions={
            <span className="flex flex-wrap gap-2">
              {detail.data && REFUNDABLE_ORDER.has(detail.data.status) ? (
                <Button size="sm" variant="secondary" onClick={() => setRefundFor(detail.data!)}>
                  Issue refund
                </Button>
              ) : null}
              <Button size="sm" variant="ghost" onClick={() => setOpen(null)}>
                Close
              </Button>
            </span>
          }
        >
          {detail.error ? <InlineProblem error={detail.error} /> : detail.data ? <OrderDetail order={detail.data} /> : <Skeleton className="h-32 w-full" />}
        </Card>
      ) : null}
      {refundFor ? (
        <FinanceRefundDialog
          order={refundFor}
          onClose={() => setRefundFor(null)}
          onDone={() => {
            void detail.reload();
            void list.reload();
          }}
        />
      ) : null}
    </div>
  );
}

const REFUNDABLE_ORDER = new Set(["paid", "partially_refunded"]);

/** schemas.FinanceRefundIn reason_code. `price_adjustment` and `duplicate_payment` keep the buyer's access (COM-01). */
export const FINANCE_REFUND_REASONS = [
  { value: "duplicate_payment", label: "Duplicate payment (keeps access)" },
  { value: "price_adjustment", label: "Price adjustment (keeps access)" },
  { value: "service_failure", label: "Service failure" },
  { value: "content_issue", label: "Content issue" },
  { value: "goodwill", label: "Goodwill (needs a second finance admin)" },
  { value: "other", label: "Other" },
] as const;

const KEEPS_ACCESS = new Set(["duplicate_payment", "price_adjustment"]);

/** Finance-initiated refund (POST finance/refunds). Goodwill or > ₹25,000 returns 202 for a second finance admin. */
export function FinanceRefundDialog({ order, onClose, onDone }: { order: OrderDetailOut; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [reason, setReason] = useState<string>("price_adjustment");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const paise = amount.trim() ? Math.round(Number(amount) * 100) : null;
  const needsDual = reason === "goodwill" || (paise ?? order.total_paise ?? 0) > REFUND_DUAL_ABOVE_PAISE;
  return (
    <ActionDialog
      open
      onClose={onClose}
      title={`Refund order ${order.order_number}`}
      description={KEEPS_ACCESS.has(reason) ? "The buyer keeps access: only money is returned." : "Access bought with this order is revoked when the refund is approved."}
      submitLabel={needsDual ? "Submit for approval" : "Issue refund"}
      validate={() => {
        if (paise !== null && !(Number.isFinite(paise) && paise > 0)) return "Enter a refund amount, or leave it empty for the full refundable amount.";
        if (paise !== null && typeof order.total_paise === "number" && paise > order.total_paise) return `Max ${formatINR(order.total_paise)}`;
        return note.trim().length < 3 ? "Add a note (3+ characters)." : null;
      }}
      onSubmit={async () =>
        toOutcome(await api.post("finance/refunds", { order_id: order.order_id, reason_code: reason as Schema<"FinanceRefundIn">["reason_code"], amount_paise: paise, note: note.trim() } satisfies Schema<"FinanceRefundIn">, { idempotencyKey: true }))
      }
      onDone={(o) => {
        if (o.kind === "ok") toast.show({ title: "Refund issued.", tone: "success" });
        onDone();
      }}
    >
      <KeyValueList items={[{ label: "Order total", value: formatINR(order.total_paise) }, { label: "Status", value: <StateBadge state={order.status} /> }]} />
      <FormField label="Reason" required>{(f) => <Select {...f} value={reason} onChange={(e) => setReason(e.target.value)} options={[...FINANCE_REFUND_REASONS]} />}</FormField>
      <FormField label="Amount (₹)" hint="Empty = the full refundable amount.">{(f) => <Input {...f} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />}</FormField>
      <FormField label="Note" required>{(f) => <TextArea {...f} value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />}</FormField>
      {needsDual ? <p className="text-sm text-info-fg"><span aria-hidden="true">ⓘ </span>A second finance admin must approve this refund.</p> : null}
    </ActionDialog>
  );
}

/* ---------------------------------------------------------------- Refunds */

/** verified: app/modules/commerce/service.py refund_json + refund_eligibility (via router.py fin_refunds). */
interface RefundRow {
  refund_id: string;
  order_id: string;
  amount_paise: number;
  reason_code?: string;
  status: string;
  consumption_pct?: number | null;
  approval_request_id?: string | null;
  gateway_refund_id?: string | null;
  created_at?: string | null;
  processed_at?: string | null;
  /** null when the order is no longer paid / partially refunded. */
  eligibility?: { eligible: boolean; reasons: string[]; days_since_purchase?: number; consumption_pct?: number; certificate_issued?: boolean; refundable_paise?: number; usage_source?: string } | null;
}

/** FIN-005 refund queue (COM-30) and decision (COM-31, P5; Dual for goodwill or > ₹25,000). */
export function Refunds() {
  const toast = useToast();
  const [status, setStatus] = useState("requested");
  // fin_refunds filters: status only.
  const list = useCursorList<RefundRow>("finance/refunds", cleanQuery({ status }));
  const [act, setAct] = useState<RefundRow | null>(null);
  const [decision, setDecision] = useState("approve");
  const [amount, setAmount] = useState("");
  const [goodwill, setGoodwill] = useState(false);
  const [note, setNote] = useState("");
  // ADM-25: the second finance admin decides a refund that is waiting for dual approval.
  const [second, setSecond] = useState<RefundRow | null>(null);
  const [secondDecision, setSecondDecision] = useState("approve");
  const [secondNote, setSecondNote] = useState("");

  const amountPaise = Math.round(Number(amount) * 100);
  const needsDual = decision === "approve" && (goodwill || amountPaise > REFUND_DUAL_ABOVE_PAISE);

  const cols: Column<RefundRow>[] = [
    { key: "order", header: "Order", cell: (r) => <span className="font-mono text-xs">{r.order_id}</span> },
    { key: "amount", header: "Requested", align: "right", cell: (r) => formatINR(r.amount_paise) },
    {
      key: "elig",
      header: "Rule",
      cell: (r) =>
        r.eligibility ? (
          <span className="text-xs">
            <Badge tone={r.eligibility.eligible ? "success" : "warning"}>{r.eligibility.eligible ? "✓ Eligible" : "✗ Outside rule"}</Badge>
            <span className="block text-fg-muted">
              {typeof r.eligibility.days_since_purchase === "number" ? `${r.eligibility.days_since_purchase} d` : ""}
              {typeof r.eligibility.consumption_pct === "number" ? ` · ${r.eligibility.consumption_pct}% used` : ""}
              {r.eligibility.certificate_issued ? " · certificate issued" : ""}
            </span>
          </span>
        ) : (
          "—"
        ),
    },
    { key: "status", header: "Status", cell: (r) => <span className="flex flex-col gap-1"><StateBadge state={r.status} />{r.approval_request_id ? <span className="text-xs text-warning-fg">⇄ Awaiting second approver</span> : null}</span> },
    { key: "at", header: "Requested on", cell: (r) => formatDateTime(r.created_at) },
    {
      key: "act",
      header: <span className="sr-only">Actions</span>,
      cell: (r) =>
        r.status === "requested" && r.approval_request_id ? (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => {
              setSecond(r);
              setSecondDecision("approve");
              setSecondNote("");
            }}
            aria-label={`Second approval for refund ${r.order_id}`}
          >
            Decide
          </Button>
        ) : r.status === "requested" ? (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => {
              setAct(r);
              setDecision("approve");
              setGoodwill(!!r.eligibility && !r.eligibility.eligible);
              setAmount((r.amount_paise / 100).toFixed(2));
            }}
            aria-label={`Decide refund for ${r.order_id}`}
          >
            Decide
          </Button>
        ) : null,
    },
  ];

  return (
    <div>
      <PageHeader eyebrow="FIN-005" title="Refunds" description="Goodwill refunds and refunds over ₹25,000 need a second finance admin." />
      <FilterBar label="Refund filters">
        <FormField label="Status">{(f) => <Select {...f} value={status} onChange={(e) => setStatus(e.target.value)} options={[{ value: "", label: "Any" }, ...["requested", "approved", "processing", "processed", "rejected", "failed"].map((s) => ({ value: s, label: humanize(s) }))]} />}</FormField>
      </FilterBar>
      <Table caption="Refund requests" columns={cols} rows={list.rows} rowKey={(r) => r.refund_id} loading={list.loading} error={list.error} onRetry={() => void list.reload()} empty={{ title: "No refunds match" }} footer={<Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} />} />
      <ActionDialog
        open={act !== null}
        onClose={() => setAct(null)}
        title={`Refund decision · ${act?.order_id ?? ""}`}
        description={act?.reason_code ? `Reason: ${humanize(act.reason_code)}` : undefined}
        submitLabel={needsDual ? "Submit for approval" : decision === "approve" ? "Approve refund" : "Reject"}
        danger={decision === "reject"}
        validate={() => {
          if (decision === "approve") {
            if (!Number.isFinite(amountPaise) || amountPaise <= 0) return "Enter a refund amount.";
            const max = act?.eligibility?.refundable_paise ?? act?.amount_paise;
            if (typeof max === "number" && amountPaise > max) return `Max ${formatINR(max)}`;
            if (act?.eligibility && !act.eligibility.eligible && !goodwill) return "This request is outside the refund rule: approve only as goodwill.";
          }
          return note.trim().length < 5 ? "Add a note." : null;
        }}
        onSubmit={async () => toOutcome(await api.post(`finance/refunds/${act!.refund_id}/decision`, { decision: decision as "approve" | "reject", amount_paise: decision === "approve" ? amountPaise : undefined, goodwill, note: note.trim() } satisfies Schema<"RefundDecisionIn">, { idempotencyKey: true }))}
        onDone={(o) => {
          setNote("");
          if (o.kind === "ok") toast.show({ title: decision === "approve" ? "Refund approved and submitted." : "Refund rejected.", tone: "success" });
          void list.reload();
        }}
      >
        {act?.eligibility ? <KeyValueList items={[{ label: "Eligible", value: act.eligibility.eligible ? "Yes" : "No" }, { label: "Reasons", value: act.eligibility.reasons.length ? act.eligibility.reasons.map(humanize).join(", ") : "—" }, { label: "Refundable", value: formatINR(act.eligibility.refundable_paise) }]} /> : null}
        <FormField label="Decision">{(f) => <Select {...f} value={decision} onChange={(e) => setDecision(e.target.value)} options={[{ value: "approve", label: "Approve" }, { value: "reject", label: "Reject" }]} />}</FormField>
        {decision === "approve" ? (
          <>
            <FormField label="Amount (₹)" required>{(f) => <Input {...f} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />}</FormField>
            <Checkbox label="Goodwill (outside the published rule)" checked={goodwill} onChange={(e) => setGoodwill(e.target.checked)} />
            {needsDual ? <p className="text-sm text-info-fg"><span aria-hidden="true">ⓘ </span>A second finance admin must approve this refund.</p> : null}
          </>
        ) : null}
        <FormField label="Note" required>{(f) => <TextArea {...f} value={note} onChange={(e) => setNote(e.target.value)} />}</FormField>
      </ActionDialog>
      <ActionDialog
        open={second !== null}
        onClose={() => setSecond(null)}
        title={`Second approval · ${second?.order_id ?? ""}`}
        description="This refund is goodwill or above ₹25,000, so a second finance admin decides it. You cannot decide a refund you approved first."
        submitLabel={secondDecision === "approve" ? "Approve refund" : "Send back"}
        danger={secondDecision === "reject"}
        validate={() => (secondDecision === "reject" && secondNote.trim().length < 5 ? "A reason is required." : null)}
        onSubmit={() => decideApproval({ approval_request_id: second!.approval_request_id!, action_type: "commerce.refund" }, secondDecision === "approve", secondNote)}
        onDone={() => {
          toast.show({ title: secondDecision === "approve" ? "Refund approved." : "Refund sent back.", tone: "success" });
          setSecondNote("");
          void list.reload();
        }}
      >
        {second ? (
          <KeyValueList
            items={[
              { label: "Requested", value: formatINR(second.amount_paise) },
              { label: "Reason", value: humanize(second.reason_code) },
              { label: "Eligible", value: second.eligibility ? (second.eligibility.eligible ? "Yes" : `No (${second.eligibility.reasons.map(humanize).join(", ") || "outside rule"})`) : "—" },
              { label: "Approval request", value: <span className="break-all font-mono text-xs">{second.approval_request_id}</span> },
            ]}
          />
        ) : null}
        <FormField label="Decision">{(f) => <Select {...f} value={secondDecision} onChange={(e) => setSecondDecision(e.target.value)} options={[{ value: "approve", label: "Approve" }, { value: "reject", label: "Send back" }]} />}</FormField>
        <FormField label={secondDecision === "reject" ? "Reason" : "Note (optional)"} required={secondDecision === "reject"}>
          {(f) => <TextArea {...f} value={secondNote} onChange={(e) => setSecondNote(e.target.value)} maxLength={1000} />}
        </FormField>
      </ActionDialog>
    </div>
  );
}

/* --------------------------------------------------------------- Invoices */

const gstOf = (i: InvoiceRow) => (i.cgst_paise ?? 0) + (i.sgst_paise ?? 0) + (i.igst_paise ?? 0);

/** FIN-007 invoices & credit notes (COM-35/36), PDF download and the GST register export (COM-37). */
export function Invoices() {
  const [kind, setKind] = useState("");
  // fin_invoices: keyset `cursor` paging and a server-side `invoice_type` filter (ADM-32).
  const list = useCursorList<InvoiceRow>("finance/invoices", cleanQuery({ invoice_type: kind, limit: 100 }));
  const rows = list.rows;
  const [cn, setCn] = useState<InvoiceRow | null>(null);
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const cols: Column<InvoiceRow>[] = [
    { key: "no", header: "Number", cell: (i) => <span className="font-mono text-xs">{i.invoice_number}</span> },
    { key: "kind", header: "Type", cell: (i) => humanize(i.invoice_type) },
    { key: "cust", header: "Customer", cell: (i) => i.buyer_name ?? "—" },
    { key: "date", header: "Issued", cell: (i) => formatDate(i.issue_date) },
    { key: "gst", header: "GST", align: "right", cell: (i) => formatINR(gstOf(i)) },
    { key: "total", header: "Total", align: "right", cell: (i) => formatINR(i.total_paise) },
    {
      key: "act",
      header: <span className="sr-only">Actions</span>,
      cell: (i) => (
        <span className="inline-flex flex-wrap gap-2">
          <InvoicePdfButton invoice={i} />
          {i.invoice_type === "tax_invoice" ? (
            <Button size="sm" variant="secondary" onClick={() => setCn(i)} aria-label={`Credit note for ${i.invoice_number}`}>
              Credit note
            </Button>
          ) : null}
        </span>
      ),
    },
  ];
  return (
    <div>
      <PageHeader eyebrow="FIN-007" title="Invoices & credit notes" />
      <FilterBar label="Invoice filters">
        <FormField label="Type">{(f) => <Select {...f} value={kind} onChange={(e) => setKind(e.target.value)} options={[{ value: "", label: "All" }, { value: "tax_invoice", label: "Invoices" }, { value: "credit_note", label: "Credit notes" }]} />}</FormField>
      </FilterBar>
      <Table caption="Invoices" columns={cols} rows={rows} rowKey={(i) => i.invoice_id} loading={list.loading} error={list.error} onRetry={() => void list.reload()} empty={{ title: "No invoices" }} footer={<Pagination hasMore={list.hasMore} hasPrevious={list.hasPrevious} onNext={list.next} onPrevious={list.previous} />} />
      <div className="mt-4">
        <GstExports />
      </div>
      <ActionDialog
        open={cn !== null}
        onClose={() => setCn(null)}
        title={`Credit note for ${cn?.invoice_number ?? ""}`}
        description="Issued in the gap-free TDCN series."
        submitLabel="Issue credit note"
        validate={() => {
          const p = Math.round(Number(amount) * 100);
          if (!Number.isFinite(p) || p <= 0) return "Enter an amount.";
          if (typeof cn?.total_paise === "number" && p > cn.total_paise) return `Max ${formatINR(cn.total_paise)}`;
          return reason.trim().length < 5 ? "Give a reason." : null;
        }}
        onSubmit={async () => toOutcome(await api.post(`finance/invoices/${cn!.invoice_id}/credit-notes`, { amount_paise: Math.round(Number(amount) * 100), reason: reason.trim() } satisfies Schema<"CreditNoteIn">, { idempotencyKey: true }))}
        onDone={() => {
          setAmount("");
          setReason("");
          void list.reload();
        }}
      >
        <FormField label="Amount (₹)" required>{(f) => <Input {...f} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />}</FormField>
        <FormField label="Reason" required>{(f) => <TextArea {...f} value={reason} onChange={(e) => setReason(e.target.value)} />}</FormField>
      </ActionDialog>
    </div>
  );
}

/* --------------------------------------------------------- Reconciliation */

/** verified: app/modules/commerce/admin.py run_json / run_reconciliation (via router.py fin_reconciliation, last 30 runs). */
interface ReconRunRow {
  run_id: string;
  gateway: string;
  range_from: string;
  range_to: string;
  status: string;
  summary?: { orders_checked?: number; payments_checked?: number; recovered?: number; provider_errors?: number } | null;
  /** e.g. { type: "amount_mismatch", payment_id, ours, provider } | { type: "missed_capture_recovered", order_number }. */
  mismatches?: ({ type: string } & Record<string, unknown>)[] | null;
  triggered_by?: string | null;
  created_at?: string | null;
}

/** Start of a calendar day in IST as an ISO timestamp (ReconciliationIn takes datetimes). */
const istDayStart = (d: string) => `${d}T00:00:00+05:30`;

/** The calendar day after `d` (YYYY-MM-DD), computed in UTC so no local offset shifts it. */
export const nextDay = (d: string) => new Date(Date.parse(`${d}T00:00:00Z`) + 86_400_000).toISOString().slice(0, 10);

/**
 * ADM-40: the api checks payments with `created_at < range_to`, so an inclusive "To" day is
 * sent as 00:00 IST of the following day. Returns the body, or an error for 1–31 calendar days.
 */
export function reconciliationRange(from: string, to: string): { body: { range_from: string; range_to: string } } | { error: string } {
  if (!from || !to) return { error: "Choose a date range." };
  const days = (Date.parse(to) - Date.parse(from)) / 86_400_000 + 1;
  if (days < 1) return { error: "From must be on or before To." };
  if (days > 31) return { error: "The range can be at most 31 days." };
  return { body: { range_from: istDayStart(from), range_to: istDayStart(nextDay(to)) } };
}

/** FIN-009 settlement reconciliation runs (COM-45) and new runs (COM-46). */
export function Reconciliation() {
  const list = useCursorList<ReconRunRow>("finance/reconciliation");
  const [open, setOpen] = useState<ReconRunRow | null>(null);
  const [run, setRun] = useState(false);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const cols: Column<ReconRunRow>[] = [
    { key: "at", header: "Run", cell: (r) => formatDateTime(r.created_at) },
    { key: "range", header: "Range", cell: (r) => `${formatDate(r.range_from)} – ${formatDate(r.range_to)}` },
    { key: "gw", header: "Gateway", cell: (r) => humanize(r.gateway) },
    { key: "checked", header: "Checked", align: "right", cell: (r) => (r.summary ? `${r.summary.orders_checked ?? 0} orders · ${r.summary.payments_checked ?? 0} payments` : "—") },
    { key: "mm", header: "Mismatches", align: "right", cell: (r) => String(r.mismatches?.length ?? 0) },
    { key: "status", header: "Status", cell: (r) => <StateBadge state={r.status} /> },
    { key: "act", header: <span className="sr-only">Details</span>, cell: (r) => (r.mismatches?.length ? <Button size="sm" variant="ghost" onClick={() => setOpen(r)}>Mismatches</Button> : null) },
  ];
  return (
    <div>
      <PageHeader eyebrow="FIN-009" title="Reconciliation" description="Payments vs. settlements." actions={<Button onClick={() => setRun(true)}>Run reconciliation</Button>} />
      <Table caption="Reconciliation runs" columns={cols} rows={list.rows} rowKey={(r) => r.run_id} loading={list.loading} error={list.error} onRetry={() => void list.reload()} empty={{ title: "No reconciliation runs" }} />
      {open ? (
        <Card title={`Mismatches · ${formatDateTime(open.created_at)}`} className="mt-4" actions={<Button size="sm" variant="ghost" onClick={() => setOpen(null)}>Close</Button>}>
          <JsonBlock label="Mismatches found in this run" value={open.mismatches} />
        </Card>
      ) : null}
      <ActionDialog
        open={run}
        onClose={() => setRun(false)}
        title="Run settlement reconciliation"
        description="Covers 1–31 days; both dates are included (IST)."
        submitLabel="Run"
        validate={() => {
          const r = reconciliationRange(from, to);
          return "error" in r ? r.error : null;
        }}
        onSubmit={async () => {
          const r = reconciliationRange(from, to);
          if (!("body" in r)) throw new Error(r.error);
          return toOutcome(await api.post<ReconRunRow>("finance/reconciliation/runs", r.body satisfies Schema<"ReconciliationIn">, { idempotencyKey: true }));
        }}
        onDone={() => void list.reload()}
      >
        <FormField label="From" required>{(f) => <Input {...f} type="date" value={from} onChange={(e) => setFrom(e.target.value)} />}</FormField>
        <FormField label="To (inclusive)" required>{(f) => <Input {...f} type="date" value={to} onChange={(e) => setTo(e.target.value)} />}</FormField>
      </ActionDialog>
    </div>
  );
}

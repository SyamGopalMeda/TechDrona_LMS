"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import {
  Button,
  Dialog,
  ErrorState,
  FormField,
  Pagination,
  Select,
  StatusBadge,
  Table,
  Tabs,
  nextCursorStack,
  previousCursorStack,
  useToast,
  buttonClasses,
} from "@/components/ui";
import { LMS_COURSES_HREF } from "@/lib/site/website";
import { api } from "@/lib/api/client";
import { formatDate, formatDateTime, formatMoney, formatPercent, humanize } from "@/features/catalog/lib/format";
import type { Paged, ProductDto } from "@/features/catalog/lib/types";
import { useResource } from "@/features/learning/lib/use-resource";
import type {
  CancelSubscriptionBody,
  CancelSubscriptionResult,
  InvoiceDto,
  OrderDto,
  RefundEligibilityDto,
  RefundRequestBody,
  RefundRequestCreatedDto,
  RefundRequestDto,
  SubscriptionDto,
} from "../lib/types";
import { ChangePlanDialog, recurringPrices } from "./ChangePlanDialog";
import { DownloadButton } from "./DownloadButton";
import { OrderStatusBadge } from "./OrderStatus";

function usePaged<T>(path: string) {
  const [stack, setStack] = useState<(string | undefined)[]>([undefined]);
  const res = useResource<Paged<T>>(path, { cursor: stack[stack.length - 1], limit: 25 });
  const pagination = (
    <Pagination
      hasMore={Boolean(res.data?.page?.has_more)}
      hasPrevious={stack.length > 1}
      loading={res.loading}
      onNext={() => setStack((s) => nextCursorStack(s, res.data?.page?.next_cursor ?? null))}
      onPrevious={() => setStack((s) => previousCursorStack(s))}
    />
  );
  return { ...res, pagination };
}

/* ----------------------------------------------------------------- Refunds */

type ReasonCode = NonNullable<RefundRequestBody["reason_code"]>;

// verified: commerce/schemas.py RefundRequestIn.reason_code
const REASONS: { value: ReasonCode; label: string }[] = [
  { value: "within_policy_window", label: "I changed my mind (within the refund window)" },
  { value: "content_issue", label: "The content didn't work for me" },
  { value: "other", label: "Something else" },
];

const REASON_COPY: Record<string, string> = {
  window_passed: "The refund window has passed.",
  consumption_exceeded: "More of the content has been used than the rule allows.",
  certificate_issued: "A certificate has been issued for this purchase.",
  mock_started: "A mock test from this pack has been started.",
  subscription_renewal: "Subscription renewals aren't refundable.",
};

export function RefundRequestDialog({ order, onClose, onRequested }: { order: OrderDto; onClose: () => void; onRequested: () => void }) {
  const toast = useToast();
  const elig = useResource<RefundEligibilityDto>(`me/orders/${encodeURIComponent(order.order_id)}/refund-eligibility`);
  const [reason, setReason] = useState<ReasonCode>("within_policy_window");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body: RefundRequestBody = { order_id: order.order_id, reason_code: reason, note: note.trim() || null };
      await api.post<RefundRequestCreatedDto>("me/refund-requests", body, { idempotencyKey: true });
      toast.show({ title: "Refund requested. We'll email you the decision.", tone: "success" });
      onRequested();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const e = elig.data;
  return (
    <Dialog open onClose={onClose} title={`Request a refund for ${order.order_number}`} dismissible={!busy}>
      <form onSubmit={submit} className="space-y-4" aria-label="Refund request">
        {elig.loading && !e ? (
          <p role="status" className="text-sm text-fg-muted">
            Checking the refund rule…
          </p>
        ) : elig.error ? (
          <ErrorState error={elig.error} onRetry={elig.reload} />
        ) : e ? (
          <div className={`rounded-md border p-3 text-sm ${e.eligible ? "border-success-border bg-success-subtle text-success-fg" : "border-warning-border bg-warning-subtle text-warning-fg"}`}>
            <p className="font-medium">{e.eligible ? "This order meets the refund rule." : "This order doesn't meet the refund rule."}</p>
            <ul className="mt-1 list-disc pl-5 text-xs">
              {typeof e.days_since_purchase === "number" ? <li>{e.days_since_purchase} days since purchase</li> : null}
              {typeof e.consumption_pct === "number" ? <li>{formatPercent(e.consumption_pct)} of the content used</li> : null}
              {e.certificate_issued ? <li>Certificate issued</li> : null}
              {(e.reasons ?? []).map((r) => (
                <li key={r}>{REASON_COPY[r] ?? humanize(r)}</li>
              ))}
            </ul>
            {typeof e.refundable_paise === "number" ? <p className="mt-1 text-xs">Refundable amount: {formatMoney(e.refundable_paise)}</p> : null}
            {!e.eligible ? <p className="mt-1 text-xs">You can still send the request; our finance team will review it.</p> : null}
          </div>
        ) : null}
        <FormField label="Reason" required>
          {(p) => <Select {...p} value={reason} onChange={(ev) => setReason(ev.target.value as ReasonCode)} options={REASONS} />}
        </FormField>
        <FormField label="Anything we should know? (optional)">
          {(p) => (
            <textarea
              {...p}
              value={note}
              onChange={(ev) => setNote(ev.target.value)}
              maxLength={1000}
              rows={3}
              className="w-full rounded-md border border-line-control bg-surface px-3 py-2 text-sm text-fg focus-visible:shadow-focus focus-visible:outline-none"
            />
          )}
        </FormField>
        {error ? <ErrorState error={error} /> : null}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" loading={busy} disabled={!e}>
            Request refund
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

/* ------------------------------------------------------------------ Orders */

function OrdersTab() {
  const { data, error, loading, reload, pagination } = usePaged<OrderDto>("me/orders");
  const [refundFor, setRefundFor] = useState<OrderDto | null>(null);
  return (
    <>
      <Table<OrderDto>
        caption="Your orders"
        rows={data?.data}
        rowKey={(r) => r.order_id}
        loading={loading}
        error={error}
        onRetry={reload}
        empty={{ icon: "card", title: "No orders yet", description: "Purchases you make appear here with their invoices.", action: <Link href={LMS_COURSES_HREF} className={buttonClasses({ variant: "secondary", size: "sm" })}>Explore courses</Link> }}
        columns={[
          {
            key: "order",
            header: "Order",
            cell: (r) => (
              <Link href={`/app/orders/${encodeURIComponent(r.order_id)}`} className="font-mono text-sm text-fg-link hover:text-fg-link-hover">
                {r.order_number}
              </Link>
            ),
          },
          { key: "date", header: "Date", cell: (r) => formatDate(r.paid_at ?? r.created_at) },
          { key: "total", header: "Total", align: "right", cell: (r) => <span className="tabular-nums">{formatMoney(r.total_paise)}</span> },
          { key: "status", header: "Status", cell: (r) => <OrderStatusBadge status={r.status} /> },
          {
            key: "actions",
            header: <span className="sr-only">Actions</span>,
            align: "right",
            cell: (r) =>
              r.status === "paid" ? (
                <Button variant="ghost" size="sm" onClick={() => setRefundFor(r)} aria-label={`Request a refund for ${r.order_number}`}>
                  Request refund
                </Button>
              ) : null,
          },
        ]}
        footer={pagination}
      />
      {refundFor ? (
        <RefundRequestDialog
          order={refundFor}
          onClose={() => setRefundFor(null)}
          onRequested={() => {
            setRefundFor(null);
            void reload();
          }}
        />
      ) : null}
    </>
  );
}

/* ----------------------------------------------------------- Subscriptions */

const TERMINAL_SUB = new Set(["cancelled", "completed"]);

function SubscriptionsTab() {
  const toast = useToast();
  const { data, error, loading, reload, pagination } = usePaged<SubscriptionDto>("me/subscriptions");
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [changeFor, setChangeFor] = useState<SubscriptionDto | null>(null);
  // The public catalogue names plans (scheduled changes) and lists the prices to switch to.
  const needCatalogue = changeFor !== null || Boolean(data?.data?.some((s) => s.scheduled_price_id));
  const catalogue = useResource<Paged<ProductDto>>(needCatalogue ? "commerce/products" : null);
  const planName = (priceId: string) => recurringPrices(catalogue.data?.data).find((o) => o.price_id === priceId)?.product_name ?? "your new plan";

  async function cancel(s: SubscriptionDto) {
    setBusy(s.subscription_id);
    setActionError(null);
    try {
      const body: CancelSubscriptionBody = { reason: null, feedback: null };
      const res = await api.post<CancelSubscriptionResult>(`me/subscriptions/${encodeURIComponent(s.subscription_id)}/cancel`, body, { idempotencyKey: true });
      const until = res.kind === "ok" ? res.data?.access_until : undefined;
      toast.show({ title: `Cancelled. You keep access until ${formatDate(until ?? s.current_period_end)}.`, tone: "success" });
      await reload();
    } catch (err) {
      setActionError(err);
    } finally {
      setBusy(null);
    }
  }

  async function resume(s: SubscriptionDto) {
    setBusy(s.subscription_id);
    setActionError(null);
    try {
      const res = await api.post<SubscriptionDto>(`me/subscriptions/${encodeURIComponent(s.subscription_id)}/resume`, undefined, { idempotencyKey: true });
      const next = res.kind === "ok" ? (res.data?.next_charge_at ?? res.data?.current_period_end) : null;
      toast.show({ title: `Subscription resumed. It renews on ${formatDate(next ?? s.current_period_end)}.`, tone: "success" });
      await reload();
    } catch (err) {
      setActionError(err);
    } finally {
      setBusy(null);
    }
  }

  const label = (r: SubscriptionDto) => `subscription started ${formatDate(r.current_period_start)}`;

  return (
    <div className="space-y-3">
      {actionError ? <ErrorState error={actionError} /> : null}
      <Table<SubscriptionDto>
        caption="Your subscriptions"
        rows={data?.data}
        rowKey={(r) => r.subscription_id}
        loading={loading}
        error={error}
        onRetry={reload}
        empty={{ icon: "calendar", title: "No subscriptions", description: "Recurring plans you start appear here. You can cancel any time in one click." }}
        columns={[
          { key: "started", header: "Started", cell: (r) => formatDate(r.current_period_start) },
          {
            key: "status",
            header: "Status",
            cell: (r) => (
              <span className="flex flex-col gap-1">
                <StatusBadge status={r.status} label={r.cancel_at_period_end ? "Cancels at period end" : humanize(r.status)} />
                {r.status === "grace" && r.grace_until ? <span className="text-xs text-warning-fg">Renewal payment failed — the bank will retry. Keep your UPI AutoPay or card mandate active; access continues until {formatDate(r.grace_until)}</span> : null}
                {r.scheduled_price_id ? (
                  <span className="text-xs text-info-fg">
                    Changes to {planName(r.scheduled_price_id)} on {formatDate(r.scheduled_change_at ?? r.current_period_end)}
                  </span>
                ) : null}
                {r.pending_addon_paise ? <span className="text-xs text-fg-muted">+{formatMoney(r.pending_addon_paise)} upgrade difference on the next renewal</span> : null}
              </span>
            ),
          },
          {
            key: "next",
            header: "Next charge / access until",
            cell: (r) => (r.cancel_at_period_end ? `Access until ${formatDate(r.current_period_end)}` : r.next_charge_at ? formatDateTime(r.next_charge_at) : formatDate(r.current_period_end)),
          },
          {
            key: "actions",
            header: <span className="sr-only">Actions</span>,
            align: "right",
            cell: (r) =>
              TERMINAL_SUB.has(r.status) ? null : r.cancel_at_period_end ? (
                <Button variant="secondary" size="sm" loading={busy === r.subscription_id} onClick={() => void resume(r)} aria-label={`Resume ${label(r)}`}>
                  Resume
                </Button>
              ) : (
                <span className="inline-flex flex-wrap justify-end gap-2">
                  {r.status === "active" ? (
                    <Button variant="secondary" size="sm" disabled={busy === r.subscription_id} onClick={() => setChangeFor(r)} aria-label={`Change plan for ${label(r)}`}>
                      Change plan
                    </Button>
                  ) : null}
                  <Button variant="secondary" size="sm" loading={busy === r.subscription_id} onClick={() => void cancel(r)} aria-label={`Cancel ${label(r)}`}>
                    Cancel subscription
                  </Button>
                </span>
              ),
          },
        ]}
        footer={pagination}
      />
      {changeFor ? (
        <ChangePlanDialog
          subscription={changeFor}
          products={catalogue.data?.data}
          catalogueLoading={catalogue.loading}
          catalogueError={catalogue.error}
          onClose={() => setChangeFor(null)}
          onChanged={() => {
            setChangeFor(null);
            void reload();
          }}
        />
      ) : null}
    </div>
  );
}

/* ---------------------------------------------------------------- Invoices */

function InvoicesTab() {
  const { data, error, loading, reload, pagination } = usePaged<InvoiceDto>("me/invoices");
  return (
    <div className="space-y-3">
      <Table<InvoiceDto>
        caption="Invoices and credit notes"
        rows={data?.data}
        rowKey={(r) => r.invoice_id}
        loading={loading}
        error={error}
        onRetry={reload}
        empty={{ icon: "document", title: "No invoices yet", description: "A GST invoice is issued for every paid order." }}
        columns={[
          { key: "number", header: "Number", cell: (r) => <span className="font-mono text-sm">{r.invoice_number}</span> },
          { key: "kind", header: "Type", cell: (r) => (r.invoice_type === "credit_note" ? "Credit note" : "Invoice") },
          { key: "date", header: "Date", cell: (r) => formatDate(r.issue_date) },
          {
            key: "order",
            header: "Order",
            cell: (r) => (
              <Link href={`/app/orders/${encodeURIComponent(r.order_id)}`} className="text-sm text-fg-link hover:text-fg-link-hover">
                View order
              </Link>
            ),
          },
          { key: "total", header: "Amount", align: "right", cell: (r) => <span className="tabular-nums">{formatMoney(r.total_paise)}</span> },
          {
            key: "pdf",
            header: <span className="sr-only">Download</span>,
            align: "right",
            // COM-16: a fresh 5-minute signed URL per click.
            cell: (r) => (
              <DownloadButton
                path={`me/invoices/${encodeURIComponent(r.invoice_id)}/pdf`}
                label="Download PDF"
                ariaLabel={`Download PDF for ${r.invoice_type === "credit_note" ? "credit note" : "invoice"} ${r.invoice_number}`}
              />
            ),
          },
        ]}
        footer={pagination}
      />
    </div>
  );
}

/* ------------------------------------------------------------ Refund list */

function RefundsTab() {
  const { data, error, loading, reload, pagination } = usePaged<RefundRequestDto>("me/refund-requests");
  return (
    <Table<RefundRequestDto>
      caption="Refund requests"
      rows={data?.data}
      rowKey={(r) => r.refund_id}
      loading={loading}
      error={error}
      onRetry={reload}
      empty={{ icon: "card", title: "No refund requests", description: "To request a refund, open the Orders tab and choose Request refund on a paid order." }}
      columns={[
        {
          key: "order",
          header: "Order",
          cell: (r) => (
            <Link href={`/app/orders/${encodeURIComponent(r.order_id)}`} className="text-sm text-fg-link hover:text-fg-link-hover">
              View order
            </Link>
          ),
        },
        { key: "requested", header: "Requested", cell: (r) => formatDate(r.created_at) },
        { key: "amount", header: "Amount", align: "right", cell: (r) => <span className="tabular-nums">{typeof r.amount_paise === "number" ? formatMoney(r.amount_paise) : "—"}</span> },
        { key: "status", header: "Status", cell: (r) => <StatusBadge status={r.status} label={humanize(r.status)} /> },
        { key: "processed", header: "Processed", cell: (r) => (r.processed_at ? formatDate(r.processed_at) : "—") },
      ]}
      footer={pagination}
    />
  );
}

/** STU-018 billing: orders, subscriptions, invoices, refund requests. */
export function Billing() {
  return (
    <Tabs
      label="Billing"
      items={[
        { id: "orders", label: "Orders", content: <OrdersTab /> },
        { id: "subscriptions", label: "Subscriptions", content: <SubscriptionsTab /> },
        { id: "invoices", label: "Invoices", content: <InvoicesTab /> },
        { id: "refunds", label: "Refunds", content: <RefundsTab /> },
      ]}
    />
  );
}

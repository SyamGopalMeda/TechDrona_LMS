"use client";

import { useState, type FormEvent } from "react";
import { StatusBadge, Button, Card, FormField, Input, Table, useToast, type Column } from "@/components/ui";
import { api } from "@/lib/api/client";
import { DownloadButton } from "@/features/commerce/components/DownloadButton";
import { InlineProblem, TextArea } from "@/features/admin/components/console-ui";
import { humanize, personLabel, useCursorList } from "@/features/admin/lib/console";
import { GST_EXPORT_APPROVAL_ROWS, GST_EXPORT_MAX_DAYS, type GstExport, type GstExportBody, type InvoiceRow } from "../lib/types";
import { formatDate, formatDateTime } from "@/lib/format";

/** Per-row invoice / credit-note PDF (fresh signed URL per click). */
export function InvoicePdfButton({ invoice }: { invoice: Pick<InvoiceRow, "invoice_id" | "invoice_number"> }) {
  return <DownloadButton path={`finance/invoices/${encodeURIComponent(invoice.invoice_id)}/pdf`} label="PDF" ariaLabel={`Download PDF for ${invoice.invoice_number}`} />;
}

/* --------------------------------------------------------- GST register export */

/* Export-specific wording; tones come from the kit status vocabulary. */
const GST_LABEL: Record<string, string> = {
  ready: "Ready",
  awaiting_approval: "Awaiting approval",
  rejected: "Rejected",
  expired: "Expired",
  failed: "Failed",
};

function GstStatusBadge({ status }: { status: string }) {
  return <StatusBadge status={status} label={GST_LABEL[status] ?? humanize(status)} />;
}

const DAY_MS = 86_400_000;

/** Inclusive number of calendar days in `from`..`to` (YYYY-MM-DD). */
export function inclusiveDays(from: string, to: string): number {
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / DAY_MS) + 1;
}

/** FIN-007 GST register export (COM-37): request, approval state, signed download. */
export function GstExports() {
  const toast = useToast();
  const list = useCursorList<GstExport>("finance/gst-exports");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [clientError, setClientError] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);

  function validate(): string | null {
    if (!from || !to) return "Choose the period.";
    const days = inclusiveDays(from, to);
    if (days < 1) return "The period must end on or after its start.";
    if (days > GST_EXPORT_MAX_DAYS) return `The period can be at most ${GST_EXPORT_MAX_DAYS} days.`;
    return null;
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const msg = validate();
    setClientError(msg);
    if (msg) return;
    setBusy(true);
    setError(null);
    try {
      const body: GstExportBody = { period_from: from, period_to: to, ...(reason.trim() ? { reason: reason.trim() } : {}) };
      const res = await api.post<GstExport>("finance/gst-exports", body, { idempotencyKey: true });
      if (res.kind === "approval_pending" || res.data?.status === "awaiting_approval") {
        toast.show({ title: "Export requested. It needs a super admin's approval before it can be downloaded.", tone: "info" });
      } else if (res.data?.status === "ready") {
        toast.show({ title: `GST register ready${typeof res.data.row_count === "number" ? ` (${res.data.row_count.toLocaleString("en-IN")} rows)` : ""}.`, tone: "success" });
      } else {
        toast.show({ title: `Export ${humanize(res.data?.status ?? "requested").toLowerCase()}.`, tone: res.data?.status === "failed" ? "danger" : "info" });
      }
      setReason("");
      await list.reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const cols: Column<GstExport>[] = [
    { key: "period", header: "Period", cell: (x) => `${formatDate(x.period_from)} – ${formatDate(x.period_to)}` },
    {
      key: "status",
      header: "Status",
      cell: (x) => (
        <span className="flex flex-col gap-1">
          <GstStatusBadge status={x.status} />
          {x.status === "awaiting_approval" ? <span className="text-xs text-warning-fg">⇄ Waiting for a super admin in the approvals queue</span> : null}
        </span>
      ),
    },
    { key: "rows", header: "Rows", align: "right", cell: (x) => (typeof x.row_count === "number" ? x.row_count.toLocaleString("en-IN") : "—") },
    { key: "by", header: "Requested by", cell: (x) => <span title={x.requested_by}>{personLabel({ id: x.requested_by })}</span> },
    { key: "at", header: "Requested", cell: (x) => formatDateTime(x.created_at) },
    { key: "done", header: "Completed", cell: (x) => formatDateTime(x.completed_at) },
    {
      key: "dl",
      header: <span className="sr-only">Download</span>,
      cell: (x) =>
        x.status === "ready" ? (
          <span className="flex flex-col items-start gap-0.5">
            <DownloadButton
              path={`finance/gst-exports/${encodeURIComponent(x.gst_export_id)}/download`}
              label="Download"
              variant="secondary"
              ariaLabel={`Download GST register ${formatDate(x.period_from)} to ${formatDate(x.period_to)}`}
            />
            {x.download_expires_at ? <span className="text-xs text-fg-muted">Available until {formatDateTime(x.download_expires_at)}</span> : null}
          </span>
        ) : null,
    },
  ];

  return (
    <Card
      title="GST register export"
      actions={
        <Button size="sm" variant="ghost" loading={list.loading} onClick={() => void list.reload()} aria-label="Refresh GST exports">
          Refresh
        </Button>
      }
    >
      <p className="mb-3 text-sm text-fg-secondary">
        Export every invoice and credit note for a period (up to {GST_EXPORT_MAX_DAYS} days). Exports over {GST_EXPORT_APPROVAL_ROWS.toLocaleString("en-IN")} rows wait for a super admin — a different person from
        the requester — to approve them in the admin approvals queue; refresh to see the new status.
      </p>
      <form onSubmit={submit} noValidate aria-label="Request GST register export" className="mb-4 space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <FormField label="Period from" required>{(f) => <Input {...f} type="date" value={from} onChange={(e) => setFrom(e.target.value)} />}</FormField>
          <FormField label="Period to" required>{(f) => <Input {...f} type="date" value={to} onChange={(e) => setTo(e.target.value)} />}</FormField>
        </div>
        <FormField label="Reason (optional)">{(f) => <TextArea {...f} value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />}</FormField>
        {clientError ? (
          <p role="alert" className="text-sm font-medium text-danger-fg">
            {clientError}
          </p>
        ) : null}
        <InlineProblem error={error} />
        <div className="flex justify-end">
          <Button type="submit" loading={busy}>
            Request export
          </Button>
        </div>
      </form>
      <Table caption="GST register exports" columns={cols} rows={list.rows} rowKey={(x) => x.gst_export_id} loading={list.loading} error={list.error} onRetry={() => void list.reload()} empty={{ title: "No GST exports yet", description: "Choose a period above and request an export.", icon: "document" }} />
    </Card>
  );
}

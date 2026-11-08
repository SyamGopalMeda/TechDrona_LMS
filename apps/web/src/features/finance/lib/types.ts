/**
 * Finance console DTOs that are hand-written against the api contract (the generated
 * `Schema<>` names for these routes may not exist yet). Money is integer paise; datetimes ISO 8601.
 */

/** commerce/service.py invoice_json (GET finance/invoices). B2C tax invoices with an optional buyer GSTIN (D1). */
export interface InvoiceRow {
  invoice_id: string;
  invoice_number: string;
  invoice_type: "tax_invoice" | "credit_note" | string;
  order_id: string | null;
  original_invoice_id?: string | null;
  issue_date?: string;
  seller_gstin?: string | null;
  buyer_name?: string | null;
  buyer_gstin?: string | null;
  place_of_supply?: string | null;
  taxable_paise?: number;
  cgst_paise?: number;
  sgst_paise?: number;
  igst_paise?: number;
  total_paise?: number;
  status?: string;
  pdf_ready?: boolean;
  description?: string | null;
  due_on?: string | null;
}

export type GstExportStatus = "ready" | "awaiting_approval" | "rejected" | "expired" | "failed";

/** GET finance/gst-exports rows / GET finance/gst-exports/{id} / POST finance/gst-exports (202). */
export interface GstExport {
  gst_export_id: string;
  period_from: string;
  period_to: string;
  status: GstExportStatus | string;
  row_count: number | null;
  approval_request_id: string | null;
  requested_by: string;
  created_at: string;
  completed_at: string | null;
  download_expires_at: string | null;
}

/** POST finance/gst-exports body. Dates are `YYYY-MM-DD`; the range is at most 366 days. */
export interface GstExportBody {
  period_from: string;
  period_to: string;
  reason?: string;
}

/** Above this many rows an export waits for a super_admin approval (a different person). */
export const GST_EXPORT_APPROVAL_ROWS = 10_000;
export const GST_EXPORT_MAX_DAYS = 366;

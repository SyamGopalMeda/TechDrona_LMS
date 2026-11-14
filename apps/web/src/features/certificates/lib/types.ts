/** Admin certificates API (apps/api/app/modules/learning/cert_admin.py). */

export type OutboxStatus = "awaiting" | "pending" | "sent" | "failed" | "cancelled";

export interface OutboxInfo {
  id: string;
  status: OutboxStatus;
  origin: string;
  attempts: number;
  last_error: string | null;
  approved_at: string | null;
  sent_at: string | null;
  cancelled_at: string | null;
  created_at: string | null;
}

export interface AdminCertificate {
  id: string;
  public_code: string;
  user_id: string;
  name_on_certificate: string;
  email: string | null;
  course_id: string;
  course_title: string | null;
  enrolment_id: string;
  issue_source: string;
  issued_at: string;
  status: "valid" | "revoked";
  revoked_at: string | null;
  revoke_reason: string | null;
  pdf_available: boolean;
  content_sha256: string | null;
  template_version: string;
  verify_url: string;
  email_status: OutboxStatus | null;
  outbox: OutboxInfo | null;
}

/** What an outbox row emails: a course certificate or an issued document (learning_0006). */
export interface OutboxItem {
  kind: "certificate" | "document";
  id: string;
  name: string | null;
  email: string | null;
  title: string | null;
  label: string;
  number: string;
}

export interface OutboxRow extends OutboxInfo {
  /** null for issued-document rows */
  certificate: AdminCertificate | null;
  /** normalised summary (older API builds may omit it: derive from `certificate`) */
  item?: OutboxItem | null;
}

export function outboxItem(r: OutboxRow): OutboxItem | null {
  if (r.item) return r.item;
  const c = r.certificate;
  return c ? { kind: "certificate", id: c.id, name: c.name_on_certificate, email: c.email, title: c.course_title, label: "Course certificate", number: c.public_code } : null;
}

export interface DueRow {
  enrolment_id: string;
  user_id: string;
  name: string | null;
  email: string | null;
  course_id: string;
  course_title: string | null;
  batch_id: string | null;
  batch_name: string | null;
  batch_ends_on: string | null;
  enrolment_status: string;
  progress_pct: number;
  completed_at: string | null;
  due_because: "completed" | "batch_ended";
  eligible: boolean;
  reason: string | null;
}

export interface CertSummary {
  issued: number;
  valid: number;
  revoked: number;
  without_pdf: number;
  due: number;
  due_eligible: number;
  outbox: Record<OutboxStatus, number>;
  auto_send: boolean;
  /** issued documents (letters + other certificates) by status */
  documents?: Record<"valid" | "revoked" | "superseded", number>;
}

export interface CursorPage<T> {
  data: T[];
  page: { next_cursor: string | null; has_more: boolean; limit: number };
  counts?: Record<string, number>;
}

export interface IssueDueResult {
  issued: number;
  certificate_ids: string[];
  skipped: { enrolment_id: string; reason: string | null }[];
}

export interface ApproveResult {
  approved: number;
  sent: number;
  failed: number;
  pending: number;
  skipped: { id: string; reason: string }[];
}

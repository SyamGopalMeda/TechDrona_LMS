/** Support ticket DTOs (app/modules/support, SUP-01..15). */

export const TICKET_CATEGORIES = ["account_access", "device_reset", "billing", "refund", "content", "assessment", "technical", "grievance", "privacy_request", "certificate", "appeal", "other"] as const;
export type TicketCategory = (typeof TICKET_CATEGORIES)[number];

/**
 * Desk-only categories: `corporate_enquiry` tickets come from the public `/enquiries` form
 * (owner decision D8, backend WS5). Learners never pick it.
 */
export const DESK_CATEGORIES = [...TICKET_CATEGORIES, "corporate_enquiry"] as const;

export const TICKET_STATUSES = ["open", "pending_user", "pending_internal", "resolved", "closed"] as const;
export type TicketStatus = (typeof TICKET_STATUSES)[number];

export const TICKET_PRIORITIES = ["low", "normal", "high", "urgent"] as const;
export type TicketPriority = (typeof TICKET_PRIORITIES)[number];

export const CATEGORY_LABELS: Record<TicketCategory, string> = {
  account_access: "Signing in / account access",
  device_reset: "Device limit or device reset",
  billing: "Billing and payments",
  refund: "Refund",
  content: "Course content",
  assessment: "Tests and assessments",
  technical: "Technical problem",
  grievance: "Grievance / complaint",
  privacy_request: "Privacy request",
  certificate: "Certificates",
  appeal: "Appeal a test decision",
  other: "Something else",
};

export const STATUS_LABELS: Record<TicketStatus, string> = {
  open: "Open",
  pending_user: "Waiting for you",
  pending_internal: "With our team",
  resolved: "Resolved",
  closed: "Closed",
};

/** Attachment metadata on tickets and messages (filename, type and size only; BE-17). */
export interface AttachmentMeta {
  filename: string | null;
  content_type: string | null;
  size_bytes: number | null;
}

/** MED-02 `support_attachment` limits (apps/api media/router.py, support/router.py). */
export const SUPPORT_ATTACHMENT_TYPES = ["application/pdf", "image/png", "image/jpeg", "image/webp", "text/plain"] as const;
export const SUPPORT_ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024;
export const SUPPORT_ATTACHMENT_MAX_COUNT = 5;

/**
 * `?topic=` from deep links (e.g. the appeal flow's `topic=assessment&attempt_id=`) → SUP-01
 * `category`. Unknown topics leave the picker empty.
 */
export function topicToCategory(topic: string | undefined): TicketCategory | "" {
  return topic && (TICKET_CATEGORIES as readonly string[]).includes(topic) ? (topic as TicketCategory) : "";
}

export function ticketAttachmentPath(ticketId: string, ref: string, index: number): string {
  return `support/tickets/${encodeURIComponent(ticketId)}/attachments/${encodeURIComponent(ref)}/${index}`;
}

export interface Ticket {
  ticket_id: string;
  ticket_number: string;
  requester_id: string;
  category: TicketCategory;
  subject: string;
  body: string;
  status: TicketStatus;
  priority: TicketPriority;
  assigned_to: string | null;
  is_grievance: boolean;
  escalated_to: string | null;
  merged_into_id: string | null;
  related_order_id: string | null;
  related_case_id: string | null;
  related_unblock_request_id: string | null;
  /** Appeal of a test attempt (SUP-01 `related_attempt_id`). */
  related_attempt_id?: string | null;
  /** Files sent with SUP-01; download with `ticketAttachmentPath(id, "ticket", i)`. */
  attachments?: AttachmentMeta[];
  first_response_due_at: string | null;
  resolution_due_at: string | null;
  first_responded_at: string | null;
  resolved_at: string | null;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
  sla: { first_response_breached: boolean; resolution_breached: boolean };
  csat_score: number | null;
  message_count: number;
  requester?: { user_id: string; display_name: string | null; email_masked: string | null };
}

export interface TicketMessage {
  message_id: string;
  author_kind: "requester" | "agent" | "system";
  author_id: string | null;
  visibility: "public" | "internal";
  body: string;
  attachments?: AttachmentMeta[];
  created_at: string;
}

export interface TicketThread extends Ticket {
  messages: TicketMessage[];
  viewer: "requester" | "agent";
}

export interface Macro {
  macro_id: string;
  title: string;
  body: string;
  category: string | null;
}

export interface SupportUserNote {
  note_id: string;
  body: string;
  author_id: string | null;
  ticket_id: string | null;
  created_at: string;
}

export interface SupportUserSummary {
  user_id: string;
  display_name: string | null;
  email_masked: string | null;
  phone_masked: string | null;
  status: string;
  privacy_tier: string | null;
  is_minor: boolean;
  email_verified: boolean;
  phone_verified: boolean;
  created_at: string | null;
  last_login_at: string | null;
  mfa_enrolled: boolean;
  restriction: { level: number; reason_text: string | null; since: string | null } | null;
  devices: { trusted_count: number; total: number };
  active_sessions: { session_id: string; device_label: string | null; approx_region: string | null; ip_masked: string | null; last_active_at: string | null }[];
  entitlements: { entitlement_id: string; kind: string; status: string; ends_at: string | null }[];
  recent_orders: { order_number: string; status: string; total_paise: number; created_at: string }[];
  notes: SupportUserNote[];
  tickets: { ticket_id: string; ticket_number: string; subject: string; status: string; created_at: string }[];
}

export const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

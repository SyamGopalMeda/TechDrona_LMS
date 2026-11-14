/**
 * DTOs for SEC-01 and UNB-*. Request bodies come from the backend's Pydantic models via
 * `@/lib/api-types`; response interfaces below were verified against the backend code (the
 * backend returns plain dicts, so OpenAPI has no response schema for them).
 */
import type { Schema } from "@/lib/api-types";

export type UnblockCreateBody = Schema<"UnblockIn">;
export type UnblockTextBody = Schema<"TextIn">;

/** verified: app/modules/security/api_student.py my_status */
export interface SecurityStatus {
  level: number;
  /** "sharing" when a sharing restriction is active, else null. */
  family?: string | null;
  scope?: string | null;
  starts_at?: string | null;
  until?: string | null;
  deferred_until?: string | null;
  lift_pending?: boolean;
  case_ref?: string | null;
  reasons?: { explanation_key: string; text: string }[];
  categories?: string[];
  /** reverify | request_review | manage_devices | contact_support */
  available_actions?: string[];
  takeover?: { protect_locked: boolean; step_up_required: boolean; since: string | null };
  unblock_request?: { reference: string | null; state: string | null };
  policy?: { max_trusted_devices?: number; max_concurrent_sessions?: number; max_concurrent_streams?: number; max_replacements_per_30d?: number };
  history?: { level: number; starts_at: string; ended_at?: string | null; end_reason?: string | null }[];
}

/** verified: app/modules/security/unblock.py request_out */
export interface UnblockSummary {
  request_id: string;
  reference: string;
  case_ref: string | null;
  state: string;
  state_label?: string;
  closure_reason?: string | null;
  submitted_at?: string | null;
  is_second_level_appeal?: boolean;
  version?: number;
}

export interface UnblockSla {
  first_response_due?: string | null;
  decision_due?: string | null;
}

/** verified: app/modules/security/unblock.py submit (create with `submit: true`) */
export interface UnblockCreated extends UnblockSummary {
  devices_revoked?: { user_device_id: string; label: string | null }[];
  sla?: UnblockSla;
  acknowledgement_sent_via?: string[];
}

/** verified: app/modules/security/unblock.py student_view (GET by id and by-reference) */
export interface UnblockDetail extends UnblockSummary {
  timeline: {
    at: string;
    state: string;
    question_template?: string;
    message?: string;
    closure_reason?: string;
    appeal_deadline?: string;
  }[];
  info_requested_due?: string | null;
  decision?: { outcome: string; summary?: string | null; decided_at?: string; appeal_deadline?: string | null } | null;
  appeal?: { allowed: boolean; deadline: string | null } | null;
  grievance_route?: string | null;
}

/** verified: app/modules/security/cases.py student_projection (SEC-02 `GET /me/security/cases/{case_ref}`) */
export interface MyCase {
  case_ref: string;
  family: string;
  level: number;
  status: string;
  restriction: { level: number; until: string | null; state: "active" | "lift_pending" | string } | null;
  notes: { at: string; body: string }[];
  decision: { outcome: string; summary: string | null; decided_at: string } | null;
}

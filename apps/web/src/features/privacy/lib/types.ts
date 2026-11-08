/**
 * PRV-01..05 (`/me/privacy-requests*`). Request bodies come from the backend's Pydantic models;
 * responses are verified against app/modules/admin/privacy.py `request_out` (plain dicts).
 */
import type { Schema } from "@/lib/api-types";

export type PrivacyCreateBody = Schema<"PrivacyIn">;
export type PrivacyRequestType = PrivacyCreateBody["request_type"];

export interface PrivacyRequest {
  request_id: string;
  request_ref: string;
  request_type: PrivacyRequestType | (string & {});
  /** received | identity_verification | in_progress | awaiting_requester | cooling_off | completed | rejected | withdrawn */
  status: string;
  received_at: string;
  due_at: string;
  cooling_off_until: string | null;
  completed_at: string | null;
  response_summary: string | null;
  export_available: boolean;
  /** erasure only */
  retained_by_law?: string[];
}

export interface PrivacyListResponse {
  data: PrivacyRequest[];
}

/** verified: admin/privacy.py OPEN_STATES */
export const OPEN_STATES = ["received", "identity_verification", "in_progress", "awaiting_requester", "cooling_off"];

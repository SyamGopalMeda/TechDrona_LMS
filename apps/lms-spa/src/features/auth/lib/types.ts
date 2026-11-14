/**
 * DTOs for AUTH-* responses. Request bodies come from the backend's Pydantic models via
 * `@/lib/api-types`; response interfaces below were verified against the router code (the
 * backend returns plain dicts, so OpenAPI has no response schema for them).
 */
import type { Schema } from "@/lib/api-types";

export type SignupBody = Schema<"SignupIn">;
export type GuardianBody = Schema<"GuardianIn">;
export type LoginBody = Schema<"LoginIn">;
export type MfaVerifyBody = Schema<"MfaVerifyIn">;
export type DeviceVerifyBody = Schema<"DeviceVerifyIn">;
export type SessionChoiceBody = Schema<"SessionChoiceIn">;
export type GuardianDecisionBody = Schema<"GuardianDecisionIn">;

/** verified: app/modules/sessions/login.py session_summary */
export interface SessionSummary {
  id?: string;
  status?: string;
  tier?: string;
  scope?: "full" | "restricted" | "status_only" | string;
  aal?: number;
  created_via?: string;
  auth_time?: string | null;
  idle_expires_at?: string;
  absolute_expires_at?: string;
}

/** verified: app/modules/sessions/login.py advance (level >= 3 only) */
export interface RestrictionSummary {
  level: number;
  case_ref?: string | null;
  until?: string | null;
}

/** verified: app/modules/sessions/login.py device_channels */
export interface DeviceChannel {
  channel: "sms" | "email" | string;
  destination_masked: string;
}

/**
 * verified: app/modules/sessions/login.py advance — the 200 body of AUTH-06 login, AUTH-11
 * mfa/verify, AUTH-13 device-verification/verify and AUTH-14 session-choice. `cancelled` is only
 * returned by session-choice `{cancel: true}`.
 */
export type LoginResponse =
  | { result: "authenticated"; session?: SessionSummary; restriction?: RestrictionSummary; redirect?: string; must_change_password?: boolean }
  | { result: "mfa_required"; methods: string[] }
  | { result: "device_verification_required"; channels: DeviceChannel[]; alternatives?: string[]; reason?: string }
  | { result: "cancelled" };

/** verified: `409 session_cap_reached` problem `sessions[]` (app/modules/sessions/login.py advance) */
export interface CapSession {
  session_id: string;
  device_label: string;
  approx_region?: string | null;
  last_active_at?: string | null;
  has_active_attempt?: boolean;
}

/** verified: `409 device_cap_reached` problem `devices[]` (app/modules/sessions/login.py _device_cap_problem) */
export interface CapDevice {
  user_device_id: string;
  label: string | null;
  user_label?: string | null;
  last_used_at?: string | null;
}

/** verified: app/modules/identity/router.py signup */
export interface SignupResponse {
  user_id: string;
  status: string;
  is_minor: boolean;
  next_steps: string[];
  session?: SessionSummary | null;
}

/**
 * verified: app/modules/identity/router.py device_verification_send, mobile_send_otp,
 * guardian_verify_contact (`sent_to` only), resend_verification (`status` + `sent_to`).
 */
export interface OtpSentResponse {
  sent_to?: string | null;
  expires_in_seconds?: number;
  status?: string;
}

/** verified: app/modules/identity/router.py guardian_view */
export interface GuardianConsentView {
  child_first_name: string;
  /** GuardianConsent.status: pending | verified | rejected */
  status: "pending" | "verified" | "rejected" | string;
  relationship: "parent" | "legal_guardian" | string;
  notice_version: string;
  items: { purpose: string; item: string; required: boolean }[];
  unavailable_for_minors: string[];
  contact_masked: string | null;
}

/** verified: app/modules/identity/router.py guardian_decision */
export interface GuardianDecisionResponse {
  status: "verified" | "rejected" | string;
  child_status: string;
}

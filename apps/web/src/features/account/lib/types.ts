/**
 * DTOs for ME-* / SES-*. Request bodies come from the backend's Pydantic models via
 * `@/lib/api-types`; response interfaces below were verified against the router code (the
 * backend returns plain dicts, so OpenAPI has no response schema for them).
 */
import type { Schema } from "@/lib/api-types";

export type ProfilePatchBody = Schema<"ProfilePatchIn">;
export type ConsentChangeBody = Schema<"ConsentChangeIn">;
export type ChangePasswordBody = Schema<"ChangePasswordIn">;
export type DeviceRenameBody = Schema<"RenameIn">;

/** verified: app/modules/identity/router.py me */
export interface Me {
  user: {
    id: string;
    email?: string | null;
    email_verified?: boolean;
    mobile_masked?: string | null;
    mobile_verified?: boolean;
    status?: string;
    is_minor?: boolean;
    privacy_tier?: string;
    locale?: string;
  };
  profile?: {
    full_name?: string | null;
    display_name?: string | null;
    graduation_year?: number | null;
    branch?: string | null;
    legal_name_locked?: boolean;
  };
  session?: {
    id?: string;
    status?: string;
    tier?: string;
    scope?: string;
    aal?: number;
    remember_device?: boolean;
    last_step_up_at?: string | null;
    idle_expires_at?: string;
    absolute_expires_at?: string;
  };
  /** Only the level is returned (no scope / case_ref / until; see SEC-01 for those). */
  restriction?: { level: number };
  mfa?: { level: string };
  portals?: string[];
}

/** verified: app/modules/sessions/router.py _session_out */
export interface OwnSession {
  session_id: string;
  is_current: boolean;
  status: string;
  device_label: string;
  device_class?: string | null;
  approx_region?: string | null;
  ip?: string | null;
  auth_method?: string;
  tier?: string;
  login_at?: string | null;
  last_active_at?: string | null;
  logout_at?: string | null;
  duration_seconds?: number | null;
  end_reason?: string | null;
}

/** verified: app/modules/sessions/router.py my_sessions */
export interface SessionsResponse {
  data: OwnSession[];
  page: { next_cursor: string | null; has_more: boolean; limit: number };
}

/** verified: app/modules/sessions/router.py _devices_payload */
export interface OwnDevice {
  user_device_id: string;
  /** Device.label_hint — may be null. */
  label: string | null;
  user_label?: string | null;
  client_type?: string | null;
  device_class?: string | null;
  /** trusted | pending_otp (removed devices are not listed). */
  trust_status: string;
  counts_toward_cap?: boolean;
  first_seen_at?: string | null;
  last_used_at?: string | null;
  /** Always null today. */
  approx_region?: string | null;
  is_current?: boolean;
  group_hint?: string | null;
}

/** verified: app/modules/sessions/service.py device_limits */
export interface DeviceLimits {
  max_trusted: number;
  trusted_counted: number;
  replacements_used_30d: number;
  replacements_max_30d: number;
  next_replacement_at?: string | null;
  inactivity_expiry_days?: number;
}

/** verified: app/modules/sessions/router.py _devices_payload */
export interface DevicesResponse {
  data: OwnDevice[];
  limits?: DeviceLimits;
  page?: { next_cursor: string | null; has_more: boolean; limit: number };
}

/** Display name for a device: the user's own label, else the detected label. */
export function deviceName(d: Pick<OwnDevice, "label" | "user_label">): string {
  return d.user_label || d.label || "Unnamed device";
}

/** verified: app/modules/identity/router.py _factor_out */
export interface MfaFactor {
  factor_id: string;
  type: string; // totp | recovery_codes
  label?: string | null;
  confirmed: boolean;
  created_at?: string | null;
  last_used_at?: string | null;
  /** recovery_codes only. */
  remaining_codes?: number | null;
}

/** verified: app/modules/identity/router.py totp_begin */
export interface TotpEnrolment {
  factor_id: string;
  otpauth_uri: string;
  secret: string;
}

/** verified: app/modules/identity/router.py get_consents (one row per purpose) */
export interface ConsentState {
  purpose: string;
  state: "granted" | "withdrawn" | "not_granted" | string;
  notice_version?: string | null;
  effective_at?: string | null;
  /** false for adult-only purposes on under-18 accounts. */
  available?: boolean;
}

/** verified: app/modules/identity/router.py get_consents */
export interface ConsentsResponse {
  data: ConsentState[];
  notice_version: string;
}

/** verified: app/modules/sessions/router.py device_policy */
export interface DevicePolicy {
  devices?: { max_trusted?: number; max_replacements_per_30d?: number; trusted_inactivity_expiry_days?: number };
  sessions?: { max_concurrent?: number; at_limit_behavior?: string; idle_minutes?: number; absolute_hours?: number; remember_device_max_days?: number };
  streams?: { max_concurrent?: number };
  attempts?: { max_rebinds_per_attempt?: number };
}

/** verified: app/modules/sessions/router.py login_history (90 days, ≤ 200 attempts) */
export interface LoginHistory {
  attempts: { at: string; method: string; mfa_method: string | null; result: string; ip: string | null }[];
  ended_sessions: OwnSession[];
}

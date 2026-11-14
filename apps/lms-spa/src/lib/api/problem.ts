/**
 * RFC 9457 problem details as used by the Tech Drona API (api-specification §1.13, §2).
 * Shared by the BFF (server) and the browser API client.
 */

export interface ValidationErrorItem {
  field: string;
  code: string;
  message: string;
}

export interface StepUpChallenge {
  max_age_seconds: number;
  allowed_methods: string[];
  options_url: string;
}

export interface ProblemDetails {
  type: string;
  title: string;
  status: number;
  detail: string;
  code: string;
  request_id: string;
  errors?: ValidationErrorItem[];
  /** step_up_required */
  step_up?: StepUpChallenge;
  /** account_restricted */
  case_ref?: string;
  level?: number;
  until?: string;
  status_url?: string;
  /** login_incomplete */
  next_step?: "mfa" | "device_verification" | "session_choice";
  /** playback_conflict */
  other_device_label?: string;
  other_playback_session_id?: string;
  takeover_allowed?: boolean;
  /** session_expired / session_revoked */
  reason?: string;
  /** Unknown extension members are tolerated (api-specification §1.12). */
  [extension: string]: unknown;
}

export function isProblemDetails(value: unknown): value is ProblemDetails {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return typeof v.code === "string" && typeof v.status === "number" && typeof v.title === "string";
}

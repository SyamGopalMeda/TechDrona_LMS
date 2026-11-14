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

export const PROBLEM_CONTENT_TYPE = "application/problem+json";

export function problemType(code: string): string {
  return `https://techdrona.in/problems/${code.replace(/_/g, "-")}`;
}

export function isProblemDetails(value: unknown): value is ProblemDetails {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return typeof v.code === "string" && typeof v.status === "number" && typeof v.title === "string";
}

/** Build a problem+json Response (used by the BFF for its own refusals). */
export function problemResponse(
  status: number,
  code: string,
  title: string,
  detail: string,
  requestId: string,
  extensions: Record<string, unknown> = {},
  headers: Record<string, string> = {},
): Response {
  const body: ProblemDetails = {
    type: problemType(code),
    title,
    status,
    detail,
    code,
    request_id: requestId,
    ...extensions,
  };
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": PROBLEM_CONTENT_TYPE,
      "cache-control": "no-store",
      "x-request-id": requestId,
      ...headers,
    },
  });
}

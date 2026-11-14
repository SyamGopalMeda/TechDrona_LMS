import { ApiError } from "@/lib/api/errors";

/** User-safe error summary for inline display (title/detail come from problem+json; §1.13). */
export interface FormErrorInfo {
  title: string;
  detail?: string;
  requestId: string | null;
  code: string;
}

export function toFormError(err: unknown, fallbackTitle = "Something went wrong"): FormErrorInfo {
  if (err instanceof ApiError) {
    return { title: err.title, detail: err.detail, requestId: err.requestId, code: err.code };
  }
  return { title: fallbackTitle, detail: "Please try again.", requestId: null, code: "unknown_error" };
}

/** problem+json `errors[]` → { field: message } (first message per field wins). */
export function problemFieldErrors(err: unknown): Record<string, string> {
  if (!(err instanceof ApiError)) return {};
  const out: Record<string, string> = {};
  for (const e of err.problem?.errors ?? []) if (!(e.field in out)) out[e.field] = e.message;
  return out;
}

/**
 * Seconds to wait for `throttled` / `otp_send_limited` / `rate_limited`. The API sends the wait
 * as a `Retry-After` header (exposed as `ApiError.retryAfter`); a numeric `retry_after` /
 * `retry_after_seconds` problem extension wins when present (FE-09).
 */
export function retryAfterSeconds(err: unknown): number | null {
  if (!(err instanceof ApiError)) return null;
  const candidates: unknown[] = [err.problem?.retry_after_seconds, err.problem?.retry_after, err.retryAfter];
  for (const v of candidates) {
    const n = typeof v === "number" ? v : typeof v === "string" ? Number.parseInt(v, 10) : NaN;
    if (Number.isFinite(n) && n > 0) return Math.min(Math.round(n), 24 * 3600);
  }
  return null;
}

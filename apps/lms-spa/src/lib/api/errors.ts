import type { ProblemDetails } from "./problem";

/**
 * Parse an HTTP `Retry-After` header (RFC 9110 §10.2.3): delay-seconds or an HTTP-date.
 * Returns whole seconds (>= 0), or null when absent/unparseable.
 */
export function parseRetryAfter(value: string | null | undefined, now: number = Date.now()): number | null {
  if (value == null) return null;
  const v = value.trim();
  if (v === "") return null;
  if (/^\d+$/.test(v)) {
    const n = Number.parseInt(v, 10);
    return Number.isSafeInteger(n) ? n : null;
  }
  if (!/^[A-Za-z]/.test(v)) return null; // HTTP-dates start with a day name
  const at = Date.parse(v);
  if (Number.isNaN(at)) return null;
  return Math.max(0, Math.ceil((at - now) / 1000));
}

/** Thrown by the API client for every non-2xx response (and for network failures). */
export class ApiError extends Error {
  override name = "ApiError";
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly problem: ProblemDetails | null;
  /** Seconds to wait before retrying, from the `Retry-After` header (429/503), else null. */
  readonly retryAfter: number | null;

  constructor(
    status: number,
    problem: ProblemDetails | null,
    requestId: string | null,
    message?: string,
    retryAfter: number | null = null,
  ) {
    super(message ?? problem?.title ?? `Request failed (${status})`);
    this.status = status;
    this.problem = problem;
    this.code = problem?.code ?? (status === 0 ? "network_error" : "unknown_error");
    this.requestId = problem?.request_id ?? requestId;
    this.retryAfter = retryAfter;
  }

  /** User-safe title (problem `title` is safe to show, api-specification §1.13). */
  get title(): string {
    if (this.problem?.title) return this.problem.title;
    if (this.status === 0) return "You appear to be offline";
    return "Something went wrong";
  }

  get detail(): string {
    if (this.problem?.detail) return this.problem.detail;
    if (this.status === 0) return "Check your connection and try again.";
    return "Please try again. If the problem continues, contact support with the reference below.";
  }
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}

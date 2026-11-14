import { uuid7 } from "@/lib/ids/uuid7";
import { ApiError, parseRetryAfter } from "./errors";
import { isProblemDetails, type ProblemDetails, type StepUpChallenge } from "./problem";

/**
 * Browser API client for the same-origin BFF (/api/v1). Never sees tokens: the session
 * cookie is HttpOnly; only the CSRF double-submit token (td_csrf, readable) is echoed.
 *
 * Cross-cutting responses handled here (api-specification §1.6, §1.7, §2):
 *  - 401 step_up_required   → hooks.requestStepUp() opens the step-up dialog; on success the
 *                              original request is retried ONCE with the same Idempotency-Key.
 *  - 403 account_restricted → navigate to /account/restricted?case_ref=…&level=…
 *  - 401 unauthenticated / session_expired / session_revoked → /login?next=…&reason=…
 *  - 403 mfa_enrolment_required → enrol_url (default /app/settings/security/mfa)
 *  - 403 password_change_required → /change-password?next=<here> (admin asked for a new password)
 *  - 403 consent_required (terms / privacy notice / core service only) → /accept-terms?next=<here>
 *  - 401 login_incomplete   → the pending login step (/login/mfa, /login/verify-device, /login/session-choice)
 *  - 409 session_cap_reached (pending_session_choice) → hooks.onSessionChoiceRequired or /login/session-choice
 *  - 409 playback_conflict  → hooks.onPlaybackConflict (player shows PLY-005), then throws
 *  - 202 approval_pending   → returned as { kind: "approval_pending" } (not an error)
 *  - 403 csrf_failed        → CSRF cookie refreshed and the request retried once
 * Every failure throws ApiError carrying `requestId` for the error UI.
 */

export const API_BASE = "/api/v1";
const CSRF_COOKIE_NAMES = ["__Host-td_csrf", "td_csrf"] as const;
const CSRF_BOOTSTRAP = `${API_BASE}/_bff/csrf`;
const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export interface ApprovalPending {
  status: "approval_pending";
  approval_request_id: string;
  action_type: string;
  required_approver_role: string;
  expires_at: string;
}

export type ApiResult<T> =
  | { kind: "ok"; status: number; data: T; requestId: string | null; etag: string | null }
  | { kind: "approval_pending"; status: 202; approval: ApprovalPending; requestId: string | null };

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface RequestOptions {
  method?: HttpMethod;
  body?: unknown;
  query?: Record<string, string | number | boolean | null | undefined>;
  headers?: Record<string, string>;
  /** `true` generates a UUIDv7 key (reused across the automatic retries of this call). */
  idempotencyKey?: string | true;
  ifMatch?: string;
  signal?: AbortSignal;
  /** Opt out of global handling for screens that render these states inline (e.g. /login). */
  handle?: Partial<Record<"stepUp" | "restriction" | "auth" | "sessionChoice", boolean>>;
}

export interface ApiClientHooks {
  requestStepUp?: (challenge: StepUpChallenge, problem: ProblemDetails) => Promise<boolean>;
  navigate?: (href: string) => void;
  onPlaybackConflict?: (problem: ProblemDetails) => void;
  onSessionChoiceRequired?: (problem: ProblemDetails) => void;
  /** Override for tests. */
  fetchImpl?: typeof fetch;
  currentPath?: () => string;
}

let hooks: ApiClientHooks = {};

export function configureApiClient(next: ApiClientHooks): () => void {
  const previous = hooks;
  hooks = { ...hooks, ...next };
  return () => {
    hooks = previous;
  };
}

function doFetch(input: string, init: RequestInit): Promise<Response> {
  return (hooks.fetchImpl ?? globalThis.fetch)(input, init);
}

function navigate(href: string): void {
  if (hooks.navigate) hooks.navigate(href);
  else if (typeof window !== "undefined") window.location.assign(href);
}

function currentPath(): string {
  if (hooks.currentPath) return hooks.currentPath();
  if (typeof window === "undefined") return "/";
  return `${window.location.pathname}${window.location.search}`;
}

export function readCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const jar = new Map<string, string>();
  for (const part of document.cookie.split(";")) {
    const i = part.indexOf("=");
    if (i > 0) jar.set(part.slice(0, i).trim(), part.slice(i + 1).trim());
  }
  for (const name of CSRF_COOKIE_NAMES) {
    const v = jar.get(name);
    if (v) return v;
  }
  return null;
}

/** Ask the BFF to (re)issue td_csrf for the current session; returns the new token. */
export async function refreshCsrfToken(): Promise<string | null> {
  try {
    await doFetch(CSRF_BOOTSTRAP, { method: "GET", credentials: "same-origin", cache: "no-store" });
  } catch {
    return null;
  }
  return readCsrfToken();
}

export function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const clean = path.replace(/^\/+/, "").replace(/^api\/v1\//, "");
  const url = `${API_BASE}/${clean}`;
  if (!query) return url;
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null) qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `${url}?${s}` : url;
}

async function readProblem(res: Response): Promise<ProblemDetails | null> {
  const ct = res.headers.get("content-type") ?? "";
  if (!ct.includes("json")) return null;
  try {
    const body: unknown = await res.json();
    return isProblemDetails(body) ? body : null;
  } catch {
    return null;
  }
}

const LOGIN_STEP_PATH: Record<string, string> = {
  mfa: "/login/mfa",
  device_verification: "/login/verify-device",
  session_choice: "/login/session-choice",
};

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<ApiResult<T>> {
  return (await send<T>(path, options, false)) as ApiResult<T>;
}

/**
 * Like apiRequest, with the same CSRF, step-up, auth and problem handling, but returns the raw
 * `Response` of a successful call (file downloads such as CSV exports). Failures throw ApiError.
 */
export async function apiRequestRaw(path: string, options: RequestOptions = {}): Promise<Response> {
  return (await send<never>(path, options, true)) as Response;
}

/** Page where an account flagged "must change password" chooses its own password. */
export const CHANGE_PASSWORD_PATH = "/change-password";
/** Page where a signed-in account agrees to the required Terms / Privacy Notice (`consent_required`). */
export const ACCEPT_TERMS_PATH = "/accept-terms";
/** Purposes every account needs (resolver `consent_required`); other consent problems are handled where they occur. */
const REQUIRED_CONSENTS = new Set(["terms", "privacy_notice", "core_service"]);

/** `/<page>?next=<here>` unless already on that page (no loop); null when already there. */
function gatePath(page: string, here: string): string | null {
  if (here.split("?")[0] === page) return null;
  return here.startsWith("/") && !here.startsWith("//") && here !== "/" ? `${page}?next=${encodeURIComponent(here)}` : page;
}

/** A 403 `consent_required` that only names required purposes (not a checkout / exam consent). */
export function isRequiredConsentProblem(problem: { code?: string; purposes?: unknown } | null | undefined): boolean {
  if (problem?.code !== "consent_required") return false;
  const p = problem.purposes;
  return Array.isArray(p) && p.length > 0 && p.every((x) => typeof x === "string" && REQUIRED_CONSENTS.has(x));
}

const MFA_ENROL_FALLBACK = "/app/settings/security/mfa";

/** INV-10: same-origin enrolment page from the problem's `enrol_url`, else the default. */
export function mfaEnrolPath(enrolUrl: unknown): string {
  if (typeof enrolUrl !== "string" || !enrolUrl.startsWith("/") || enrolUrl.startsWith("//") || /[\u0000-\u001F\u007F\s\\]/.test(enrolUrl)) {
    return MFA_ENROL_FALLBACK;
  }
  if (enrolUrl === "/api" || enrolUrl.startsWith("/api/")) return MFA_ENROL_FALLBACK;
  return enrolUrl;
}

async function send<T>(path: string, options: RequestOptions, raw: boolean): Promise<ApiResult<T> | Response> {
  const method = options.method ?? "GET";
  const url = buildUrl(path, options.query);
  const idemKey = options.idempotencyKey === true ? uuid7() : options.idempotencyKey;
  const handle = { stepUp: true, restriction: true, auth: true, sessionChoice: true, ...options.handle };

  let csrfRetried = false;
  let stepUpRetried = false;

  for (;;) {
    const headers: Record<string, string> = { accept: raw ? "*/*" : "application/json", ...options.headers };
    if (options.body !== undefined) headers["content-type"] = "application/json";
    if (idemKey) headers["idempotency-key"] = idemKey;
    if (options.ifMatch) headers["if-match"] = options.ifMatch;
    if (UNSAFE.has(method)) {
      const token = readCsrfToken() ?? (await refreshCsrfToken());
      if (token) headers["x-csrf-token"] = token;
    }

    let res: Response;
    try {
      res = await doFetch(url, {
        method,
        headers,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
        credentials: "same-origin",
        cache: "no-store",
        signal: options.signal,
      });
    } catch (err) {
      if ((err as Error).name === "AbortError") throw err;
      throw new ApiError(0, null, null);
    }

    const requestId = res.headers.get("x-request-id");

    if (res.ok && raw) return res;
    if (res.ok) {
      if (res.status === 204 || res.status === 205) {
        return { kind: "ok", status: res.status, data: undefined as T, requestId, etag: res.headers.get("etag") };
      }
      const text = await res.text();
      const data: unknown = text ? JSON.parse(text) : undefined;
      if (res.status === 202 && data && typeof data === "object" && (data as { status?: unknown }).status === "approval_pending") {
        return { kind: "approval_pending", status: 202, approval: data as ApprovalPending, requestId };
      }
      return { kind: "ok", status: res.status, data: data as T, requestId, etag: res.headers.get("etag") };
    }

    const problem = await readProblem(res);
    const code = problem?.code;

    if (code === "csrf_failed" && !csrfRetried) {
      csrfRetried = true;
      await refreshCsrfToken();
      continue;
    }

    if (code === "step_up_required" && handle.stepUp && !stepUpRetried && problem?.step_up && hooks.requestStepUp) {
      stepUpRetried = true;
      const ok = await hooks.requestStepUp(problem.step_up, problem);
      if (ok) continue; // same Idempotency-Key (api-specification §1.6)
    }

    if (code === "account_restricted" && handle.restriction) {
      const qs = new URLSearchParams();
      if (problem?.case_ref) qs.set("case_ref", problem.case_ref);
      if (problem?.level !== undefined) qs.set("level", String(problem.level));
      if (problem?.until) qs.set("until", problem.until);
      navigate(`/account/restricted${qs.size ? `?${qs.toString()}` : ""}`);
    }

    if ((code === "unauthenticated" || code === "session_expired" || code === "session_revoked") && handle.auth) {
      // A session evicted by the device cap gets its own message ("signed in on another device").
      const evicted = code === "session_revoked" && (problem as { reason?: unknown } | null)?.reason === "session_cap_evicted";
      const qs = new URLSearchParams({ next: currentPath(), reason: evicted ? "session_cap_evicted" : code });
      navigate(`/login?${qs.toString()}`);
    }

    if (code === "mfa_enrolment_required" && handle.auth) {
      const target = mfaEnrolPath(problem?.enrol_url);
      const here = currentPath().split("?")[0];
      if (here !== target.split("?")[0]) navigate(target);
    }

    if (code === "password_change_required" && handle.auth) {
      const target = gatePath(CHANGE_PASSWORD_PATH, currentPath());
      if (target) navigate(target);
    }

    if (res.status === 403 && handle.auth && isRequiredConsentProblem(problem)) {
      const target = gatePath(ACCEPT_TERMS_PATH, currentPath());
      if (target) navigate(target);
    }

    if (code === "login_incomplete" && handle.auth && problem?.next_step) {
      const target = LOGIN_STEP_PATH[problem.next_step];
      if (target) navigate(target);
    }

    if (code === "session_cap_reached" && handle.sessionChoice && problem) {
      if (hooks.onSessionChoiceRequired) hooks.onSessionChoiceRequired(problem);
      else navigate("/login/session-choice");
    }

    if (code === "playback_conflict" && problem) hooks.onPlaybackConflict?.(problem);

    throw new ApiError(res.status, problem, requestId, undefined, parseRetryAfter(res.headers.get("retry-after")));
  }
}

function okData<T>(result: ApiResult<T>): T {
  if (result.kind !== "ok") {
    throw new Error("Unexpected approval_pending response for a read request");
  }
  return result.data;
}

export const api = {
  get: async <T>(path: string, options: Omit<RequestOptions, "method" | "body"> = {}): Promise<T> =>
    okData(await apiRequest<T>(path, { ...options, method: "GET" })),
  post: <T>(path: string, body?: unknown, options: Omit<RequestOptions, "method" | "body"> = {}) =>
    apiRequest<T>(path, { ...options, method: "POST", body }),
  put: <T>(path: string, body?: unknown, options: Omit<RequestOptions, "method" | "body"> = {}) =>
    apiRequest<T>(path, { ...options, method: "PUT", body }),
  patch: <T>(path: string, body?: unknown, options: Omit<RequestOptions, "method" | "body"> = {}) =>
    apiRequest<T>(path, { ...options, method: "PATCH", body }),
  delete: <T>(path: string, options: Omit<RequestOptions, "method" | "body"> = {}) =>
    apiRequest<T>(path, { ...options, method: "DELETE" }),
};

/** Cursor-paginated list envelope (api-specification §1.10). */
export interface Page<T> {
  data: T[];
  page: { next_cursor: string | null; has_more: boolean; limit: number };
  counts?: Record<string, number>;
}

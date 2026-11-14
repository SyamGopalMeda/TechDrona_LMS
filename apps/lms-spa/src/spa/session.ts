/**
 * Session presence in the browser, from the API function's `GET /api/v1/_bff/session`
 * (functions-lms/lms_edge/app.py `_session_probe`, contract `200 {"session": bool,
 * "refreshed": bool}`, same-origin only). It does what the Next page middleware did on a page load:
 *
 * - remember-device re-issue (AUTH-28): no session cookie but a remember cookie → the function
 *   re-authenticates and sets the new session cookies on this response (`refreshed: true`);
 * - `td_csrf` issue / refresh (readable cookie for the browser client's X-CSRF-Token);
 * - and it answers whether a session cookie is present, which replaces `hasSessionCookie()`
 *   (the cookie is HttpOnly and packed into `__session` on Hosting).
 *
 * States: `session: true` → "yes", `false` → "no"; network error / non-200 / non-JSON →
 * "unknown" (public chrome shows signed-out, portal shells render and let the API's own 401
 * handling apply, as before when the cookie was present but the API was down).
 *
 * Called once at app start (src/spa/main.tsx) and again when a layout or ex-server page asks after
 * the memo expired: "yes" is memoised for 60 s, anything else for 3 s, and entering or leaving the
 * auth pages drops the memo (sign-in and sign-out change the answer).
 */
import { apiRequest } from "@/lib/api/client";

export type SessionState = "yes" | "no" | "unknown";

export const SESSION_PROBE_PATH = "_bff/session";
const NO_HANDLE = { stepUp: false, restriction: false, auth: false, sessionChoice: false } as const;
const YES_TTL_MS = 60_000;
const OTHER_TTL_MS = 3_000;

let memo: { p: Promise<SessionState>; at: number; value?: SessionState } | null = null;

/**
 * Identity-change signals for src/lib/api/session-cache.ts (the cached `me` / `me/grants` /
 * `me/modules`): no session, a re-issued session (remember-device), or entering / leaving the auth
 * pages (sign-in, sign-out, password change). Listeners must not throw.
 */
type SessionResetListener = (reason: "signed-out" | "reissued" | "auth-page") => void;
const resetListeners = new Set<SessionResetListener>();
export function onSessionReset(fn: SessionResetListener): () => void {
  resetListeners.add(fn);
  return () => resetListeners.delete(fn);
}
function emitReset(reason: Parameters<SessionResetListener>[0]): void {
  for (const fn of resetListeners) fn(reason);
}

async function callProbe(): Promise<SessionState> {
  try {
    const res = await apiRequest<{ session?: unknown; refreshed?: unknown }>(SESSION_PROBE_PATH, { method: "GET", handle: NO_HANDLE });
    if (res.kind !== "ok" || res.status !== 200 || !res.data || typeof res.data.session !== "boolean") return "unknown";
    if (!res.data.session) emitReset("signed-out");
    else if (res.data.refreshed === true) emitReset("reissued");
    return res.data.session ? "yes" : "no";
  } catch {
    return "unknown";
  }
}

export function probeSession(): Promise<SessionState> {
  const now = Date.now();
  if (memo) {
    if (memo.value === undefined) return memo.p;
    const ttl = memo.value === "yes" ? YES_TTL_MS : OTHER_TTL_MS;
    if (now - memo.at < ttl) return memo.p;
  }
  const p = callProbe();
  const entry: { p: Promise<SessionState>; at: number; value?: SessionState } = { p, at: now };
  memo = entry;
  void p.then((v) => {
    entry.value = v;
    entry.at = Date.now();
  });
  return p;
}

/** App start: the probe, bounded so a hung API never blocks the first render for long. */
export function bootstrapSession(timeoutMs = 8_000): Promise<SessionState> {
  return Promise.race([probeSession(), new Promise<SessionState>((resolve) => setTimeout(() => resolve("unknown"), timeoutMs))]);
}

export function invalidateSession(): void {
  memo = null;
}

const AUTH_PAGES = /^\/(login|signup|change-password|accept-terms|reset-password|account\/restricted)(\/|$)/;

/** Called on every location change (src/spa/runtime.tsx). */
export function onPathChange(prev: string | null, next: string): void {
  if ((prev && AUTH_PAGES.test(prev)) || AUTH_PAGES.test(next)) {
    invalidateSession();
    // Entering an auth page: sign-in / sign-out / password change follow. (Leaving one after
    // signing in needs nothing more: the auth/* POST already reset the identity cache.)
    if (AUTH_PAGES.test(next)) emitReset("auth-page");
  } else if (memo?.value && memo.value !== "yes") invalidateSession();
}

/**
 * The LMS host's `/` (Caddy on the VM, by session cookie): signed out → `/login`, signed in →
 * `/modules`. Used for a document load of `/` (src/spa/main.tsx) and by the `/` page itself
 * (app/(public)/page.tsx) for client-side links to `/`. Returns the target, or null to stay.
 */
export function homeRedirect(pathname: string, state: SessionState): string | null {
  if (pathname !== "/") return null;
  return state === "yes" ? "/modules" : "/login";
}

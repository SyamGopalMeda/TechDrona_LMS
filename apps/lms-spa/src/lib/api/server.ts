/**
 * SPA override of apps/web/src/lib/api/server.ts. The ex-server pages keep calling
 * `serverApiGet()` / `hasSessionCookie()`; in the browser they go through the same-origin BFF
 * (`/api/v1/**`, Firebase Hosting rewrite to the API function) with the browser client.
 *
 * Behaviour kept from the server version:
 * - GET only, errors THROW (no global redirects: the client's auth / restriction / step-up /
 *   session-choice handling is switched off, the page decides, exactly as before);
 * - network failures and non-JSON answers surface as non-ApiErrors / 503 like a failed fetch;
 * - `navigation: true` sends `x-td-activity: navigation` (the BFF set it for page loads; the API
 *   function must accept it from the browser for the idle timer).
 */
import { apiRequest } from "./client";
import { ApiError } from "./errors";
import { probeSession } from "@/spa/session";

const NO_HANDLE = { stepUp: false, restriction: false, auth: false, sessionChoice: false } as const;

export async function serverApiGet<T>(path: string, init: { navigation?: boolean; revalidate?: false } = {}): Promise<T> {
  // buildUrl() keeps a `?query` already in the path (no `query` option passed).
  const clean = path.replace(/^\/+/, "");
  let result;
  try {
    result = await apiRequest<T>(clean, {
      method: "GET",
      handle: NO_HANDLE,
      headers: init.navigation ? { "x-td-activity": "navigation" } : undefined,
    });
  } catch (err) {
    if (err instanceof ApiError && err.status === 0) throw new ApiError(503, null, null);
    throw err;
  }
  if (result.kind !== "ok") throw new ApiError(502, null, result.requestId);
  return result.data;
}

/** Session presence (UX gating only; the api decides). One `GET /me` probe, memoised briefly. */
export async function hasSessionCookie(): Promise<boolean> {
  return (await probeSession()) === "yes";
}

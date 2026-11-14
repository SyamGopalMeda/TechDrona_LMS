import "server-only";
import { createHash, timingSafeEqual } from "node:crypto";
import type { Me } from "@/features/account/lib/types";
import { canEnterPortal, type MyGrantsPortals } from "@/features/staff-portal/access";
import { isApiError } from "@/lib/api/errors";
import { serverApiGet } from "@/lib/api/server";
import { cookieName, loadBffConfig, type BffConfig } from "@/lib/bff/config";
import { parseCookieHeader } from "@/lib/bff/cookies";
import { HOP_BY_HOP_RESPONSE_HEADERS, resolveClientIp } from "@/lib/bff/headers";

/**
 * Same-origin proxy for the College Data Portal (a separate first-party app):
 * browser → web (/college-portal/*) → portal (TD_COLLEGE_PORTAL_URL).
 *
 * - Every request (HTML, assets, API) is authenticated against the LMS session and limited to
 *   Admin-portal users (`GET /me/grants`). Failures FAIL CLOSED (503), unlike StaffPortalGate.
 * - The LMS session never reaches the portal: request headers are an allow-list, and the
 *   proxy identifies the user with `x-td-proxy-user` + the shared `x-td-proxy-secret`.
 * - The portal's own CSP passes through (middleware skips /college-portal/); X-Frame-Options is
 *   SAMEORIGIN from next.config.ts (config headers win over route-handler headers).
 * - The auth cache is keyed on session + device cookie + user agent, so a replayed session with a
 *   different device/UA always reaches the api (which revokes it, TO-04/TO-08). Writes and page
 *   loads bypass the cache and mark activity, so working in the portal keeps the LMS session alive.
 */

export const PORTAL_PREFIX = "/college-portal";
export const PORTAL_ENTRY = `${PORTAL_PREFIX}/index.html`;
export const ADMIN_PAGE = "/admin/college-data";
export const MAX_BODY_BYTES = 1024 * 1024;
const DEV_DEFAULT_URL = "http://127.0.0.1:4173";
const UPSTREAM_TIMEOUT_MS = 15_000;
const AUTH_CACHE_TTL_MS = 60_000;
const AUTH_CACHE_MAX = 500;

const ALLOWED_METHODS = new Set(["GET", "HEAD", "POST", "PATCH", "PUT", "DELETE"]);
const UNSAFE_METHODS = new Set(["POST", "PATCH", "PUT", "DELETE"]);

/** Browser headers that may reach the portal. Cookie, Authorization, X-CSRF-Token, X-TD-* never do. */
export const FORWARDED_PORTAL_HEADERS = ["accept", "content-type", "idempotency-key", "if-modified-since", "if-none-match", "user-agent"] as const;

/** Response headers never passed back to the browser (on top of the BFF hop-by-hop set). */
const DROPPED_RESPONSE_HEADERS = new Set([...HOP_BY_HOP_RESPONSE_HEADERS, "set-cookie", "content-encoding", "content-length", "server"]);

export interface CollegePortalDeps {
  env?: NodeJS.ProcessEnv;
  fetchImpl?: typeof fetch;
  config?: BffConfig;
  /** Defaults to `serverApiGet` (reads the session from the current request's cookies). */
  apiGet?: ApiGet;
  now?: () => number;
}

interface PortalTarget {
  base: string;
  secret: string;
}

type ApiGet = <T>(path: string, init?: { navigation?: boolean }) => Promise<T>;

type AuthResult = { kind: "ok"; name: string } | { kind: "unauthenticated" } | { kind: "forbidden" } | { kind: "unavailable" };

// ---------------------------------------------------------------------------------------------
// Auth cache: SHA-256(session) → display name, 60 s. Positive results only.

const authCache = new Map<string, { name: string; expires: number }>();
const inFlight = new Map<string, Promise<AuthResult>>();

/** Test helper. */
export function resetCollegePortalAuthCache(): void {
  authCache.clear();
  inFlight.clear();
}

function cacheGet(key: string, now: number): string | null {
  const hit = authCache.get(key);
  if (!hit) return null;
  if (hit.expires <= now) {
    authCache.delete(key);
    return null;
  }
  return hit.name;
}

function cacheSet(key: string, name: string, now: number): void {
  authCache.delete(key);
  while (authCache.size >= AUTH_CACHE_MAX) {
    const oldest = authCache.keys().next().value;
    if (oldest === undefined) break;
    authCache.delete(oldest);
  }
  authCache.set(key, { name, expires: now + AUTH_CACHE_TTL_MS });
}

/**
 * Actor recorded in the portal's audit log: "Name (email)". Display names are neither unique nor
 * fixed, the email is. At most 100 characters (the portal's limit).
 */
export function displayNameOf(me: Me | null | undefined): string {
  const pick = (v: string | null | undefined) => (typeof v === "string" && v.trim() ? v.trim().replace(/\s+/g, " ") : null);
  const name = pick(me?.profile?.display_name) ?? pick(me?.profile?.full_name);
  const email = pick(me?.user?.email);
  if (name && email && name.toLowerCase() !== email.toLowerCase()) {
    const suffix = ` (${email})`;
    return suffix.length < 60 ? `${name.slice(0, 100 - suffix.length).trim()}${suffix}` : name.slice(0, 100);
  }
  return (name ?? email ?? "LMS admin").slice(0, 100);
}

async function checkAccess(apiGet: ApiGet, activity: boolean): Promise<AuthResult> {
  // `navigation: true` extends the LMS idle timer (x-td-activity), like a page view in the LMS.
  const [grants, me] = await Promise.allSettled([apiGet<MyGrantsPortals>("me/grants", { navigation: activity }), apiGet<Me>("me")]);
  if (grants.status === "rejected") {
    return isApiError(grants.reason) && grants.reason.status === 401 ? { kind: "unauthenticated" } : { kind: "unavailable" };
  }
  const roleKeys = grants.value?.data?.map((g) => g.role_key);
  if (!canEnterPortal(grants.value?.portals, "admin", roleKeys)) return { kind: "forbidden" };
  if (me.status === "rejected") {
    return isApiError(me.reason) && me.reason.status === 401 ? { kind: "unauthenticated" } : { kind: "unavailable" };
  }
  return { kind: "ok", name: displayNameOf(me.value) };
}

/** Cache key: the session is only reused with the same device cookie and user agent. */
function authKey(session: string, device: string, userAgent: string): string {
  return createHash("sha256").update(`${session}\0${device}\0${userAgent}`).digest("hex");
}

async function authorize(key: string, apiGet: ApiGet, now: number, activity: boolean): Promise<AuthResult> {
  if (!activity) {
    const cached = cacheGet(key, now);
    if (cached !== null) return { kind: "ok", name: cached };
    // Concurrent asset requests on first load share one grants lookup.
    const shared = inFlight.get(key);
    if (shared) return shared;
  }
  const pending: Promise<AuthResult> = checkAccess(apiGet, activity).finally(() => {
    if (inFlight.get(key) === pending) inFlight.delete(key);
  });
  if (!activity) inFlight.set(key, pending);
  const result = await pending;
  if (result.kind === "ok") cacheSet(key, result.name, now);
  return result;
}

// ---------------------------------------------------------------------------------------------
// Helpers

/** Upstream base URL + shared secret, or null when the portal is not configured. */
export function portalTarget(env: NodeJS.ProcessEnv): PortalTarget | null {
  const prod = env.NODE_ENV === "production";
  const raw = (env.TD_COLLEGE_PORTAL_URL ?? "").trim() || (prod ? "" : DEV_DEFAULT_URL);
  const secret = (env.TD_COLLEGE_PORTAL_SECRET ?? "").trim();
  // Always required: without it the portal runs standalone (own passcode, frame-ancestors 'none').
  if (!raw || secret.length < 32) return null;
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return null;
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") return null;
  return { base: `${url.origin}${url.pathname}`.replace(/\/+$/, ""), secret };
}

type PathCheck = { kind: "entry" } | { kind: "ok"; rest: string } | { kind: "bad" } | { kind: "not_found" };

/** Path after /college-portal (still percent-encoded), rejecting traversal, backslashes and NUL. */
export function extractPortalPath(pathname: string): PathCheck {
  if (pathname === PORTAL_PREFIX || pathname === `${PORTAL_PREFIX}/`) return { kind: "entry" };
  if (!pathname.startsWith(`${PORTAL_PREFIX}/`)) return { kind: "not_found" };
  const rest = pathname.slice(PORTAL_PREFIX.length);
  if (rest.length > 2048 || /[\\\0]/.test(rest)) return { kind: "bad" };
  const segments = rest.slice(1).split("/");
  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i]!;
    let decoded: string;
    try {
      decoded = decodeURIComponent(seg);
    } catch {
      return { kind: "bad" };
    }
    if (decoded === "" && i < segments.length - 1) return { kind: "bad" }; // "//"
    if (decoded === "." || decoded === ".." || /[/\\\0]/.test(decoded)) return { kind: "bad" };
  }
  return { kind: "ok", rest };
}

function isNavigation(request: Request): boolean {
  const method = request.method.toUpperCase();
  if (method !== "GET" && method !== "HEAD") return false;
  const dest = request.headers.get("sec-fetch-dest");
  if (dest) return dest === "document" || dest === "iframe";
  return (request.headers.get("accept") ?? "").includes("text/html");
}

function json(status: number, body: Record<string, unknown>, extra: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store", "x-content-type-options": "nosniff", ...extra },
  });
}

const escapeHtml = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

function htmlPage(status: number, title: string, message: string, link = { href: "/admin", label: "Back to the LMS" }): Response {
  const body = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escapeHtml(title)}</title><style>body{font-family:system-ui,sans-serif;margin:0;padding:2rem;color:#1f2937}h1{font-size:1.25rem}a{color:#1d4ed8}</style></head><body><h1>${escapeHtml(title)}</h1><p>${escapeHtml(message)}</p><p><a href="${escapeHtml(link.href)}" target="_top">${escapeHtml(link.label)}</a></p></body></html>`;
  return new Response(body, {
    status,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "x-frame-options": "SAMEORIGIN",
      "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'",
    },
  });
}

function redirect(status: 303 | 308, location: string): Response {
  return new Response(null, { status, headers: { location, "cache-control": "no-store" } });
}

const LOGIN_URL = `/login?next=${encodeURIComponent(ADMIN_PAGE)}`;

function unauthenticated(request: Request): Response {
  // Inside the admin page's frame a redirect would load /login (frame-ancestors 'none') into the
  // frame and show a blocked page: answer in the frame with a link that leaves it.
  if (request.headers.get("sec-fetch-dest") === "iframe") {
    return htmlPage(401, "Signed out", "Your LMS session has ended. Sign in again to open the College Data Portal.", { href: LOGIN_URL, label: "Sign in" });
  }
  if (isNavigation(request)) return redirect(303, LOGIN_URL);
  return json(401, { error: "Please sign in to the LMS again", code: "auth_required" });
}

function forbidden(request: Request): Response {
  if (isNavigation(request)) return htmlPage(403, "Admins only", "The College Data Portal is available to LMS admins only.");
  return json(403, { error: "Admins only", code: "forbidden" });
}

function unavailable(request: Request): Response {
  if (isNavigation(request)) return htmlPage(503, "College Data Portal", "We could not verify your access right now. Please try again shortly.");
  return json(503, { error: "Could not verify your access. Please try again.", code: "auth_unavailable" }, { "retry-after": "5" });
}

function constantTimeEqual(a: string, b: string): boolean {
  const x = Buffer.from(a);
  const y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
}

/** Map an upstream redirect back under /college-portal (never to another origin). */
function rewriteLocation(location: string, base: string): string | null {
  const baseUrl = new URL(`${base}/`);
  let target: URL;
  try {
    target = new URL(location, baseUrl);
  } catch {
    return null;
  }
  if (target.origin !== baseUrl.origin) return null;
  const basePath = baseUrl.pathname.replace(/\/+$/, "");
  let path = target.pathname;
  if (basePath && path.startsWith(`${basePath}/`)) path = path.slice(basePath.length);
  if (!path.startsWith(`${PORTAL_PREFIX}/`)) path = `${PORTAL_PREFIX}${path}`;
  return `${path}${target.search}${target.hash}`;
}

// ---------------------------------------------------------------------------------------------

export async function handleCollegePortalRequest(request: Request, deps: CollegePortalDeps = {}): Promise<Response> {
  const env = deps.env ?? process.env;
  const fetchImpl = deps.fetchImpl ?? fetch;
  const apiGet = deps.apiGet ?? serverApiGet;
  const now = (deps.now ?? Date.now)();
  const method = request.method.toUpperCase();

  if (!ALLOWED_METHODS.has(method)) return json(405, { error: "Method not allowed" }, { allow: [...ALLOWED_METHODS].join(", ") });

  const url = new URL(request.url);
  const path = extractPortalPath(url.pathname);
  if (path.kind === "not_found") return json(404, { error: "Not found" });
  if (path.kind === "bad") return json(400, { error: "Invalid path", code: "bad_path" });
  if (path.kind === "entry") return redirect(308, PORTAL_ENTRY);

  const target = portalTarget(env);
  if (!target) return json(503, { error: "College Data Portal is not configured" });

  let config: BffConfig;
  try {
    config = deps.config ?? loadBffConfig(env);
  } catch (err) {
    console.error(`[college-portal] LMS configuration error: ${(err as Error).message}`);
    return json(503, { error: "College Data Portal is not configured" });
  }

  if (config.originVerifyValue && !constantTimeEqual(request.headers.get("x-origin-verify") ?? "", config.originVerifyValue)) {
    return json(403, { error: "Forbidden", code: "forbidden" });
  }

  // Cross-site request forgery: unsafe methods only from our own pages (same rule as the BFF).
  if (UNSAFE_METHODS.has(method)) {
    const fetchSite = request.headers.get("sec-fetch-site");
    const origin = request.headers.get("origin");
    if ((fetchSite !== null && fetchSite !== "same-origin" && fetchSite !== "none") || (origin !== null && origin !== config.publicOrigin)) {
      return json(403, { error: "Request blocked", code: "cross_origin" });
    }
  }

  // AuthN / AuthZ on every request.
  const cookies = parseCookieHeader(request.headers.get("cookie"));
  const session = cookies.get(cookieName("session", env));
  if (!session) return unauthenticated(request);
  const key = authKey(session, cookies.get(cookieName("device", env)) ?? "", request.headers.get("user-agent") ?? "");
  const auth = await authorize(key, apiGet, now, UNSAFE_METHODS.has(method) || isNavigation(request));
  if (auth.kind === "unauthenticated") return unauthenticated(request);
  if (auth.kind === "forbidden") return forbidden(request);
  if (auth.kind === "unavailable") return unavailable(request);

  let body: ArrayBuffer | undefined;
  if (method !== "GET" && method !== "HEAD") {
    const declared = Number.parseInt(request.headers.get("content-length") ?? "", 10);
    if (Number.isFinite(declared) && declared > MAX_BODY_BYTES) return json(413, { error: "Request too large", code: "payload_too_large" });
    const buf = await request.arrayBuffer();
    if (buf.byteLength > MAX_BODY_BYTES) return json(413, { error: "Request too large", code: "payload_too_large" });
    if (buf.byteLength > 0) body = buf;
  }

  const upstreamHeaders = new Headers();
  for (const name of FORWARDED_PORTAL_HEADERS) {
    const value = request.headers.get(name);
    if (value !== null) upstreamHeaders.set(name, value);
  }
  upstreamHeaders.set("accept-encoding", "identity");
  if (target.secret) upstreamHeaders.set("x-td-proxy-secret", target.secret);
  upstreamHeaders.set("x-td-proxy-user", encodeURIComponent(auth.name));
  // Everyone admitted holds the Admin portal (super admin): full edit rights in the portal.
  upstreamHeaders.set("x-td-proxy-role", "editor");
  const clientIp = resolveClientIp(request.headers, config.trustedProxyHops);
  if (clientIp) upstreamHeaders.set("x-forwarded-for", clientIp);
  const publicUrl = new URL(config.publicOrigin);
  upstreamHeaders.set("x-forwarded-proto", publicUrl.protocol.replace(":", ""));
  upstreamHeaders.set("x-forwarded-host", publicUrl.host);

  // The timeout covers the response headers only; a slow body keeps streaming (client abort still applies).
  const timeout = new AbortController();
  const timer = setTimeout(() => timeout.abort(new DOMException("upstream timeout", "TimeoutError")), UPSTREAM_TIMEOUT_MS);
  let upstream: Response;
  try {
    upstream = await fetchImpl(`${target.base}${path.rest}${url.search}`, {
      method,
      headers: upstreamHeaders,
      body,
      redirect: "manual",
      signal: AbortSignal.any([request.signal, timeout.signal]),
      cache: "no-store",
    });
  } catch (err) {
    console.error(`[college-portal] upstream ${(err as Error).name} ${method} ${PORTAL_PREFIX}${path.rest}`);
    return json(502, { error: "College Data Portal is unavailable" }, { "retry-after": "5" });
  } finally {
    clearTimeout(timer);
  }
  // The portal answers 401 only when the shared secret is wrong (proxy_required). That is a server
  // misconfiguration, not an LMS sign-out: never let the SPA send the admin to /login for it.
  if (upstream.status === 401) {
    void upstream.body?.cancel();
    console.error("[college-portal] upstream refused the proxy secret (check TD_COLLEGE_PORTAL_SECRET / PORTAL_PROXY_SECRET)");
    return json(502, { error: "College Data Portal is misconfigured", code: "portal_misconfigured" });
  }

  const headers = new Headers();
  upstream.headers.forEach((value, name) => {
    if (!DROPPED_RESPONSE_HEADERS.has(name.toLowerCase())) headers.set(name, value);
  });
  const location = upstream.headers.get("location");
  if (location !== null) {
    const rewritten = rewriteLocation(location, target.base);
    if (rewritten) headers.set("location", rewritten);
    else headers.delete("location");
  }
  const contentType = (upstream.headers.get("content-type") ?? "").toLowerCase();
  const upstreamCache = (upstream.headers.get("cache-control") ?? "").toLowerCase();
  const sensitive = path.rest.startsWith("/api/") || path.rest === "/api" || contentType.startsWith("text/html") || /\.html?$/i.test(path.rest);
  headers.set("cache-control", sensitive || upstreamCache.includes("no-store") ? "private, no-store" : "private, no-cache");
  headers.set("x-content-type-options", "nosniff");
  if (!headers.has("x-frame-options")) headers.set("x-frame-options", "SAMEORIGIN");

  const noBody = method === "HEAD" || upstream.status === 204 || upstream.status === 304;
  return new Response(noBody ? null : upstream.body, { status: upstream.status, statusText: upstream.statusText, headers });
}

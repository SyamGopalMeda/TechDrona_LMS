import { problemResponse } from "@/lib/api/problem";
import { uuid7 } from "@/lib/ids/uuid7";
import { cookieName, loadBffConfig, upstreamCookieName, type BffConfig } from "./config";
import { cookieKindFromName, parseCookieHeader, parseSetCookie, serializeCookie } from "./cookies";
import { checkDoubleSubmit, constantTimeEqual, mintCsrfToken, verifyCsrfToken } from "./csrf";
import { HOP_BY_HOP_RESPONSE_HEADERS, newTraceparent, pickForwardedHeaders, resolveClientIp } from "./headers";

/**
 * Same-origin BFF proxy: browser → web (/api/v1/*) → api (TD_API_INTERNAL_URL).
 * ADR-0010; api-specification §1.1–§1.3. Pure function of (Request, deps) for testing.
 */

export const API_PREFIX = "/api/v1/";
const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const ALLOWED_METHODS = new Set(["GET", "HEAD", ...UNSAFE_METHODS]);
const DEFAULT_MAX_BODY = 256 * 1024;
const SMALL_MAX_BODY = 64 * 1024;
export const BEACON_PATH = "analytics/events/beacon";
export const CSRF_BOOTSTRAP_PATH = "_bff/csrf";
/** Problem codes meaning the presented session is over (api-specification §1.4 steps 1–5). */
const ENDED_SESSION_CODES = new Set(["unauthenticated", "session_expired", "session_revoked"]);

export interface ProxyDeps {
  config?: BffConfig;
  fetchImpl?: typeof fetch;
  env?: NodeJS.ProcessEnv;
}

type PathCheck = { ok: true; path: string } | { ok: false };

/** Raw (still percent-encoded) path after /api/v1/, rejecting traversal and encoded separators. */
export function extractApiPath(pathname: string): PathCheck {
  if (!pathname.startsWith(API_PREFIX)) return { ok: false };
  const raw = pathname.slice(API_PREFIX.length);
  if (!raw || raw.length > 1024) return { ok: false };
  const segments = raw.split("/");
  for (const seg of segments) {
    let decoded: string;
    try {
      decoded = decodeURIComponent(seg);
    } catch {
      return { ok: false };
    }
    if (decoded === "" || decoded === "." || decoded === ".." || /[/\\\0]/.test(decoded)) return { ok: false };
  }
  return { ok: true, path: raw };
}

function maxBodyFor(path: string): number {
  return path.startsWith("analytics/") ? SMALL_MAX_BODY : DEFAULT_MAX_BODY;
}

function isJsonContentType(ct: string | null): boolean {
  if (!ct) return false;
  const base = ct.split(";")[0]?.trim().toLowerCase() ?? "";
  return base === "application/json" || (base.startsWith("application/") && base.endsWith("+json"));
}

function isPrefetch(headers: Headers): boolean {
  const purpose = `${headers.get("sec-purpose") ?? ""} ${headers.get("purpose") ?? ""}`.toLowerCase();
  return purpose.includes("prefetch") || headers.get("next-router-prefetch") === "1";
}

interface CsrfCookieOpts {
  config: BffConfig;
  env: NodeJS.ProcessEnv;
}

function csrfCookie(token: string, { config, env }: CsrfCookieOpts): string {
  // Not HttpOnly: the client reads it to echo it in X-CSRF-Token (double submit).
  return serializeCookie(cookieName("csrf", env), token, config.cookieMode, { httpOnly: false, sameSite: "Strict" });
}

/** GET /api/v1/_bff/csrf — (re)issue the CSRF cookie for the current session. Never proxied. */
function csrfBootstrap(request: Request, config: BffConfig, env: NodeJS.ProcessEnv, requestId: string): Response {
  const cookies = parseCookieHeader(request.headers.get("cookie"));
  const session = cookies.get(cookieName("session", env));
  const existing = cookies.get(cookieName("csrf", env));
  const headers = new Headers({ "cache-control": "no-store", "x-request-id": requestId });
  if (!existing || !verifyCsrfToken(config.csrfKeys.slice(0, 1), existing, session)) {
    headers.append("set-cookie", csrfCookie(mintCsrfToken(config.csrfKeys[0]!, session), { config, env }));
  }
  return new Response(null, { status: 204, headers });
}

export async function handleBffRequest(request: Request, deps: ProxyDeps = {}): Promise<Response> {
  const requestId = uuid7();
  const env = deps.env ?? process.env;
  const fetchImpl = deps.fetchImpl ?? fetch;
  const method = request.method.toUpperCase();

  let config: BffConfig;
  try {
    config = deps.config ?? loadBffConfig(env);
  } catch (err) {
    console.error(`[bff] configuration error request_id=${requestId}: ${(err as Error).message}`);
    return problemResponse(503, "service_unavailable", "Service unavailable", "The service is temporarily unavailable.", requestId, {}, { "retry-after": "30" });
  }

  // Defence in depth: CloudFront → ALB origin-verify secret (enforced at the ALB in AWS).
  if (config.originVerifyValue) {
    const presented = request.headers.get("x-origin-verify") ?? "";
    if (!constantTimeEqual(presented, config.originVerifyValue)) {
      return problemResponse(403, "permission_denied", "Forbidden", "Request did not arrive through the edge.", requestId);
    }
  }

  const url = new URL(request.url);
  const pathCheck = extractApiPath(url.pathname);
  if (!pathCheck.ok) return notFound(requestId);
  const path = pathCheck.path;

  // Webhooks never go through the BFF: the ALB routes /api/v1/webhooks/* to api-webhooks
  // (HMAC-authenticated, no cookies, no CSRF). Reaching here means misrouting → 404.
  if (path === "webhooks" || path.startsWith("webhooks/")) return notFound(requestId);
  // AUTH-28 is BFF-internal (service token); browsers may not call it.
  if (path === "auth/remember/refresh") return notFound(requestId);
  if (path === CSRF_BOOTSTRAP_PATH) {
    if (method !== "GET") return methodNotAllowed(requestId, "GET");
    return csrfBootstrap(request, config, env, requestId);
  }
  if (path.startsWith("_")) return notFound(requestId); // reserved BFF-local namespace (e.g. _errors: not yet implemented)

  if (!ALLOWED_METHODS.has(method)) return methodNotAllowed(requestId, [...ALLOWED_METHODS].join(", "));

  const cookies = parseCookieHeader(request.headers.get("cookie"));
  const session = cookies.get(cookieName("session", env));
  const device = cookies.get(cookieName("device", env));
  const csrfFromCookie = cookies.get(cookieName("csrf", env));

  let body: ArrayBuffer | string | undefined;
  let upstreamContentType: string | null = request.headers.get("content-type");

  if (UNSAFE_METHODS.has(method)) {
    const isBeacon = method === "POST" && path === BEACON_PATH;
    const fetchSite = request.headers.get("sec-fetch-site");

    // 1. Fetch Metadata (fallback: Origin).
    if (isBeacon) {
      if (fetchSite !== "same-origin") return csrfFailed(requestId);
    } else if (fetchSite !== null) {
      if (fetchSite !== "same-origin" && fetchSite !== "none") return csrfFailed(requestId);
    } else {
      const origin = request.headers.get("origin");
      if (origin !== null && origin !== config.publicOrigin) return csrfFailed(requestId);
    }

    // 2. Body size + media type (JSON only; beacons may be text/plain).
    const limit = maxBodyFor(path);
    const declared = Number.parseInt(request.headers.get("content-length") ?? "", 10);
    if (Number.isFinite(declared) && declared > limit) return payloadTooLarge(requestId, limit);
    const buf = await request.arrayBuffer();
    if (buf.byteLength > limit) return payloadTooLarge(requestId, limit);
    if (buf.byteLength > 0) {
      const ct = request.headers.get("content-type");
      const textPlain = (ct ?? "").toLowerCase().startsWith("text/plain");
      if (!isJsonContentType(ct) && !(isBeacon && textPlain)) {
        return problemResponse(415, "unsupported_media_type", "Unsupported media type", "Send JSON.", requestId, {
          allowed: ["application/json"],
        });
      }
      body = buf;
    }

    // 3. Signed double-submit token.
    if (isBeacon) {
      let parsed: Record<string, unknown>;
      try {
        parsed = JSON.parse(new TextDecoder().decode(buf)) as Record<string, unknown>;
      } catch {
        return problemResponse(400, "validation_failed", "Invalid request", "Body is not valid JSON.", requestId, { errors: [] });
      }
      const token = typeof parsed.csrf === "string" ? parsed.csrf : undefined;
      if (!checkDoubleSubmit(config.csrfKeys, csrfFromCookie, token, session)) return csrfFailed(requestId);
      // The api never holds TD_CSRF_KEY and does not need the token.
      delete parsed.csrf;
      body = JSON.stringify(parsed);
      upstreamContentType = "application/json";
    } else if (!checkDoubleSubmit(config.csrfKeys, csrfFromCookie, request.headers.get("x-csrf-token"), session)) {
      return csrfFailed(requestId);
    }
  }

  // Upstream request headers (allow-list + BFF-owned headers).
  const upstreamHeaders = pickForwardedHeaders(request.headers);
  if (upstreamContentType) upstreamHeaders.set("content-type", upstreamContentType);
  upstreamHeaders.set("accept-encoding", "identity");
  if (config.serviceToken) upstreamHeaders.set("authorization", `Service ${config.serviceToken}`);
  const upstreamCookies: string[] = [];
  if (session) {
    upstreamHeaders.set("x-td-session", session);
    upstreamCookies.push(`${upstreamCookieName("session")}=${session}`);
  }
  if (device) {
    upstreamHeaders.set("x-td-device", device);
    upstreamCookies.push(`${upstreamCookieName("device")}=${device}`);
  }
  if (upstreamCookies.length) upstreamHeaders.set("cookie", upstreamCookies.join("; "));
  const clientIp = resolveClientIp(request.headers, config.trustedProxyHops);
  if (clientIp) {
    upstreamHeaders.set("x-td-client-ip", clientIp);
    upstreamHeaders.set("x-forwarded-for", clientIp);
  }
  const publicUrl = new URL(config.publicOrigin);
  upstreamHeaders.set("x-forwarded-proto", publicUrl.protocol.replace(":", ""));
  upstreamHeaders.set("x-forwarded-host", publicUrl.host);
  upstreamHeaders.set("x-request-id", requestId);
  upstreamHeaders.set("traceparent", newTraceparent());
  if (
    method === "GET" &&
    request.headers.get("sec-fetch-mode") === "navigate" &&
    !isPrefetch(request.headers)
  ) {
    upstreamHeaders.set("x-td-activity", "navigation");
  }

  const isStream = (request.headers.get("accept") ?? "").includes("text/event-stream");
  const signals: AbortSignal[] = [request.signal];
  if (!isStream) signals.push(AbortSignal.timeout(config.proxyTimeoutMs));

  let upstream: Response;
  try {
    upstream = await fetchImpl(`${config.apiInternalUrl}${API_PREFIX}${path}${url.search}`, {
      method,
      headers: upstreamHeaders,
      body: method === "GET" || method === "HEAD" ? undefined : body,
      redirect: "manual",
      signal: AbortSignal.any(signals),
      cache: "no-store",
    });
  } catch (err) {
    const name = (err as Error).name;
    console.error(`[bff] upstream ${name} request_id=${requestId} ${method} /api/v1/${path}`);
    return problemResponse(503, "service_unavailable", "Service unavailable", "We could not reach the service. Please try again.", requestId, {}, { "retry-after": "5" });
  }

  // Response headers.
  const headers = new Headers();
  upstream.headers.forEach((value, name) => {
    if (!HOP_BY_HOP_RESPONSE_HEADERS.has(name.toLowerCase())) headers.set(name, value);
  });
  if (!headers.has("x-request-id")) headers.set("x-request-id", requestId);
  if (!headers.has("cache-control")) headers.set("cache-control", "no-store");

  // Cookies from the api are re-issued under the BFF's names and attributes.
  let sessionAfter: string | undefined = session;
  let sessionChanged = false;
  for (const raw of upstream.headers.getSetCookie()) {
    const parsed = parseSetCookie(raw);
    if (!parsed) continue;
    const kind = cookieKindFromName(parsed.name);
    if (!kind || kind === "csrf") continue; // only the BFF mints td_csrf; unknown cookies are dropped
    headers.append(
      "set-cookie",
      serializeCookie(cookieName(kind, env), parsed.value, config.cookieMode, {
        httpOnly: true,
        sameSite: "Lax",
        maxAge: parsed.maxAge,
        expires: parsed.expires,
      }),
    );
    if (kind === "session") {
      sessionChanged = true;
      const cleared = parsed.value === "" || (parsed.maxAge !== undefined && parsed.maxAge <= 0);
      sessionAfter = cleared ? undefined : parsed.value;
    }
  }
  // A session the api reports as ended is cleared in the browser too, so the next top-level
  // navigation can use the remember-device re-issue (AUTH-28, SEC-07) or go to /login.
  let bufferedBody: string | undefined;
  if (upstream.status === 401 && session && !sessionChanged) {
    bufferedBody = await upstream.text();
    let code: unknown;
    try {
      code = (JSON.parse(bufferedBody) as { code?: unknown } | null)?.code;
    } catch {
      code = undefined;
    }
    if (typeof code === "string" && ENDED_SESSION_CODES.has(code)) {
      headers.append(
        "set-cookie",
        serializeCookie(cookieName("session", env), "", config.cookieMode, { httpOnly: true, sameSite: "Lax", maxAge: 0 }),
      );
      sessionChanged = true;
      sessionAfter = undefined;
    }
  }
  // Mint td_csrf whenever the session is set/rotated/cleared, or self-heal a missing/stale one
  // (including tokens still signed with TD_CSRF_KEY_PREVIOUS, so rotation converges).
  if (sessionChanged || !csrfFromCookie || !verifyCsrfToken(config.csrfKeys.slice(0, 1), csrfFromCookie, sessionAfter)) {
    headers.append("set-cookie", csrfCookie(mintCsrfToken(config.csrfKeys[0]!, sessionAfter), { config, env }));
  }

  const noBody = method === "HEAD" || upstream.status === 204 || upstream.status === 304;
  if (bufferedBody !== undefined) headers.delete("content-length");
  return new Response(noBody ? null : (bufferedBody ?? upstream.body), {
    status: upstream.status,
    statusText: upstream.statusText,
    headers,
  });
}

function notFound(requestId: string): Response {
  return problemResponse(404, "not_found", "Not found", "The requested resource was not found.", requestId);
}

function methodNotAllowed(requestId: string, allow: string): Response {
  return problemResponse(405, "method_not_allowed", "Method not allowed", "This method is not supported here.", requestId, {}, { allow });
}

function csrfFailed(requestId: string): Response {
  return problemResponse(403, "csrf_failed", "Request blocked", "Your request could not be verified. Refresh the page and try again.", requestId);
}

function payloadTooLarge(requestId: string, limit: number): Response {
  return problemResponse(413, "payload_too_large", "Request too large", "The request body is too large.", requestId, { max_bytes: limit });
}

import "server-only";
import { cookies, headers } from "next/headers";
import { cookieName, loadBffConfig, upstreamCookieName } from "@/lib/bff/config";
import { newTraceparent, resolveClientIp } from "@/lib/bff/headers";
import { uuid7 } from "@/lib/ids/uuid7";
import { ApiError, parseRetryAfter } from "./errors";
import { isProblemDetails } from "./problem";

/**
 * Server-component data access: calls the internal api directly over the private network
 * (ADR-0010 "Server components call api directly"), with the same BFF-owned headers as the
 * proxy. GET only — mutations go through the browser → BFF path so CSRF applies.
 *
 * Only return explicit DTO fields to client components (threat model: no raw API objects
 * in RSC payloads).
 */
export async function serverApiGet<T>(path: string, init: { navigation?: boolean; revalidate?: false } = {}): Promise<T> {
  const config = loadBffConfig();
  const jar = await cookies();
  const incoming = await headers();
  const requestId = uuid7();

  const h = new Headers({ accept: "application/json", "x-request-id": requestId, traceparent: newTraceparent() });
  if (config.serviceToken) h.set("authorization", `Service ${config.serviceToken}`);
  const session = jar.get(cookieName("session"))?.value;
  const device = jar.get(cookieName("device"))?.value;
  const cookieParts: string[] = [];
  if (session) {
    h.set("x-td-session", session);
    cookieParts.push(`${upstreamCookieName("session")}=${session}`);
  }
  if (device) {
    h.set("x-td-device", device);
    cookieParts.push(`${upstreamCookieName("device")}=${device}`);
  }
  if (cookieParts.length) h.set("cookie", cookieParts.join("; "));
  const ua = incoming.get("user-agent");
  if (ua) h.set("user-agent", ua);
  const ip = resolveClientIp(incoming, config.trustedProxyHops);
  if (ip) h.set("x-td-client-ip", ip);
  // Only a real page navigation (not a prefetch) may extend the idle timer.
  if (init.navigation && !incoming.get("next-router-prefetch")) h.set("x-td-activity", "navigation");

  const clean = path.replace(/^\/+/, "");
  const res = await fetch(`${config.apiInternalUrl}/api/v1/${clean}`, {
    headers: h,
    cache: "no-store",
    signal: AbortSignal.timeout(config.proxyTimeoutMs),
  });
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      body = null;
    }
    throw new ApiError(
      res.status,
      isProblemDetails(body) ? body : null,
      res.headers.get("x-request-id") ?? requestId,
      undefined,
      parseRetryAfter(res.headers.get("retry-after")),
    );
  }
  return (await res.json()) as T;
}

/** Session cookie presence (UX gating only; the api decides). */
export async function hasSessionCookie(): Promise<boolean> {
  const jar = await cookies();
  return Boolean(jar.get(cookieName("session"))?.value);
}

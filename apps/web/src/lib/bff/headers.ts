/**
 * Header policy for the BFF hop (ADR-0010, api-specification §1.2).
 *
 * Request side is an ALLOW-list: only these browser headers reach the api. Everything
 * else — hop-by-hop headers, Cookie, Authorization, X-Forwarded-*, X-TD-*, X-Request-Id,
 * traceparent, X-CSRF-Token — is dropped and, where needed, re-created by the BFF.
 */
export const FORWARDED_REQUEST_HEADERS = [
  "accept",
  "accept-language",
  "content-type",
  "idempotency-key",
  "if-match",
  "if-none-match",
  "if-modified-since",
  "last-event-id",
  "user-agent",
  // Client hints feed ua_family / os_family drift checks (TO-08).
  "sec-ch-ua",
  "sec-ch-ua-mobile",
  "sec-ch-ua-platform",
] as const;

/** Response headers never passed back to the browser. */
export const HOP_BY_HOP_RESPONSE_HEADERS = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  // fetch() already decoded the body; length/encoding no longer match.
  "content-encoding",
  "content-length",
  // Cookies are rewritten by the BFF (see proxy.ts).
  "set-cookie",
  "server",
  "x-powered-by",
]);

export function pickForwardedHeaders(source: Headers): Headers {
  const out = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = source.get(name);
    if (value !== null) out.set(name, value);
  }
  return out;
}

const IP_PATTERN = /^[0-9a-fA-F:.]{2,45}$/;

/**
 * Client IP as seen by the outermost trusted proxy.
 *
 * - `CloudFront-Viewer-Address` (`ip:port`) is used when TD_TRUSTED_PROXY_HOPS > 0
 *   (i.e. we are behind CloudFront/ALB and the edge sets it).
 * - Otherwise X-Forwarded-For is read from the RIGHT, skipping `trustedProxyHops`
 *   entries appended by our own proxies (CloudFront → ALB → web: hops = 1).
 *   Left-most entries are client-controlled and never trusted.
 * - With `trustedProxyHops === 0` there is no trusted proxy in front of the BFF, so
 *   every forwarding header is browser-supplied: return null (SEC-01). Never trust
 *   X-Forwarded-For in that configuration.
 */
export function resolveClientIp(headers: Headers, trustedProxyHops: number): string | null {
  if (!Number.isFinite(trustedProxyHops) || trustedProxyHops <= 0) return null;
  const viewer = headers.get("cloudfront-viewer-address");
  if (viewer) {
    const ip = viewer.includes("]")
      ? viewer.slice(viewer.indexOf("[") + 1, viewer.indexOf("]"))
      : viewer.lastIndexOf(":") > viewer.indexOf(":") // IPv6 without brackets: last ":" is the port
        ? viewer.slice(0, viewer.lastIndexOf(":"))
        : viewer.split(":")[0] ?? "";
    if (IP_PATTERN.test(ip)) return ip;
  }
  const xff = headers.get("x-forwarded-for");
  if (!xff) return null;
  const chain = xff
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const idx = chain.length - 1 - trustedProxyHops;
  const candidate = idx >= 0 ? chain[idx] : undefined;
  return candidate && IP_PATTERN.test(candidate) ? candidate : null;
}

function randomHex(bytes: number): string {
  const buf = globalThis.crypto.getRandomValues(new Uint8Array(bytes));
  return Array.from(buf, (b) => b.toString(16).padStart(2, "0")).join("");
}

/** New W3C traceparent for the BFF → api hop (browser-supplied values are not trusted). */
export function newTraceparent(): string {
  return `00-${randomHex(16)}-${randomHex(8)}-01`;
}

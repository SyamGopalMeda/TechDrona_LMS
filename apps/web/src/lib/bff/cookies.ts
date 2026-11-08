import { COOKIE_BASE, type CookieKind, type CookieMode } from "./config";

/** Parse a `Cookie` request header into a map (first occurrence wins). */
export function parseCookieHeader(header: string | null | undefined): Map<string, string> {
  const out = new Map<string, string>();
  if (!header) return out;
  for (const part of header.split(";")) {
    const idx = part.indexOf("=");
    if (idx <= 0) continue;
    const name = part.slice(0, idx).trim();
    const value = part.slice(idx + 1).trim();
    if (name && !out.has(name)) out.set(name, value);
  }
  return out;
}

export interface CookieAttributes {
  maxAge?: number;
  expires?: string;
  httpOnly: boolean;
  sameSite: "Lax" | "Strict";
}

/**
 * Serialise a BFF cookie. Secure mode: `__Host-` rules (Secure, Path=/, no Domain).
 * Dev-insecure mode: same attributes minus Secure, so http://localhost works.
 */
export function serializeCookie(
  name: string,
  value: string,
  mode: CookieMode,
  attrs: CookieAttributes,
): string {
  const parts = [`${name}=${value}`, "Path=/"];
  if (attrs.maxAge !== undefined) parts.push(`Max-Age=${Math.trunc(attrs.maxAge)}`);
  if (attrs.expires) parts.push(`Expires=${attrs.expires}`);
  if (mode === "secure") parts.push("Secure");
  if (attrs.httpOnly) parts.push("HttpOnly");
  parts.push(`SameSite=${attrs.sameSite}`);
  return parts.join("; ");
}

export interface ParsedSetCookie {
  name: string;
  value: string;
  maxAge?: number;
  expires?: string;
}

export function parseSetCookie(header: string): ParsedSetCookie | null {
  const [pair, ...attrs] = header.split(";");
  if (!pair) return null;
  const idx = pair.indexOf("=");
  if (idx <= 0) return null;
  const parsed: ParsedSetCookie = { name: pair.slice(0, idx).trim(), value: pair.slice(idx + 1).trim() };
  for (const attr of attrs) {
    const [k, ...rest] = attr.split("=");
    const key = (k ?? "").trim().toLowerCase();
    const val = rest.join("=").trim();
    if (key === "max-age") {
      const n = Number.parseInt(val, 10);
      if (Number.isFinite(n)) parsed.maxAge = n;
    } else if (key === "expires") {
      parsed.expires = val;
    }
  }
  return parsed;
}

/** Map an upstream cookie name (`__Host-td_session`, `td_session`) to its kind. */
export function cookieKindFromName(name: string): CookieKind | null {
  const base = name.startsWith("__Host-") ? name.slice("__Host-".length) : name;
  for (const [kind, b] of Object.entries(COOKIE_BASE) as [CookieKind, string][]) {
    if (b === base) return kind;
  }
  return null;
}

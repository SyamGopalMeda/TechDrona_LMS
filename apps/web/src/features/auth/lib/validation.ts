/**
 * Client-side checks that mirror the API rules (api-specification AUTH-01). The API is
 * authoritative; these only give earlier, clearer feedback.
 */

export const PASSWORD_MIN = 15; // without MFA (AUTH-01 `password_too_short`)
export const PASSWORD_MIN_WITH_MFA = 8;
export const PASSWORD_MAX = 128;

export function validatePassword(pw: string, min = PASSWORD_MIN): string | null {
  if (!pw) return "Enter a password.";
  if (pw.length < min) return `Use at least ${min} characters.`;
  if (pw.length > PASSWORD_MAX) return `Use at most ${PASSWORD_MAX} characters.`;
  return null;
}

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
export function isEmail(v: string): boolean {
  return EMAIL.test(v.trim());
}

/** Indian mobile, 10 digits starting 6–9, returned as E.164 (+91…), or null. */
export function normaliseIndianMobile(v: string): string | null {
  const digits = v.replace(/[\s-]/g, "").replace(/^\+?91/, "").replace(/^0/, "");
  return /^[6-9]\d{9}$/.test(digits) ? `+91${digits}` : null;
}

export function isOtp(v: string, length = 6): boolean {
  return new RegExp(`^\\d{${length}}$`).test(v);
}

/** Age in completed years on `on` (default today), or null for an invalid date. */
export function ageOn(dobIso: string, on: Date = new Date()): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dobIso);
  if (!m) return null;
  const y = Number(m[1]);
  const mo = Number(m[2]);
  const d = Number(m[3]);
  const dob = new Date(Date.UTC(y, mo - 1, d));
  if (dob.getUTCFullYear() !== y || dob.getUTCMonth() !== mo - 1 || dob.getUTCDate() !== d) return null;
  const today = new Date(Date.UTC(on.getFullYear(), on.getMonth(), on.getDate()));
  if (dob > today) return null;
  let age = today.getUTCFullYear() - y;
  const beforeBirthday =
    today.getUTCMonth() < mo - 1 || (today.getUTCMonth() === mo - 1 && today.getUTCDate() < d);
  if (beforeBirthday) age -= 1;
  return age;
}

/**
 * Only same-origin relative paths are allowed as post-login targets (open-redirect guard).
 *
 * Rejects control characters, whitespace and backslashes anywhere (the WHATWG URL parser
 * strips tabs/newlines and treats `\` as `/`, so `/<TAB>/evil.example` would become
 * `//evil.example`), then resolves against a sentinel origin and returns the normalised
 * same-origin path (SEC-04).
 */
const NEXT_SENTINEL_ORIGIN = "http://next.invalid";

export function safeNextPath(next: string | null | undefined, fallback = "/app"): string {
  if (!next || typeof next !== "string") return fallback;
  if (!next.startsWith("/") || next.startsWith("//")) return fallback;
  if (/[\u0000-\u001F\u007F\s\\]/.test(next)) return fallback;
  let url: URL;
  try {
    url = new URL(next, NEXT_SENTINEL_ORIGIN);
  } catch {
    return fallback;
  }
  if (url.origin !== NEXT_SENTINEL_ORIGIN) return fallback;
  const path = `${url.pathname}${url.search}${url.hash}`;
  if (!path.startsWith("/") || path.startsWith("//")) return fallback;
  if (path === "/api" || path.startsWith("/api/")) return fallback;
  return path;
}

import { createHash, createHmac, randomBytes, timingSafeEqual } from "node:crypto";

/**
 * Signed double-submit CSRF token (api-specification §1.2/§1.3, ADR-0010 v0.3).
 *
 *   token   = "v1." + nonce + "." + mac          (base64url parts)
 *   mac     = HMAC-SHA256(TD_CSRF_KEY, "td-csrf|v1|" + binding + "|" + nonce)
 *   binding = "s:" + hex(SHA-256(session cookie value))   when a session cookie exists
 *           = "anon"                                        pre-session (login/signup forms)
 *
 * The BFF (web) is the only holder of TD_CSRF_KEY; the api never sees it. Verification
 * accepts the current key and TD_CSRF_KEY_PREVIOUS (rotation window).
 */

const VERSION = "v1";
const NONCE_BYTES = 16;

export function sessionBinding(sessionToken: string | undefined | null): string {
  if (!sessionToken) return "anon";
  return `s:${createHash("sha256").update(sessionToken, "utf8").digest("hex")}`;
}

function mac(key: string, binding: string, nonce: string): string {
  return createHmac("sha256", key).update(`td-csrf|${VERSION}|${binding}|${nonce}`, "utf8").digest("base64url");
}

export function mintCsrfToken(key: string, sessionToken: string | undefined | null): string {
  const nonce = randomBytes(NONCE_BYTES).toString("base64url");
  return `${VERSION}.${nonce}.${mac(key, sessionBinding(sessionToken), nonce)}`;
}

export function constantTimeEqual(a: string, b: string): boolean {
  const ab = Buffer.from(a, "utf8");
  const bb = Buffer.from(b, "utf8");
  if (ab.length !== bb.length) {
    // Still spend comparable time so length is the only signal.
    timingSafeEqual(ab, ab);
    return false;
  }
  return timingSafeEqual(ab, bb);
}

/** True when `token` is a well-formed token signed by one of `keys` for this session. */
export function verifyCsrfToken(
  keys: readonly string[],
  token: string | undefined | null,
  sessionToken: string | undefined | null,
): boolean {
  if (!token || token.length > 256) return false;
  const parts = token.split(".");
  if (parts.length !== 3 || parts[0] !== VERSION) return false;
  const [, nonce, sig] = parts as [string, string, string];
  if (!/^[A-Za-z0-9_-]{16,64}$/.test(nonce) || !/^[A-Za-z0-9_-]{43}$/.test(sig)) return false;
  const binding = sessionBinding(sessionToken);
  let ok = false;
  for (const key of keys) {
    // Evaluate every key so timing does not reveal which one matched.
    if (constantTimeEqual(mac(key, binding, nonce), sig)) ok = true;
  }
  return ok;
}

/**
 * Double-submit check: the header must equal the cookie, and the cookie must verify for
 * the session presented with the request.
 */
export function checkDoubleSubmit(
  keys: readonly string[],
  cookieToken: string | undefined | null,
  headerToken: string | undefined | null,
  sessionToken: string | undefined | null,
): boolean {
  if (!cookieToken || !headerToken) return false;
  if (!constantTimeEqual(cookieToken, headerToken)) return false;
  return verifyCsrfToken(keys, cookieToken, sessionToken);
}

import { uuid7 } from "@/lib/ids/uuid7";
import { API_PREFIX } from "./proxy";
import { cookieName, upstreamCookieName, type BffConfig } from "./config";
import { cookieKindFromName, parseSetCookie, serializeCookie } from "./cookies";
import { mintCsrfToken } from "./csrf";
import { newTraceparent, resolveClientIp } from "./headers";

/**
 * Remember-device re-issue (AUTH-28, api-specification §1.2 / §4 AUTH-28; SEC-07).
 *
 * Called by the page middleware ONLY on a top-level user navigation
 * (`Sec-Fetch-Mode: navigate` + `Sec-Fetch-User: ?1`) that arrives without a session
 * cookie but with a `td_remember` cookie. Never for XHR, prefetches, beacons or heartbeats.
 * The api route is BFF-internal: it requires the service token, so the browser cannot call
 * it through the proxy (`proxy.ts` returns 404 for that path).
 */

export const REMEMBER_REFRESH_PATH = "auth/remember/refresh";

export type RememberOutcome =
  /** New session issued: append `setCookies` to the response and re-navigate. */
  | { kind: "refreshed"; setCookies: string[] }
  /** api refused the credential (401 remember_invalid etc.): clear the remember cookie. */
  | { kind: "invalid"; setCookies: string[] }
  /** api unreachable / unexpected: leave cookies alone and fall through to the login redirect. */
  | { kind: "unavailable"; setCookies: [] };

export function isTopLevelUserNavigation(headers: Headers): boolean {
  if (headers.get("sec-fetch-mode") !== "navigate") return false;
  if (headers.get("sec-fetch-user") !== "?1") return false;
  if (headers.get("next-router-prefetch") !== null) return false;
  const purpose = (headers.get("purpose") ?? headers.get("sec-purpose") ?? "").toLowerCase();
  return !purpose.includes("prefetch");
}

export interface RememberDeps {
  config: BffConfig;
  env?: NodeJS.ProcessEnv;
  fetchImpl?: typeof fetch;
}

function clearRememberCookie(config: BffConfig, env: NodeJS.ProcessEnv): string {
  return serializeCookie(cookieName("remember", env), "", config.cookieMode, {
    httpOnly: true,
    sameSite: "Lax",
    maxAge: 0,
  });
}

export async function refreshRememberedSession(
  requestHeaders: Headers,
  rememberToken: string,
  deviceToken: string | undefined,
  { config, env = process.env, fetchImpl = fetch }: RememberDeps,
): Promise<RememberOutcome> {
  if (!config.serviceToken || rememberToken.length < 16 || rememberToken.length > 128) {
    return config.serviceToken ? { kind: "invalid", setCookies: [clearRememberCookie(config, env)] } : { kind: "unavailable", setCookies: [] };
  }
  const headers = new Headers({
    "content-type": "application/json",
    accept: "application/json",
    "accept-encoding": "identity",
    authorization: `Service ${config.serviceToken}`,
    "x-request-id": uuid7(),
    traceparent: newTraceparent(),
  });
  const ua = requestHeaders.get("user-agent");
  if (ua) headers.set("user-agent", ua);
  const lang = requestHeaders.get("accept-language");
  if (lang) headers.set("accept-language", lang);
  const upstreamCookies = [`${upstreamCookieName("remember")}=${rememberToken}`];
  if (deviceToken) {
    headers.set("x-td-device", deviceToken);
    upstreamCookies.push(`${upstreamCookieName("device")}=${deviceToken}`);
  }
  headers.set("cookie", upstreamCookies.join("; "));
  const clientIp = resolveClientIp(requestHeaders, config.trustedProxyHops);
  if (clientIp) {
    headers.set("x-td-client-ip", clientIp);
    headers.set("x-forwarded-for", clientIp);
  }

  let res: Response;
  try {
    res = await fetchImpl(`${config.apiInternalUrl}${API_PREFIX}${REMEMBER_REFRESH_PATH}`, {
      method: "POST",
      headers,
      body: JSON.stringify({ remember_token: rememberToken }),
      redirect: "manual",
      signal: AbortSignal.timeout(config.proxyTimeoutMs),
      cache: "no-store",
    });
  } catch {
    return { kind: "unavailable", setCookies: [] };
  }

  if (res.status === 401 || res.status === 403 || res.status === 400 || res.status === 422) {
    return { kind: "invalid", setCookies: [clearRememberCookie(config, env)] };
  }
  if (res.status !== 200) return { kind: "unavailable", setCookies: [] };
  let result: unknown;
  try {
    result = ((await res.json()) as { result?: unknown } | null)?.result;
  } catch {
    result = undefined;
  }
  // Anything but a fully authenticated session (e.g. a pending device-OTP or session-cap
  // step) needs the interactive login: drop the api's cookies and fall through.
  if (result !== "authenticated") return { kind: "unavailable", setCookies: [] };

  const setCookies: string[] = [];
  let newSession: string | undefined;
  for (const raw of res.headers.getSetCookie()) {
    const parsed = parseSetCookie(raw);
    if (!parsed) continue;
    const kind = cookieKindFromName(parsed.name);
    if (!kind || kind === "csrf") continue;
    setCookies.push(
      serializeCookie(cookieName(kind, env), parsed.value, config.cookieMode, {
        httpOnly: true,
        sameSite: "Lax",
        maxAge: parsed.maxAge,
        expires: parsed.expires,
      }),
    );
    if (kind === "session" && parsed.value && (parsed.maxAge === undefined || parsed.maxAge > 0)) {
      newSession = parsed.value;
    }
  }
  if (!newSession) return { kind: "unavailable", setCookies: [] };
  setCookies.push(
    serializeCookie(cookieName("csrf", env), mintCsrfToken(config.csrfKeys[0]!, newSession), config.cookieMode, {
      httpOnly: false,
      sameSite: "Strict",
    }),
  );
  return { kind: "refreshed", setCookies };
}

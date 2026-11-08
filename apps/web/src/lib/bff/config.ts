/**
 * Server-only BFF configuration. Read lazily (per call) so tests can change env vars and so
 * `next build` does not need secrets at build time.
 *
 * Never import this module from a client component: it reads secrets.
 */

export type CookieMode = "secure" | "dev-insecure";

/** Canonical cookie base names (api-specification §1.2). */
export const COOKIE_BASE = {
  session: "td_session",
  device: "td_device",
  remember: "td_remember",
  csrf: "td_csrf",
} as const;

export type CookieKind = keyof typeof COOKIE_BASE;

/**
 * `__Host-` cookies must be `Secure`, which browsers refuse to store over plain
 * http://localhost. Outside production (NODE_ENV !== "production") and unless
 * TD_COOKIE_SECURE=true, the BFF uses un-prefixed, non-Secure names (`td_session`, ...).
 * Production always uses the `__Host-` names; there is no override for that direction.
 */
export function cookieMode(env: NodeJS.ProcessEnv = process.env): CookieMode {
  if (env.NODE_ENV === "production") return "secure";
  return env.TD_COOKIE_SECURE === "true" ? "secure" : "dev-insecure";
}

export function cookieName(kind: CookieKind, env: NodeJS.ProcessEnv = process.env): string {
  const base = COOKIE_BASE[kind];
  return cookieMode(env) === "secure" ? `__Host-${base}` : base;
}

/** Name the api service uses for the same credential (always canonical, `__Host-`). */
export function upstreamCookieName(kind: CookieKind): string {
  return `__Host-${COOKIE_BASE[kind]}`;
}

export interface BffConfig {
  apiInternalUrl: string;
  serviceToken: string;
  csrfKeys: string[];
  publicOrigin: string;
  proxyTimeoutMs: number;
  originVerifyValue: string;
  trustedProxyHops: number;
  cookieMode: CookieMode;
}

class ConfigError extends Error {
  override name = "ConfigError";
}

export function loadBffConfig(env: NodeJS.ProcessEnv = process.env): BffConfig {
  const mode = cookieMode(env);
  const csrfKey = env.TD_CSRF_KEY ?? "";
  const apiInternalUrl = (env.TD_API_INTERNAL_URL ?? env.API_INTERNAL_URL ?? "").replace(/\/+$/, "");
  if (!apiInternalUrl) throw new ConfigError("TD_API_INTERNAL_URL is not set");
  if (!csrfKey) throw new ConfigError("TD_CSRF_KEY is not set");
  if (mode === "secure" && (csrfKey.length < 32 || csrfKey.includes("REPLACE"))) {
    throw new ConfigError("TD_CSRF_KEY must be a real 256-bit secret outside local development");
  }
  const publicBase = env.TD_PUBLIC_BASE_URL ?? env.NEXT_PUBLIC_BASE_URL ?? "http://localhost:3000";
  const timeout = Number.parseInt(env.TD_BFF_PROXY_TIMEOUT_MS ?? "15000", 10);
  const hops = Number.parseInt(env.TD_TRUSTED_PROXY_HOPS ?? "0", 10);
  return {
    apiInternalUrl,
    serviceToken: env.TD_SERVICE_TOKEN ?? "",
    csrfKeys: [csrfKey, env.TD_CSRF_KEY_PREVIOUS ?? ""].filter((k) => k.length > 0),
    publicOrigin: new URL(publicBase).origin,
    proxyTimeoutMs: Number.isFinite(timeout) && timeout > 0 ? timeout : 15000,
    originVerifyValue: env.TD_ORIGIN_VERIFY_HEADER ?? "",
    trustedProxyHops: Number.isFinite(hops) && hops >= 0 ? hops : 0,
    cookieMode: mode,
  };
}

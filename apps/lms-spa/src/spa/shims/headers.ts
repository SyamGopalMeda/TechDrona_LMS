/**
 * `next/headers` in the browser: the request headers the server components read are rebuilt
 * from the current location (x-td-request-path, set by the Next middleware) and the user agent.
 * `cookies()` sees only JS-readable cookies (the session cookie is HttpOnly: use
 * `hasSessionCookie()` from `@/lib/api/server`, which probes the API).
 */
export async function headers(): Promise<Headers> {
  const h = new Headers();
  if (typeof window !== "undefined") {
    h.set("x-td-request-path", `${window.location.pathname}${window.location.search}`);
    h.set("user-agent", window.navigator.userAgent);
  }
  return h;
}

export async function cookies(): Promise<{ get(name: string): { name: string; value: string } | undefined; has(name: string): boolean }> {
  const jar = new Map<string, string>();
  if (typeof document !== "undefined") {
    for (const part of document.cookie.split(";")) {
      const i = part.indexOf("=");
      if (i > 0) jar.set(part.slice(0, i).trim(), decodeURIComponent(part.slice(i + 1).trim()));
    }
  }
  return {
    get: (name) => (jar.has(name) ? { name, value: jar.get(name) ?? "" } : undefined),
    has: (name) => jar.has(name),
  };
}

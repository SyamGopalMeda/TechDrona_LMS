// @vitest-environment node
import { describe, expect, it, vi } from "vitest";
import type { BffConfig } from "./config";
import { cookieName, loadBffConfig } from "./config";
import { mintCsrfToken, verifyCsrfToken } from "./csrf";
import { resolveClientIp } from "./headers";
import { extractApiPath, handleBffRequest, maxBodyFor } from "./proxy";

const KEY = "k".repeat(64);
const devEnv = { NODE_ENV: "development" } as NodeJS.ProcessEnv;
const prodEnv = { NODE_ENV: "production" } as NodeJS.ProcessEnv;

function config(overrides: Partial<BffConfig> = {}): BffConfig {
  return {
    apiInternalUrl: "http://api.internal:8000",
    serviceToken: "svc-token",
    csrfKeys: [KEY],
    publicOrigin: "http://localhost:3000",
    proxyTimeoutMs: 5000,
    originVerifyValue: "",
    trustedProxyHops: 0,
    cookieMode: "dev-insecure",
    ...overrides,
  };
}

function upstreamOk(body: unknown = { ok: true }, init: ResponseInit = {}) {
  return vi.fn(async (_url: string | URL | Request, _init?: RequestInit) =>
    new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" }, ...init }),
  );
}

function call(fetchImpl: { mock: { calls: unknown[][] } }, index = 0) {
  const c = fetchImpl.mock.calls[index];
  if (!c) throw new Error("fetch not called");
  return { url: String(c[0]), init: c[1] as RequestInit, headers: new Headers((c[1] as RequestInit).headers) };
}

describe("extractApiPath", () => {
  it("accepts normal paths and rejects traversal / encoded separators", () => {
    expect(extractApiPath("/api/v1/me")).toEqual({ ok: true, path: "me" });
    expect(extractApiPath("/api/v1/courses/abc/lessons")).toEqual({ ok: true, path: "courses/abc/lessons" });
    expect(extractApiPath("/api/v1/%2e%2e/admin").ok).toBe(false);
    expect(extractApiPath("/api/v1/a%2Fb").ok).toBe(false);
    expect(extractApiPath("/api/v1/a%5Cb").ok).toBe(false);
    expect(extractApiPath("/api/v1/a//b").ok).toBe(false);
    expect(extractApiPath("/api/v1/").ok).toBe(false);
  });
});

describe("BFF routing exclusions", () => {
  it("never proxies webhooks", async () => {
    const fetchImpl = upstreamOk();
    const res = await handleBffRequest(
      new Request("http://localhost:3000/api/v1/webhooks/razorpay", { method: "POST", body: "{}" }),
      { config: config(), fetchImpl, env: devEnv },
    );
    expect(res.status).toBe(404);
    expect(res.headers.get("content-type")).toBe("application/problem+json");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("blocks the BFF-internal remember refresh route", async () => {
    const fetchImpl = upstreamOk();
    const res = await handleBffRequest(
      new Request("http://localhost:3000/api/v1/auth/remember/refresh", { method: "POST" }),
      { config: config(), fetchImpl, env: devEnv },
    );
    expect(res.status).toBe(404);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("returns 503 problem when configuration is missing", async () => {
    const res = await handleBffRequest(new Request("http://localhost:3000/api/v1/me"), { env: devEnv, fetchImpl: upstreamOk() });
    expect(res.status).toBe(503);
    const body = (await res.json()) as { code: string; request_id: string };
    expect(body.code).toBe("service_unavailable");
    expect(body.request_id).toBeTruthy();
  });
});

describe("BFF GET proxying", () => {
  it("forwards an allow-list of headers and adds BFF-owned ones", async () => {
    const fetchImpl = upstreamOk();
    const res = await handleBffRequest(
      new Request("http://localhost:3000/api/v1/me?x=1", {
        headers: {
          cookie: "td_session=SESS; td_device=DEV; other=1",
          authorization: "Bearer evil",
          "x-td-session": "spoofed",
          "x-td-activity": "navigation",
          "x-request-id": "spoofed",
          "x-forwarded-for": "6.6.6.6, 10.0.0.1",
          accept: "application/json",
          "user-agent": "UA",
          "idempotency-key": "abc12345",
        },
      }),
      { config: config(), fetchImpl, env: devEnv },
    );
    expect(res.status).toBe(200);
    const { url, headers } = call(fetchImpl);
    expect(url).toBe("http://api.internal:8000/api/v1/me?x=1");
    expect(headers.get("authorization")).toBe("Service svc-token");
    expect(headers.get("x-td-session")).toBe("SESS");
    expect(headers.get("x-td-device")).toBe("DEV");
    expect(headers.get("cookie")).toBe("__Host-td_session=SESS; __Host-td_device=DEV");
    expect(headers.get("x-td-activity")).toBeNull();
    expect(headers.get("x-request-id")).not.toBe("spoofed");
    expect(headers.get("x-request-id")).toMatch(/^[0-9a-f-]{36}$/);
    expect(headers.get("traceparent")).toMatch(/^00-[0-9a-f]{32}-[0-9a-f]{16}-01$/);
    // SEC-01: hops=0 (no trusted proxy) → browser-supplied X-Forwarded-For is ignored.
    expect(headers.get("x-td-client-ip")).toBeNull();
    expect(headers.get("x-forwarded-for")).toBeNull();
    expect(headers.get("user-agent")).toBe("UA");
    expect(headers.get("idempotency-key")).toBe("abc12345");
    expect(res.headers.get("x-request-id")).toBeTruthy();
    expect(res.headers.get("cache-control")).toBe("no-store");
    // CSRF cookie minted (dev name, readable by JS, bound to the session)
    const setCookie = res.headers.getSetCookie();
    const csrf = setCookie.find((c) => c.startsWith("td_csrf="));
    expect(csrf).toBeDefined();
    expect(csrf).not.toContain("HttpOnly");
    expect(csrf).not.toContain("Secure");
    const token = csrf!.split(";")[0]!.split("=")[1]!;
    expect(verifyCsrfToken([KEY], token, "SESS")).toBe(true);
  });

  it("marks top-level navigations but never prefetches", async () => {
    const fetchImpl = upstreamOk();
    await handleBffRequest(new Request("http://localhost:3000/api/v1/me", { headers: { "sec-fetch-mode": "navigate" } }), {
      config: config(),
      fetchImpl,
      env: devEnv,
    });
    await handleBffRequest(
      new Request("http://localhost:3000/api/v1/me", { headers: { "sec-fetch-mode": "navigate", "sec-purpose": "prefetch" } }),
      { config: config(), fetchImpl, env: devEnv },
    );
    expect(call(fetchImpl, 0).headers.get("x-td-activity")).toBe("navigation");
    expect(call(fetchImpl, 1).headers.get("x-td-activity")).toBeNull();
  });

  it("strips hop-by-hop response headers and maps upstream errors to 503", async () => {
    const fetchImpl = vi.fn(async () => new Response("{}", { headers: { connection: "keep-alive", "x-request-id": "UP-1", "content-encoding": "gzip" } }));
    const res = await handleBffRequest(new Request("http://localhost:3000/api/v1/me"), { config: config(), fetchImpl, env: devEnv });
    expect(res.headers.get("connection")).toBeNull();
    expect(res.headers.get("content-encoding")).toBeNull();
    expect(res.headers.get("x-request-id")).toBe("UP-1");

    const failing = vi.fn(async () => {
      throw new TypeError("fetch failed");
    });
    const res2 = await handleBffRequest(new Request("http://localhost:3000/api/v1/me"), { config: config(), fetchImpl: failing, env: devEnv });
    expect(res2.status).toBe(503);
  });
});

describe("BFF CSRF and Fetch Metadata", () => {
  const session = "SESS";
  const token = mintCsrfToken(KEY, session);
  const base = {
    method: "POST",
    body: JSON.stringify({ a: 1 }),
  };

  function post(headers: Record<string, string>, init: Partial<RequestInit> = {}) {
    return new Request("http://localhost:3000/api/v1/support/tickets", {
      ...base,
      ...init,
      headers: { "content-type": "application/json", cookie: `td_session=${session}; td_csrf=${token}`, ...headers },
    });
  }

  it("accepts a valid double-submit token", async () => {
    const fetchImpl = upstreamOk();
    const res = await handleBffRequest(post({ "x-csrf-token": token, "sec-fetch-site": "same-origin" }), { config: config(), fetchImpl, env: devEnv });
    expect(res.status).toBe(200);
    const { headers, init } = call(fetchImpl);
    expect(headers.get("x-csrf-token")).toBeNull();
    expect(new TextDecoder().decode(init.body as ArrayBuffer)).toBe('{"a":1}');
  });

  it("rejects a missing or mismatched header", async () => {
    const fetchImpl = upstreamOk();
    const r1 = await handleBffRequest(post({ "sec-fetch-site": "same-origin" }), { config: config(), fetchImpl, env: devEnv });
    const r2 = await handleBffRequest(post({ "x-csrf-token": mintCsrfToken(KEY, session) }), { config: config(), fetchImpl, env: devEnv });
    expect(r1.status).toBe(403);
    expect(((await r1.json()) as { code: string }).code).toBe("csrf_failed");
    expect(r2.status).toBe(403);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("rejects a token bound to another session or to the pre-session binding", async () => {
    const fetchImpl = upstreamOk();
    const anon = mintCsrfToken(KEY, null);
    const req = new Request("http://localhost:3000/api/v1/x", {
      ...base,
      headers: { "content-type": "application/json", cookie: `td_session=${session}; td_csrf=${anon}`, "x-csrf-token": anon },
    });
    expect((await handleBffRequest(req, { config: config(), fetchImpl, env: devEnv })).status).toBe(403);
  });

  it("accepts the pre-session token on public auth forms", async () => {
    const fetchImpl = upstreamOk();
    const anon = mintCsrfToken(KEY, null);
    const req = new Request("http://localhost:3000/api/v1/auth/login", {
      ...base,
      headers: { "content-type": "application/json", cookie: `td_csrf=${anon}`, "x-csrf-token": anon, "sec-fetch-site": "same-origin" },
    });
    expect((await handleBffRequest(req, { config: config(), fetchImpl, env: devEnv })).status).toBe(200);
  });

  it("rejects cross-site requests and foreign or null Origin", async () => {
    const fetchImpl = upstreamOk();
    const cases: Record<string, string>[] = [{ "sec-fetch-site": "cross-site" }, { "sec-fetch-site": "same-site" }, { origin: "https://evil.example" }, { origin: "null" }];
    for (const h of cases) {
      const res = await handleBffRequest(post({ "x-csrf-token": token, ...h }), { config: config(), fetchImpl, env: devEnv });
      expect(res.status).toBe(403);
    }
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("accepts the previous key during rotation", async () => {
    const fetchImpl = upstreamOk();
    const oldToken = mintCsrfToken("old".repeat(22), session);
    const req = new Request("http://localhost:3000/api/v1/x", {
      ...base,
      headers: { "content-type": "application/json", cookie: `td_session=${session}; td_csrf=${oldToken}`, "x-csrf-token": oldToken },
    });
    const res = await handleBffRequest(req, { config: config({ csrfKeys: [KEY, "old".repeat(22)] }), fetchImpl, env: devEnv });
    expect(res.status).toBe(200);
    // re-minted with the current key
    const fresh = res.headers.getSetCookie().find((c) => c.startsWith("td_csrf="));
    expect(fresh).toBeDefined();
  });

  it("rejects non-JSON bodies and oversize bodies", async () => {
    const fetchImpl = upstreamOk();
    const r1 = await handleBffRequest(post({ "x-csrf-token": token, "content-type": "text/plain" }), { config: config(), fetchImpl, env: devEnv });
    expect(r1.status).toBe(415);
    const big = "x".repeat(256 * 1024 + 1);
    const r2 = await handleBffRequest(post({ "x-csrf-token": token }, { body: JSON.stringify({ big }) }), { config: config(), fetchImpl, env: devEnv });
    expect(r2.status).toBe(413);
  });

  it("validates the beacon token from the body and requires Sec-Fetch-Site: same-origin", async () => {
    const fetchImpl = vi.fn(async (_url: string | URL | Request, _init?: RequestInit) => new Response(null, { status: 204 }));
    const beacon = (headers: Record<string, string>) =>
      new Request("http://localhost:3000/api/v1/analytics/events/beacon", {
        method: "POST",
        body: JSON.stringify({ sent_at: "2026-11-03T10:00:00.000Z", csrf: token, events: [] }),
        headers: { "content-type": "text/plain;charset=UTF-8", cookie: `td_session=${session}; td_csrf=${token}`, ...headers },
      });
    const missing = await handleBffRequest(beacon({}), { config: config(), fetchImpl, env: devEnv });
    expect(missing.status).toBe(403);
    const ok = await handleBffRequest(beacon({ "sec-fetch-site": "same-origin" }), { config: config(), fetchImpl, env: devEnv });
    expect(ok.status).toBe(204);
    const { init, headers } = call(fetchImpl);
    expect(headers.get("content-type")).toBe("application/json");
    expect(JSON.parse(init.body as string)).toEqual({ sent_at: "2026-11-03T10:00:00.000Z", events: [] });
  });
});

describe("BFF cookie rewriting", () => {
  it("re-issues api session cookies under dev names and mints a CSRF token for the new session", async () => {
    const fetchImpl = vi.fn(async () => {
      const h = new Headers({ "content-type": "application/json" });
      h.append("set-cookie", "__Host-td_session=NEWSESS; Path=/; Max-Age=86400; Secure; HttpOnly; SameSite=Lax");
      h.append("set-cookie", "__Host-td_device=DEV2; Path=/; Max-Age=34560000; Secure; HttpOnly; SameSite=Lax");
      h.append("set-cookie", "tracking=1; Path=/");
      h.append("set-cookie", "td_csrf=forged; Path=/");
      return new Response("{}", { headers: h });
    });
    const anon = mintCsrfToken(KEY, null);
    const res = await handleBffRequest(
      new Request("http://localhost:3000/api/v1/auth/login", {
        method: "POST",
        body: "{}",
        headers: { "content-type": "application/json", cookie: `td_csrf=${anon}`, "x-csrf-token": anon },
      }),
      { config: config(), fetchImpl, env: devEnv },
    );
    const cookies = res.headers.getSetCookie();
    expect(cookies).toContain("td_session=NEWSESS; Path=/; Max-Age=86400; HttpOnly; SameSite=Lax");
    expect(cookies.some((c) => c.startsWith("td_device=DEV2;"))).toBe(true);
    expect(cookies.some((c) => c.startsWith("tracking="))).toBe(false);
    expect(cookies.some((c) => c.includes("forged"))).toBe(false);
    const csrf = cookies.find((c) => c.startsWith("td_csrf="))!;
    expect(verifyCsrfToken([KEY], csrf.split(";")[0]!.slice("td_csrf=".length), "NEWSESS")).toBe(true);
  });

  it("uses __Host- names with Secure in production", async () => {
    expect(cookieName("session", prodEnv)).toBe("__Host-td_session");
    expect(cookieName("csrf", { NODE_ENV: "development", TD_COOKIE_SECURE: "true" } as NodeJS.ProcessEnv)).toBe("__Host-td_csrf");
    const fetchImpl = vi.fn(async () => {
      const h = new Headers();
      h.append("set-cookie", "__Host-td_session=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Lax");
      return new Response(null, { status: 204, headers: h });
    });
    const token = mintCsrfToken(KEY, "S1");
    const res = await handleBffRequest(
      new Request("https://app.techdrona.in/api/v1/auth/logout", {
        method: "POST",
        headers: { cookie: `__Host-td_session=S1; __Host-td_csrf=${token}`, "x-csrf-token": token, "sec-fetch-site": "same-origin" },
      }),
      { config: config({ cookieMode: "secure", publicOrigin: "https://app.techdrona.in" }), fetchImpl, env: prodEnv },
    );
    expect(res.status).toBe(204);
    const cookies = res.headers.getSetCookie();
    expect(cookies[0]).toBe("__Host-td_session=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Lax");
    const csrf = cookies.find((c) => c.startsWith("__Host-td_csrf="))!;
    expect(csrf).toContain("Secure");
    expect(verifyCsrfToken([KEY], csrf.split(";")[0]!.slice("__Host-td_csrf=".length), null)).toBe(true);
  });

  it("serves the CSRF bootstrap endpoint locally", async () => {
    const fetchImpl = upstreamOk();
    const res = await handleBffRequest(new Request("http://localhost:3000/api/v1/_bff/csrf"), { config: config(), fetchImpl, env: devEnv });
    expect(res.status).toBe(204);
    expect(res.headers.getSetCookie()[0]).toMatch(/^td_csrf=v1\./);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});

describe("config and client IP", () => {
  it("refuses placeholder CSRF keys in production", () => {
    expect(() =>
      loadBffConfig({ NODE_ENV: "production", TD_API_INTERNAL_URL: "http://api", TD_CSRF_KEY: "local-csrf-key-REPLACE-with-64-hex" } as NodeJS.ProcessEnv),
    ).toThrow();
    expect(loadBffConfig({ NODE_ENV: "development", TD_API_INTERNAL_URL: "http://api/", TD_CSRF_KEY: "dev" } as NodeJS.ProcessEnv).apiInternalUrl).toBe("http://api");
  });

  it("reads the client IP from the right of X-Forwarded-For", () => {
    const h = new Headers({ "x-forwarded-for": "1.1.1.1, 203.0.113.9, 130.176.0.1" });
    expect(resolveClientIp(h, 1)).toBe("203.0.113.9");
    // SEC-01: with no trusted proxy every forwarding header is browser-supplied.
    expect(resolveClientIp(h, 0)).toBeNull();
    expect(resolveClientIp(new Headers({ "x-forwarded-for": "6.6.6.6" }), 0)).toBeNull();
    expect(resolveClientIp(new Headers({ "cloudfront-viewer-address": "6.6.6.6:443" }), 0)).toBeNull();
    expect(resolveClientIp(h, Number.NaN)).toBeNull();
    expect(resolveClientIp(new Headers({ "x-forwarded-for": "6.6.6.6" }), 1)).toBeNull();
    expect(resolveClientIp(new Headers({ "cloudfront-viewer-address": "198.51.100.7:443" }), 1)).toBe("198.51.100.7");
    expect(resolveClientIp(new Headers({ "x-forwarded-for": "not-an-ip" }), 0)).toBeNull();
  });
});

describe("ended sessions (SEC-07)", () => {
  function upstream401(code: string) {
    return vi.fn(async () =>
      new Response(JSON.stringify({ code, status: 401, title: "x" }), {
        status: 401,
        headers: { "content-type": "application/problem+json" },
      }),
    );
  }

  it("clears the session cookie when the api says the session has ended, keeping the problem body", async () => {
    for (const code of ["session_expired", "session_revoked", "unauthenticated"]) {
      const res = await handleBffRequest(
        new Request("http://localhost:3000/api/v1/me", { headers: { cookie: "td_session=OLD; td_device=DEV" } }),
        { config: config(), fetchImpl: upstream401(code), env: devEnv },
      );
      expect(res.status).toBe(401);
      expect(((await res.json()) as { code: string }).code).toBe(code);
      const cookies = res.headers.getSetCookie();
      expect(cookies.some((c) => c.startsWith("td_session=;") && c.includes("Max-Age=0"))).toBe(true);
      const csrf = cookies.find((c) => c.startsWith("td_csrf="))!;
      expect(verifyCsrfToken([KEY], csrf.split(";")[0]!.slice("td_csrf=".length), null)).toBe(true);
    }
  });

  it("keeps the session cookie on other 401s (e.g. wrong password)", async () => {
    const res = await handleBffRequest(
      new Request("http://localhost:3000/api/v1/me", { headers: { cookie: "td_session=OLD" } }),
      { config: config(), fetchImpl: upstream401("invalid_credentials"), env: devEnv },
    );
    expect(res.status).toBe(401);
    expect(res.headers.getSetCookie().some((c) => c.startsWith("td_session="))).toBe(false);
  });
});

describe("maxBodyFor", () => {
  it("allows payment-proof uploads (one base64 file) and keeps the default elsewhere", () => {
    expect(maxBodyFor("me/admissions/registrations")).toBe(4 * 1024 * 1024);
    expect(maxBodyFor("me/admissions/claims")).toBe(4 * 1024 * 1024);
    expect(maxBodyFor("public/admissions/registrations")).toBe(4 * 1024 * 1024);
    expect(maxBodyFor("public/admissions/claims")).toBe(4 * 1024 * 1024);
    expect(maxBodyFor("me/admissions")).toBe(256 * 1024);
    expect(maxBodyFor("analytics/events")).toBe(64 * 1024);
  });
});

// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
vi.mock("@/lib/api/server", () => ({ serverApiGet: vi.fn() }));

import { ApiError } from "@/lib/api/errors";
import type { BffConfig } from "@/lib/bff/config";
import { displayNameOf, extractPortalPath, handleCollegePortalRequest, portalTarget, resetCollegePortalAuthCache, type CollegePortalDeps } from "./proxy";

const SECRET = "test-portal-secret-0123456789abcdefXYZ";
const devEnv = { NODE_ENV: "development", TD_COLLEGE_PORTAL_URL: "http://portal.internal:4173", TD_COLLEGE_PORTAL_SECRET: SECRET } as NodeJS.ProcessEnv;

const config: BffConfig = {
  apiInternalUrl: "http://api.internal:8000",
  serviceToken: "svc",
  csrfKeys: ["k".repeat(64)],
  publicOrigin: "http://localhost:3000",
  proxyTimeoutMs: 5000,
  originVerifyValue: "",
  trustedProxyHops: 1,
  cookieMode: "dev-insecure",
};

const ADMIN_GRANTS = { portals: ["/admin"], data: [{ role_key: "super_admin" }] };
const ME = { user: { id: "u1", email: "a@x.test" }, profile: { display_name: "Asha Rao" } };

function apiGetFor(grants: unknown = ADMIN_GRANTS, me: unknown = ME) {
  return vi.fn(async (path: string) => {
    const v = path === "me/grants" ? grants : me;
    if (v instanceof Error) throw v;
    return v;
  }) as unknown as NonNullable<CollegePortalDeps["apiGet"]> & { mock: { calls: unknown[][] } };
}

function upstreamOk(body = "ok", headers: Record<string, string> = { "content-type": "application/javascript" }, status = 200) {
  return vi.fn(async (_url: string | URL | Request, _init?: RequestInit) => new Response(body, { status, headers }));
}

function req(path: string, init: RequestInit & { session?: string | null } = {}) {
  const { session = "SESSION-1", ...rest } = init;
  const headers = new Headers(rest.headers);
  if (session) headers.set("cookie", `td_session=${session}; td_csrf=abc; other=1`);
  return new Request(`http://localhost:3000${path}`, { ...rest, headers });
}

function sentHeaders(fetchImpl: { mock: { calls: unknown[][] } }) {
  return new Headers((fetchImpl.mock.calls[0]![1] as RequestInit).headers);
}

beforeEach(() => resetCollegePortalAuthCache());

describe("extractPortalPath", () => {
  it("accepts portal paths and rejects traversal, backslashes and NUL", () => {
    expect(extractPortalPath("/college-portal")).toEqual({ kind: "entry" });
    expect(extractPortalPath("/college-portal/")).toEqual({ kind: "entry" });
    expect(extractPortalPath("/college-portal/index.html")).toEqual({ kind: "ok", rest: "/index.html" });
    expect(extractPortalPath("/college-portal/api/colleges/42")).toEqual({ kind: "ok", rest: "/api/colleges/42" });
    expect(extractPortalPath("/college-portalx/a")).toEqual({ kind: "not_found" });
    for (const bad of ["/college-portal/../x", "/college-portal/a/%2e%2e/x", "/college-portal/%2E%2E", "/college-portal/a%2Fb", "/college-portal/a%5Cb", "/college-portal/a\\b", "/college-portal/a%00", "/college-portal/a//b", "/college-portal/%E0%A4%A"]) {
      expect(extractPortalPath(bad).kind, bad).toBe("bad");
    }
  });

  it("never proxies encoded traversal", async () => {
    const fetchImpl = upstreamOk();
    const deps = { env: devEnv, config, fetchImpl, apiGet: apiGetFor() };
    expect((await handleCollegePortalRequest(req("/college-portal/assets/..%2f..%2fsecret"), deps)).status).toBe(400);
    expect((await handleCollegePortalRequest(req("/college-portal/assets/%5c..%5csecret"), deps)).status).toBe(400);
    // The URL parser resolves %2e%2e segments; the result is outside the prefix → 404.
    expect((await handleCollegePortalRequest(req("/college-portal/assets/%2e%2e/%2e%2e/etc/passwd"), deps)).status).toBe(404);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});

describe("portalTarget", () => {
  it("defaults the URL outside production and always requires a >= 32 char secret", () => {
    expect(portalTarget({ NODE_ENV: "development", TD_COLLEGE_PORTAL_SECRET: SECRET } as NodeJS.ProcessEnv)).toEqual({ base: "http://127.0.0.1:4173", secret: SECRET });
    expect(portalTarget({ NODE_ENV: "development" } as NodeJS.ProcessEnv)).toBeNull();
    expect(portalTarget({ NODE_ENV: "development", TD_COLLEGE_PORTAL_SECRET: "short" } as NodeJS.ProcessEnv)).toBeNull();
    expect(portalTarget({ NODE_ENV: "production", TD_COLLEGE_PORTAL_SECRET: SECRET } as NodeJS.ProcessEnv)).toBeNull();
    expect(portalTarget({ NODE_ENV: "production", TD_COLLEGE_PORTAL_URL: "http://college-data:4173" } as NodeJS.ProcessEnv)).toBeNull();
    expect(portalTarget({ NODE_ENV: "production", TD_COLLEGE_PORTAL_URL: "http://college-data:4173/", TD_COLLEGE_PORTAL_SECRET: SECRET } as NodeJS.ProcessEnv)).toEqual({ base: "http://college-data:4173", secret: SECRET });
    expect(portalTarget({ NODE_ENV: "development", TD_COLLEGE_PORTAL_URL: "file:///etc" } as NodeJS.ProcessEnv)).toBeNull();
  });

  it("answers 503 when production has no portal configured", async () => {
    const res = await handleCollegePortalRequest(req("/college-portal/index.html"), { env: { NODE_ENV: "production" } as NodeJS.ProcessEnv, config, fetchImpl: upstreamOk(), apiGet: apiGetFor() });
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({ error: "College Data Portal is not configured" });
  });
});

describe("handleCollegePortalRequest", () => {
  it("redirects the bare prefix to index.html", async () => {
    const res = await handleCollegePortalRequest(req("/college-portal"), { env: devEnv, config, fetchImpl: upstreamOk(), apiGet: apiGetFor() });
    expect(res.status).toBe(308);
    expect(res.headers.get("location")).toBe("/college-portal/index.html");
  });

  it("forwards only allow-listed headers plus the proxy identity; never the LMS cookie or CSRF token", async () => {
    const fetchImpl = upstreamOk();
    const res = await handleCollegePortalRequest(
      req("/college-portal/assets/app.js?v=2", {
        headers: {
          accept: "*/*",
          authorization: "Bearer leak",
          "x-csrf-token": "tok",
          "x-td-proxy-secret": "spoofed",
          "x-td-proxy-user": "spoofed",
          "x-forwarded-for": "6.6.6.6, 10.0.0.9",
          "user-agent": "UA",
        },
      }),
      { env: devEnv, config, fetchImpl, apiGet: apiGetFor() },
    );
    expect(res.status).toBe(200);
    expect(String(fetchImpl.mock.calls[0]![0])).toBe("http://portal.internal:4173/assets/app.js?v=2");
    const h = sentHeaders(fetchImpl);
    expect(h.get("cookie")).toBeNull();
    expect(h.get("authorization")).toBeNull();
    expect(h.get("x-csrf-token")).toBeNull();
    expect(h.get("x-td-session")).toBeNull();
    expect(h.get("x-td-proxy-secret")).toBe(SECRET);
    expect(h.get("x-td-proxy-user")).toBe(encodeURIComponent("Asha Rao (a@x.test)"));
    expect(h.get("x-td-proxy-role")).toBe("editor");
    expect(h.get("x-forwarded-for")).toBe("6.6.6.6");
    expect(h.get("x-forwarded-host")).toBe("localhost:3000");
    expect(h.get("x-forwarded-proto")).toBe("http");
    expect(h.get("user-agent")).toBe("UA");
    expect([...h.keys()].sort()).toEqual(
      ["accept", "accept-encoding", "user-agent", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-td-proxy-role", "x-td-proxy-secret", "x-td-proxy-user"].sort(),
    );
  });

  it("never proxies without the shared secret (a standalone portal cannot be framed or SSO'd)", async () => {
    const fetchImpl = upstreamOk();
    const res = await handleCollegePortalRequest(req("/college-portal/index.html"), { env: { NODE_ENV: "development" } as NodeJS.ProcessEnv, config, fetchImpl, apiGet: apiGetFor() });
    expect(res.status).toBe(503);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("maps a portal 401 (secret mismatch) to 502 instead of an LMS sign-out", async () => {
    const fetchImpl = upstreamOk(JSON.stringify({ code: "proxy_required" }), { "content-type": "application/json" }, 401);
    const res = await handleCollegePortalRequest(req("/college-portal/api/colleges"), { env: devEnv, config, fetchImpl, apiGet: apiGetFor() });
    expect(res.status).toBe(502);
    expect(await res.json()).toEqual({ error: "College Data Portal is misconfigured", code: "portal_misconfigured" });
  });

  it("without a session: navigations go to /login, other requests get 401 JSON", async () => {
    const fetchImpl = upstreamOk();
    const apiGet = apiGetFor();
    const nav = await handleCollegePortalRequest(req("/college-portal/index.html", { session: null, headers: { "sec-fetch-dest": "document" } }), { env: devEnv, config, fetchImpl, apiGet });
    expect(nav.status).toBe(303);
    expect(nav.headers.get("location")).toBe("/login?next=%2Fadmin%2Fcollege-data");
    // In the admin page's frame: no redirect (/login cannot be framed), a page with a top-level link.
    const framed = await handleCollegePortalRequest(req("/college-portal/index.html", { session: null, headers: { "sec-fetch-dest": "iframe" } }), { env: devEnv, config, fetchImpl, apiGet });
    expect(framed.status).toBe(401);
    expect(framed.headers.get("content-type")).toContain("text/html");
    const html = await framed.text();
    expect(html).toContain('href="/login?next=%2Fadmin%2Fcollege-data" target="_top"');
    const api = await handleCollegePortalRequest(req("/college-portal/api/colleges", { session: null, headers: { "sec-fetch-dest": "empty" } }), { env: devEnv, config, fetchImpl, apiGet });
    expect(api.status).toBe(401);
    expect(await api.json()).toEqual({ error: "Please sign in to the LMS again", code: "auth_required" });
    expect(fetchImpl).not.toHaveBeenCalled();
    expect(apiGet).not.toHaveBeenCalled();
  });

  it("treats an api 401 as signed out", async () => {
    const res = await handleCollegePortalRequest(req("/college-portal/api/x"), { env: devEnv, config, fetchImpl: upstreamOk(), apiGet: apiGetFor(new ApiError(401, null, null)) });
    expect(res.status).toBe(401);
  });

  it("forbids non-admins (JSON for fetches, HTML for navigations)", async () => {
    const fetchImpl = upstreamOk();
    const apiGet = apiGetFor({ portals: ["/app", "/trainer"], data: [{ role_key: "trainer" }] });
    const res = await handleCollegePortalRequest(req("/college-portal/api/colleges"), { env: devEnv, config, fetchImpl, apiGet });
    expect(res.status).toBe(403);
    expect(await res.json()).toEqual({ error: "Admins only", code: "forbidden" });
    const page = await handleCollegePortalRequest(req("/college-portal/index.html", { headers: { accept: "text/html" } }), { env: devEnv, config, fetchImpl, apiGet });
    expect(page.status).toBe(403);
    expect(page.headers.get("content-type")).toContain("text/html");
    expect(fetchImpl).not.toHaveBeenCalled();
    // Negative results are not cached.
    expect(apiGet.mock.calls.filter((c) => c[0] === "me/grants")).toHaveLength(2);
  });

  it("fails closed (503) when the grants lookup errors", async () => {
    const fetchImpl = upstreamOk();
    const res = await handleCollegePortalRequest(req("/college-portal/assets/app.js"), { env: devEnv, config, fetchImpl, apiGet: apiGetFor(new ApiError(500, null, null)) });
    expect(res.status).toBe(503);
    const down = await handleCollegePortalRequest(req("/college-portal/assets/app.js"), { env: devEnv, config, fetchImpl, apiGet: apiGetFor(new TypeError("fetch failed")) });
    expect(down.status).toBe(503);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("caches a positive auth result per session for 60 s", async () => {
    const fetchImpl = upstreamOk();
    const apiGet = apiGetFor();
    let t = 1_000_000;
    const deps = { env: devEnv, config, fetchImpl, apiGet, now: () => t };
    expect((await handleCollegePortalRequest(req("/college-portal/a.js"), deps)).status).toBe(200);
    expect((await handleCollegePortalRequest(req("/college-portal/b.css"), deps)).status).toBe(200);
    expect(apiGet.mock.calls.filter((c) => c[0] === "me/grants")).toHaveLength(1);
    // A different session is checked separately.
    await handleCollegePortalRequest(req("/college-portal/a.js", { session: "SESSION-2" }), deps);
    expect(apiGet.mock.calls.filter((c) => c[0] === "me/grants")).toHaveLength(2);
    t += 61_000;
    await handleCollegePortalRequest(req("/college-portal/a.js"), deps);
    expect(apiGet.mock.calls.filter((c) => c[0] === "me/grants")).toHaveLength(3);
  });

  it("binds the cache to the device cookie and user agent (a replayed session reaches the api)", async () => {
    const apiGet = apiGetFor();
    const deps = { env: devEnv, config, fetchImpl: upstreamOk(), apiGet };
    const grants = () => apiGet.mock.calls.filter((c) => c[0] === "me/grants").length;
    const withDevice = (device: string, ua: string) => {
      const r = req("/college-portal/a.js", { headers: { "user-agent": ua } });
      const h = new Headers(r.headers);
      h.set("cookie", `${h.get("cookie")}; td_device=${device}`);
      return new Request(r.url, { headers: h });
    };
    await handleCollegePortalRequest(withDevice("D1", "Chrome"), deps);
    await handleCollegePortalRequest(withDevice("D1", "Chrome"), deps);
    expect(grants()).toBe(1);
    await handleCollegePortalRequest(withDevice("D2", "Chrome"), deps);
    expect(grants()).toBe(2);
    await handleCollegePortalRequest(withDevice("D1", "curl"), deps);
    expect(grants()).toBe(3);
  });

  it("re-checks with activity on writes and page loads (keeps the LMS session alive)", async () => {
    const apiGet = apiGetFor();
    const deps = { env: devEnv, config, fetchImpl: upstreamOk("{}", { "content-type": "application/json" }, 201), apiGet };
    await handleCollegePortalRequest(req("/college-portal/a.js"), deps); // fills the cache
    const grantCalls = () => apiGet.mock.calls.filter((c) => c[0] === "me/grants");
    expect(grantCalls()).toHaveLength(1);
    expect(grantCalls()[0]![1]).toEqual({ navigation: false });
    await handleCollegePortalRequest(req("/college-portal/api/followups", { method: "POST", body: "{}", headers: { "content-type": "application/json", origin: "http://localhost:3000" } }), deps);
    await handleCollegePortalRequest(req("/college-portal/index.html", { headers: { "sec-fetch-dest": "iframe" } }), deps);
    expect(grantCalls()).toHaveLength(3);
    expect(grantCalls()[1]![1]).toEqual({ navigation: true });
    expect(grantCalls()[2]![1]).toEqual({ navigation: true });
  });

  it("blocks cross-origin unsafe requests", async () => {
    const fetchImpl = upstreamOk();
    const deps = { env: devEnv, config, fetchImpl, apiGet: apiGetFor() };
    const site = await handleCollegePortalRequest(req("/college-portal/api/colleges", { method: "POST", body: "{}", headers: { "sec-fetch-site": "cross-site", "content-type": "application/json" } }), deps);
    expect(site.status).toBe(403);
    expect(((await site.json()) as { code: string }).code).toBe("cross_origin");
    const origin = await handleCollegePortalRequest(req("/college-portal/api/colleges", { method: "DELETE", headers: { origin: "https://evil.example" } }), deps);
    expect(origin.status).toBe(403);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("proxies same-origin POST bodies and rejects bodies over 1 MB", async () => {
    const fetchImpl = upstreamOk('{"id":1}', { "content-type": "application/json" }, 201);
    const deps = { env: devEnv, config, fetchImpl, apiGet: apiGetFor() };
    const ok = await handleCollegePortalRequest(
      req("/college-portal/api/colleges", { method: "POST", body: '{"name":"X"}', headers: { "sec-fetch-site": "same-origin", origin: "http://localhost:3000", "content-type": "application/json", "idempotency-key": "k1" } }),
      deps,
    );
    expect(ok.status).toBe(201);
    const init = fetchImpl.mock.calls[0]![1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(new TextDecoder().decode(init.body as ArrayBuffer)).toBe('{"name":"X"}');
    expect(sentHeaders(fetchImpl).get("idempotency-key")).toBe("k1");
    expect(ok.headers.get("cache-control")).toBe("private, no-store");
    const big = await handleCollegePortalRequest(req("/college-portal/api/colleges", { method: "POST", body: "x".repeat(1024 * 1024 + 1), headers: { "sec-fetch-site": "same-origin" } }), deps);
    expect(big.status).toBe(413);
  });

  it("filters response headers and sets cache policy", async () => {
    const fetchImpl = upstreamOk("<html></html>", {
      "content-type": "text/html; charset=utf-8",
      "set-cookie": "portal=1",
      server: "uvicorn",
      "content-security-policy": "default-src 'self'; frame-ancestors 'self'",
      "x-frame-options": "SAMEORIGIN",
      "cache-control": "public, max-age=600",
    });
    const res = await handleCollegePortalRequest(req("/college-portal/index.html"), { env: devEnv, config, fetchImpl, apiGet: apiGetFor() });
    expect(res.headers.get("set-cookie")).toBeNull();
    expect(res.headers.get("server")).toBeNull();
    expect(res.headers.get("content-security-policy")).toBe("default-src 'self'; frame-ancestors 'self'");
    expect(res.headers.get("x-frame-options")).toBe("SAMEORIGIN");
    expect(res.headers.get("cache-control")).toBe("private, no-store");
    expect(res.headers.get("x-content-type-options")).toBe("nosniff");
    expect(await res.text()).toBe("<html></html>");

    resetCollegePortalAuthCache();
    const asset = await handleCollegePortalRequest(req("/college-portal/assets/app.js"), { env: devEnv, config, fetchImpl: upstreamOk("x", { "content-type": "text/javascript" }), apiGet: apiGetFor() });
    expect(asset.headers.get("cache-control")).toBe("private, no-cache");
  });

  it("keeps upstream redirects under /college-portal and drops off-site ones", async () => {
    const deps = (location: string) => ({ env: devEnv, config, fetchImpl: upstreamOk("", { location }, 302), apiGet: apiGetFor() });
    expect((await handleCollegePortalRequest(req("/college-portal/x"), deps("/index.html"))).headers.get("location")).toBe("/college-portal/index.html");
    expect((await handleCollegePortalRequest(req("/college-portal/x"), deps("http://portal.internal:4173/a?b=1"))).headers.get("location")).toBe("/college-portal/a?b=1");
    expect((await handleCollegePortalRequest(req("/college-portal/x"), deps("https://evil.example/"))).headers.get("location")).toBeNull();
  });

  it("answers 502 when the portal is unreachable", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError("fetch failed");
    });
    const res = await handleCollegePortalRequest(req("/college-portal/api/colleges"), { env: devEnv, config, fetchImpl, apiGet: apiGetFor() });
    expect(res.status).toBe(502);
    expect(await res.json()).toEqual({ error: "College Data Portal is unavailable" });
  });

  it("names the user from profile, then email, then a fallback", () => {
    expect(displayNameOf({ user: { id: "1", email: "e@x" }, profile: { display_name: " ", full_name: "Full Name" } })).toBe("Full Name (e@x)");
    expect(displayNameOf({ user: { id: "1" }, profile: { full_name: "Full Name" } })).toBe("Full Name");
    expect(displayNameOf({ user: { id: "1", email: "e@x" }, profile: { display_name: "x".repeat(200) } })!.length).toBeLessThanOrEqual(100);
    expect(displayNameOf({ user: { id: "1", email: "e@x" } })).toBe("e@x");
    expect(displayNameOf(null)).toBe("LMS admin");
  });
});

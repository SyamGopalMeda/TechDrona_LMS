// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mintCsrfToken, verifyCsrfToken } from "@/lib/bff/csrf";
import { isPortalPath, safeNextPath } from "@/lib/nav/portals";
import { parseCsp } from "@/lib/security/csp";
import { config, middleware } from "./middleware";

const KEY = "m".repeat(64);

describe("middleware", () => {
  beforeEach(() => {
    vi.stubEnv("TD_CSRF_KEY", KEY);
    vi.stubEnv("NODE_ENV", "development");
  });
  afterEach(() => vi.unstubAllEnvs());

  it("redirects portal routes without a session cookie to /login with next", async () => {
    const res = await middleware(new NextRequest("http://localhost:3000/trainer/grading?tab=late"));
    expect(res.status).toBe(307);
    expect(res.headers.get("location")).toBe("http://localhost:3000/login?next=%2Ftrainer%2Fgrading%3Ftab%3Dlate");
  });

  it("treats the module hub and /continue as signed-in pages", async () => {
    const res = await middleware(new NextRequest("http://localhost:3000/continue?area=colleges"));
    expect(res.status).toBe(307);
    expect(res.headers.get("location")).toBe("http://localhost:3000/login?next=%2Fcontinue%3Farea%3Dcolleges");
    const hub = await middleware(new NextRequest("http://localhost:3000/modules"));
    expect(hub.headers.get("location")).toBe("http://localhost:3000/login?next=%2Fmodules");
  });

  it("lets portal routes through with a session cookie, no-store, CSP nonce and a session-bound CSRF cookie", async () => {
    const req = new NextRequest("http://localhost:3000/app", { headers: { cookie: "td_session=S1" } });
    const res = await middleware(req);
    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toBe("no-store");
    expect(res.headers.get("content-security-policy")).toMatch(/script-src 'self' 'nonce-[A-Za-z0-9+/=]+' 'strict-dynamic'/);
    const csrf = res.headers.getSetCookie().find((c) => c.startsWith("td_csrf="))!;
    expect(verifyCsrfToken([KEY], csrf.split(";")[0]!.slice("td_csrf=".length), "S1")).toBe(true);
  });

  it("forwards the requested path (deep links) and overwrites a spoofed value", async () => {
    const req = new NextRequest("http://localhost:3000/app/orders/42?tab=invoice", {
      headers: { cookie: "td_session=S1", "x-td-request-path": "//evil.example" },
    });
    const res = await middleware(req);
    expect(res.headers.get("x-middleware-request-x-td-request-path")).toBe("/app/orders/42?tab=invoice");
  });

  it("keeps a valid CSRF cookie and does not gate public pages", async () => {
    const token = mintCsrfToken(KEY, null);
    const res = await middleware(new NextRequest("http://localhost:3000/courses", { headers: { cookie: `td_csrf=${token}` } }));
    expect(res.status).toBe(200);
    expect(res.headers.getSetCookie()).toHaveLength(0);
    expect(res.headers.get("cache-control")).toBeNull();
  });
});

describe("middleware: College Data Portal", () => {
  beforeEach(() => vi.stubEnv("NODE_ENV", "development"));
  afterEach(() => vi.unstubAllEnvs());

  it("lets only /admin/college-data frame same-origin content", async () => {
    const page = await middleware(new NextRequest("http://localhost:3000/admin/college-data", { headers: { cookie: "td_session=S1" } }));
    const d = parseCsp(page.headers.get("content-security-policy")!);
    expect(d["frame-src"]).toContain("'self'");
    expect(d["frame-ancestors"]).toEqual(["'none'"]);
    const other = await middleware(new NextRequest("http://localhost:3000/admin/users", { headers: { cookie: "td_session=S1" } }));
    expect(parseCsp(other.headers.get("content-security-policy")!)["frame-src"]).not.toContain("'self'");
  });

  it("does not run on /college-portal (the route handler authenticates and keeps the portal's CSP)", () => {
    const source = config.matcher[0]!.source;
    const re = new RegExp(`^${source}$`);
    expect(re.test("/college-portal/index.html")).toBe(false);
    expect(re.test("/college-portal/api/colleges")).toBe(false);
    expect(re.test("/college-portal")).toBe(false);
    expect(re.test("/admin/college-data")).toBe(true);
    expect(re.test("/college-portals")).toBe(true);
  });
});

describe("middleware remember-device re-issue (AUTH-28, SEC-07)", () => {
  const REMEMBER = "r".repeat(43);
  const nav = { "sec-fetch-mode": "navigate", "sec-fetch-user": "?1" };

  beforeEach(() => {
    vi.stubEnv("TD_CSRF_KEY", KEY);
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("TD_API_INTERNAL_URL", "http://api.internal:8000");
    vi.stubEnv("TD_SERVICE_TOKEN", "svc-token");
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("re-issues the session on a top-level navigation and re-navigates to the same URL", async () => {
    const fetchMock = vi.fn(async () => {
      const headers = new Headers({ "content-type": "application/json" });
      headers.append("set-cookie", "__Host-td_session=NEW; Max-Age=86400; Path=/; Secure; HttpOnly; SameSite=Lax");
      headers.append("set-cookie", "__Host-td_remember=ROT; Max-Age=86400; Path=/; Secure; HttpOnly; SameSite=Lax");
      return new Response(JSON.stringify({ result: "authenticated" }), { status: 200, headers });
    });
    vi.stubGlobal("fetch", fetchMock);
    const res = await middleware(
      new NextRequest("http://localhost:3000/app/courses?x=1", {
        headers: { ...nav, cookie: `td_remember=${REMEMBER}; td_device=DEV` },
      }),
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(res.status).toBe(303);
    expect(res.headers.get("location")).toBe("http://localhost:3000/app/courses?x=1");
    const cookies = res.headers.getSetCookie();
    expect(cookies.some((c) => c.startsWith("td_session=NEW;"))).toBe(true);
    expect(cookies.some((c) => c.startsWith("td_remember=ROT;"))).toBe(true);
    const csrf = cookies.find((c) => c.startsWith("td_csrf="))!;
    expect(verifyCsrfToken([KEY], csrf.split(";")[0]!.slice("td_csrf=".length), "NEW")).toBe(true);
  });

  it("never calls AUTH-28 for background requests or prefetches", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    for (const headers of <Record<string, string>[]>[
      { cookie: `td_remember=${REMEMBER}` },
      { "sec-fetch-mode": "navigate", cookie: `td_remember=${REMEMBER}` },
      { ...nav, "next-router-prefetch": "1", cookie: `td_remember=${REMEMBER}` },
    ]) {
      const res = await middleware(new NextRequest("http://localhost:3000/app", { headers }));
      expect(res.status).toBe(307);
      expect(res.headers.get("location")).toContain("/login?next=");
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("clears a refused remember cookie and falls back to /login", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ code: "remember_invalid" }), { status: 401 })));
    const res = await middleware(
      new NextRequest("http://localhost:3000/app", { headers: { ...nav, cookie: `td_remember=${REMEMBER}` } }),
    );
    expect(res.status).toBe(307);
    expect(res.headers.get("location")).toBe("http://localhost:3000/login?next=%2Fapp");
    expect(res.headers.getSetCookie()).toEqual([expect.stringMatching(/^td_remember=; Path=\/; Max-Age=0/)]);
  });
});

describe("portal helpers", () => {
  it("matches portal prefixes exactly", () => {
    expect(isPortalPath("/app")).toBe(true);
    expect(isPortalPath("/app/tests")).toBe(true);
    expect(isPortalPath("/application")).toBe(false);
    expect(isPortalPath("/api/v1/me")).toBe(false);
    expect(isPortalPath("/security/cases")).toBe(true);
    expect(isPortalPath("/account/restricted")).toBe(false);
  });

  it("only allows same-origin relative redirect targets", () => {
    expect(safeNextPath("/app/tests")).toBe("/app/tests");
    expect(safeNextPath("//evil.example")).toBeNull();
    expect(safeNextPath("/\\evil.example")).toBeNull();
    expect(safeNextPath("https://evil.example")).toBeNull();
  });
});

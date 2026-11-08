// @vitest-environment node
import { describe, expect, it, vi } from "vitest";
import type { BffConfig } from "./config";
import { verifyCsrfToken } from "./csrf";
import { isTopLevelUserNavigation, refreshRememberedSession } from "./remember";

const KEY = "k".repeat(64);
const devEnv = { NODE_ENV: "development" } as NodeJS.ProcessEnv;
const REMEMBER = "r".repeat(43);

function config(overrides: Partial<BffConfig> = {}): BffConfig {
  return {
    apiInternalUrl: "http://api.internal:8000",
    serviceToken: "svc-token",
    csrfKeys: [KEY],
    publicOrigin: "http://localhost:3000",
    proxyTimeoutMs: 5000,
    originVerifyValue: "",
    trustedProxyHops: 1,
    cookieMode: "dev-insecure",
    ...overrides,
  };
}

const navHeaders = () =>
  new Headers({ "sec-fetch-mode": "navigate", "sec-fetch-user": "?1", "user-agent": "UA", "x-forwarded-for": "6.6.6.6, 203.0.113.9, 130.176.0.1" });

describe("isTopLevelUserNavigation", () => {
  it("requires navigate + user activation and no prefetch", () => {
    expect(isTopLevelUserNavigation(navHeaders())).toBe(true);
    expect(isTopLevelUserNavigation(new Headers({ "sec-fetch-mode": "navigate" }))).toBe(false);
    expect(isTopLevelUserNavigation(new Headers({ "sec-fetch-mode": "cors", "sec-fetch-user": "?1" }))).toBe(false);
    const pf = navHeaders();
    pf.set("next-router-prefetch", "1");
    expect(isTopLevelUserNavigation(pf)).toBe(false);
    const sp = navHeaders();
    sp.set("sec-purpose", "prefetch;prerender");
    expect(isTopLevelUserNavigation(sp)).toBe(false);
  });
});

describe("refreshRememberedSession (AUTH-28)", () => {
  it("calls AUTH-28 with the service token, device and client IP, and re-issues cookies under BFF names", async () => {
    const fetchImpl = vi.fn(async (_u: string | URL | Request, _i?: RequestInit) => {
      const headers = new Headers({ "content-type": "application/json" });
      headers.append("set-cookie", "__Host-td_session=NEWSESS; Max-Age=86400; Path=/; Secure; HttpOnly; SameSite=Lax");
      headers.append("set-cookie", "__Host-td_remember=NEWREM; Max-Age=2000000; Path=/; Secure; HttpOnly; SameSite=Lax");
      headers.append("set-cookie", "__Host-td_csrf=evil; Path=/");
      return new Response(JSON.stringify({ result: "authenticated", session: { id: "s" } }), { status: 200, headers });
    });
    const out = await refreshRememberedSession(navHeaders(), REMEMBER, "DEV", { config: config(), env: devEnv, fetchImpl });
    expect(out.kind).toBe("refreshed");
    const [url, init] = fetchImpl.mock.calls[0]!;
    expect(String(url)).toBe("http://api.internal:8000/api/v1/auth/remember/refresh");
    expect(init!.method).toBe("POST");
    const h = new Headers(init!.headers);
    expect(h.get("authorization")).toBe("Service svc-token");
    expect(h.get("x-td-device")).toBe("DEV");
    expect(h.get("cookie")).toBe(`__Host-td_remember=${REMEMBER}; __Host-td_device=DEV`);
    expect(h.get("x-td-client-ip")).toBe("203.0.113.9");
    expect(JSON.parse(String(init!.body))).toEqual({ remember_token: REMEMBER });
    expect(out.setCookies.some((c) => c.startsWith("td_session=NEWSESS;") && c.includes("HttpOnly"))).toBe(true);
    expect(out.setCookies.some((c) => c.startsWith("td_remember=NEWREM;"))).toBe(true);
    const csrf = out.setCookies.filter((c) => c.startsWith("td_csrf="));
    expect(csrf).toHaveLength(1);
    expect(verifyCsrfToken([KEY], csrf[0]!.split(";")[0]!.slice("td_csrf=".length), "NEWSESS")).toBe(true);
  });

  it("clears the remember cookie when the api refuses it", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ code: "remember_invalid" }), { status: 401 }));
    const out = await refreshRememberedSession(navHeaders(), REMEMBER, "DEV", { config: config(), env: devEnv, fetchImpl });
    expect(out.kind).toBe("invalid");
    expect(out.setCookies).toEqual([expect.stringMatching(/^td_remember=; Path=\/; Max-Age=0; HttpOnly; SameSite=Lax$/)]);
  });

  it("does not set cookies when the api needs another login step or is unreachable", async () => {
    const pending = vi.fn(async () => {
      const headers = new Headers({ "content-type": "application/json" });
      headers.append("set-cookie", "__Host-td_session=PENDING; Path=/");
      return new Response(JSON.stringify({ result: "device_otp_required" }), { status: 200, headers });
    });
    expect(await refreshRememberedSession(navHeaders(), REMEMBER, "DEV", { config: config(), env: devEnv, fetchImpl: pending })).toEqual({ kind: "unavailable", setCookies: [] });
    const down = vi.fn(async () => {
      throw new TypeError("fetch failed");
    });
    expect(await refreshRememberedSession(navHeaders(), REMEMBER, "DEV", { config: config(), env: devEnv, fetchImpl: down })).toEqual({ kind: "unavailable", setCookies: [] });
    const noToken = vi.fn();
    expect((await refreshRememberedSession(navHeaders(), REMEMBER, "DEV", { config: config({ serviceToken: "" }), env: devEnv, fetchImpl: noToken })).kind).toBe("unavailable");
    expect(noToken).not.toHaveBeenCalled();
  });
});

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { configurePortalApi, isPortalApiError, portalApi, portalUrl, resetPortalApiForTests, type PortalApiError } from "./api";
import { clearPortalCacheForTests, fetchCached, peekCached } from "./cache";
import { matchPortalRoute, resolveAlias, searchHitHref, toPortalHref } from "./routes";
import { SCOPE_KEY, getScope, parseScopeQuery, resetScopeForTests, scopeLabel, scopeParam, setDistrictScope, setScopeContext } from "./scope";
import { mergeQuery, historyModeFor } from "./query";
import { fmt } from "./fmt";
import { collegesCsp, hostingHeaders } from "@/spa/hosting-headers";
import { isCollegesPath } from "@/spa/nav-store";

function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });
}

beforeEach(() => {
  localStorage.clear();
  resetScopeForTests();
  resetPortalApiForTests();
  clearPortalCacheForTests();
});
afterEach(() => vi.restoreAllMocks());

describe("district scope", () => {
  it("defaults to the 7 target districts and persists choices", () => {
    expect(getScope()).toEqual({ all: false, ids: ["guntur", "palnadu", "bapatla", "krishna", "ntr", "west-godavari", "eluru"], isDefault: true });
    expect(scopeLabel()).toBe("Guntur · Krishna · West Godavari");
    expect(setDistrictScope(["guntur", "ntr"])).toBe(true);
    expect(localStorage.getItem(SCOPE_KEY)).toBe('["guntur","ntr"]');
    expect(scopeParam()).toBe("guntur,ntr");
    expect(scopeLabel()).toBe("Guntur · Ntr");
    setScopeContext({ districts: [{ id: "ntr", name: "NTR" }] });
    expect(scopeLabel()).toBe("Guntur · NTR");
    setDistrictScope("all");
    expect(getScope().all).toBe(true);
    expect(scopeParam()).toBeUndefined();
    expect(localStorage.getItem(SCOPE_KEY)).toBe("all");
  });

  it("stores the target list as the default and parses ?d=", () => {
    setDistrictScope("ntr,krishna,guntur,palnadu,bapatla,eluru,west-godavari");
    expect(localStorage.getItem(SCOPE_KEY)).toBeNull();
    expect(getScope().isDefault).toBe(true);
    expect(parseScopeQuery("all")).toBe("all");
    expect(parseScopeQuery("target")).toBe("target");
    expect(parseScopeQuery("guntur,nowhere", new Set(["guntur"]))).toEqual(["guntur"]);
    expect(parseScopeQuery("nowhere", new Set(["guntur"]))).toBeNull();
  });

  it("keeps the same snapshot object until the scope changes", () => {
    const a = getScope();
    setScopeContext({ districts: [{ id: "guntur", name: "Guntur" }] });
    expect(getScope()).toBe(a);
    setDistrictScope(["guntur"]);
    expect(getScope()).not.toBe(a);
  });
});

describe("portal API client", () => {
  it("builds /college-portal/api URLs with readable comma lists", () => {
    expect(portalUrl("/colleges", { districts: ["guntur", "ntr"], q: "", page: 2 })).toBe("/college-portal/api/colleges?districts=guntur,ntr&page=2");
    expect(portalUrl("api/meta")).toBe("/college-portal/api/meta");
  });

  it("adds the scope to scoped reads and flags a rejected scope", async () => {
    setDistrictScope(["guntur"]);
    const fetchImpl = vi.fn().mockResolvedValueOnce(json(200, [])).mockResolvedValueOnce(json(400, { error: "Unknown district", fields: { districts: "Unknown district: x" } }));
    const onScopeRejected = vi.fn();
    configurePortalApi({ fetchImpl, onScopeRejected });
    await portalApi.get("colleges", { scoped: true, query: { q: "kl" } });
    expect(fetchImpl.mock.calls[0]![0]).toBe("/college-portal/api/colleges?districts=guntur&q=kl");
    const err = (await portalApi.get("summary", { scoped: true }).catch((e: unknown) => e)) as PortalApiError;
    expect(err.code).toBe("scope_rejected");
    expect(onScopeRejected).toHaveBeenCalledOnce();
  });

  it("401 → signed-out hook; 403 forbidden → admins only", async () => {
    const onSignedOut = vi.fn();
    configurePortalApi({
      onSignedOut,
      fetchImpl: vi.fn().mockResolvedValueOnce(json(401, { code: "auth_required" })).mockResolvedValueOnce(json(403, { error: "Admins only", code: "forbidden" })),
    });
    const e1 = await portalApi.get("meta").catch((e: unknown) => e);
    expect(isPortalApiError(e1) && e1.isSignedOut).toBe(true);
    expect(onSignedOut).toHaveBeenCalledOnce();
    const e2 = (await portalApi.get("meta").catch((e: unknown) => e)) as PortalApiError;
    expect(e2.isAdminsOnly).toBe(true);
    expect(e2.message).toBe("The College Data Portal is available to LMS admins only.");
  });

  it("writes send an Idempotency-Key, keep it after a network failure and spend it after an HTTP error", async () => {
    const fetchImpl = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("offline"))
      .mockResolvedValueOnce(json(400, { error: "Please fix", fields: { name: "Required" } }))
      .mockResolvedValueOnce(json(201, { id: 1 }));
    const onNetwork = vi.fn();
    configurePortalApi({ fetchImpl, onNetwork });
    const key = "k-1";
    const e0 = (await portalApi.post("people", { a: 1 }, { idempotencyKey: key }).catch((e: unknown) => e)) as PortalApiError;
    expect(e0.status).toBe(0);
    expect(onNetwork).toHaveBeenCalledWith(false);
    const e1 = (await portalApi.post("people", { a: 1 }, { idempotencyKey: key }).catch((e: unknown) => e)) as PortalApiError;
    expect(e1.fields).toEqual({ name: "Required" });
    await portalApi.post("people", { a: 1 }, { idempotencyKey: key });
    const keys = fetchImpl.mock.calls.map((c) => (c[1] as RequestInit & { headers: Record<string, string> }).headers["idempotency-key"]);
    expect(keys[0]).toBe(key);
    expect(keys[1]).toBe(key);
    expect(keys[2]).not.toBe(key);
    expect((fetchImpl.mock.calls[0]![1] as RequestInit).credentials).toBe("same-origin");
  });
});

describe("read cache", () => {
  it("de-duplicates concurrent reads, serves fresh answers and clears on writes", async () => {
    const fetchImpl = vi.fn().mockImplementation(async (url: string) => (url.includes("people") ? json(201, {}) : json(200, { n: 1 })));
    configurePortalApi({ fetchImpl });
    const [a, b] = await Promise.all([fetchCached("meta"), fetchCached("meta")]);
    expect(a).toEqual({ n: 1 });
    expect(b).toBe(a);
    await fetchCached("meta");
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(peekCached("meta")?.data).toEqual({ n: 1 });
    await portalApi.post("people", {});
    expect(peekCached("meta")).toBeUndefined();
  });
});

describe("routes", () => {
  it("maps old hash links and aliases to the new paths", () => {
    expect(toPortalHref("#/")).toBe("/colleges");
    expect(toPortalHref("#/college/c9?tab=people")).toBe("/colleges/college/c9?tab=people");
    expect(toPortalHref("#/team")).toBe("/colleges/people");
    expect(toPortalHref("/admin")).toBe("/admin");
    expect(resolveAlias("/colleges/reports")).toBe("/colleges/analytics");
    expect(resolveAlias("/colleges/home")).toBe("/colleges");
    expect(resolveAlias("/colleges/nope")).toBeNull();
    expect(searchHitHref({ type: "district", id: "ntr" })).toBe("/colleges/d/ntr");
  });

  it("matches screens with their nav item and params", () => {
    expect(matchPortalRoute("/colleges")?.route.nav).toBe("home");
    const m = matchPortalRoute("/colleges/d/guntur/guntur--tenali");
    expect(m?.route.title).toBe("Town");
    expect(m?.params).toEqual({ district: "guntur", city: "guntur--tenali" });
    expect(matchPortalRoute("/colleges/followups")?.route.section).toBe("calls");
    expect(matchPortalRoute("/admin")).toBeNull();
  });
});

describe("query + format helpers", () => {
  it("merges query patches and picks the history mode", () => {
    expect(mergeQuery("?d=all&page=2", { page: null, status: "open", ids: ["a", "b"] })).toBe("?d=all&status=open&ids=a,b");
    expect(historyModeFor({ q: "a" }, { q: "ab" })).toBe("replace");
    expect(historyModeFor({}, { status: "done" })).toBe("push");
    expect(fmt.pctPts(4.75)).toBe("4.8%");
    expect(fmt.num(123456)).toBe("1,23,456");
  });
});

describe("hosting", () => {
  it("serves /colleges with the map tiles allowed and loads it as its own document", () => {
    const csp = collegesCsp({});
    expect(csp).toMatch(/img-src [^;]*https:\/\/tile\.openstreetmap\.org/);
    const rule = hostingHeaders({}).find((r) => r.source === "/colleges/**");
    expect(rule?.headers[0]?.value).toBe(csp);
    expect(isCollegesPath("/colleges/college/c9")).toBe(true);
    expect(isCollegesPath("/college-portal/index.html")).toBe(false);
  });
});

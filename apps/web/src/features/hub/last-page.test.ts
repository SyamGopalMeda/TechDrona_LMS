import { afterEach, describe, expect, it } from "vitest";
import {
  LAST_PAGE_KEY,
  LAST_PAGE_MAX_AGE_MS,
  allowedFor,
  areaOf,
  clearLastPage,
  continueFallback,
  continueHref,
  isTrackablePath,
  needsDocumentLoad,
  pickContinueTarget,
  readLastPage,
  recordLastPage,
} from "./last-page";

const NOW = 1_800_000_000_000;
const ADMIN = ["/admin", "/app"];

afterEach(() => window.localStorage.clear());

describe("last-page store", () => {
  it("records portal pages with their query string", () => {
    recordLastPage("/admin/users?status=active", NOW);
    expect(readLastPage()).toEqual({ path: "/admin/users?status=active", at: NOW });
    recordLastPage("/finance/orders/42", NOW + 1);
    expect(readLastPage()?.path).toBe("/finance/orders/42");
  });

  it("never records sign-in, hub, continue, sso or public pages", () => {
    recordLastPage("/admin", NOW);
    for (const p of ["/login", "/login/mfa", "/modules", "/continue?area=lms", "/sso/website", "/", "/courses/java", "/application", "/administrator"]) {
      recordLastPage(p, NOW + 5);
      expect(readLastPage()).toEqual({ path: "/admin", at: NOW });
    }
    expect(isTrackablePath("/read/abc")).toBe(true);
    expect(isTrackablePath("/college-portal/index.html")).toBe(false);
  });

  it("rejects unsafe paths and survives junk in storage", () => {
    recordLastPage("/admin/a b", NOW);
    expect(readLastPage()).toBeNull();
    window.localStorage.setItem(LAST_PAGE_KEY, "{not json");
    expect(readLastPage()).toBeNull();
    window.localStorage.setItem(LAST_PAGE_KEY, JSON.stringify({ path: 5 }));
    expect(readLastPage()).toBeNull();
  });

  it("clears on sign-out", () => {
    recordLastPage("/trainer/batches", NOW);
    clearLastPage();
    expect(readLastPage()).toBeNull();
  });
});

describe("pickContinueTarget", () => {
  const pick = (path: string | null, opts: { area?: "lms" | "colleges"; portals?: string[] | null; at?: number } = {}) =>
    pickContinueTarget({
      record: path ? { path, at: opts.at ?? NOW - 1000 } : null,
      area: opts.area,
      portals: opts.portals === undefined ? ADMIN : opts.portals,
      fallback: "/fallback",
      now: NOW,
    });

  it("resumes the remembered page", () => {
    expect(pick("/admin/users?status=active")).toBe("/admin/users?status=active");
    expect(pick("/finance/orders", { area: "lms" })).toBe("/finance/orders");
    expect(pick("/admin/college-data", { area: "colleges" })).toBe("/admin/college-data");
  });

  it("filters by area", () => {
    expect(pick("/admin/college-data", { area: "lms" })).toBe("/fallback");
    expect(pick("/admin/users", { area: "colleges" })).toBe("/fallback");
    expect(areaOf("/admin/college-data?x=1")).toBe("colleges");
    expect(areaOf("/admin/college-dataset")).toBe("lms");
  });

  it("falls back when nothing usable is remembered", () => {
    expect(pick(null)).toBe("/fallback");
    expect(pick("/admin", { at: NOW - LAST_PAGE_MAX_AGE_MS - 1 })).toBe("/fallback");
    expect(pick("/modules")).toBe("/fallback");
    expect(pick("//evil.example/admin")).toBe("/fallback");
    expect(pick("/admin", { portals: null })).toBe("/fallback");
  });

  it("never resumes a page this account cannot open (shared browser)", () => {
    expect(pick("/admin/users", { portals: ["/trainer"] })).toBe("/fallback");
    expect(pick("/trainer/batches", { portals: ["/trainer"] })).toBe("/trainer/batches");
    expect(allowedFor("/security/cases", ["/admin"])).toBe(true);
    expect(allowedFor("/studio", ["/admin"])).toBe(false);
    expect(allowedFor("/app/tests", ["/trainer"])).toBe(true);
  });

  it("never sends a student to a staff portal: a remembered /admin page or an /admin fallback lands on /app", () => {
    const go = (fallback: string, path: string | null) =>
      pickContinueTarget({ record: path ? { path, at: NOW - 1000 } : null, area: "lms", portals: ["/app"], fallback, now: NOW });
    expect(go("/modules", "/admin/users")).toBe("/modules");
    expect(go("/admin", "/admin/users")).toBe("/app");
    expect(go("/admin", null)).toBe("/app");
    expect(go("/app/learning", null)).toBe("/app/learning");
    expect(go("/trainer", null)).toBe("/app");
  });
});

describe("continue helpers", () => {
  it("accepts only portal or hub fallbacks", () => {
    expect(continueFallback("lms", "/trainer")).toBe("/trainer");
    expect(continueFallback("lms", "https://evil.example")).toBe("/modules");
    expect(continueFallback("lms", "/login")).toBe("/modules");
    expect(continueFallback("colleges", undefined)).toBe("/college-portal/index.html");
    expect(continueFallback(undefined, "/modules")).toBe("/modules");
  });

  it("builds links", () => {
    expect(continueHref()).toBe("/continue");
    expect(continueHref("colleges", "/admin/college-data")).toBe("/continue?area=colleges&fallback=%2Fadmin%2Fcollege-data");
  });

  it("opens the College Data Portal as a document", () => {
    expect(needsDocumentLoad("/admin/college-data")).toBe(true);
    expect(needsDocumentLoad("/admin/users")).toBe(false);
  });
});

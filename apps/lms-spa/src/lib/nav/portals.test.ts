import { describe, expect, it } from "vitest";
import { searchNav } from "@/components/shell/PortalNav";
import { ACCOUNT_SETTINGS_HREF, PORTALS, safeNextPath, signInNext, visibleNav } from "./portals";

describe("portal registry (w3web)", () => {
  it("SEC-04: safeNextPath uses the hardened guard", () => {
    expect(safeNextPath("/app/orders/42?tab=x")).toBe("/app/orders/42?tab=x");
    expect(safeNextPath("//evil.example")).toBeNull();
    expect(safeNextPath("/\t/evil.example")).toBeNull();
    expect(safeNextPath("/%2F/x")).toBe("/%2F/x");
    expect(safeNextPath("/api/v1/me")).toBeNull();
    expect(safeNextPath("https://evil.example")).toBeNull();
    expect(safeNextPath(null)).toBeNull();
  });

  it("PortalShell sign-in redirect keeps the deep link only inside the portal", () => {
    expect(signInNext("/app/orders/42?tab=invoice", "/app")).toBe("/app/orders/42?tab=invoice");
    expect(signInNext("/application", "/app")).toBe("/app");
    expect(signInNext("/admin/users", "/app")).toBe("/app");
    expect(signInNext("//evil.example", "/app")).toBe("/app");
    expect(signInNext(null, "/evaluator")).toBe("/evaluator");
  });

  it("has no duplicate hrefs in any portal and hides unbuilt screens", () => {
    for (const p of Object.values(PORTALS)) {
      const hrefs = p.nav.map((n) => n.href);
      expect(new Set(hrefs).size).toBe(hrefs.length);
    }
    const all = Object.values(PORTALS).flatMap((p) => p.nav.map((n) => n.href));
    expect(all).not.toContain("/app/analytics");
    expect(all).not.toContain("/admin/notifications");
    for (const gone of ["/college", "/college/shortlists", "/app/college", "/admin/organizations", "/finance/contracts", "/security/networks"]) expect(all).not.toContain(gone);
    // Removed 2026-11-14 (docs/cleanup/feature-removal-plan.md): the pages no longer exist.
    for (const gone of ["/mentor", "/mentor/students", "/mentor/slots", "/mentor/resume-reviews", "/app/mentoring", "/app/companies", "/studio/companies", "/app/diagnostic", "/desk/enquiries", "/admin/question-review", "/security/policies"]) {
      expect(all, gone).not.toContain(gone);
    }
    expect(Object.keys(PORTALS)).not.toContain("mentor");
  });

  it("lists the learner and security pages", () => {
    const student = PORTALS.student.nav.map((n) => n.href);
    expect(student).toEqual(expect.arrayContaining(["/app/notifications", "/app/path/my", "/app/interview-prep", "/app/resume"]));
    // "Learning path" duplicated the dashboard + "My paths"; account status moved to the account menu.
    expect(student).not.toContain("/app/path");
    expect(student).not.toContain("/app/account-status");
    const security = PORTALS.security.nav.map((n) => n.href);
    expect(security).toEqual(expect.arrayContaining(["/security/incidents", "/security/cases"]));
  });

  it("D2: the Admin portal absorbs finance, support and security", () => {
    expect(Object.keys(PORTALS)).not.toContain("college");
    const admin = PORTALS.admin.nav;
    expect(PORTALS.admin.title).toBe("Admin");
    expect(admin.map((n) => n.href)).toEqual(expect.arrayContaining(["/admin/batches", "/admin/ai", "/finance", "/desk", "/security"]));
    expect([...new Set(admin.map((n) => n.section))]).toEqual(["Overview", "People", "Colleges", "Website", "Learning", "Payments", "Support", "Security", "Settings"]);
    expect(admin.find((n) => n.href === "/admin/ai")?.label).toBe("Apps");
    for (const key of ["finance", "support", "security"] as const) {
      expect(PORTALS[key].roles).toEqual(["super_admin"]);
      expect(PORTALS[key].parent).toBe("admin");
      expect(PORTALS[key].nav).toBe(PORTALS.admin.nav);
    }
  });

  it("links the College Data Portal once, as Colleges Data in its own Colleges section", () => {
    const admin = PORTALS.admin.nav;
    const i = admin.findIndex((n) => n.href === "/college-portal/index.html");
    expect(admin[i]).toEqual({ href: "/college-portal/index.html", label: "Colleges Data", screen: "ADM-015", section: "Colleges", documentNav: true });
    expect(admin.filter((n) => n.screen === "ADM-015")).toHaveLength(1);
    expect(admin.filter((n) => n.section === "Colleges")).toHaveLength(1);
  });

  it("groups every nav item that has sections, with one entry per page and plain labels", () => {
    for (const p of Object.values(PORTALS)) {
      const sections = p.nav.map((n) => n.section);
      // A section is one contiguous run (PortalNav groups consecutive items).
      const runs = sections.filter((s, i) => s && s !== sections[i - 1]);
      expect(new Set(runs).size, p.key).toBe(runs.length);
      for (const n of p.nav) expect(n.label, n.href).not.toMatch(/\(|[A-Z]\d+–[A-Z]\d+/);
    }
    const admin = PORTALS.admin.nav;
    expect(admin.every((n) => n.section)).toBe(true);
    expect(admin.filter((n) => /approvals/i.test(n.label))).toHaveLength(1);
    expect(admin.filter((n) => /polic/i.test(n.label))).toHaveLength(1);
    const student = PORTALS.student.nav;
    expect([...new Set(student.map((n) => n.section).filter(Boolean))]).toEqual(["Learn", "Practice & tests", "Placement", "Account"]);
  });

  it("has an Evaluator portal with grading screens only", () => {
    expect(PORTALS.evaluator.prefix).toBe("/evaluator");
    expect(PORTALS.evaluator.roles).toEqual(["evaluator"]);
    expect(PORTALS.evaluator.nav.map((n) => n.label)).toEqual(["Grading", "Tests", "Integrity flags", "Account settings"]);
  });
});

/* Live audit 2026-11-14 (docs/qa/live-audit/fixes-nav.md): what the sidebar actually lists. */
describe("visibleNav (live audit nav cleanup)", () => {
  const hrefs = (items: { href: string }[]) => items.map((i) => i.href);
  const GATEWAY = ["/finance", "/finance/orders", "/finance/refunds", "/finance/subscriptions", "/finance/invoices", "/finance/products", "/finance/coupons", "/finance/reconciliation"];

  it("admin: about two dozen items, no gateway, duplicates or engineering tools", () => {
    const shown = visibleNav(PORTALS.admin.nav, { connected: { payments: false } });
    // 25 after the live audit + People › Import students (student management, 2026-11-14).
    expect(shown.length).toBeLessThanOrEqual(26);
    const h = hrefs(shown);
    for (const gone of [...GATEWAY, "/security/unblock-requests", "/security/rules", "/security/reports", "/admin/feature-flags", "/admin/break-glass"]) {
      expect(h, gone).not.toContain(gone);
    }
    for (const kept of ["/admin", "/admin/approvals", "/admin/users", "/admin/roles", "/admin/courses", "/admin/batches", "/admin/certificates", "/finance/admissions", "/finance/admissions/verify", "/finance/admissions/registrations", "/finance/admissions/plans", "/desk", "/desk/unblock-requests", "/security", "/security/incidents", "/security/cases", "/security/restrictions", "/admin/audit", "/admin/policies", "/admin/system", "/college-portal/index.html", ACCOUNT_SETTINGS_HREF]) {
      expect(h, kept).toContain(kept);
    }
    expect([...new Set(shown.map((n) => n.section))]).toEqual(["Overview", "People", "Colleges", "Website", "Learning", "Payments", "Support", "Security", "Settings"]);
    // "Find a page" → "settings" finds the shared account page.
    expect(shown.filter((n) => /settings/i.test(n.label)).map((n) => n.href)).toEqual([ACCOUNT_SETTINGS_HREF]);
  });

  it("admin: the gateway pages come back once payments are connected, and stay hidden while unknown", () => {
    expect(hrefs(visibleNav(PORTALS.admin.nav, { connected: { payments: true } }))).toEqual(expect.arrayContaining(GATEWAY));
    expect(hrefs(visibleNav(PORTALS.admin.nav, { connected: null }))).not.toContain("/finance/orders");
    expect(hrefs(visibleNav(PORTALS.admin.nav))).not.toContain("/finance/orders");
  });

  it("keeps every hidden page in the registry (its route and title still exist)", () => {
    const all = hrefs(PORTALS.admin.nav);
    for (const h of [...GATEWAY, "/admin/feature-flags", "/admin/break-glass", "/security/rules"]) expect(all).toContain(h);
  });

  it("student: 13–15 items, nothing empty or duplicated by the header; tab bar targets stay listed", () => {
    // The sidebar lists what visibleNav keeps minus the `searchOnly` items (PortalNav).
    const shown = visibleNav(PORTALS.student.nav, { connected: {} }).filter((i) => !i.searchOnly);
    expect(shown.length).toBeGreaterThanOrEqual(13);
    expect(shown.length).toBeLessThanOrEqual(15);
    const h = hrefs(shown);
    for (const gone of ["/app/billing", "/app/access", "/app/path/my", "/app/notifications", ACCOUNT_SETTINGS_HREF]) expect(h, gone).not.toContain(gone);
    for (const kept of ["/app", "/app/learning", "/app/practice", "/app/tests", "/app/courses", "/app/registrations", "/app/certificates", "/app/interview-prep", "/app/resume", "/app/support"]) expect(h, kept).toContain(kept);
  });

  it("staff portals list the account settings page for Find a page", () => {
    for (const key of ["trainer", "evaluator", "studio", "admin"] as const) {
      expect(hrefs(visibleNav(PORTALS[key].nav)), key).toContain(ACCOUNT_SETTINGS_HREF);
    }
  });

  it("Find a page: settings and profile find the account page for every role; marks find grading", () => {
    for (const key of ["student", "trainer", "evaluator", "studio", "admin"] as const) {
      const items = visibleNav(PORTALS[key].nav, { connected: {} });
      for (const q of ["settings", "profile", "password"]) expect(hrefs(searchNav(items, q)), `${key}: ${q}`).toContain(ACCOUNT_SETTINGS_HREF);
    }
    expect(hrefs(searchNav(visibleNav(PORTALS.trainer.nav), "marks"))[0]).toBe("/trainer/grading");
    expect(hrefs(searchNav(visibleNav(PORTALS.evaluator.nav), "mark"))[0]).toBe("/evaluator");
    expect(hrefs(searchNav(visibleNav(PORTALS.student.nav, { connected: {} }), "marks"))[0]).toBe("/app/progress");
  });

  it("`only` keeps the listed pages plus account settings", () => {
    expect(hrefs(visibleNav(PORTALS.studio.nav, { only: ["/studio/courses", "/studio/review"] }))).toEqual(["/studio/review", "/studio/courses", ACCOUNT_SETTINGS_HREF]);
  });
});

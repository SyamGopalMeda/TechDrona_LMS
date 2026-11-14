import { describe, expect, it } from "vitest";
import { PORTALS, safeNextPath, signInNext } from "./portals";

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

  it("D2: the Admin portal absorbs finance, support, security and mentoring", () => {
    expect(Object.keys(PORTALS)).not.toContain("college");
    const admin = PORTALS.admin.nav;
    expect(PORTALS.admin.title).toBe("Admin");
    expect(admin.map((n) => n.href)).toEqual(expect.arrayContaining(["/admin/batches", "/admin/ai", "/finance", "/desk", "/security", "/mentor"]));
    expect([...new Set(admin.map((n) => n.section))]).toEqual(["Overview", "People", "Colleges", "Website", "Learning", "Mentoring", "Payments", "Support", "Security", "Settings"]);
    for (const key of ["finance", "support", "security", "mentor"] as const) {
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
    expect(PORTALS.evaluator.nav.map((n) => n.label)).toEqual(["Grading", "Tests", "Integrity flags"]);
  });
});

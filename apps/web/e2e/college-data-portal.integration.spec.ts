import { expect, test, type APIResponse } from "@playwright/test";
import { account, signIn } from "./support/auth";

/**
 * ADM-015 College Data Portal embedded in the Admin portal (proxied same-origin under /college-portal/).
 * Needs the LMS web + api + the portal running in proxy mode (TD_COLLEGE_PORTAL_URL / _SECRET).
 *   E2E_INTEGRATION=1 npx playwright test e2e/college-data-portal.integration.spec.ts --project=chromium --workers=1
 * Env: E2E_ADMIN_* (super admin with TOTP), E2E_STUDENT_* (no staff grants).
 * Writes: one follow-up is created and deleted again (the portal audit log keeps both entries).
 */
const enabled = !!process.env.E2E_INTEGRATION;

function csp(res: APIResponse): string {
  return res.headers()["content-security-policy"] ?? "";
}
function directive(policy: string, name: string): string {
  return policy.split(";").map((d) => d.trim()).find((d) => d.startsWith(`${name} `)) ?? "";
}

interface College { id: string; name: string; short_name?: string | null }
/** Evidence for the report (Playwright annotation; console.log is not allowed by lint). */
const note = (...parts: unknown[]) => test.info().annotations.push({ type: "evidence", description: parts.map(String).join(" ") });

interface AuditRow { id: number; actor: string; action: string; entity: string; entity_id: string | number }

test.describe("College Data Portal in the Admin portal", { tag: "@integration" }, () => {
  test.skip(!enabled, "set E2E_INTEGRATION=1 with the api and the portal running");

  test("unauthenticated: page redirects to login, portal api is 401", async ({ page }) => {
    await page.goto("/admin/college-data");
    await page.waitForURL((u) => u.pathname === "/login");
    expect(new URL(page.url()).search).toBe("?next=%2Fadmin%2Fcollege-data");

    const api = await page.request.get("/college-portal/api/colleges");
    expect(api.status()).toBe(401);
    expect((await api.json()).code).toBe("auth_required");

    const entry = await page.request.get("/college-portal/index.html", { maxRedirects: 0, headers: { accept: "text/html", "sec-fetch-dest": "document" } });
    expect(entry.status()).toBe(303);
    expect(entry.headers()["location"]).toBe("/login?next=%2Fadmin%2Fcollege-data");
  });

  test("admin: embedded portal, data round trip, security headers, LMS smoke, logout", async ({ page, request }) => {
    test.setTimeout(180_000);
    const admin = account("ADMIN");
    test.skip(!admin, "set E2E_ADMIN_*");
    await signIn(page, request, admin!, "/admin");
    await page.waitForURL((u) => u.pathname.startsWith("/admin"));
    const origin = new URL(page.url()).origin;

    let adminName = "";
    let colleges: College[] = [];

    await test.step("sidebar link → /admin/college-data → iframe shell without sign-in", async () => {
      const link = page.getByRole("link", { name: "College Data Portal" });
      await expect(link).toBeVisible();
      await link.click();
      await page.waitForURL((u) => u.pathname === "/admin/college-data");
      await expect(page.getByRole("heading", { level: 1, name: "College Data Portal" })).toBeVisible();

      const session = await page.request.get("/college-portal/api/session");
      expect(session.status()).toBe(200);
      const s = await session.json();
      note("[portal] api/session =", JSON.stringify(s));
      expect(s.sso).toBe(true);
      expect(s.role).toBe("editor");
      adminName = String(s.user ?? "");
      expect(adminName).not.toBe("");
      // The audit actor is "Name (email)": display names are neither unique nor fixed.
      expect(adminName).toMatch(/^.+ [(].+@.+[)]$/);

      // Also check a plain reload of /admin/college-data (the sidebar click is covered below).
      await page.reload();
      const frame = page.frameLocator('iframe[title="College Data Portal"]');
      const userBtn = frame.locator("button.td-user");
      await expect(userBtn).toBeVisible({ timeout: 20_000 });
      await expect(userBtn.locator(".td-user__name")).toHaveText(adminName);
      await expect(frame.locator("#td-login-pass")).toHaveCount(0);
      await expect(frame.getByText(/team passcode/i)).toHaveCount(0);

      const list = await page.request.get("/college-portal/api/colleges?op_status=");
      expect(list.status()).toBe(200);
      const body = await list.json();
      colleges = Array.isArray(body) ? body : body.items;
      note("[portal] colleges via api =", colleges.length);
      expect(colleges.length).toBeGreaterThanOrEqual(150);

      // Inside the portal: navigate to the colleges list (hash route) via its own nav.
      await frame.locator('a[href="#/colleges"]').first().click();
      await expect(frame.getByRole("heading", { level: 1, name: "Colleges" })).toBeVisible({ timeout: 20_000 });
      const names = new Set(colleges.flatMap((c) => [c.name, c.short_name].filter(Boolean) as string[]));
      const rows = frame.locator("table tbody tr");
      await expect.poll(async () => rows.count(), { timeout: 20_000 }).toBeGreaterThanOrEqual(10);
      const firstRowText = (await rows.first().innerText()).trim();
      expect([...names].some((n) => firstRowText.includes(n)), `first row "${firstRowText.slice(0, 80)}" names a DB college`).toBe(true);
      note("[portal] UI rows on first page =", await rows.count());
    });

    await test.step("data round trip: create, read back, delete a follow-up; audit actor", async () => {
      const headers = { Origin: origin, "Content-Type": "application/json" };
      const title = `E2E follow-up ${Date.now()}`;
      const created = await page.request.post("/college-portal/api/followups", {
        headers,
        data: { scope_type: "college", scope_id: colleges[0]!.id, title, issue: "other", due_date: "2026-12-31" },
      });
      expect(created.status(), await created.text()).toBeLessThan(300);
      const row = await created.json();
      const id = row.id ?? row.followup?.id;
      expect(id).toBeTruthy();

      const open = await page.request.get("/college-portal/api/followups?status=open");
      expect(open.status()).toBe(200);
      const openRows = await open.json();
      const found = (Array.isArray(openRows) ? openRows : openRows.items).find((f: { id: number }) => f.id === id);
      expect(found?.title).toBe(title);
      expect(found?.created_by).toBe(adminName);

      const del = await page.request.delete(`/college-portal/api/followups/${id}`, { headers: { Origin: origin } });
      expect(del.status(), await del.text()).toBeLessThan(300);

      const audit = await page.request.get("/college-portal/api/audit?limit=5");
      expect(audit.status()).toBe(200);
      const a = await audit.json();
      const entries: AuditRow[] = Array.isArray(a) ? a : a.items ?? a.rows;
      // Newest first; SQLite may reuse a deleted row id, so only the newest create+delete pair is ours.
      const mine = entries.filter((e) => e.entity === "followup" && String(e.entity_id) === String(id)).slice(0, 2);
      note("[portal] audit for followup", id, "=", JSON.stringify(mine.map((e) => ({ action: e.action, actor: e.actor }))));
      expect(mine.map((e) => e.action).sort()).toEqual(["create", "delete"]);
      for (const e of mine) expect(e.actor).toBe(adminName);
    });

    await test.step("security: cross-origin write, frame headers, CSP, no cookies to/from portal", async () => {
      const evil = await page.request.post("/college-portal/api/followups", {
        headers: { Origin: "https://evil.example", "Content-Type": "application/json" },
        data: { scope_type: "college", scope_id: colleges[0]!.id, title: "should never be saved" },
      });
      expect(evil.status()).toBe(403);
      expect((await evil.json()).code).toBe("cross_origin");

      const entry = await page.request.get("/college-portal/index.html");
      expect(entry.status()).toBe(200);
      const eh = entry.headers();
      note("[portal] index.html x-frame-options =", eh["x-frame-options"], "| csp frame-ancestors =", directive(csp(entry), "frame-ancestors"));
      expect(eh["x-frame-options"]).toBe("SAMEORIGIN");
      expect(directive(csp(entry), "frame-ancestors")).toBe("frame-ancestors 'self'");
      expect(eh["set-cookie"]).toBeUndefined();
      for (const p of ["/college-portal/api/session", "/college-portal/api/colleges", "/college-portal/js/app.js"]) {
        const r = await page.request.get(p);
        expect(r.headers()["set-cookie"], p).toBeUndefined();
      }

      const adminPage = await page.request.get("/admin/college-data");
      const dash = await page.request.get("/admin");
      expect(adminPage.status()).toBe(200);
      expect(dash.status()).toBe(200);
      const fsAdmin = directive(csp(adminPage), "frame-src");
      const fsDash = directive(csp(dash), "frame-src");
      note("[portal] /admin/college-data", fsAdmin, "\n[portal] /admin", fsDash);
      expect(fsAdmin.split(/\s+/)).toContain("'self'");
      expect(fsDash.split(/\s+/)).not.toContain("'self'");

      // The portal sees the LMS identity from proxy headers, not the LMS cookie: the session answers with
      // the SSO user and the portal never knows about an LMS session of its own.
      const s = await (await page.request.get("/college-portal/api/session")).json();
      expect(s.sso).toBe(true);
      expect(s.user).toBe(adminName);
      const cookieNames = (await page.context().cookies()).map((c) => c.name);
      expect(cookieNames.some((n) => /__session$/.test(n) && !n.startsWith("__Host-td"))).toBe(false);
    });

    await test.step("LMS regression smoke", async () => {
      for (const [path, heading] of [["/admin", null], ["/admin/users", null]] as const) {
        const res = await page.goto(path);
        expect(res?.status(), path).toBe(200);
        await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
        void heading;
      }
      for (const p of ["/", "/courses"]) {
        const r = await page.request.get(p);
        note("[portal] public", p, r.status());
        expect(r.status(), p).toBeLessThan(400);
      }
    });

    await test.step("logout ends portal access", async () => {
      await page.goto("/admin");
      await page.getByRole("button", { name: "Sign out" }).first().click();
      await page.waitForURL((u) => u.pathname === "/login");
      const r = await page.request.get("/college-portal/api/colleges");
      expect(r.status()).toBe(401);
      const nav = await page.request.get("/college-portal/index.html", { maxRedirects: 0, headers: { accept: "text/html", "sec-fetch-dest": "document" } });
      expect(nav.status()).toBe(303);
    });
  });

  test("sidebar click (client-side navigation) renders the portal iframe", async ({ page, request }) => {
    // Regression: a Next.js soft navigation would keep /admin's CSP (frame-src without 'self') and
    // Chrome would block the frame. The nav item does a full document load (documentNav) instead.
    test.setTimeout(120_000);
    const admin = account("ADMIN");
    test.skip(!admin, "set E2E_ADMIN_*");
    const cspErrors: string[] = [];
    page.on("console", (m) => { if (m.type() === "error" && /Framing .*college-portal.*frame-src/.test(m.text())) cspErrors.push(m.text()); });
    await signIn(page, request, admin!, "/admin");
    await page.waitForURL((u) => u.pathname.startsWith("/admin"));
    await page.getByRole("link", { name: "College Data Portal" }).click();
    await page.waitForURL((u) => u.pathname === "/admin/college-data");
    const userBtn = page.frameLocator('iframe[title="College Data Portal"]').locator("button.td-user");
    try {
      await expect(userBtn).toBeVisible({ timeout: 15_000 });
    } finally {
      note("[portal] soft-nav CSP frame errors:", cspErrors.length, cspErrors[0]?.slice(0, 160) ?? "");
    }
    expect(cspErrors).toHaveLength(0);
  });

  test("student: portal api is 403, admin page is the forbidden page", async ({ page, request }) => {
    const student = account("STUDENT");
    test.skip(!student, "set E2E_STUDENT_*");
    await signIn(page, request, student!, "/app");
    await page.waitForURL((u) => u.pathname.startsWith("/app"));

    const api = await page.request.get("/college-portal/api/colleges");
    expect(api.status()).toBe(403);
    expect((await api.json()).code).toBe("forbidden");

    const nav = await page.request.get("/college-portal/index.html", { headers: { accept: "text/html", "sec-fetch-dest": "document" } });
    expect(nav.status()).toBe(403);
    expect(await nav.text()).toContain("Admins only");

    const res = await page.goto("/admin/college-data");
    note("[portal] student /admin/college-data status =", res?.status(), "url =", page.url());
    await expect(page.getByRole("heading", { level: 1, name: /don.t have access to the .+ portal/ })).toBeVisible();
    await expect(page.locator('iframe[title="College Data Portal"]')).toHaveCount(0);
  });
});

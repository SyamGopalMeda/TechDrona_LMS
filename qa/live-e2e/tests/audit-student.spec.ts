import fs from "node:fs";
import { test, type Page, type BrowserContext } from "@playwright/test";
import { HOME, creds, roles, stateFile, type RoleKey } from "../lib/roles";
import { layoutIssues, watch } from "../lib/probe";

/**
 * Audit of the Student portal (/app), the shared entry flows and cross-role access on the LIVE LMS.
 * Navigation and reading only: no form that creates/changes/deletes data is submitted (the only
 * form submitted is the sign-in form, which is what lib/global-setup.ts does through the API).
 * Findings: out/findings/audit-student-<part>-<role>-<project>.json
 */

const SITE = process.env.SITE_URL ?? "https://techdrona-website.web.app";
const STUDENT_NAV = [
  "/app", "/app/learning", "/app/classes", "/app/courses", "/app/registrations", "/app/path/my", "/app/assignments",
  "/app/engage", "/app/certificates", "/app/practice", "/app/tests", "/app/coding", "/app/progress",
  "/app/interview-prep", "/app/resume", "/app/notifications", "/app/billing",
  "/app/access", "/app/support", "/app/settings/profile",
  // not in the sidebar but reachable: account menu / dashboard
  "/app/account-status", "/app/path", "/app/orders", "/app/onboarding",
];

const MATRIX: Record<string, string[]> = {
  "/app": ["/app", "/app/learning", "/app/billing"],
  "/admin": ["/admin", "/admin/users", "/admin/certificates"],
  "/finance": ["/finance", "/finance/orders", "/finance/admissions/registrations"],
  "/desk": ["/desk", "/desk/unblock-requests"],
  "/security": ["/security", "/security/cases", "/security/restrictions"],
  "/studio": ["/studio", "/studio/questions", "/studio/courses"],
  "/trainer": ["/trainer", "/trainer/grading", "/trainer/tests"],
  "/evaluator": ["/evaluator", "/evaluator/tests", "/evaluator/integrity"],
};

const API_PROBES = [
  "admin/users", "admin/certificates", "admin/dashboard", "admin/admissions/registrations", "admin/privacy-requests",
  "admin/feature-flags", "rbac/grants", "audit/events", "finance/orders", "finance/reports/revenue",
  "studio/questions", "studio/courses", "security/cases", "support/queue", "batches",
];

function save(name: string, data: unknown) {
  fs.mkdirSync("out/findings", { recursive: true });
  fs.writeFileSync(`out/findings/${name}.json`, JSON.stringify(data, null, 1));
}

async function settle(page: Page, ms = 1500) {
  await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => undefined);
  await page.waitForTimeout(ms);
}

/** What shell is showing: sidebar badge ("<title> portal"), top-bar pill, h1, forbidden page. */
async function shellOf(page: Page) {
  return page.evaluate(() => {
    const t = (el: Element | null | undefined) => (el?.textContent ?? "").replace(/\s+/g, " ").trim();
    const badge = t(document.querySelector(".td-adm-badge"));
    const pills = Array.from(document.querySelectorAll("header span")).map(t).filter((s) => s && s.length < 40);
    const h1 = t(document.querySelector("main h1") ?? document.querySelector("h1"));
    const main = document.querySelector("main");
    const text = (main as HTMLElement | null)?.innerText ?? document.body.innerText;
    return { badge, pills: Array.from(new Set(pills)).slice(0, 4), h1, mainLen: text.trim().length, snippet: text.replace(/\s+/g, " ").trim().slice(0, 500), title: document.title };
  });
}

function trackApi(page: Page) {
  const calls: string[] = [];
  page.on("response", (r) => {
    const u = r.url();
    if (u.includes("/api/v1/")) calls.push(`${r.status()} ${r.request().method()} ${u.split("/api/v1/")[1]?.split("?")[0]?.slice(0, 90)}`);
  });
  return calls;
}

const LMS_ORIGIN = new URL(process.env.LMS_URL ?? "https://techdrona-lms-app.web.app").origin;
const path = (page: Page) => { const u = new URL(page.url()); return u.origin === LMS_ORIGIN ? `${u.pathname}${u.search}` : page.url(); };

/**
 * A new sign-in of the same account revokes its older sessions on live (seen in build 5f3a1867),
 * and other audit builds sign the same QA accounts in. So: sign in again (API, like global-setup)
 * into this browser context when a page bounces to /login, and retry once.
 */
async function relogin(ctx: BrowserContext, r: RoleKey) {
  await ctx.request.get("/api/v1/_bff/csrf");
  const tok = (await ctx.storageState()).cookies.find((k) => k.name.endsWith("td_csrf"))?.value ?? "";
  const c = creds();
  const res = await ctx.request.post("/api/v1/auth/login", { data: { identifier: c.accounts[r], password: c.password }, headers: { "x-csrf-token": tok, origin: LMS_ORIGIN } });
  return res.status();
}
let relogins = 0;
async function visit(page: Page, ctx: BrowserContext, r: RoleKey, p: string, ms = 1500) {
  const resp = await page.goto(p).catch(() => null);
  await settle(page, ms);
  if (!p.startsWith("/login") && path(page).startsWith("/login")) {
    relogins++;
    await relogin(ctx, r);
    const again = await page.goto(p).catch(() => null);
    await settle(page, ms);
    return { resp: again, relogged: true };
  }
  return { resp, relogged: false };
}

async function newCtx(browser: import("@playwright/test").Browser, info: import("@playwright/test").TestInfo, r: RoleKey | null): Promise<BrowserContext> {
  return browser.newContext({ ...info.project.use, ...(r ? { storageState: stateFile(r) } : {}) });
}

/* ------------------------------------------------------------------ 1. Student portal */

test("student portal pages", async ({ browser }, info) => {
  test.skip(!roles().includes("student"), "student not selected");
  const ctx = await newCtx(browser, info, "student");
  const page = await ctx.newPage();
  const w = watch(page);
  const calls = trackApi(page);
  const pages: unknown[] = [];
  for (const p of STUDENT_NAV) {
    w.reset(); calls.length = 0;
    const { resp, relogged } = await visit(page, ctx, "student", p);
    await settle(page);
    const s = await shellOf(page);
    const links = await page.$$eval("main a[href]", (as) => as.map((a) => `${(a.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, 40)} -> ${a.getAttribute("href")}`)).catch(() => []);
    const buttons = await page.$$eval("main button", (bs) => bs.map((b) => (b.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, 40)).filter(Boolean)).catch(() => []);
    pages.push({ goto: p, relogged, http: resp?.status(), final: path(page), ...s, links: Array.from(new Set(links)).slice(0, 40), buttons: Array.from(new Set(buttons)).slice(0, 15), api: [...calls], apiErrors: [...w.api], console: [...w.errors], layout: await layoutIssues(page) });
    if (process.env.CI) await page.screenshot({ path: info.outputPath(`stu${p.replace(/\//g, "_")}.png`), fullPage: true }).catch(() => undefined);
  }

  // Shell chrome on the dashboard
  await visit(page, ctx, "student", "/app");
  const chrome: Record<string, unknown> = {};
  chrome.sidebar = await page.$$eval("aside nav a[href]", (as) => as.map((a) => `${(a.textContent ?? "").trim()} -> ${a.getAttribute("href")}`)).catch(() => []);
  chrome.sidebarSections = await page.$$eval("aside nav button, aside nav h2, aside nav p", (els) => els.map((e) => (e.textContent ?? "").trim()).filter(Boolean)).catch(() => []);
  chrome.headerActions = await page.$$eval("header a[aria-label], header button[aria-label], header summary", (els) => els.map((e) => `${e.tagName}:${e.getAttribute("aria-label") ?? e.textContent?.trim()} -> ${e.getAttribute("href") ?? ""}`)).catch(() => []);
  // account menu
  const acct = page.locator("header button[aria-label^='Account']").first();
  if (await acct.isVisible().catch(() => false)) {
    await acct.click();
    await page.waitForTimeout(500);
    chrome.accountMenu = await page.$$eval("header [id] ul a[href]", (as) => as.map((a) => `${(a.textContent ?? "").trim()} -> ${a.getAttribute("href")}`)).catch(() => []);
    await page.keyboard.press("Escape");
  }
  // bell
  const bell = page.locator("header a[aria-label^='Notifications']").first();
  if (await bell.isVisible().catch(() => false)) {
    chrome.bell = { label: await bell.getAttribute("aria-label"), href: await bell.getAttribute("href") };
    await bell.click(); await settle(page, 800);
    chrome.bellTarget = { url: path(page), ...(await shellOf(page)) };
    await visit(page, ctx, "student", "/app", 800);
  }
  // Find a page
  const find = page.getByRole("searchbox", { name: "Find a page" }).first();
  const finds: Record<string, string[]> = {};
  if (await find.isVisible().catch(() => false)) {
    for (const q of ["course", "bill", "interview", "admin", "settings", "certificate", "pay", "zzz"]) {
      await find.fill(q); await page.waitForTimeout(400);
      finds[q] = await page.$$eval("ul[aria-label='Matching pages'] a, aside [role=status], aside nav p", (els) => els.map((e) => `${(e.textContent ?? "").trim()} ${e.getAttribute("href") ?? ""}`)).catch(() => []);
    }
    await find.fill("");
  }
  chrome.find = finds;
  // Mobile tab bar + More sheet
  const tabbar = page.locator("nav[data-td-tabbar]");
  if (await tabbar.isVisible().catch(() => false)) {
    chrome.tabs = await tabbar.locator("a, button").allInnerTexts();
    await tabbar.getByText("More", { exact: true }).click().catch(() => undefined);
    await page.waitForTimeout(600);
    chrome.moreSheet = await page.$$eval("[role=dialog] a[href]", (as) => as.map((a) => `${(a.textContent ?? "").trim()} -> ${a.getAttribute("href")}`)).catch(() => []);
    if (process.env.CI) await page.screenshot({ path: info.outputPath("stu_more_sheet.png") });
    await page.keyboard.press("Escape");
  }
  // Dashboard links: does every CTA land somewhere real?
  await visit(page, ctx, "student", "/app");
  const dashLinks = await page.$$eval("main a[href]", (as) => Array.from(new Set(as.map((a) => a.getAttribute("href") ?? "")))).catch(() => [] as string[]);
  const dash: unknown[] = [];
  for (const h of dashLinks.slice(0, 30)) {
    if (!h.startsWith("/")) { dash.push({ href: h, external: true }); continue; }
    w.reset();
    await visit(page, ctx, "student", h, 600);
    const s = await shellOf(page);
    dash.push({ href: h, final: path(page), h1: s.h1, badge: s.badge, api: [...w.api] });
  }
  chrome.dashLinks = dash;

  // catalog.json (CORS) — what the server says, and what the dashboard shows
  const cat = await ctx.request.get(`${SITE}/catalog.json`).catch(() => null);
  chrome.catalogJson = cat ? { status: cat.status(), ct: cat.headers()["content-type"], acao: cat.headers()["access-control-allow-origin"] ?? null, head: (await cat.text()).slice(0, 200) } : null;

  save(`audit-student-pages-${info.project.name}`, { pages, chrome });
  await ctx.close();
});

/* ------------------------------------------------------------------ 2. Entry flows per role */

for (const r of roles()) {
  test(`entry flows ${r}`, async ({ browser }, info) => {
    const ctx = await newCtx(browser, info, r);
    const page = await ctx.newPage();
    const w = watch(page);
    const out: Record<string, unknown> = { role: r };
    for (const p of ["/", "/login", "/continue", "/modules", "/app", "/app/learning", "/app/courses", "/app/settings/profile", "/app/account-status"]) {
      w.reset();
      const { relogged } = await visit(page, ctx, r, p);
      await settle(page);
      const s = await shellOf(page);
      out[p] = { relogged, final: path(page), badge: s.badge, pills: s.pills, h1: s.h1, snippet: s.snippet.slice(0, 220), api: [...w.api] };
      if (p === "/modules") out.moduleCards = await page.$$eval("main a[href], main li a", (as) => as.map((a) => `${(a.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, 120)} -> ${a.getAttribute("href")}`)).catch(() => []);
    }
    // Account menu -> Settings from the role's own home portal
    await visit(page, ctx, r, HOME[r]);
    const homeShell = await shellOf(page);
    out.home = { final: path(page), badge: homeShell.badge, pills: homeShell.pills, h1: homeShell.h1 };
    const acct = page.locator("header button[aria-label^='Account']").first();
    if (await acct.isVisible().catch(() => false)) {
      await acct.click(); await page.waitForTimeout(500);
      out.accountMenu = await page.$$eval("header ul a[href]", (as) => as.map((a) => `${(a.textContent ?? "").trim()} -> ${a.getAttribute("href")}`)).catch(() => []);
      await page.locator("header a", { hasText: "Settings" }).first().click().catch((e) => (out.settingsClickError = String(e)));
      await settle(page);
      const s = await shellOf(page);
      out.settingsViaMenu = { final: path(page), badge: s.badge, pills: s.pills, h1: s.h1, sidebar: await page.$$eval("aside nav a[href]", (as) => as.slice(0, 6).map((a) => a.getAttribute("href"))).catch(() => []) };
      if (process.env.CI) await page.screenshot({ path: info.outputPath(`settings_${r}.png`) });
      // then a student page from inside settings (staff must go home)
      await visit(page, ctx, r, "/app/practice");
      const s2 = await shellOf(page);
      out.studentPageAfterSettings = { final: path(page), badge: s2.badge, h1: s2.h1 };
    }
    await ctx.close();
    save(`audit-student-entry-${r}-${info.project.name}`, out);
  });
}

/*
 * Post-login landing in a clean browser (sign-in form, as a user would). Run it ON ITS OWN
 * (`--grep post-login`, desktop): a fresh sign-in revokes the account's other sessions on live, so
 * mixing it with the storageState tests logs them out (seen in build 5f3a1867).
 */
for (const r of roles()) {
  test(`post-login ${r}`, async ({ browser }, info) => {
    test.skip(info.project.name !== "desktop", "desktop only");
    const out: Record<string, unknown> = { role: r };
    const fresh = await newCtx(browser, info, null);
    const fp = await fresh.newPage();
    try {
      await fp.goto("/"); await settle(fp, 500);
      out.signedOutRoot = path(fp);
      await fp.goto("/login"); await settle(fp, 500);
      const c = creds();
      await fp.locator("input[name=identifier]").fill(c.accounts[r]);
      await fp.locator("input[name=password]").fill(c.password);
      await fp.locator("form button[type=submit]").first().click();
      await fp.waitForURL((u) => u.pathname !== "/login", { timeout: 30_000 }).catch(() => undefined);
      await settle(fp, 3000);
      const s = await shellOf(fp);
      out.postLogin = { final: path(fp), badge: s.badge, pills: s.pills, h1: s.h1, snippet: s.snippet.slice(0, 200) };
      if (process.env.CI) await fp.screenshot({ path: info.outputPath(`postlogin_${r}.png`) });
    } catch (e) {
      out.postLoginError = String(e).slice(0, 300);
    }
    await fresh.close();
    // Does the earlier (global-setup) session survive this new sign-in?
    const old = await newCtx(browser, info, r);
    const sres = await old.request.get("/api/v1/me/grants").catch(() => null);
    out.olderSessionAfterNewLogin = sres ? sres.status() : null;
    await old.close();
    save(`audit-student-postlogin-${r}-${info.project.name}`, out);
  });
}

/* ------------------------------------------------------------------ 3. Access matrix per role */

for (const r of roles()) {
  test(`access matrix ${r}`, async ({ browser }, info) => {
    test.skip(info.project.name !== "desktop", "matrix on desktop only");
    const ctx = await newCtx(browser, info, r);
    const page = await ctx.newPage();
    const calls = trackApi(page);
    const rows: unknown[] = [];
    for (const [portal, list] of Object.entries(MATRIX)) {
      for (const p of list) {
        calls.length = 0;
        const { relogged } = await visit(page, ctx, r, p, 0);
        await settle(page, 1500);
        const s = await shellOf(page);
        const staffApi = calls.filter((c) => !/ (GET|POST) (me|_bff|notifications|me\/|auth|ai\/apps|public)/.test(c));
        rows.push({ portal, goto: p, relogged, final: path(page), badge: s.badge, pills: s.pills, h1: s.h1, forbidden: /no access|don.t have access|not found/i.test(s.snippet.slice(0, 300)), api: Array.from(new Set(staffApi)).slice(0, 12) });
      }
    }
    save(`audit-student-matrix-${r}-${info.project.name}`, rows);
    await ctx.close();
  });
}

/* ------------------------------------------------------------------ 4. Staff API probes per role */

for (const r of roles()) {
  test(`api probes ${r}`, async ({ browser }, info) => {
    test.skip(info.project.name !== "desktop", "desktop only");
    const ctx = await newCtx(browser, info, r);
    const page = await ctx.newPage();
    await relogin(ctx, r); await page.goto("/app/settings/profile"); await settle(page, 300);
    const rows: unknown[] = [{ sanity: "me/grants", status: (await ctx.request.get("/api/v1/me/grants")).status() }];
    for (const ep of API_PROBES) {
      let res = await ctx.request.get(`/api/v1/${ep}`, { headers: { accept: "application/json" } }).catch(() => null);
      if (res?.status() === 401) { await relogin(ctx, r); res = await ctx.request.get(`/api/v1/${ep}`, { headers: { accept: "application/json" } }).catch(() => null); }
      const body = res ? (await res.text()).slice(0, 400) : "";
      let summary = body.slice(0, 160);
      try {
        const j = JSON.parse(body) as Record<string, unknown>;
        summary = j.code ? `code=${j.code} ${String(j.title ?? j.detail ?? "").slice(0, 80)}` : `keys=${Object.keys(j).join(",")}${Array.isArray(j.data) ? ` data.len=${(j.data as unknown[]).length}` : ""}`;
      } catch { /* body cut or not json */ }
      // the same call from inside the page (fetch with the session cookie), as the SPA would
      const inPage = await page.evaluate(async (u) => { try { const x = await fetch(u, { credentials: "include", headers: { accept: "application/json" } }); return x.status; } catch (e) { return String(e); } }, `/api/v1/${ep}`);
      rows.push({ ep, status: res?.status(), inPage, summary });
    }
    save(`audit-student-api-${r}-${info.project.name}`, rows);
    await ctx.close();
  });
}

/* ------------------------------------------------------------------ 5. College Data Portal access (fixes-college-portal.md) */
test("college portal: student and signed out", async ({ browser }, info) => {
  test.skip(info.project.name !== "desktop", "desktop only");
  const out: Record<string, unknown> = {};
  const probe = async (ctx: BrowserContext, label: string) => {
    const res: Record<string, unknown> = {};
    for (const [k, p, h] of [["doc", "/college-portal/index.html", { "sec-fetch-dest": "document", accept: "text/html" }], ["api", "/college-portal/api/colleges", { accept: "application/json" }], ["root", "/college-portal/", {}]] as const) {
      const r = await ctx.request.get(p, { maxRedirects: 0, failOnStatusCode: false, headers: { ...h } }).catch(() => null);
      res[k] = r ? { status: r.status(), location: r.headers()["location"] ?? null, type: r.headers()["content-type"] ?? null, body: (await r.text()).replace(/\s+/g, " ").slice(0, 200) } : null;
    }
    const page = await ctx.newPage();
    const resp = await page.goto("/college-portal/index.html").catch(() => null);
    await settle(page, 1500);
    res.browser = { http: resp?.status() ?? null, final: path(page), title: await page.title(), text: (await page.evaluate(() => document.body.innerText.replace(/\s+/g, " ").slice(0, 300)).catch(() => "")) };
    if (process.env.CI) await page.screenshot({ path: info.outputPath(`college-portal-${label}.png`) }).catch(() => undefined);
    const resp2 = await page.goto("/admin/college-data").catch(() => null);
    await settle(page, 1500);
    res.adminRoute = { http: resp2?.status() ?? null, final: path(page), h1: (await shellOf(page)).h1, snippet: (await shellOf(page)).snippet.slice(0, 200) };
    await page.close();
    return res;
  };
  if (roles().includes("student")) {
    const s = await newCtx(browser, info, "student");
    out.student = await probe(s, "student");
    await s.close();
  }
  const anon = await newCtx(browser, info, null);
  out.signedOut = await probe(anon, "signed-out");
  await anon.close();
  save(`audit-student-college-portal-${info.project.name}`, out);
});

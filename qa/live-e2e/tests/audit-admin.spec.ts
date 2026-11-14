import fs from "node:fs";
import { test, type Page, type BrowserContext, type TestInfo } from "@playwright/test";
import { stateFile } from "../lib/roles";
import { layoutIssues, shot } from "../lib/probe";

/**
 * Admin portal audit (read-only): every Admin nav page + related entry points, as the QA
 * super_admin. Navigation / reading / opening tabs and menus only — nothing is submitted.
 * Findings: out/findings/audit-admin-<project>-<slug>.json (+ audit-admin-<project>-shell.json).
 * Re-run ONE device per build (desktop, then tablet): the session cookie from global-setup is
 * revoked when the same session is used with two different user agents (2026-11-14 run 9fbdd251:
 * every page redirected to /login ~2 min in when desktop + tablet ran together).
 *   bash qa/live-e2e/run.sh tests/audit-admin.spec.ts --roles=admin --projects=desktop --shots
 *   bash qa/live-e2e/run.sh tests/audit-admin.spec.ts --roles=admin --projects=tablet --shots
 */

const PAGES: string[] = [
  // ADMIN_NAV (apps/lms-spa/src/lib/nav/portals.ts)
  "/admin", "/admin/approvals", "/admin/users", "/admin/roles", "/admin/privacy-requests",
  "/college-portal/index.html",
  "/admin/courses", "/admin/question-review", "/admin/batches", "/admin/certificates",
  "/mentor", "/mentor/students", "/mentor/slots", "/mentor/resume-reviews",
  "/finance", "/finance/admissions", "/finance/admissions/verify", "/finance/admissions/registrations", "/finance/admissions/plans",
  "/finance/orders", "/finance/refunds", "/finance/subscriptions", "/finance/invoices", "/finance/products", "/finance/coupons", "/finance/reconciliation",
  "/desk", "/desk/unblock-requests", "/desk/enquiries",
  "/security", "/security/cases", "/security/incidents", "/security/restrictions", "/security/unblock-requests", "/security/rules", "/security/reports",
  "/admin/audit", "/admin/policies", "/admin/ai", "/admin/system", "/admin/feature-flags", "/admin/break-glass",
  // Routes outside the nav but reachable / linked from admin pages
  "/admin/notifications", "/admin/college-data", "/security/approvals", "/security/policies",
  "/modules", "/app/settings/profile", "/app/account-status",
  // Cross-portal targets linked from the admin dashboard / courses page
  "/studio", "/studio/courses", "/studio/review", "/studio/taxonomy", "/studio/questions", "/studio/reports/errors", "/studio/coding",
  "/studio/media", "/studio/companies", "/studio/question-banks", "/studio/tests",
  "/trainer", "/app", "/app/learning",
];

/** List pages whose first detail link is also opened. */
const DETAIL_FROM: Record<string, RegExp> = {
  "/admin/users": /^\/admin\/users\/[^/?]+$/,
  "/admin/batches": /^\/admin\/batches\/[^/?]+$/,
  "/desk": /^\/desk\/tickets\/[^/?]+$/,
  "/desk/enquiries": /^\/desk\/enquiries\/[^/?]+$/,
  "/security/cases": /^\/security\/cases\/[^/?]+$/,
  "/security/reports": /^\/security\/reports\/[^/?]+$/,
  "/finance/admissions/registrations": /^\/finance\/admissions\/registrations\/[^/?]+$/,
  "/mentor/students": /^\/mentor\/students\/[^/?]+$/,
};

const PROBLEM_RX = /permission|forbidden|not allowed|something went wrong|could not load|couldn['’]t load|failed to load|error|not integrated|not available|coming soon|page not found|404/i;

const slug = (p: string) => (p.replace(/^\//, "").replace(/[^a-z0-9]+/gi, "_") || "root").slice(0, 70);

function save(name: string, data: unknown) {
  fs.mkdirSync("out/findings", { recursive: true });
  fs.writeFileSync(`out/findings/${name}.json`, JSON.stringify(data, null, 1));
}

async function ctxFor(browser: import("@playwright/test").Browser, info: TestInfo): Promise<BrowserContext> {
  return browser.newContext({ ...info.project.use, storageState: stateFile("admin") });
}

/** All /api/ responses (status + path) plus console errors. */
function monitor(page: Page) {
  const calls: string[] = [];
  const errors: string[] = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text().slice(0, 300)); });
  page.on("pageerror", (e) => errors.push(`pageerror: ${String(e).slice(0, 300)}`));
  page.on("response", (r) => {
    const u = r.url();
    if (u.includes("/api/")) calls.push(`${r.status()} ${r.request().method()} ${u.split("/api/")[1]?.slice(0, 160)}`);
  });
  return { calls, errors, reset() { calls.length = 0; errors.length = 0; } };
}

async function settle(page: Page) {
  await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => undefined);
  // wait for loading placeholders to go away (max ~12 s)
  for (let i = 0; i < 24; i++) {
    const busy = await page.evaluate(() => {
      const m = document.querySelector("main") ?? document.body;
      const t = (m as HTMLElement).innerText ?? "";
      return !!m.querySelector('[aria-busy="true"]') || /^\s*Loading|Loading\b.*…/m.test(t.slice(0, 400));
    }).catch(() => false);
    if (!busy) break;
    await page.waitForTimeout(500);
  }
  await page.waitForTimeout(600);
}

async function readPage(page: Page) {
  return page.evaluate(() => {
    const main = (document.querySelector("main") ?? document.body) as HTMLElement;
    const text = (main.innerText ?? "").replace(/\n{2,}/g, "\n").trim();
    const h1 = Array.from(document.querySelectorAll("h1")).map((h) => (h as HTMLElement).innerText.trim()).filter(Boolean);
    const crumbs = Array.from(document.querySelectorAll('nav[aria-label*="readcrumb" i] a, nav[aria-label*="readcrumb" i] li')).map((e) => `${(e as HTMLElement).innerText.trim()}${e instanceof HTMLAnchorElement ? ` -> ${e.getAttribute("href")}` : ""}`);
    const tabs = Array.from(document.querySelectorAll('[role="tab"]')).map((e) => (e as HTMLElement).innerText.trim());
    const links = Array.from(main.querySelectorAll("a[href]")).map((a) => ({ t: ((a as HTMLElement).innerText || a.getAttribute("aria-label") || "").trim().replace(/\s+/g, " ").slice(0, 60), h: a.getAttribute("href") ?? "" }));
    const buttons = Array.from(main.querySelectorAll("button")).map((b) => (b as HTMLElement).innerText.trim().replace(/\s+/g, " ").slice(0, 40)).filter(Boolean);
    const rows = main.querySelectorAll("tbody tr").length;
    const navLabel = document.querySelector("aside nav[aria-label]")?.getAttribute("aria-label") ?? document.querySelector("nav[aria-label$='navigation']")?.getAttribute("aria-label") ?? null;
    const badge = (document.querySelector(".td-adm-badge") as HTMLElement | null)?.innerText ?? null;
    const alerts = Array.from(document.querySelectorAll('[role="alert"]')).map((e) => (e as HTMLElement).innerText.trim().slice(0, 200)).filter(Boolean);
    return { h1, crumbs, tabs, links, buttons: buttons.slice(0, 40), rows, navLabel, badge, alerts, text: text.slice(0, 1800), textLen: text.length };
  });
}

async function audit(page: Page, info: TestInfo, path: string, mon: ReturnType<typeof monitor>) {
  mon.reset();
  let navError: string | null = null;
  const t0 = Date.now();
  try {
    await page.goto(path, { waitUntil: "domcontentloaded" });
  } catch (e) {
    navError = String(e).slice(0, 200);
  }
  await settle(page);
  const final = page.url();
  const info1 = await readPage(page).catch(() => null);
  const layout = await layoutIssues(page).catch(() => [] as string[]);
  const problems = info1 ? Array.from(new Set((info1.text.match(new RegExp(PROBLEM_RX.source, "gi")) ?? []).map((s) => s.toLowerCase()))) : [];
  // Tabs: click each (navigation only) and note API failures they trigger.
  const tabResults: { tab: string; failed: string[] }[] = [];
  if (info1?.tabs.length) {
    const tabs = page.getByRole("tab");
    const n = Math.min(await tabs.count(), 8);
    for (let i = 0; i < n; i++) {
      const before = mon.calls.length;
      const name = (await tabs.nth(i).innerText().catch(() => "")).trim();
      if (!name || !(await tabs.nth(i).isVisible().catch(() => false))) continue; // unnamed / hidden tab elements
      await tabs.nth(i).click({ timeout: 5000 }).catch(() => undefined);
      await settle(page);
      tabResults.push({ tab: name, failed: mon.calls.slice(before).filter((c) => /^[45]\d\d /.test(c)) });
    }
  }
  const png = info.project.name === "desktop" || info.project.name === "tablet" ? await shot(page, info, `${info.project.name}-${slug(path)}`).catch(() => null) : null;
  const finding = {
    path,
    project: info.project.name,
    final: final.startsWith("http") ? (new URL(final).host.includes("techdrona-lms-app") ? new URL(final).pathname + new URL(final).search : final) : final,
    ms: Date.now() - t0,
    title: await page.title().catch(() => ""),
    navError,
    sessionLost: /^\/login/.test(new URL(final).pathname),
    ...info1,
    problems,
    apiFailed: mon.calls.filter((c) => /^[45]\d\d /.test(c)),
    apiCalls: Array.from(new Set(mon.calls)).slice(0, 40),
    consoleErrors: mon.errors.slice(0, 10),
    layout,
    tabResults,
    screenshot: png ? png.split("out/artifacts/")[1] ?? png : null,
  };
  return finding;
}

test.describe("admin audit", () => {


  // Shell inventory: sidebar, header, account menu, switchers, Find a page, dashboard links.
  test("shell inventory", async ({ browser }, info) => {
    const ctx = await ctxFor(browser, info);
    const page = await ctx.newPage();
    const mon = monitor(page);
    await page.goto("/admin");
    await settle(page);
    const out: Record<string, unknown> = { project: info.project.name };
    out.sidebar = await page.evaluate(() =>
      Array.from(document.querySelectorAll("nav[aria-label$='navigation'] a[href]")).map((a) => ({ t: (a.textContent ?? "").trim(), h: a.getAttribute("href") })),
    );
    out.sections = await page.evaluate(() => Array.from(document.querySelectorAll("nav[aria-label$='navigation'] h2")).map((h) => (h.textContent ?? "").trim()));
    out.header = await page.evaluate(() => Array.from(document.querySelectorAll("header a, header button, header summary")).map((e) => ((e as HTMLElement).innerText || e.getAttribute("aria-label") || "").trim().replace(/\s+/g, " ")).filter(Boolean));
    out.dashboard = await readPage(page);
    // Account menu
    const acct = page.locator("header button[aria-label^='Account']");
    if (await acct.count()) {
      await acct.first().click().catch(() => undefined);
      await page.waitForTimeout(500);
      out.accountMenu = await page.evaluate(() => {
        const b = document.querySelector("header button[aria-label^='Account']");
        const panel = b ? document.getElementById(b.getAttribute("aria-controls") ?? "") : null;
        return panel ? Array.from(panel.querySelectorAll("a, button")).map((e) => `${(e as HTMLElement).innerText.trim()}${e instanceof HTMLAnchorElement ? ` -> ${e.getAttribute("href")}` : ""}`) : [];
      });
      await page.screenshot({ path: info.outputPath(`${info.project.name}-account-menu.png`) }).catch(() => undefined);
      await page.keyboard.press("Escape");
    }
    for (const [key, label] of [["portalSwitcher", "Switch portal"], ["modules", "Modules"]] as const) {
      const s = page.locator("header summary", { hasText: label });
      if (await s.count()) {
        await s.first().click().catch(() => undefined);
        await page.waitForTimeout(400);
        out[key] = await s.first().evaluate((el) => Array.from(el.parentElement!.querySelectorAll("a")).map((a) => `${(a.textContent ?? "").trim()} -> ${a.getAttribute("href")}`));
        await page.screenshot({ path: info.outputPath(`${info.project.name}-${key}.png`) }).catch(() => undefined);
        await s.first().click().catch(() => undefined);
      } else out[key] = "not shown";
    }
    // Find a page (Ctrl+K)
    const box = page.locator("input[aria-label='Find a page']").filter({ visible: true });
    if (await box.count()) {
      await page.locator("main").click({ position: { x: 5, y: 5 } }).catch(() => undefined);
      await page.keyboard.press("Control+K");
      out.ctrlKFocuses = await page.evaluate(() => document.activeElement?.getAttribute("aria-label") ?? document.activeElement?.tagName ?? null);
      const finds: Record<string, string[]> = {};
      for (const q of ["learn", "my", "practice", "student", "course", "test", "question", "approval", "unblock", "polic", "mentor", "certificate", "admission", "enquir", "setting"]) {
        await box.first().fill(q);
        await page.waitForTimeout(250);
        finds[q] = await page.evaluate(() => Array.from(document.querySelectorAll("ul[aria-label='Matching pages'] a")).filter((a) => (a as HTMLElement).offsetParent !== null).map((a) => `${(a.textContent ?? "").trim()} -> ${a.getAttribute("href")}`));
      }
      await box.first().fill("");
      out.findAPage = finds;
    } else out.findAPage = "search box not visible (menu sheet on this viewport)";
    // Tablet: the staff "Menu" button
    const menuBtn = page.getByRole("button", { name: /menu/i }).filter({ visible: true });
    if (info.project.name !== "desktop" && (await menuBtn.count())) {
      await menuBtn.first().click().catch(() => undefined);
      await page.waitForTimeout(600);
      await page.screenshot({ path: info.outputPath(`${info.project.name}-menu-sheet.png`) }).catch(() => undefined);
      out.menuSheet = await page.evaluate(() => Array.from(document.querySelectorAll("nav a[href]")).filter((a) => (a as HTMLElement).offsetParent !== null).map((a) => (a.textContent ?? "").trim()));
      await page.keyboard.press("Escape");
    }
    out.apiFailed = mon.calls.filter((c) => /^[45]\d\d /.test(c));
    out.consoleErrors = mon.errors;
    save(`audit-admin-${info.project.name}-shell`, out);
    await ctx.close();
  });

  // College Data Portal through Hosting /college-portal/** (fixes-college-portal.md): the framed portal,
  // its headers, and CSP violations in the console. Read-only GETs.
  test("college portal (admin)", async ({ browser }, info) => {
    test.skip(info.project.name !== "desktop", "desktop only");
    const ctx = await ctxFor(browser, info);
    const page = await ctx.newPage();
    const mon = monitor(page);
    const csp: string[] = [];
    page.on("console", (m) => { if (/Content Security Policy|Refused to|frame-ancestors/i.test(m.text())) csp.push(m.text().slice(0, 300)); });
    const out: Record<string, unknown> = {};
    const r1 = await ctx.request.get("/college-portal/index.html", { maxRedirects: 0, failOnStatusCode: false });
    const h = r1.headers();
    out.indexHtml = { status: r1.status(), type: h["content-type"], csp: h["content-security-policy"] ?? null, xfo: h["x-frame-options"] ?? null, cache: h["cache-control"] ?? null, location: h["location"] ?? null, head: (await r1.text()).slice(0, 300) };
    const r2 = await ctx.request.get("/college-portal/api/session", { failOnStatusCode: false });
    out.apiSession = { status: r2.status(), body: (await r2.text()).slice(0, 300) };
    const r3 = await ctx.request.get("/college-portal/api/colleges", { failOnStatusCode: false });
    let n: number | null = null; try { const j = await r3.json(); n = Array.isArray(j) ? j.length : Array.isArray(j?.data) ? j.data.length : Array.isArray(j?.colleges) ? j.colleges.length : null; } catch { /* not json */ }
    out.apiColleges = { status: r3.status(), count: n };
    await page.goto("/admin/college-data");
    await settle(page);
    await page.waitForTimeout(4000);
    const frameEl = page.locator("main iframe").first();
    out.iframe = await frameEl.count() ? { src: await frameEl.getAttribute("src"), title: await frameEl.getAttribute("title") } : null;
    const fr = page.frames().find((f) => f.url().includes("/college-portal"));
    if (fr) {
      await fr.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => undefined);
      await page.waitForTimeout(2000);
      out.frame = await fr.evaluate(() => ({ url: location.pathname, title: document.title, textLen: (document.body?.innerText ?? "").length, text: (document.body?.innerText ?? "").replace(/\s+/g, " ").slice(0, 400), lmsShell: !!document.getElementById("root") && !document.querySelector("script[src*='app.js']") })).catch((e) => ({ error: String(e).slice(0, 200) }));
    } else out.frame = null;
    out.page = await readPage(page);
    out.cspErrors = csp;
    out.consoleErrors = mon.errors;
    out.apiFailed = mon.calls.filter((c) => /^[45]\d\d /.test(c));
    out.screenshot = (await shot(page, info, "desktop-college-data-framed")).split("out/artifacts/")[1] ?? null;
    // "Open full screen" target = the portal page as a document
    await page.goto("/college-portal/index.html");
    await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => undefined);
    out.fullScreen = { final: new URL(page.url()).pathname, title: await page.title(), text: (await page.evaluate(() => document.body.innerText.replace(/\s+/g, " ").slice(0, 300))) };
    out.cspErrorsAfterFullScreen = csp.slice();
    save("audit-admin-desktop-college-portal", out);
    await ctx.close();
  });

  // Website admin (another site, opened via SSO): just record where it lands.
  test("website admin link", async ({ browser }, info) => {
    test.skip(info.project.name !== "desktop", "desktop only");
    const ctx = await ctxFor(browser, info);
    const page = await ctx.newPage();
    await page.goto("/admin");
    await settle(page);
    const href = await page.locator("nav[aria-label$='navigation'] a", { hasText: "Website Admin Panel" }).first().getAttribute("href").catch(() => null);
    let final: string | null = null;
    let title = "";
    if (href) {
      await page.goto(href, { waitUntil: "domcontentloaded" }).catch(() => undefined);
      await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => undefined);
      final = page.url();
      title = await page.title().catch(() => "");
      await shot(page, info, "desktop-website-admin").catch(() => undefined);
    }
    save("audit-admin-desktop-website-admin", { href, final, title, h1: await page.locator("h1").allInnerTexts().catch(() => []) });
    await ctx.close();
  });

  for (const path of PAGES) {
    test(`page ${path}`, async ({ browser }, info) => {
      const ctx = await ctxFor(browser, info);
      const page = await ctx.newPage();
      const mon = monitor(page);
      const f = await audit(page, info, path, mon);
      save(`audit-admin-${info.project.name}-${slug(path)}`, f);
      const rx = DETAIL_FROM[path];
      if (rx && f.links) {
        const detail = f.links.map((l) => l.h).find((h) => rx.test(h));
        if (detail) {
          const d = await audit(page, info, detail, mon);
          save(`audit-admin-${info.project.name}-${slug(path)}--detail`, d);
        } else save(`audit-admin-${info.project.name}-${slug(path)}--detail`, { path, detail: "no detail link found" });
      }
      await ctx.close();
    });
  }
});

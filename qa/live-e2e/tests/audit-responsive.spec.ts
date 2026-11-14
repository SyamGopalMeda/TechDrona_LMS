import fs from "node:fs";
import path from "node:path";
import { test, type Browser, type Page, type TestInfo } from "@playwright/test";
import { creds, roles, stateFile, type RoleKey } from "../lib/roles";
import { layoutReport, watch } from "../lib/probe";

/**
 * Responsive UI/UX audit of the LIVE LMS: every role's portal pages on every device project, plus
 * the public pages signed out. Navigation and reading only (menus, drawers and dialogs are opened,
 * nothing is submitted). Writes out/findings/responsive-*.json and JPEG screenshots under
 * out/artifacts/shots/<project>/<role>/<page>.jpg. Role "public" (signed out) is selected with
 * --roles=public (ROLE_ONLY), or runs when no role filter is set.
 *
 * Page lists mirror apps/lms-spa/src/lib/nav/portals.ts (the build only uploads qa/live-e2e).
 */
const STUDENT = ["/app", "/app/learning", "/app/classes", "/app/courses", "/app/registrations", "/app/path/my", "/app/assignments", "/app/engage", "/app/certificates", "/app/practice", "/app/tests", "/app/coding", "/app/progress", "/app/diagnostic", "/app/interview-prep", "/app/mentoring", "/app/resume", "/app/companies", "/app/notifications", "/app/billing", "/app/access", "/app/support", "/app/settings/profile", "/app/account-status"];
const ADMIN = ["/admin", "/admin/approvals", "/admin/users", "/admin/roles", "/admin/privacy-requests", "/college-portal/index.html", "/admin/courses", "/admin/question-review", "/admin/batches", "/admin/certificates", "/mentor", "/mentor/students", "/mentor/slots", "/mentor/resume-reviews", "/finance", "/finance/admissions", "/finance/admissions/verify", "/finance/admissions/registrations", "/finance/admissions/plans", "/finance/orders", "/finance/refunds", "/finance/subscriptions", "/finance/invoices", "/finance/products", "/finance/coupons", "/finance/reconciliation", "/desk", "/desk/unblock-requests", "/desk/enquiries", "/security", "/security/cases", "/security/incidents", "/security/restrictions", "/security/unblock-requests", "/security/rules", "/security/reports", "/admin/audit", "/admin/policies", "/admin/ai", "/admin/system", "/admin/feature-flags", "/admin/break-glass", "/app/settings/profile", "/modules"];
const STUDIO = ["/studio", "/studio/review", "/studio/reports/errors", "/studio/courses", "/studio/media", "/studio/taxonomy", "/studio/companies", "/studio/questions", "/studio/question-banks", "/studio/coding", "/studio/tests"];
const TRAINER = ["/trainer", "/trainer/courses", "/trainer/paths", "/trainer/paths/articles", "/trainer/engage", "/trainer/grading", "/trainer/assignments", "/trainer/tests", "/trainer/integrity"];
const EVALUATOR = ["/evaluator", "/evaluator/tests", "/evaluator/integrity"];
// /courses last: it redirects to the company website (firebase.json) and WebKit has crashed on the pages after it.
const PUBLIC = ["/login", "/signup", "/forgot-password", "/help", "/legal/terms", "/legal/privacy", "/legal/refund-policy", "/legal/device-policy", "/verify", "/modules", "/courses"];

type Who = RoleKey | "public";
const PAGES: Record<Who, string[]> = { student: STUDENT, admin: ADMIN, content: STUDIO, trainer: TRAINER, evaluator: EVALUATOR, public: PUBLIC };
/** Nav hrefs each role's mobile menu must reach (the sidebar list; account pages excluded). */
// fixes-nav.md: hidden items left the menus (Admin 25 items without a gateway, Student 15). Their URLs still load (page sweep).
const ADMIN_VISIBLE = ["/admin", "/admin/approvals", "/admin/users", "/admin/roles", "/admin/privacy-requests", "/college-portal/index.html", "/admin/courses", "/admin/batches", "/admin/certificates", "/finance/admissions", "/finance/admissions/verify", "/finance/admissions/registrations", "/finance/admissions/plans", "/desk", "/desk/unblock-requests", "/security", "/security/incidents", "/security/cases", "/security/restrictions", "/admin/audit", "/admin/policies", "/admin/ai", "/admin/system", "/app/settings/profile"];
const STUDENT_VISIBLE = ["/app", "/app/learning", "/app/classes", "/app/courses", "/app/registrations", "/app/assignments", "/app/engage", "/app/certificates", "/app/practice", "/app/tests", "/app/coding", "/app/progress", "/app/interview-prep", "/app/resume", "/app/support"];
const NAV: Partial<Record<Who, string[]>> = {
  student: STUDENT_VISIBLE,
  admin: ADMIN_VISIBLE,
  content: STUDIO,
  trainer: TRAINER,
  evaluator: EVALUATOR,
};

const only = (process.env.ROLE_ONLY ?? "").split(",").map((s) => s.trim()).filter(Boolean);
const WHO: Who[] = [...roles(), ...(!only.length || only.includes("public") ? (["public"] as const) : [])];
const CHUNK = 6;
const slug = (p: string) => p.replace(/^\//, "").replace(/[^a-z0-9]+/gi, "_") || "root";

function write(name: string, data: unknown) {
  fs.mkdirSync("out/findings", { recursive: true });
  fs.writeFileSync(`out/findings/${name}.json`, JSON.stringify(data, null, 1));
}
function shotPath(info: TestInfo, who: Who, name: string) {
  const p = path.join("out", "artifacts", "shots", info.project.name, who, `${name}.jpg`);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  return p;
}
async function open(browser: Browser, info: TestInfo, who: Who) {
  const ctx = await browser.newContext({ ...info.project.use, ...(who === "public" ? {} : { storageState: stateFile(who) }) });
  return { ctx, page: await ctx.newPage() };
}
/**
 * Sign the role in again inside this context. QA accounts share a concurrent-session cap (staff 3,
 * student 2: apps/api/app/modules/admin/policy.py), so parallel runs can evict each other's session.
 */
async function relogin(page: Page, who: RoleKey) {
  const base = new URL(page.url()).origin;
  await page.request.get("/api/v1/_bff/csrf");
  const tok = (await page.context().cookies()).find((k) => k.name.endsWith("td_csrf"))?.value ?? "";
  const c = creds();
  const res = await page.request.post("/api/v1/auth/login", { data: { identifier: c.accounts[who], password: c.password }, headers: { "x-csrf-token": tok, origin: base } });
  return res.status();
}
async function settle(page: Page) {
  await page.waitForLoadState("networkidle", { timeout: 12_000 }).catch(() => undefined);
  await page.waitForTimeout(600);
}
async function snap(page: Page, file: string) {
  const h = await page.evaluate(() => document.documentElement.scrollHeight).catch(() => 0);
  const vp = page.viewportSize()!;
  await page.screenshot({ path: file, type: "jpeg", quality: 55, fullPage: true, clip: { x: 0, y: 0, width: vp.width, height: Math.max(vp.height, Math.min(h, 2600)) } }).catch(() => undefined);
}

/** Shell facts for the consistency checks (which nav is visible, header, badge, heading sizes, grid columns). */
async function shellFacts(page: Page) {
  return page.evaluate(() => {
    const vis = (el: Element | null) => { if (!el) return false; const r = el.getBoundingClientRect(); const cs = getComputedStyle(el); return r.width > 0 && r.height > 0 && cs.display !== "none" && cs.visibility !== "hidden"; };
    const header = document.querySelector("main")?.parentElement?.querySelector(":scope > header") ?? document.querySelector("header");
    const hr = header?.getBoundingClientRect();
    const h1 = document.querySelector("main h1") ?? document.querySelector("h1");
    const h1cs = h1 ? getComputedStyle(h1) : null;
    const h2 = document.querySelector("main h2");
    const main = document.querySelector("main");
    const mcs = main ? getComputedStyle(main) : null;
    const grids = Array.from(document.querySelectorAll("main *")).filter((el) => getComputedStyle(el).display === "grid" && el.children.length >= 2).slice(0, 4)
      .map((el) => ({ cols: getComputedStyle(el).gridTemplateColumns.split(" ").length, w: Math.round(el.getBoundingClientRect().width), childW: Math.round(el.children[0]!.getBoundingClientRect().width) }));
    const staffMenu = Array.from(document.querySelectorAll("button[aria-expanded]")).find((b) => /^\s*Menu/.test(b.textContent ?? "") && b.closest(".sticky"));
    return {
      sidebar: vis(document.querySelector("aside.td-adm-side")),
      tabbar: vis(document.querySelector("[data-td-tabbar]")),
      staffMenu: vis(staffMenu ?? null),
      publicHeader: vis(document.querySelector("[data-td-public-header]")),
      publicToggle: vis(document.querySelector(".td-nav-toggle-round")),
      headerH: hr ? Math.round(hr.height) : null,
      headerRight: hr ? Math.round(hr.right) : null,
      badge: Array.from(document.querySelectorAll(".td-adm-badge, header .rounded-full.font-display")).filter(vis).map((b) => (b.textContent ?? "").trim()).slice(0, 3),
      h1: h1 ? { text: (h1.textContent ?? "").trim().slice(0, 60), size: h1cs!.fontSize, weight: h1cs!.fontWeight } : null,
      h2size: h2 ? getComputedStyle(h2).fontSize : null,
      mainPad: mcs ? `${mcs.paddingLeft}/${mcs.paddingTop}` : null,
      mainW: main ? Math.round(main.getBoundingClientRect().width) : null,
      grids,
      text: (main?.textContent ?? document.body.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 160),
    };
  });
}

async function boxIn(page: Page, sel: string) {
  return page.evaluate((s) => {
    const el = document.querySelector(s); if (!el) return null;
    const r = el.getBoundingClientRect(); const vw = document.documentElement.clientWidth, vh = window.innerHeight;
    return { l: Math.round(r.left), t: Math.round(r.top), r: Math.round(r.right), b: Math.round(r.bottom), vw, vh, fits: r.left >= -1 && r.right <= vw + 1 && r.top >= -1 && r.bottom <= vh + 1, scrolls: (el as HTMLElement).scrollHeight > (el as HTMLElement).clientHeight + 1 ? getComputedStyle(el).overflowY : "n/a" };
  }, sel);
}

/** Expand every collapsed section inside `scope` and return the nav hrefs listed there. */
async function reachable(page: Page, scope: string) {
  for (let i = 0; i < 12; i++) {
    const closed = page.locator(`${scope} nav h2 button[aria-expanded=false]`);
    if (!(await closed.count())) break;
    await closed.first().tap().catch(() => closed.first().click());
    await page.waitForTimeout(100);
  }
  return page.$$eval(`${scope} nav a[href]`, (as) => as.filter((a) => (a as HTMLElement).offsetParent !== null).map((a) => new URL((a as HTMLAnchorElement).href).pathname));
}
const tapOrClick = async (page: Page, sel: string) => { const l = page.locator(sel).first(); const touch = await page.evaluate(() => matchMedia("(pointer: coarse)").matches); if (touch) await l.tap(); else await l.click(); };

// ---------------------------------------------------------------- page sweep
for (const who of WHO) {
  const pages = PAGES[who];
  for (let c = 0; c < pages.length; c += CHUNK) {
    const chunk = pages.slice(c, c + CHUNK);
    test(`responsive ${who} pages ${c / CHUNK + 1}`, async ({ browser }, info) => {
      const { ctx, page } = await open(browser, info, who);
      const w = watch(page);
      for (const url of chunk) {
        w.reset();
        const t0 = Date.now();
        let status = 0;
        try {
          const res = await page.goto(url, { waitUntil: "domcontentloaded" });
          status = res?.status() ?? 0;
          await settle(page);
        } catch (e) { w.errors.push(`goto: ${String(e).slice(0, 200)}`); }
        let relogged: number | null = null;
        if (who !== "public" && new URL(page.url()).pathname.startsWith("/login")) {
          relogged = await relogin(page, who).catch(() => -1);
          w.reset();
          await page.goto(url, { waitUntil: "domcontentloaded" }).catch(() => undefined);
          await settle(page);
        }
        const finalUrl = new URL(page.url()).pathname;
        const issues = await layoutReport(page).catch((e) => [{ kind: "probe-error", detail: String(e).slice(0, 200) }]);
        const facts = await shellFacts(page).catch(() => null);
        const shot = shotPath(info, who, slug(url));
        await snap(page, shot);
        write(`responsive-${who}-${info.project.name}-${slug(url)}`, { who, project: info.project.name, viewport: page.viewportSize(), url, finalUrl, status, relogged, ms: Date.now() - t0, issues, facts, shot: shot.replace(/^out[\\/]/, ""), api: w.api, errors: w.errors.slice(0, 5) });
      }
      await ctx.close();
    });
  }
}

// ---------------------------------------------------------------- navigation behaviour
for (const who of WHO) {
  test(`responsive ${who} navigation`, async ({ browser }, info) => {
    const { ctx, page } = await open(browser, info, who);
    const r: Record<string, unknown> = { who, project: info.project.name, viewport: page.viewportSize() };
    const step = async (name: string, fn: () => Promise<unknown>) => { try { r[name] = await fn(); } catch (e) { r[name] = { error: String(e).slice(0, 240) }; } };
    const shotsDir = (n: string) => shotPath(info, who, `nav-${n}`);

    if (who === "public") {
      // /courses redirects to the company website (firebase.json); /login carries the LMS public header.
      await page.goto("/login"); await settle(page);
      await step("facts", () => shellFacts(page));
      await step("publicMenu", async () => {
        const sel = "header button[aria-expanded][aria-controls]";
        const t = page.locator(sel).last();
        if (!(await t.count()) || !(await t.isVisible())) return { toggle: false };
        const bb = await t.boundingBox();
        await t.tap().catch(() => t.click());
        await page.waitForTimeout(400);
        const id = await t.getAttribute("aria-controls");
        const panel = await boxIn(page, `[id="${id}"] [class*=panel], [id="${id}"]`);
        await snap(page, shotsDir("public-menu"));
        const links = await page.$$eval(`[id="${id}"] a[href]`, (as) => as.filter((a) => (a as HTMLElement).offsetParent !== null).map((a) => (a.textContent ?? "").trim()).filter(Boolean));
        const close = page.locator(`[id="${id}"] button[aria-label="Close menu"]`).filter({ visible: true }).first();
        if (await close.count()) await close.tap().catch(() => close.click()); else await page.keyboard.press("Escape");
        await page.waitForTimeout(300);
        return { toggle: true, button: bb, panel, links, closed: !(await page.locator(`[id="${id}"]`).isVisible().catch(() => false)) };
      });
      write(`responsive-nav-${who}-${info.project.name}`, r);
      await ctx.close();
      return;
    }

    const home = PAGES[who][0]!;
    await page.goto(home); await settle(page);
    if (new URL(page.url()).pathname.startsWith("/login")) { r.relogged = await relogin(page, who); await page.goto(home); await settle(page); }
    await step("facts", () => shellFacts(page));
    const isLg = (page.viewportSize()?.width ?? 0) >= 1024;

    if (isLg) {
      await step("ctrlK", async () => {
        await page.keyboard.press("Control+k");
        await page.waitForTimeout(200);
        return page.evaluate(() => (document.activeElement as HTMLInputElement | null)?.getAttribute("aria-label") ?? document.activeElement?.tagName ?? null);
      });
      await step("sidebarReach", async () => {
        const got = await reachable(page, "aside.td-adm-side");
        return { missing: (NAV[who] ?? []).filter((h) => !got.includes(h)), extra: got.filter((h) => !(NAV[who] ?? []).includes(h)), count: got.length };
      });
    } else if (who === "student") {
      await step("moreSheet", async () => {
        await tapOrClick(page, "[data-td-tabbar] button[aria-controls]");
        await page.waitForTimeout(400);
        const sheet = await boxIn(page, "[role=dialog][aria-labelledby]");
        await snap(page, shotsDir("more-sheet"));
        const got = await reachable(page, "[role=dialog][aria-labelledby]");
        const tabs = await page.$$eval("[data-td-tabbar] a[href]", (as) => as.map((a) => new URL((a as HTMLAnchorElement).href).pathname));
        const reach = [...got, ...tabs];
        const search = await page.locator("[role=dialog][aria-labelledby] input[type=search]").count();
        const target = got.find((h) => h !== "/app" && h !== page.url()) ?? "/app/support";
        await page.locator(`[role=dialog][aria-labelledby] nav a[href="${target}"]`).first().tap();
        await page.waitForURL((u) => u.pathname === target, { timeout: 15_000 }).catch(() => undefined);
        await page.waitForTimeout(400);
        const closed = !(await page.locator("[role=dialog][aria-labelledby]").isVisible().catch(() => false));
        return { sheet, missing: (NAV[who] ?? []).filter((h) => !reach.includes(h)), extra: Array.from(new Set(reach)).filter((h) => !(NAV[who] ?? []).includes(h)), count: new Set(reach).size, search: search > 0, navigatedTo: new URL(page.url()).pathname, closedAfterNav: closed };
      });
    } else {
      await step("staffMenu", async () => {
        const btn = page.locator("div.sticky > button[aria-expanded]").filter({ hasText: "Menu" }).first();
        if (!(await btn.isVisible())) return { visible: false };
        await btn.tap();
        await page.waitForTimeout(400);
        const id = await btn.getAttribute("aria-controls");
        const panel = await boxIn(page, `[id="${id}"]`);
        await snap(page, shotsDir("staff-menu"));
        const got = await reachable(page, `[id="${id}"]`);
        const search = await page.locator(`[id="${id}"] input[type=search]`).count();
        // search on touch (the Ctrl K equivalent): type and read the filtered list
        let searchWorks: unknown = null;
        if (search) {
          await page.locator(`[id="${id}"] input[type=search]`).fill("test");
          await page.waitForTimeout(200);
          searchWorks = await page.$$eval(`[id="${id}"] ul[aria-label="Matching pages"] a`, (as) => as.length);
          await page.locator(`[id="${id}"] input[type=search]`).fill("");
        }
        const target = (NAV[who] ?? []).find((h) => h !== home && got.includes(h) && !h.endsWith(".html"));
        if (target) {
          await page.locator(`[id="${id}"] nav a[href="${target}"]`).first().tap();
          await page.waitForURL((u) => u.pathname === target, { timeout: 15_000 }).catch(() => undefined);
          await page.waitForTimeout(400);
        }
        return { visible: true, panel, missing: (NAV[who] ?? []).filter((h) => !got.includes(h)), extra: got.filter((h) => !(NAV[who] ?? []).includes(h)), count: got.length, search: search > 0, searchWorks, navigatedTo: new URL(page.url()).pathname, closedAfterNav: (await btn.getAttribute("aria-expanded")) === "false" };
      });
    }

    await page.goto(home); await settle(page);
    await step("accountMenu", async () => {
      const b = page.locator("header button[aria-label^=Account]").first();
      if (!(await b.isVisible())) return { visible: false };
      const bb = await b.boundingBox();
      await tapOrClick(page, "header button[aria-label^=Account]");
      await page.waitForTimeout(300);
      const id = await b.getAttribute("aria-controls");
      const panel = await boxIn(page, `[id="${id}"]`);
      await snap(page, shotsDir("account-menu"));
      await page.keyboard.press("Escape");
      return { button: bb, panel };
    });
    for (const [name, text] of [["portalSwitcher", "Switch portal"], ["moduleSwitcher", "Modules"]] as const) {
      await step(name, async () => {
        const s = page.locator("header summary").filter({ hasText: text }).first();
        if (!(await s.count()) || !(await s.isVisible())) return { visible: false };
        const bb = await s.boundingBox();
        await s.tap().catch(() => s.click());
        await page.waitForTimeout(300);
        const panel = await page.evaluate((t) => {
          const d = Array.from(document.querySelectorAll("header details")).find((x) => x.querySelector("summary")?.textContent?.includes(t));
          const ul = d?.querySelector("ul"); if (!ul) return null;
          const r = ul.getBoundingClientRect(); const vw = document.documentElement.clientWidth;
          return { open: (d as HTMLDetailsElement).open, l: Math.round(r.left), r: Math.round(r.right), b: Math.round(r.bottom), vw, fits: r.left >= -1 && r.right <= vw + 1 };
        }, text);
        await snap(page, shotsDir(name));
        await s.tap().catch(() => s.click());
        return { button: bb, panel };
      });
    }
    write(`responsive-nav-${who}-${info.project.name}`, r);
    await ctx.close();
  });
}

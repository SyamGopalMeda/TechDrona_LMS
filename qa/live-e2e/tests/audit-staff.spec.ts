import fs from "node:fs";
import { test, type Page, type BrowserContext } from "@playwright/test";
import { HOME, roles, stateFile, type RoleKey } from "../lib/roles";
import { layoutIssues, watch, shot } from "../lib/probe";

/**
 * Staff portal audit (trainer / evaluator / content). READ-ONLY: navigation, opening tabs,
 * menus and the "Find a page" search. Never submits a form. Findings → out/findings/audit-staff-*.json
 */

const NAV: Record<string, string[]> = {
  trainer: ["/trainer", "/trainer/courses", "/trainer/paths", "/trainer/paths/articles", "/trainer/engage", "/trainer/engage/new", "/trainer/grading", "/trainer/assignments", "/trainer/tests", "/trainer/integrity"],
  evaluator: ["/evaluator", "/evaluator/tests", "/evaluator/integrity"],
  content: ["/studio", "/studio/review", "/studio/reports/errors", "/studio/courses", "/studio/media", "/studio/taxonomy", "/studio/questions", "/studio/questions/import", "/studio/question-banks", "/studio/coding", "/studio/tests"],
};

const FOREIGN: Record<string, string[]> = {
  "/admin": ["/admin", "/admin/users", "/admin/audit"],
  "/finance": ["/finance", "/finance/orders", "/finance/admissions/verify"],
  "/desk": ["/desk", "/desk/unblock-requests"],
  "/security": ["/security", "/security/cases", "/security/rules"],
  "/studio": ["/studio", "/studio/questions", "/studio/review"],
  "/trainer": ["/trainer", "/trainer/tests", "/trainer/courses"],
  "/evaluator": ["/evaluator", "/evaluator/tests", "/evaluator/integrity"],
  "/app": ["/app", "/app/learning", "/app/billing"],
};

const FOREIGN_API = [
  "admin/approvals", "admin/feature-flags", "admin/privacy-requests", "admin/ai-settings", "admin/apps",
  "reports/platform", "reports/revenue", "orders", "refunds", "reconciliation", "invoices", "subscriptions",
  "coupons", "support/queue", "roles", "grants", "security/cases", "audit", "users", "admin/users",
  "studio/coding/problems", "questions", "studio/tests", "batches",
];

type Visit = {
  url: string; final: string; h1: string; title: string; status: string; api: string[]; errors: string[];
  tabs: { name: string; api: string[]; text: string }[]; layout: string[]; snippet: string; links: string[]; ms: number;
};

async function settle(page: Page) {
  await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => undefined);
  await page.waitForTimeout(1200);
}

async function pageState(page: Page) {
  return page.evaluate(() => {
    const main = document.querySelector("main") ?? document.body;
    const text = (main as HTMLElement).innerText ?? "";
    const h1 = document.querySelector("h1")?.textContent?.trim() ?? "";
    const busy = !!document.querySelector("[aria-busy=true]") || /Loading/i.test(text.slice(0, 600));
    const bad: string[] = [];
    for (const re of [/don.t have permission/i, /permission denied/i, /forbidden/i, /something went wrong/i, /couldn.t be loaded/i, /couldn.t load/i, /not found/i, /unexpected error/i, /no access/i, /try again/i])
      if (re.test(text)) bad.push(re.source);
    const links = Array.from(document.querySelectorAll("main a[href], nav a[href], header a[href]"))
      .map((a) => (a as HTMLAnchorElement).getAttribute("href") ?? "").filter((h) => h.startsWith("/") || h.startsWith("http"));
    return { h1, busy, bad, snippet: text.replace(/\s+/g, " ").slice(0, 500), links: Array.from(new Set(links)), empty: text.trim().length < 40 };
  });
}

async function visit(page: Page, w: ReturnType<typeof watch>, url: string, info: Parameters<typeof shot>[1], doShot: boolean, tabs = true): Promise<Visit> {
  w.reset();
  const t0 = Date.now();
  await page.goto(url, { waitUntil: "domcontentloaded" }).catch((e) => w.errors.push(`goto: ${String(e).slice(0, 200)}`));
  await settle(page);
  const s = await pageState(page);
  const v: Visit = {
    url, final: new URL(page.url()).pathname + new URL(page.url()).search, h1: s.h1, title: await page.title(),
    status: [s.busy ? "busy/loading" : "", s.empty ? "blank" : "", ...s.bad].filter(Boolean).join(", ") || "ok",
    api: [...w.api], errors: [...w.errors], tabs: [], layout: await layoutIssues(page), snippet: s.snippet, links: s.links, ms: Date.now() - t0,
  };
  if (doShot) await shot(page, info, `${url}`).catch(() => undefined);
  if (tabs) {
    const tabEls = page.locator("[role=tab]");
    const n = Math.min(await tabEls.count(), 8);
    for (let i = 0; i < n; i++) {
      const tab = tabEls.nth(i);
      const name = ((await tab.textContent()) ?? "").trim().slice(0, 40);
      w.reset();
      await tab.click({ timeout: 5000 }).catch(() => undefined);
      await settle(page);
      const ts = await pageState(page);
      v.tabs.push({ name, api: [...w.api], text: ts.snippet.slice(0, 200) });
      if (doShot) await shot(page, info, `${url}-tab-${name}`).catch(() => undefined);
    }
  }
  return v;
}

async function api(ctx: BrowserContext, path: string) {
  const r = await ctx.request.get(`/api/v1/${path}`).catch(() => null);
  if (!r) return { status: 0, body: null as unknown };
  let body: unknown = null;
  try { body = await r.json(); } catch { body = null; }
  return { status: r.status(), body };
}

const ids = (body: unknown, ...keys: string[]): string[] => {
  const arr = (body as { data?: unknown[]; items?: unknown[] } | null);
  const list = (arr?.data ?? arr?.items ?? (Array.isArray(body) ? body : [])) as Record<string, unknown>[];
  return list.map((x) => keys.map((k) => x?.[k]).find(Boolean) as string).filter(Boolean);
};

for (const r of roles().filter((x) => ["trainer", "evaluator", "content"].includes(x))) {
  test(`audit-staff ${r}`, async ({ browser }, info) => {
    test.setTimeout(25 * 60_000);
    const full = info.project.name === "desktop";
    const doShot = true;
    const ctx = await browser.newContext({ ...info.project.use, storageState: stateFile(r as RoleKey) });
    const page = await ctx.newPage();
    const w = watch(page);
    const home = HOME[r as RoleKey];
    const out: Record<string, unknown> = { role: r, project: info.project.name };
    const save = () => {
      fs.mkdirSync("out/findings", { recursive: true });
      fs.writeFileSync(`out/findings/audit-staff-${r}-${info.project.name}.json`, JSON.stringify(out, null, 1));
    };

    // ---- API discovery (GETs only)
    const grants = await api(ctx, "me/grants");
    out.grants = grants;
    out.modules = await api(ctx, "me/modules");
    const batchIds = ((grants.body as { data?: { scope_type?: string; scope_id?: string }[] })?.data ?? [])
      .filter((g) => g.scope_type === "batch" && g.scope_id).map((g) => g.scope_id!) ;
    const tests = await api(ctx, "studio/tests");
    const testIds = ids(tests.body, "id", "test_id").slice(0, 3);
    const assigns = await api(ctx, "assignments?scope=mine&limit=100");
    const assignIds = ids(assigns.body, "assignment_id", "id").slice(0, 2);
    const ownApi: Record<string, number> = {};
    const probe = async (p: string) => { const res = await api(ctx, p); ownApi[p] = res.status; return res; };
    for (const p of ["me", "me/grants", "batches", "batches?mine=true", "studio/tests", "assignments?scope=mine&limit=100", "integrity/flags?status=open&limit=25", "courses", "paths", "path-articles", "activities", "questions", "companies", "topics", "placement/subjects"]) await probe(p);
    const attemptIds: string[] = [];
    for (const b of batchIds) { await probe(`batches/${b}`); await probe(`batches/${b}/members`); await probe(`batches/${b}/classes`); }
    for (const t of testIds) {
      const at = await probe(`tests/${t}/attempts`);
      attemptIds.push(...ids(at.body, "id", "attempt_id").slice(0, 2));
      await probe(`tests/${t}/report`); await probe(`tests/${t}/evaluation`); await probe(`tests/${t}/overrides`); await probe(`studio/tests/${t}`);
    }
    for (const a of attemptIds.slice(0, 2)) { await probe(`attempts/${a}/result`); await probe(`attempts/${a}/review`); await probe(`attempts/${a}/evaluation`); }
    for (const a of assignIds) { await probe(`assignments/${a}`); await probe(`assignments/${a}/submissions`); }
    out.discovered = { batchIds, testIds, attemptIds, assignIds, testsStatus: tests.status, assignsStatus: assigns.status };
    out.ownApi = ownApi;
    const foreignApi: Record<string, number> = {};
    for (const p of FOREIGN_API) foreignApi[p] = (await api(ctx, p)).status;
    out.foreignApi = foreignApi;
    save();

    // ---- home: shell chrome
    const homeVisit = await visit(page, w, home, info, doShot, false);
    const chrome = await page.evaluate(() => {
      const navs = Array.from(document.querySelectorAll("nav")).map((n) => ({
        label: n.getAttribute("aria-label"),
        items: Array.from(n.querySelectorAll("a[href]")).map((a) => `${(a.textContent ?? "").trim()} -> ${a.getAttribute("href")}`),
        sections: Array.from(n.querySelectorAll("h2 button")).map((b) => (b.textContent ?? "").trim()),
      }));
      const headerBtns = Array.from(document.querySelectorAll("header button, header summary")).map((b) => (b.getAttribute("aria-label") ?? b.textContent ?? "").trim());
      return { navs, headerBtns };
    });
    out.chrome = chrome;
    // account menu
    const acct = page.locator("button[aria-label^='Account']").first();
    if (await acct.count()) {
      await acct.click().catch(() => undefined);
      await page.waitForTimeout(500);
      out.accountMenu = await page.evaluate(() => {
        const b = document.querySelector("button[aria-label^='Account']");
        const panel = b ? document.getElementById(b.getAttribute("aria-controls") ?? "") : null;
        return panel ? Array.from(panel.querySelectorAll("a, button")).map((a) => `${(a.textContent ?? "").trim()} -> ${a.getAttribute("href") ?? "(button)"}`) : [];
      });
      if (doShot) await shot(page, info, "account-menu");
      await page.keyboard.press("Escape");
    }
    // portal + module switchers
    for (const label of ["Switch portal", "Modules"]) {
      const s = page.locator("summary", { hasText: label }).first();
      if (await s.count()) {
        await s.click().catch(() => undefined);
        await page.waitForTimeout(300);
        out[`switcher:${label}`] = await s.locator("xpath=..").locator("a").evaluateAll((as) => as.map((a) => `${(a.textContent ?? "").trim()} -> ${a.getAttribute("href")}`));
        await s.click().catch(() => undefined);
      } else out[`switcher:${label}`] = "not shown";
    }
    // Find a page (Ctrl K)
    const find: Record<string, unknown> = {};
    await page.keyboard.press("Control+k");
    await page.waitForTimeout(300);
    find.focused = await page.evaluate(() => document.activeElement?.getAttribute("aria-label") ?? document.activeElement?.tagName ?? null);
    const box = page.locator("input[aria-label='Find a page']").first();
    if (await box.count() && (await box.isVisible())) {
      for (const q of ["a", "e", "admin", "finance", "student", "grade", "grades", "test", "tests", "test results", "pract", "settings", "profile", "question", "course", "billing"]) {
        await box.fill(q);
        await page.waitForTimeout(250);
        find[q] = await page.evaluate(() => {
          const ul = document.querySelector("ul[aria-label='Matching pages']");
          return ul ? Array.from(ul.querySelectorAll("a")).map((a) => `${(a.textContent ?? "").trim()} -> ${a.getAttribute("href")}`) : ["(no matches)"];
        });
      }
      await box.fill("");
    } else find.visible = false;
    out.find = find;
    save();

    // ---- own portal pages
    const visits: Visit[] = [homeVisit];
    const seen = new Set<string>([home]);
    for (const u of NAV[r]) {
      if (seen.has(u)) continue;
      seen.add(u);
      visits.push(await visit(page, w, u, info, doShot));
      out.visits = visits; save();
    }
    // Integrity batch filter (staff-portals F1 / fixes-api F1): options listed, choosing one makes no 4xx call.
    if (r === "trainer" || r === "evaluator") {
      w.reset();
      const ip = r === "evaluator" ? "/evaluator/integrity" : "/trainer/integrity";
      const calls: string[] = [];
      const onResp = (res: import("@playwright/test").Response) => { const u = res.url(); if (u.includes("/api/")) calls.push(`${res.status()} ${res.request().method()} ${u.split("/api/")[1]?.slice(0, 140)}`); };
      page.on("response", onResp);
      await page.goto(ip, { waitUntil: "domcontentloaded" }).catch(() => undefined);
      await settle(page);
      await page.waitForTimeout(1500);
      const sel = page.getByLabel("Batch", { exact: true }).first();
      const filter: Record<string, unknown> = { page: ip, present: (await sel.count()) > 0 };
      if (filter.present) {
        filter.options = await sel.evaluate((el) => Array.from((el as HTMLSelectElement).options ?? []).map((o) => `${o.value}|${o.textContent?.trim()}`)).catch(() => null);
        const opts = (filter.options as string[] | null) ?? [];
        const first = opts.map((o) => o.split("|")[0]).find((v) => v);
        if (first) {
          const before = calls.length;
          await sel.selectOption(first).catch((e) => (filter.selectError = String(e).slice(0, 200)));
          await settle(page);
          filter.afterSelect = calls.slice(before);
          filter.afterSelectText = (await pageState(page)).snippet.slice(0, 300);
        }
      }
      filter.calls = calls.slice();
      filter.failed = calls.filter((c) => /^[45]\d\d /.test(c));
      filter.errors = [...w.errors];
      await shot(page, info, `${ip}-batch-filter`).catch(() => undefined);
      page.off("response", onResp);
      out.integrityFilter = filter;
      save();
    }

    // deep pages: links discovered in own prefix + id-based routes
    const deep: string[] = [];
    for (const v of visits) for (const l of v.links) if (l.startsWith(home + "/") && !seen.has(l.split("#")[0]!)) deep.push(l.split("#")[0]!);
    const guessed: string[] = [];
    if (r === "trainer") {
      for (const b of batchIds) guessed.push(`/trainer/batches/${b}`);
      for (const t of testIds) for (const s of ["attempts", "edit", "evaluation", "overrides", "report"]) guessed.push(`/trainer/tests/${t}/${s}`);
      for (const a of assignIds) guessed.push(`/trainer/assignments/${a}`, `/trainer/grading/assignments/${a}`);
    } else if (r === "evaluator") {
      for (const t of testIds) for (const s of ["evaluation", "report"]) guessed.push(`/evaluator/tests/${t}/${s}`);
      for (const a of assignIds) guessed.push(`/evaluator/grading/assignments/${a}`);
      for (const b of batchIds) guessed.push(`/trainer/batches/${b}`);
    } else {
      for (const t of testIds) guessed.push(`/studio/tests/${t}`);
    }
    const deepList = Array.from(new Set([...guessed, ...deep])).slice(0, full ? 30 : 8);
    for (const u of deepList) {
      if (seen.has(u)) continue;
      seen.add(u);
      visits.push(await visit(page, w, u, info, doShot && full));
      out.visits = visits; save();
    }
    out.externalLinks = Array.from(new Set(visits.flatMap((v) => v.links).filter((l) => !l.startsWith(home)))).slice(0, 80);

    // ---- shared account pages
    if (full) {
      const acc: Visit[] = [];
      for (const u of ["/app/settings/profile", "/app/account-status"]) acc.push(await visit(page, w, u, info, doShot, false));
      out.accountPages = acc;
    }

    // ---- cross-portal
    if (full) {
      const cross: { url: string; final: string; h1: string; api: string[]; navLabels: string[] }[] = [];
      for (const [prefix, urls] of Object.entries(FOREIGN)) {
        if (prefix === home) continue;
        for (const u of urls) {
          w.reset();
          await page.goto(u, { waitUntil: "domcontentloaded" }).catch(() => undefined);
          await settle(page);
          const s = await pageState(page);
          const navLabels = await page.evaluate(() => Array.from(document.querySelectorAll("nav a[href]")).slice(0, 6).map((a) => (a.textContent ?? "").trim()));
          cross.push({ url: u, final: new URL(page.url()).pathname, h1: s.h1, api: [...w.api], navLabels });
          if (new URL(page.url()).pathname.startsWith("/login")) { (out.sessionLost as string[] | undefined)?.push(u) ?? (out.sessionLost = [u]); }
          if (!new URL(page.url()).pathname.startsWith(home) && !new URL(page.url()).pathname.startsWith("/login")) await shot(page, info, `cross-${u}`).catch(() => undefined);
        }
      }
      out.cross = cross;
    }
    save();
    await ctx.close();
  });
}

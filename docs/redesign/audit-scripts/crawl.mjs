// Page-by-page crawl for one role: every static route of the role's portals, then dynamic routes
// filled from links discovered on the way, then a link check of every internal href seen, then
// cross-portal access probes. Read-only: it only navigates (GET); it never clicks submit buttons.
// Usage: node crawl.mjs <role> <inv.json>
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { chromium, roleContext, watch, BASE, SHOTS, STATE, slug, sleep } from "./lib.mjs";

const role = process.argv[2];
const inv = JSON.parse(readFileSync(process.argv[3], "utf8"));
const PREFIX = {
  student: ["/app", "/read"],
  admin: ["/admin", "/finance", "/desk", "/security", "/mentor"],
  trainer: ["/trainer", "/read"],
  evaluator: ["/evaluator"],
  content: ["/studio"],
  public: ["PUBLIC"],
};
const PORTAL_ROOTS = ["/app", "/admin", "/trainer", "/evaluator", "/studio", "/finance", "/desk", "/security", "/mentor"];
const inScope = (r) =>
  PREFIX[role].includes("PUBLIC")
    ? !PORTAL_ROOTS.some((p) => r === p || r.startsWith(`${p}/`)) && !r.startsWith("/read")
    : PREFIX[role].some((p) => r === p || r.startsWith(`${p}/`));
const routes = inv.filter((x) => inScope(x.route));
const statics = routes.filter((x) => !x.route.includes("["));
const dynamics = routes.filter((x) => x.route.includes("["));
const toRe = (r) => new RegExp(`^${r.replace(/\[\.\.\.[^\]]+\]/g, ".+").replace(/\[[^\]]+\]/g, "[^/?#]+")}$`);

const browser = await chromium.launch();
const ctx = role === "public" ? await browser.newContext({ viewport: { width: 1280, height: 800 } }) : await roleContext(browser, role);
const bucket = watch(ctx);
const page = await ctx.newPage();
const results = [];
const hrefs = new Set();

async function visit(route, url) {
  bucket.reset();
  const t0 = Date.now();
  let docStatus = null;
  let navErr = null;
  try {
    const resp = await page.goto(`${BASE}${url}`, { waitUntil: "load", timeout: 45_000 });
    docStatus = resp?.status() ?? null;
  } catch (e) {
    navErr = String(e).slice(0, 200);
  }
  await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => undefined);
  await sleep(600);
  const info = await page
    .evaluate(() => {
      const main = document.querySelector("main") ?? document.body;
      const txt = (el) => (el?.textContent ?? "").replace(/\s+/g, " ").trim();
      const alerts = Array.from(main.querySelectorAll('[role="alert"]')).map((a) => txt(a).slice(0, 200)).filter(Boolean);
      const links = Array.from(document.querySelectorAll("a[href]")).map((a) => a.getAttribute("href"));
      const buttons = Array.from(main.querySelectorAll("button"));
      const deadButtons = buttons.filter((b) => !b.disabled && !b.type?.match(/submit|reset/) && !b.getAttribute("aria-controls") && !b.getAttribute("aria-haspopup") && !b.getAttribute("aria-expanded") && !b.closest("form") && !b.onclick && !Object.keys(b).some((k) => k.startsWith("__reactProps") && b[k]?.onClick)).map((b) => txt(b).slice(0, 40));
      const busy = main.querySelectorAll('[aria-busy="true"]').length;
      const emptyHeads = Array.from(main.querySelectorAll("p.font-display, h2, h3")).map((e) => txt(e)).filter((t) => /^No |nothing|not available|aren't available|Not yet implemented|coming/i.test(t)).slice(0, 4);
      return {
        h1: txt(document.querySelector("h1")).slice(0, 100),
        title: document.title,
        alerts,
        links,
        buttons: buttons.length,
        deadButtons,
        busy,
        emptyHeads,
        forbidden: /You don.t have access to the/.test(txt(main)),
        notFound: /Page not found/.test(txt(document.querySelector("h1"))),
        notImplemented: /Not yet implemented/.test(txt(main)),
        textLen: txt(main).length,
      };
    })
    .catch((e) => ({ evalErr: String(e).slice(0, 200), links: [] }));
  for (const h of info.links ?? []) {
    if (!h || !h.startsWith("/") || h.startsWith("//") || h.startsWith("/api/")) continue;
    hrefs.add(h.split("#")[0]);
  }
  const shot = `${role}__${slug(url)}.png`;
  await page.screenshot({ path: path.join(SHOTS, shot) }).catch(() => undefined);
  const final = page.url().replace(BASE, "");
  const r = {
    route,
    url,
    final,
    docStatus,
    navErr,
    ms: Date.now() - t0,
    ...info,
    links: undefined,
    console: [...new Set(bucket.console)].slice(0, 8),
    http: [...new Set(bucket.http)].slice(0, 12),
    failed: [...new Set(bucket.failed)].slice(0, 6),
    shot: `docs/redesign/shots/audit/${shot}`,
  };
  results.push(r);
  console.log(`${docStatus ?? "ERR"} ${url} -> ${final} | h1="${r.h1 ?? ""}" alerts=${r.alerts?.length ?? "?"} http=${r.http.length} console=${r.console.length}${r.forbidden ? " FORBIDDEN" : ""}${r.notFound ? " 404" : ""}${r.notImplemented ? " NOT-IMPL" : ""}${r.busy ? ` busy=${r.busy}` : ""}`);
  return r;
}

for (const x of statics) await visit(x.route, x.route);

// dynamic routes: up to 3 discovery rounds
const done = new Set();
for (let round = 0; round < 3; round += 1) {
  for (const x of dynamics) {
    if (done.has(x.route)) continue;
    const re = toRe(x.route);
    const hit = [...hrefs].map((h) => h.split("?")[0]).find((h) => re.test(h) && !/\/new$/.test(h));
    if (hit) {
      done.add(x.route);
      await visit(x.route, hit);
    }
  }
}
for (const x of dynamics) if (!done.has(x.route)) results.push({ route: x.route, url: null, skipped: "no instance link discovered" });

// link check: every internal href seen that was not visited
const visited = new Set(results.map((r) => r.url));
const linkCheck = [];
for (const h of [...hrefs].filter((h) => !visited.has(h)).slice(0, 400)) {
  try {
    const r = await page.request.get(`${BASE}${h}`, { maxRedirects: 5, timeout: 30_000 });
    if (r.status() >= 400) linkCheck.push({ href: h, status: r.status() });
  } catch (e) {
    linkCheck.push({ href: h, error: String(e).slice(0, 120) });
  }
}

// cross-portal probes (UX gate) — every other portal root plus one deep page each
const probes = [];
if (role !== "public") {
  const deep = ["/app", "/app/billing", "/admin", "/admin/users", "/admin/ai", "/trainer", "/trainer/assignments", "/evaluator", "/studio", "/studio/questions", "/finance", "/desk/enquiries", "/security", "/mentor"];
  for (const u of deep) {
    if (PREFIX[role].some((p) => u === p || u.startsWith(`${p}/`))) continue;
    const r = await visit(`PROBE ${u}`, u);
    probes.push({ url: u, final: r.final, forbidden: r.forbidden, h1: r.h1, http: r.http });
  }
}

writeFileSync(path.join(STATE, `crawl-${role}.json`), JSON.stringify({ role, results, linkCheck, probes, hrefCount: hrefs.size }, null, 1));
console.log(`DONE ${role}: pages=${results.length} links=${hrefs.size} brokenLinks=${linkCheck.length}`);
await browser.close();

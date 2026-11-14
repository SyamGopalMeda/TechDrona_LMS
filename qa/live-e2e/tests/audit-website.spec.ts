import fs from "node:fs";
import { test, type Page, type BrowserContext } from "@playwright/test";
import { layoutIssues, watch } from "../lib/probe";

/**
 * Read-only audit of the LIVE public website and its links into the LIVE LMS.
 * No storageState (no QA login needed). Never submits a form: it only opens forms, focuses and
 * blurs empty fields, and checks that buttons exist.
 *   bash qa/live-e2e/run.sh tests/audit-website.spec.ts --projects=all --roles=student --shots
 */
const SITE = (process.env.SITE_URL ?? "https://techdrona-website.web.app").replace(/\/+$/, "");
const LMS = (process.env.LMS_URL ?? "https://techdrona-lms-app.web.app").replace(/\/+$/, "");
const SITE_HOST = new URL(SITE).host;
const LMS_HOST = new URL(LMS).host;

function save(name: string, data: unknown) {
  fs.mkdirSync("out/findings", { recursive: true });
  fs.writeFileSync(`out/findings/website-${name}.json`, JSON.stringify(data, null, 1));
}

async function freshPage(browser: import("@playwright/test").Browser, info: import("@playwright/test").TestInfo) {
  const ctx = await browser.newContext({ ...info.project.use, storageState: undefined });
  const page = await ctx.newPage();
  return { ctx, page };
}

/** Every failed request and every HTTP >= 400 response on the page (not only /api/). */
function net(page: Page) {
  const failed: string[] = [];
  page.on("requestfailed", (r) => {
    const e = r.failure()?.errorText ?? "";
    if (/ERR_ABORTED/.test(e) && /\.(mp4|webm)(\?|$)/.test(r.url())) return; // media range aborts are normal
    failed.push(`FAILED(${e}) ${r.method()} ${r.url().slice(0, 220)}`);
  });
  page.on("response", (r) => { if (r.status() >= 400) failed.push(`${r.status()} ${r.request().method()} ${r.url().slice(0, 220)}`); });
  return { failed, reset() { failed.length = 0; } };
}

/** Wait for the network, then scroll the whole page so scroll-reveal sections and lazy images load. */
async function settle(page: Page) {
  await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
  await page.evaluate(async () => {
    const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
    const L = (window as unknown as { __lenis?: { scrollTo: (y: number, o: object) => void } }).__lenis;
    const go = (y: number) => { if (L) L.scrollTo(y, { immediate: true, force: true }); window.scrollTo(0, y); };
    for (let i = 0, y = 0; i < 80 && y < document.documentElement.scrollHeight; i++) { y += Math.round(innerHeight * 0.7); go(y); await sleep(110); }
    await sleep(400);
    go(0);
    await sleep(300);
  }).catch(() => {});
  await page.waitForLoadState("networkidle", { timeout: 8_000 }).catch(() => {});
}

/** SEO + content + image audit of the current page. */
async function pageFacts(page: Page) {
  return page.evaluate(() => {
    const vw = innerWidth, vh = innerHeight;
    const metas = (n: string) => Array.from(document.querySelectorAll(`meta[name="${n}"]`)).map((m) => m.getAttribute("content") ?? "");
    const h1 = Array.from(document.querySelectorAll("h1")).map((h) => (h.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 90));
    const img: string[] = [];
    let imgCount = 0;
    for (const el of Array.from(document.images)) {
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      if (r.width < 8 || r.height < 8 || cs.visibility === "hidden" || cs.display === "none") continue;
      imgCount++;
      const src = (el.currentSrc || el.src).split("/").slice(-2).join("/").slice(0, 80);
      if (el.complete && el.naturalWidth === 0) img.push(`broken: ${src}`);
      if (!el.hasAttribute("alt")) img.push(`no alt attribute: ${src}`);
      if (el.naturalWidth > 0 && cs.objectFit === "fill") {
        const nat = el.naturalWidth / el.naturalHeight, ren = r.width / r.height;
        if (Math.abs(nat - ren) / nat > 0.06 && r.width > 40) img.push(`stretched ${Math.round(r.width)}x${Math.round(r.height)} (natural ${el.naturalWidth}x${el.naturalHeight}): ${src}`);
      }
      if (el.naturalWidth > 0 && el.naturalWidth < r.width * 0.75 && r.width > 120) img.push(`upscaled/blurry rendered ${Math.round(r.width)}px from ${el.naturalWidth}px: ${src}`);
      const top = r.top + scrollY;
      if (top > vh * 2 && el.loading !== "lazy") img.push(`not lazy (y=${Math.round(top)}): ${src}`);
    }
    // smallest visible text
    let small = 0; const smallSample: string[] = [];
    for (const el of Array.from(document.querySelectorAll("p, li, a, span, small, label, td, button"))) {
      const t = Array.from(el.childNodes).filter((n) => n.nodeType === 3).map((n) => n.textContent ?? "").join("").trim();
      if (t.length < 3) continue;
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      const fs = parseFloat(getComputedStyle(el).fontSize);
      if (fs < 12) { small++; if (smallSample.length < 4) smallSample.push(`${fs}px "${t.slice(0, 40)}"`); }
    }
    const links = Array.from(document.querySelectorAll("a[href]")).map((a) => ({ href: (a as HTMLAnchorElement).href, text: (a.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 60), raw: a.getAttribute("href") ?? "" }));
    return {
      title: document.title,
      descriptions: metas("description"),
      canonical: Array.from(document.querySelectorAll('link[rel="canonical"]')).map((l) => l.getAttribute("href")),
      robots: metas("robots"),
      ogImage: document.querySelector('meta[property="og:image"]')?.getAttribute("content") ?? null,
      favicon: document.querySelector('link[rel="icon"]')?.getAttribute("href") ?? null,
      h1,
      textLength: (document.body.innerText ?? "").trim().length,
      notFound: /page not found/i.test(h1.join(" ")),
      images: imgCount,
      imageIssues: img.slice(0, 12),
      smallText: small, smallSample,
      links,
      vw, vh,
    };
  });
}

/** Fixed/sticky elements and how much of the viewport they cover (header, toasts, floating CTAs). */
async function overlays(page: Page) {
  return page.evaluate(() => {
    const out: string[] = [];
    const vh = innerHeight, vw = innerWidth;
    for (const el of Array.from(document.querySelectorAll("body *"))) {
      const cs = getComputedStyle(el);
      if (cs.position !== "fixed" && cs.position !== "sticky") continue;
      const r = el.getBoundingClientRect();
      if (r.width < 20 || r.height < 20 || cs.visibility === "hidden" || cs.display === "none" || Number(cs.opacity) === 0) continue;
      if (r.bottom <= 0 || r.top >= vh) continue;
      const area = (Math.min(r.right, vw) - Math.max(r.left, 0)) * (Math.min(r.bottom, vh) - Math.max(r.top, 0));
      const pct = Math.round((100 * area) / (vw * vh));
      const label = `${el.tagName.toLowerCase()}.${String(el.className).split(/\s+/).slice(0, 2).join(".")}`;
      out.push(`${cs.position} ${label} ${Math.round(r.width)}x${Math.round(r.height)} @y${Math.round(r.top)} = ${pct}% of viewport`);
    }
    return out.slice(0, 10);
  });
}

const SEED = [
  "/", "/solutions", "/software-solutions", "/training", "/courses", "/apply/internship", "/verify", "/payment/status",
  "/pay-installment", "/my-registrations", "/register", "/procurement", "/recruitment", "/projects", "/about", "/contact",
  "/privacy", "/unsubscribe", "/about.html", "/products.html", "/blog", "/resources", "/terms", "/this-page-does-not-exist-qa",
];

/* ------------------------------------------------------------------ 1. crawl (desktop only) */
test("website crawl: pages, links, console, SEO", async ({ browser }, info) => {
  test.skip(info.project.name !== "desktop", "crawl runs once, on desktop");
  test.setTimeout(25 * 60_000);
  const { ctx, page } = await freshPage(browser, info);
  const w = watch(page);
  const n = net(page);
  const queue = [...SEED];
  const seen = new Set<string>();
  const pages: Record<string, unknown>[] = [];
  const external = new Map<string, Set<string>>(); // url -> pages it appears on
  const hashLinks = new Map<string, Set<string>>();
  while (queue.length && pages.length < 80) {
    const path = queue.shift()!;
    if (seen.has(path)) continue;
    seen.add(path);
    w.reset(); n.reset();
    const t0 = Date.now();
    let status = 0, err = "";
    try {
      const res = await page.goto(SITE + path, { waitUntil: "load" });
      status = res?.status() ?? 0;
    } catch (e) { err = String(e).slice(0, 200); }
    const loadMs = Date.now() - t0;
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
    const idleMs = Date.now() - t0;
    await settle(page);
    const f = await pageFacts(page).catch((e) => ({ error: String(e) }) as never);
    const finalUrl = page.url();
    for (const l of f.links ?? []) {
      let u: URL; try { u = new URL(l.href); } catch { continue; }
      if (u.host === SITE_HOST) {
        if (u.hash && u.hash.length > 1) { const k = u.pathname + u.hash; if (!hashLinks.has(k)) hashLinks.set(k, new Set()); hashLinks.get(k)!.add(path); }
        const p = u.pathname.replace(/\/+$/, "") || "/";
        if (!seen.has(p) && !queue.includes(p) && !/\.(pdf|png|jpe?g|webp|svg|zip|docx?)$/i.test(p)) queue.push(p);
        if (/\.(pdf|png|jpe?g|webp|svg|zip|docx?)$/i.test(p)) { const k = u.href.split("#")[0]; if (!external.has(k)) external.set(k, new Set()); external.get(k)!.add(path); }
      } else if (/^https?:/.test(u.protocol)) {
        const k = u.href; if (!external.has(k)) external.set(k, new Set()); external.get(k)!.add(path);
      } else {
        const k = `${u.protocol}${u.pathname}`.slice(0, 120); if (!external.has(k)) external.set(k, new Set()); external.get(k)!.add(path);
      }
    }
    pages.push({
      path, finalUrl, status, err, loadMs, idleMs,
      title: f.title, descriptions: f.descriptions, canonical: f.canonical, ogImage: f.ogImage, favicon: f.favicon, robots: f.robots,
      h1: f.h1, textLength: f.textLength, notFound: f.notFound, images: f.images, imageIssues: f.imageIssues,
      smallText: f.smallText, smallSample: f.smallSample, linkCount: (f.links ?? []).length,
      sslipLinks: (f.links ?? []).filter((l: { href: string }) => /sslip\.io|localhost|127\.0\.0\.1/.test(l.href)),
      lmsLinks: (f.links ?? []).filter((l: { href: string }) => l.href.includes(LMS_HOST)),
      consoleErrors: [...w.errors], failedRequests: [...n.failed],
    });
    save("crawl-pages", pages);
  }

  // hash targets: does #id exist on the target page?
  const hashes: Record<string, unknown>[] = [];
  for (const [k, from] of Array.from(hashLinks).slice(0, 60)) {
    await page.goto(SITE + k, { waitUntil: "load" }).catch(() => {});
    const id = decodeURIComponent(k.split("#")[1]);
    const found = await page.waitForFunction((i) => !!document.getElementById(i), id, { timeout: 6000 }).then(() => true).catch(() => false);
    const inView = found ? await page.evaluate((i) => { const r = document.getElementById(i)!.getBoundingClientRect(); return Math.round(r.top); }, id).catch(() => null) : null;
    hashes.push({ link: k, found, topAfterScroll: inView, from: Array.from(from).slice(0, 4) });
  }
  save("crawl-hashes", hashes);

  // external / file links: HTTP status (GET, follows redirects). mailto/tel just listed.
  const ext: Record<string, unknown>[] = [];
  for (const [u, from] of external) {
    if (!/^https?:/.test(u)) { ext.push({ url: u, from: Array.from(from).slice(0, 3), status: "n/a" }); continue; }
    let status: number | string = 0, final = "";
    try {
      const r = await page.request.get(u, { maxRedirects: 8, timeout: 20_000, failOnStatusCode: false });
      status = r.status(); final = r.url();
    } catch (e) { status = String(e).slice(0, 120); }
    ext.push({ url: u, status, final, from: Array.from(from).slice(0, 3), sslip: /sslip\.io/.test(u) });
  }
  save("crawl-external", ext);

  // HTTP-level checks of static resources and soft 404s
  const http: Record<string, unknown> = {};
  for (const p of ["/this-page-does-not-exist-qa", "/favicon.ico", "/favicon-32.png", "/apple-touch-icon.png", "/site.webmanifest", "/robots.txt", "/sitemap.xml", "/og-image.jpg", "/catalog.json"]) {
    const r = await page.request.get(SITE + p, { failOnStatusCode: false });
    const body = await r.text();
    http[p] = { status: r.status(), type: r.headers()["content-type"], length: body.length, head: body.slice(0, 160) };
  }
  save("crawl-http", http);
  await ctx.close();
});

/* ------------------------------------------------------------------ 2. website -> LMS links (desktop only) */
test("website to LMS: login, learn/teach, register, course status, catalog.json CORS", async ({ browser }, info) => {
  test.skip(info.project.name !== "desktop", "link checks run once, on desktop");
  test.setTimeout(15 * 60_000);
  const { ctx, page } = await freshPage(browser, info);
  const w = watch(page);
  const out: Record<string, unknown> = {};

  // Header Login
  await page.goto(SITE + "/", { waitUntil: "load" });
  await settle(page);
  const login = page.locator("a.header-login").first();
  out.headerLoginHref = await login.getAttribute("href").catch(() => null);
  w.reset();
  if (await login.isVisible().catch(() => false)) {
    await Promise.all([page.waitForURL((u) => u.host === LMS_HOST, { timeout: 30_000 }).catch(() => {}), login.click()]);
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
    out.headerLoginLanded = { url: page.url(), title: await page.title(), h1: await page.locator("h1").first().textContent().catch(() => null), errors: [...w.errors] };
    await page.screenshot({ path: info.outputPath("lms-login-landing.png") });
  }

  // /learn and /teach redirects
  for (const p of ["/learn", "/teach", "/learn/x", "/admin"]) {
    w.reset();
    await page.goto(SITE + p, { waitUntil: "load" }).catch(() => {});
    await page.waitForURL((u) => u.host === LMS_HOST, { timeout: 15_000 }).catch(() => {});
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
    out[`redirect ${p}`] = { url: page.url(), title: await page.title(), errors: [...w.errors] };
  }

  // Course status API: from the website origin (real browser CORS) + raw headers
  await page.goto(SITE + "/courses", { waitUntil: "load" });
  await settle(page);
  out.courseStatusFromSite = await page.evaluate(async (u) => {
    try { const r = await fetch(u, { credentials: "omit", mode: "cors", cache: "no-store" }); return { ok: r.ok, status: r.status, body: (await r.text()).slice(0, 1500) }; }
    catch (e) { return { error: String(e) }; }
  }, `${LMS}/api/public/courses/status`);
  const st = await page.request.get(`${LMS}/api/public/courses/status`, { headers: { origin: SITE }, failOnStatusCode: false });
  out.courseStatusHeaders = { status: st.status(), acao: st.headers()["access-control-allow-origin"] ?? null, cache: st.headers()["cache-control"] ?? null, type: st.headers()["content-type"] };
  // what the /courses page shows per card (badges)
  out.coursesPageBadges = await page.evaluate(() => Array.from(document.querySelectorAll("a[href*='/courses/']")).map((a) => {
    const card = a.closest("article, li, .card, [class*=card]") ?? a;
    return { href: a.getAttribute("href"), text: (card.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, 160) };
  }).filter((x, i, arr) => arr.findIndex((y) => y.href === x.href) === i));

  // every course page: register target + status text
  const slugs = Array.from(new Set(((out.coursesPageBadges as { href: string }[]) ?? []).map((x) => x.href.split("#")[0]).filter((h) => /^\/courses\/[^/]+$/.test(h))));
  const courses: Record<string, unknown>[] = [];
  const lmsLinks = new Map<string, string>();
  for (const href of slugs) {
    w.reset();
    await page.goto(SITE + href, { waitUntil: "load" });
    await settle(page);
    const facts = await page.evaluate((lh) => {
      const links = Array.from(document.querySelectorAll("a[href]")).map((a) => ({ href: (a as HTMLAnchorElement).href, text: (a.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, 60) }));
      const status = Array.from(document.querySelectorAll("body *")).map((e) => Array.from(e.childNodes).filter((n) => n.nodeType === 3).map((n) => n.textContent).join("").trim())
        .filter((t) => /^(open for registration|registrations? open|coming soon|closed|registration closed|open)$/i.test(t)).slice(0, 6);
      const register = Array.from(document.querySelectorAll("#register a, #register button, a[href*='/register']")).map((e) => ({ tag: e.tagName, text: (e.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, 60), href: e.getAttribute("href") }));
      return { lms: links.filter((l) => l.href.includes(lh)), sslip: links.filter((l) => /sslip\.io/.test(l.href)), status, register, h1: document.querySelector("h1")?.textContent?.trim().slice(0, 80) };
    }, LMS_HOST);
    for (const l of facts.lms) lmsLinks.set(l.href, `${href}: ${l.text}`);
    courses.push({ href, ...facts, errors: [...w.errors] });
  }
  out.coursePages = courses;

  // every LMS link from course pages + the main LMS entry points
  for (const u of [`${LMS}/continue`, `${LMS}/login`, `${LMS}/app`, `${LMS}/trainer`, `${LMS}/register`]) if (!lmsLinks.has(u)) lmsLinks.set(u, "entry point");
  const visits: Record<string, unknown>[] = [];
  for (const [u, from] of lmsLinks) {
    w.reset();
    let status = 0;
    try { status = (await page.goto(u, { waitUntil: "load" }))?.status() ?? 0; } catch { /* recorded below */ }
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
    await page.waitForTimeout(1200);
    const body = await page.evaluate(() => (document.body.innerText ?? "").replace(/\s+/g, " ").trim().slice(0, 300)).catch(() => "");
    visits.push({ url: u, from, status, final: page.url(), title: await page.title(), notFound: /not found|404|doesn.t exist/i.test(body), body: body.slice(0, 220), errors: [...w.errors], api: [...w.api] });
  }
  out.lmsVisits = visits;
  const reg = visits.find((v) => String(v.url).includes("/register/"));
  if (reg) { await page.goto(String(reg.url)); await page.waitForLoadState("networkidle").catch(() => {}); await page.screenshot({ path: info.outputPath("lms-register-page.png"), fullPage: true }); }

  // catalog.json: headers, content and the cross-origin fetch the LMS dashboard makes
  const cj = await page.request.get(`${SITE}/catalog.json`, { headers: { origin: LMS }, failOnStatusCode: false });
  const cjText = await cj.text();
  let parsed: { courses?: unknown[]; generated_at?: string } | null = null; try { parsed = JSON.parse(cjText); } catch { /* html */ }
  out.catalogJson = { status: cj.status(), headers: cj.headers(), isJson: !!parsed, courses: parsed?.courses?.length ?? null, generated_at: parsed?.generated_at ?? null, head: cjText.slice(0, 200) };
  const pre = await page.request.fetch(`${SITE}/catalog.json`, { method: "OPTIONS", headers: { origin: LMS, "access-control-request-method": "GET", "access-control-request-headers": "accept" }, failOnStatusCode: false });
  out.catalogJsonPreflight = { status: pre.status(), acao: pre.headers()["access-control-allow-origin"] ?? null };
  w.reset();
  await page.goto(`${LMS}/login`, { waitUntil: "load" });
  await page.waitForLoadState("networkidle").catch(() => {});
  out.catalogFromLmsOrigin = await page.evaluate(async (u) => {
    try { const r = await fetch(u, { headers: { accept: "application/json" } }); return { ok: r.ok, status: r.status, len: (await r.text()).length }; }
    catch (e) { return { error: String(e) }; }
  }, `${SITE}/catalog.json`);
  out.catalogFromLmsOriginConsole = [...w.errors];
  save("lms-links", out);
  await ctx.close();
});

/* ------------------------------------------------------------------ 3. responsive, every device */
const RESPONSIVE = ["/", "/courses", "/courses/nextgen-career-accelerator-2026", "/courses/generative-ai", "/training", "/solutions", "/projects", "/about", "/contact", "/apply/internship", "/verify", "/procurement", "/recruitment", "/pay-installment", "/privacy", "/this-page-does-not-exist-qa"];

test("responsive layout on this device", async ({ browser }, info) => {
  test.setTimeout(25 * 60_000);
  const { ctx, page } = await freshPage(browser, info);
  const w = watch(page);
  const n = net(page);
  const res: Record<string, unknown>[] = [];
  for (const p of RESPONSIVE) {
    w.reset(); n.reset();
    const t0 = Date.now();
    await page.goto(SITE + p, { waitUntil: "load" }).catch(() => {});
    const loadMs = Date.now() - t0;
    await page.screenshot({ path: info.outputPath(`top-${p.replace(/\W+/g, "_") || "home"}.png`) }).catch(() => {});
    await settle(page);
    const layout = await layoutIssues(page);
    const f = await pageFacts(page);
    const ov = await overlays(page);
    const header = await page.evaluate(() => { const h = document.querySelector(".site-header"); if (!h) return null; const r = h.getBoundingClientRect(); return { h: Math.round(r.height), pctOfViewport: Math.round((100 * r.height) / innerHeight) }; });
    const blankHero = await page.evaluate(() => { const m = document.querySelector("main"); return m ? Math.round(m.getBoundingClientRect().height) : 0; });
    await page.screenshot({ path: info.outputPath(`full-${p.replace(/\W+/g, "_") || "home"}.png`), fullPage: true }).catch(() => {});
    res.push({ path: p, loadMs, layout, header, mainHeight: blankHero, overlays: ov, imageIssues: f.imageIssues, smallText: f.smallText, smallSample: f.smallSample, title: f.title, consoleErrors: [...w.errors], failed: [...n.failed] });
    save(`responsive-${info.project.name}`, res);
  }
  await ctx.close();
});

/* ------------------------------------------------------------------ 4. navigation: mobile menu / desktop dropdowns */
test("navigation menu on this device", async ({ browser }, info) => {
  test.setTimeout(10 * 60_000);
  const { ctx, page } = await freshPage(browser, info);
  const w = watch(page);
  const out: Record<string, unknown> = { project: info.project.name };
  // Run 3f334141 showed the lead popup (.lp, z-index 270) opening over the menu (.mp, z-index 250) after 20 s.
  // Pre-answer the cookie bar and snooze the popup here so this test measures the menu itself.
  await page.addInitScript(() => {
    try {
      localStorage.setItem("td_consent", JSON.stringify({ v: 2, analytics: false, at: new Date().toISOString() }));
      localStorage.setItem("td_lead", JSON.stringify({ state: "closed", at: new Date().toISOString() }));
    } catch { /* storage blocked */ }
  });
  await page.goto(SITE + "/", { waitUntil: "load" });
  await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
  const toggle = page.locator("button.nav-toggle-round");
  out.toggleVisible = await toggle.isVisible();
  out.desktopNavVisible = await page.locator("nav.nav").isVisible();
  out.loginVisible = await page.locator("a.header-login").isVisible();
  out.contactBtnVisible = await page.locator("a.header-contact-btn").isVisible();
  out.headerButtons = await page.evaluate(() => Array.from(document.querySelectorAll(".site-header a, .site-header button")).map((e) => { const r = e.getBoundingClientRect(); return r.width ? `${e.className.toString().split(" ")[0]} ${Math.round(r.width)}x${Math.round(r.height)} x=${Math.round(r.left)}` : null; }).filter(Boolean));

  if (out.toggleVisible) {
    await toggle.click();
    const panel = page.locator(".mp-panel");
    out.opened = await panel.waitFor({ state: "visible", timeout: 5000 }).then(() => true).catch(() => false);
    await page.waitForTimeout(700); // slide-in
    out.scrollLocked = await page.evaluate(() => document.documentElement.classList.contains("nav-locked"));
    out.panelBox = await panel.boundingBox();
    await page.screenshot({ path: info.outputPath("menu-open.png") });
    // expand every accordion section
    const secs = page.locator(".mp-sec-btn");
    for (let i = 0; i < await secs.count(); i++) {
      const b = secs.nth(i);
      if ((await b.getAttribute("aria-expanded")) !== "true") await b.click();
      await page.waitForTimeout(300);
      // only one may be open at a time: audit the items of this section now
    }
    // reach every item: scroll into view, check it is on screen and not covered
    const reach = async () => page.evaluate(() => {
      const res: { label: string; ok: boolean; why?: string; h: number }[] = [];
      for (const el of Array.from(document.querySelectorAll(".mp-panel a, .mp-panel button"))) {
        const he = el as HTMLElement;
        if (he.closest("[hidden]")) continue;
        he.scrollIntoView({ block: "center" });
        const r = he.getBoundingClientRect();
        const label = (he.textContent ?? he.getAttribute("aria-label") ?? "").replace(/\s+/g, " ").trim().slice(0, 50) || he.getAttribute("aria-label") || he.className;
        if (r.width === 0 || r.height === 0) { res.push({ label, ok: false, why: "zero size", h: 0 }); continue; }
        const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
        if (cy < 0 || cy > innerHeight || cx < 0 || cx > innerWidth) { res.push({ label, ok: false, why: `off-screen at ${Math.round(cx)},${Math.round(cy)}`, h: Math.round(r.height) }); continue; }
        const top = document.elementFromPoint(cx, cy);
        const ok = !!top && (top === he || he.contains(top));
        res.push({ label, ok, why: ok ? undefined : `covered by ${top?.tagName}.${String(top?.className).split(" ")[0]}`, h: Math.round(r.height) });
      }
      return res;
    });
    const items: unknown[] = [];
    for (let i = 0; i < await secs.count(); i++) {
      const b = secs.nth(i);
      if ((await b.getAttribute("aria-expanded")) !== "true") { await b.click(); await page.waitForTimeout(300); }
      items.push(...await reach());
      await page.screenshot({ path: info.outputPath(`menu-section-${i}.png`) });
    }
    if (!(await secs.count())) items.push(...await reach());
    const uniq = new Map<string, unknown>();
    for (const it of items as { label: string }[]) uniq.set(it.label, it);
    out.items = Array.from(uniq.values());
    // Escape closes
    await page.keyboard.press("Escape");
    await page.waitForTimeout(400);
    out.escapeCloses = !(await panel.isVisible());
    // X button closes
    await toggle.click(); await panel.waitFor({ state: "visible" }).catch(() => {});
    await page.locator(".mp-x").click().catch(() => {});
    await page.waitForTimeout(400);
    out.xCloses = !(await panel.isVisible());
    out.unlockedAfterClose = !(await page.evaluate(() => document.documentElement.classList.contains("nav-locked")));
    // scrim closes
    await toggle.click(); await panel.waitFor({ state: "visible" }).catch(() => {});
    const box = await panel.boundingBox();
    const vp = page.viewportSize()!;
    if (box && box.x > 30) { await page.mouse.click(10, vp.height / 2); await page.waitForTimeout(400); out.scrimCloses = !(await panel.isVisible()); }
    else { out.scrimCloses = "panel covers full width"; await page.locator(".mp-x").click().catch(() => {}); }
    // navigating from the menu closes it and lands on the page
    await toggle.click(); await panel.waitFor({ state: "visible" }).catch(() => {});
    await page.locator(".mp-panel a.mp-link", { hasText: "About" }).first().click().catch(() => {});
    await page.waitForURL(/\/about/, { timeout: 8000 }).catch(() => {});
    await page.waitForTimeout(500);
    out.linkNavigates = { url: page.url(), panelClosed: !(await panel.isVisible()), scrollY: await page.evaluate(() => scrollY) };
  } else {
    // desktop dropdowns
    const dd: Record<string, unknown>[] = [];
    const chev = page.locator("button.nav-chev-btn");
    for (let i = 0; i < await chev.count(); i++) {
      await chev.nth(i).click();
      await page.waitForTimeout(400);
      const vis = await page.evaluate(() => {
        const li = document.querySelector(".nav-item.has-menu.is-open");
        if (!li) return null;
        const links = Array.from(li.querySelectorAll(".menu a"));
        return { links: links.length, visible: links.filter((a) => { const r = a.getBoundingClientRect(); return r.width > 0 && r.bottom <= innerHeight && r.right <= innerWidth; }).length };
      });
      dd.push({ i, ...vis });
      await page.screenshot({ path: info.outputPath(`dropdown-${i}.png`) });
      await page.keyboard.press("Escape");
    }
    out.dropdowns = dd;
    // hover opens too
    await page.locator(".nav-item.has-menu").first().hover();
    await page.waitForTimeout(400);
    out.hoverOpens = await page.locator(".nav-item.has-menu.is-open").count();
  }
  out.errors = [...w.errors];
  save(`nav-${info.project.name}`, out);
  await ctx.close();
});

/* ------------------------------------------------------------------ 5. forms (never submitted) */
const FORMS = ["/contact", "/apply/internship", "/verify", "/pay-installment", "/courses/nextgen-career-accelerator-2026#register"];
test("forms on this device (no submission)", async ({ browser }, info) => {
  test.skip(!["phone-small", "phone-iphone", "phone-android", "tablet", "desktop"].includes(info.project.name), "forms on phones, tablet and desktop");
  test.setTimeout(10 * 60_000);
  const { ctx, page } = await freshPage(browser, info);
  const w = watch(page);
  const out: Record<string, unknown>[] = [];
  for (const p of FORMS) {
    w.reset();
    await page.goto(SITE + p, { waitUntil: "load" }).catch(() => {});
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
    await page.waitForTimeout(1500);
    const forms = await page.evaluate(() => Array.from(document.querySelectorAll("form")).map((f, fi) => {
      const fields = Array.from(f.querySelectorAll("input, select, textarea")).filter((e) => {
        const r = e.getBoundingClientRect(); const t = (e as HTMLInputElement).type; return r.width > 0 && t !== "hidden" && !e.closest(".hp");
      }).map((e) => {
        const r = e.getBoundingClientRect(); const id = e.id;
        const lab = id ? document.querySelector(`label[for="${id}"]`) : e.closest("label");
        return { id, type: (e as HTMLInputElement).type || e.tagName.toLowerCase(), label: (lab?.textContent ?? e.getAttribute("aria-label") ?? "").trim().slice(0, 40), w: Math.round(r.width), h: Math.round(r.height), right: Math.round(r.right), fontPx: parseFloat(getComputedStyle(e).fontSize), required: (e as HTMLInputElement).required || e.getAttribute("aria-required") === "true" };
      });
      const submit = f.querySelector("button[type=submit], button:not([type]), input[type=submit]");
      const sr = submit?.getBoundingClientRect();
      return { fi, fields, submit: submit ? { text: (submit.textContent ?? "").trim().slice(0, 40), w: Math.round(sr!.width), h: Math.round(sr!.height) } : null, noValidate: f.noValidate };
    }));
    // blur empty fields (focus then Tab away) and count inline error messages. Never press Enter / submit.
    const before = await page.locator(".field-error, [role=alert], .has-error, [aria-invalid=true]").count();
    const ids = forms.flatMap((f) => f.fields.filter((x) => x.id && x.type !== "checkbox" && x.type !== "radio" && x.type !== "select-one").map((x) => x.id)).slice(0, 8);
    for (const id of ids) {
      const el = page.locator(`#${id.replace(/[^\w-]/g, "\\$&")}`);
      await el.focus().catch(() => {});
      await el.evaluate((e) => (e as HTMLElement).blur()).catch(() => {});
    }
    await page.waitForTimeout(400);
    const after = await page.locator(".field-error, [role=alert], .has-error, [aria-invalid=true]").count();
    const layout = await layoutIssues(page);
    await page.screenshot({ path: info.outputPath(`form-${p.replace(/\W+/g, "_")}.png`), fullPage: true }).catch(() => {});
    out.push({ path: p, forms, inlineErrorsBeforeBlur: before, inlineErrorsAfterBlur: after, layout, errors: [...w.errors] });
    save(`forms-${info.project.name}`, out);
  }
  await ctx.close();
});

/* ------------------------------------------------------------------ 6. fix checks (fixes-website.md items 2, 3) */
/**
 * Lead popup vs open menu: cookie bar pre-answered (popup due after ~4 s) but the popup NOT snoozed.
 * The menu is opened at once and kept open ~30 s: the popup must not open over it. After closing the
 * menu the popup should appear (proves the timer is only deferred, not broken).
 */
test("fix: lead popup waits for the open menu", async ({ browser }, info) => {
  test.skip(!["phone-small", "phone-android", "phone-iphone", "tablet"].includes(info.project.name), "menu toggle devices");
  test.setTimeout(4 * 60_000);
  const { ctx, page } = await freshPage(browser, info);
  await page.addInitScript(() => {
    try { localStorage.setItem("td_consent", JSON.stringify({ v: 2, analytics: false, at: new Date().toISOString() })); } catch { /* storage blocked */ }
  });
  const out: Record<string, unknown> = { project: info.project.name };
  await page.goto(SITE + "/", { waitUntil: "load" });
  const toggle = page.locator("button.nav-toggle-round");
  out.toggleVisible = await toggle.isVisible().catch(() => false);
  if (out.toggleVisible) {
    await toggle.click();
    await page.locator(".mp-panel").waitFor({ state: "visible", timeout: 5000 }).catch(() => {});
    const samples: unknown[] = [];
    for (let i = 0; i < 10; i++) {
      await page.waitForTimeout(3000);
      samples.push(await page.evaluate(() => {
        const lp = document.querySelector(".lp"); const mp = document.querySelector(".mp-panel");
        const vis = (e: Element | null) => { if (!e) return false; const r = e.getBoundingClientRect(); const cs = getComputedStyle(e); return r.width > 0 && r.height > 0 && cs.display !== "none" && cs.visibility !== "hidden"; };
        let topIsMenu: boolean | null = null;
        if (mp && vis(mp)) { const r = mp.getBoundingClientRect(); const el = document.elementFromPoint(r.left + r.width / 2, r.top + Math.min(200, r.height / 2)); topIsMenu = !!el && mp.contains(el); }
        return { t: Math.round(performance.now() / 1000), popup: vis(lp), menu: vis(mp), topIsMenu, mpZ: mp ? getComputedStyle(mp.closest(".mp") ?? mp).zIndex : null };
      }));
    }
    out.whileMenuOpen = samples;
    out.popupOverMenu = (samples as { popup: boolean; menu: boolean }[]).some((s) => s.popup && s.menu);
    await page.screenshot({ path: info.outputPath("menu-open-30s.png") });
    await page.locator(".mp-x").click().catch(() => page.keyboard.press("Escape"));
    await page.locator(".lp").waitFor({ state: "visible", timeout: 15_000 }).catch(() => {});
    out.popupAfterClose = await page.locator(".lp").isVisible().catch(() => false);
    await page.screenshot({ path: info.outputPath("after-menu-close.png") });
  }
  save(`fix-popup-${info.project.name}`, out);
  await ctx.close();
});

/** Cookie bar at this viewport (fresh visitor): the Accept button is fully on screen; bar height share. */
test("fix: cookie bar fits", async ({ browser }, info) => {
  const { ctx, page } = await freshPage(browser, info);
  const out: Record<string, unknown> = { project: info.project.name };
  for (const p of ["/", "/courses", "/training"]) {
    await page.goto(SITE + p, { waitUntil: "load" });
    await page.locator(".ck").waitFor({ state: "visible", timeout: 10_000 }).catch(() => {});
    await page.waitForTimeout(800);
    out[p] = await page.evaluate(() => {
      const vw = document.documentElement.clientWidth, vh = innerHeight;
      const box = (s: string) => { const e = document.querySelector(s); if (!e) return null; const r = e.getBoundingClientRect(); if (!r.width) return null; return { l: Math.round(r.left), r: Math.round(r.right), t: Math.round(r.top), b: Math.round(r.bottom), w: Math.round(r.width), h: Math.round(r.height) }; };
      const bar = box(".ck"), btn = box(".ck-btn"), link = box(".ck-link");
      const inView = (b: { l: number; r: number; t: number; b: number } | null) => !!b && b.l >= -1 && b.r <= vw + 1 && b.t >= -1 && b.b <= vh + 1;
      const more = document.querySelector(".ck-more"); const moreShown = !!more && getComputedStyle(more).display !== "none";
      return { vw, vh, bar, btn, link, btnInView: inView(btn), linkInView: inView(link), barPct: bar ? Math.round((100 * bar.h) / vh) : null, hscroll: document.documentElement.scrollWidth > vw + 1, consentSentenceShown: moreShown };
    });
    if (p === "/") await page.screenshot({ path: info.outputPath("cookie-bar.png") });
  }
  save(`fix-cookie-${info.project.name}`, out);
  await ctx.close();
});

/** Deep-link landing after the page settles (fixes-website.md item 5): target top at 0.5 s, 3 s and 6 s after load. */
test("fix: hash deep links settle on target", async ({ browser }, info) => {
  test.skip(!["desktop", "phone-android"].includes(info.project.name), "desktop + one phone");
  test.setTimeout(6 * 60_000);
  const { ctx, page } = await freshPage(browser, info);
  await page.addInitScript(() => {
    try {
      localStorage.setItem("td_consent", JSON.stringify({ v: 2, analytics: false, at: new Date().toISOString() }));
      localStorage.setItem("td_lead", JSON.stringify({ state: "closed", at: new Date().toISOString() }));
    } catch { /* storage blocked */ }
  });
  const URLS = ["/courses/python-full-stack-development#register", "/courses/java-full-stack-spring-boot-microservices#register", "/courses/mern-stack-development#register", "/courses/mean-stack-development#register", "/courses/nextgen-career-accelerator-2026#register", "/recruitment#hire", "/procurement#quote", "/projects#companion", "/training#overview"];
  const out: Record<string, unknown>[] = [];
  const top = (id: string) => page.evaluate((i) => { const e = document.getElementById(i); return e ? { top: Math.round(e.getBoundingClientRect().top), scrollY: Math.round(scrollY), vh: innerHeight, docH: document.documentElement.scrollHeight } : null; }, id);
  for (const u of URLS) {
    const id = u.split("#")[1]!;
    // fresh document each time (a same-page hash change would not re-run the landing logic)
    await page.goto("about:blank");
    await page.goto(SITE + u, { waitUntil: "load" }).catch(() => {});
    await page.waitForTimeout(500); const a = await top(id);
    await page.waitForTimeout(2500); const b = await top(id);
    await page.waitForTimeout(3000); const c = await top(id);
    out.push({ url: u, at500ms: a, at3s: b, at6s: c });
  }
  save(`fix-hash-${info.project.name}`, out);
  await ctx.close();
});

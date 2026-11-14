/*
 * A11y + responsive audit (read-only). Run from repo root:
 *   node docs/archive/redesign-next-app/a11y/audit.cjs [roleFilter]
 * Uses apps/web/node_modules (playwright, @axe-core/playwright). Writes
 *   docs/archive/redesign-next-app/a11y/results/<role>.json and docs/redesign/shots/a11y/<page>-<vp>.png
 * One browser context per role (one "device"); viewports are switched with setViewportSize.
 */
const path = require("node:path");
const fs = require("node:fs");
const crypto = require("node:crypto");
const WEB = path.resolve(__dirname, "../../../apps/web");
const req = require("node:module").createRequire(path.join(WEB, "package.json"));
const { chromium } = req("playwright");
const AxeBuilder = req("@axe-core/playwright").default;

const BASE = "http://localhost:13000";
const MAILPIT = "http://localhost:8025";
const PW = "dev-only-lantern-harbour-2026";
const TOTP = {
  admin: "334SDLG2HT25N3YTC36RU2ZBOWFQT22R",
  trainer: "KA2PKEZOIRDDNMOPL2PJ5GJUZW44EC5R",
  evaluator: "HVNXMW4RJCMBYNNSGG5CWHP4EBLWUH6E",
  content: "6BLD7TM27IYROCA7NI5PT4PR2EY66AQP",
};
const OUT = path.join(__dirname, "results");
const SHOTS = path.resolve(__dirname, "../shots/a11y");
const STATE = path.join(__dirname, ".state"); // device cookies + totp steps (dev only; gitignore-able)
for (const d of [OUT, SHOTS, STATE]) fs.mkdirSync(d, { recursive: true });

const VIEWPORTS = { mobile: { width: 390, height: 844 }, tablet: { width: 820, height: 1180 }, desktop: { width: 1440, height: 900 } };

// [key, path or resolver]. resolver: { from, match } → first href on `from` matching regex.
const ROLES = {
  public: {
    who: null,
    pages: [
      ["pub-landing", "/"],
      ["pub-login", "/login", { form: true }],
      ["pub-signup", "/signup", { form: true }],
      ["pub-courses", "/courses"],
      ["pub-course-detail", { from: "/courses", match: "^/courses/[^/]+$" }],
      ["pub-pricing", "/pricing"],
      ["pub-forgot-password", "/forgot-password", { form: true }],
    ],
  },
  student: {
    who: "ravi.student",
    pages: [
      ["stu-dashboard", "/app"],
      ["stu-courses", "/app/courses"],
      ["stu-learn", { from: "/app/learning", match: "^/app/(learn|courses)/[^/]+" }],
      ["stu-practice", "/app/practice"],
      ["stu-tests", "/app/tests"],
      ["stu-assignments", "/app/assignments"],
      ["stu-profile", "/app/settings/profile", { form: true }],
      ["stu-support-new", "/app/support/new", { form: true }],
    ],
  },
  admin: {
    who: "admin",
    pages: [
      ["adm-home", "/admin"],
      ["adm-users", "/admin/users"],
      ["adm-batches", "/admin/batches"],
      ["adm-user-detail", { from: "/admin/users", match: "^/admin/users/[^/]+$" }],
    ],
  },
  trainer: {
    who: "trainer",
    pages: [
      ["trn-home", "/trainer"],
      ["trn-tests", "/trainer/tests"],
      ["trn-grading", "/trainer/grading"],
      ["trn-assignments", "/trainer/assignments"],
    ],
  },
  evaluator: {
    who: "evaluator",
    pages: [
      ["evl-home", "/evaluator"],
      ["evl-tests", "/evaluator/tests"],
    ],
  },
  content: {
    who: "content",
    pages: [
      ["std-home", "/studio"],
      ["std-courses", "/studio/courses"],
      ["std-questions", "/studio/questions"],
      ["std-question-banks", "/studio/question-banks"],
    ],
  },
};

// ---------- auth ----------
function b32(input) {
  const a = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = 0, v = 0; const out = [];
  for (const ch of input.toUpperCase()) { const i = a.indexOf(ch); if (i < 0) continue; v = (v << 5) | i; bits += 5; if (bits >= 8) { out.push((v >>> (bits - 8)) & 255); bits -= 8; } }
  return Buffer.from(out);
}
function totpAt(secret, step) {
  const c = Buffer.alloc(8); c.writeBigUInt64BE(BigInt(step));
  const h = crypto.createHmac("sha1", b32(secret)).update(c).digest();
  const o = h[h.length - 1] & 15;
  return ((h.readUInt32BE(o) & 0x7fffffff) % 1e6).toString().padStart(6, "0");
}
async function freshTotp(role) {
  const f = path.join(STATE, `${role}.step`);
  const last = fs.existsSync(f) ? Number(fs.readFileSync(f, "utf8")) : -1;
  let step = Math.floor(Date.now() / 30000);
  if (step <= last + 0 || Date.now() % 30000 > 26000) { await new Promise((r) => setTimeout(r, (step + 1) * 30000 - Date.now() + 300)); step = Math.floor(Date.now() / 30000); }
  fs.writeFileSync(f, String(step));
  return totpAt(TOTP[role], step);
}
const usedMail = new Set();
async function latestOtp(to, after) {
  for (let i = 0; i < 30; i++) {
    const r = await fetch(`${MAILPIT}/api/v1/search?query=${encodeURIComponent("to:" + to)}`);
    if (r.ok) {
      const msgs = ((await r.json()).messages || []).filter((m) => !usedMail.has(m.ID) && Date.parse(m.Created) >= after - 1000).sort((a, b) => Date.parse(b.Created) - Date.parse(a.Created));
      if (msgs[0]) {
        const body = await (await fetch(`${MAILPIT}/api/v1/message/${msgs[0].ID}`)).json();
        const code = /\b(\d{6})\b/.exec(body.Text || "")?.[1];
        if (code) { usedMail.add(msgs[0].ID); return code; }
      }
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error("no OTP mail for " + to);
}
async function signIn(page, role) {
  const email = `${role}@dev.techdrona.local`;
  const dev = path.join(STATE, `${role}.device.json`);
  if (fs.existsSync(dev)) await page.context().addCookies(JSON.parse(fs.readFileSync(dev, "utf8"))).catch(() => {});
  await page.goto(`${BASE}/login`);
  await page.getByLabel("Email or mobile").fill(email);
  await page.getByLabel(/^Password/).fill(PW);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL((u) => !/^\/login\/?$/.test(u.pathname), { timeout: 25000 });
  if (/\/login\/mfa/.test(page.url())) {
    await page.getByLabel("Authenticator code").fill(await freshTotp(role));
    await page.getByRole("button", { name: "Verify" }).click();
    await page.waitForURL((u) => !/\/login\/mfa/.test(u.pathname), { timeout: 25000 });
  }
  if (/\/login\/verify-device/.test(page.url())) {
    const sent = Date.now();
    await page.getByRole("button", { name: /Send code by email/ }).click();
    await page.getByLabel("6-digit code").fill(await latestOtp(email, sent));
    await page.getByRole("button", { name: "Confirm" }).click();
    await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 10000 }).catch(() => {});
    const replace = page.getByRole("button", { name: "Remove and continue" });
    if (await replace.isVisible().catch(() => false)) {
      { const rr = page.getByRole("radio", { name: /last used (?!now|just)/ }); if (await rr.count()) await rr.first().check(); else await page.getByRole("radio").last().check(); }
      await replace.click();
    }
    await page.waitForURL((u) => !u.pathname.startsWith("/login") || /session-choice/.test(u.pathname), { timeout: 25000 });
  }
  if (/\/login\/session-choice/.test(page.url())) {
    await page.getByRole("radio", { name: /active (?!now)/ }).first().check();
    await page.getByRole("button", { name: "Sign out selected and continue" }).click();
    await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 25000 });
  }
  const cookies = (await page.context().cookies()).filter((c) => /td_device$/.test(c.name));
  if (cookies.length) fs.writeFileSync(dev, JSON.stringify(cookies));
}

// ---------- in-page checks ----------
function domChecks() {
  const vw = document.documentElement.clientWidth;
  const vh = window.innerHeight;
  const desc = (el) => {
    if (!el || !el.tagName) return String(el);
    let s = el.tagName.toLowerCase();
    if (el.id) s += "#" + el.id;
    const cls = (typeof el.className === "string" ? el.className : "").trim().split(/\s+/).filter(Boolean).slice(0, 4);
    if (cls.length) s += "." + cls.join(".");
    const name = (el.getAttribute("aria-label") || el.textContent || "").trim().replace(/\s+/g, " ").slice(0, 40);
    if (name) s += ` "${name}"`;
    return s;
  };
  const visible = (el) => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el); return r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && cs.display !== "none"; };
  const res = {};
  // overflow
  const sw = document.documentElement.scrollWidth;
  res.hOverflow = sw - vw;
  const off = [];
  if (sw > vw + 1) {
    for (const el of document.body.querySelectorAll("*")) {
      const r = el.getBoundingClientRect();
      if (r.right > vw + 1 && r.width > 0 && visible(el)) {
        // keep only outermost offenders
        if (!off.some((o) => o.el.contains(el))) off.push({ el, right: Math.round(r.right) });
      }
      if (off.length > 8) break;
    }
  }
  res.overflowEls = off.map((o) => `${desc(o.el)} right=${o.right}`);
  // landmarks + headings
  res.landmarks = { main: document.querySelectorAll("main,[role=main]").length, nav: document.querySelectorAll("nav,[role=navigation]").length, header: document.querySelectorAll("header,[role=banner]").length, footer: document.querySelectorAll("footer,[role=contentinfo]").length };
  const hs = [...document.querySelectorAll("h1,h2,h3,h4,h5,h6,[role=heading]")].filter(visible).map((h) => ({ l: Number(h.getAttribute("aria-level") || h.tagName[1]), t: (h.textContent || "").trim().slice(0, 50) }));
  res.headings = hs.slice(0, 25);
  res.h1count = hs.filter((h) => h.l === 1).length;
  res.headingSkips = [];
  for (let i = 1; i < hs.length; i++) if (hs[i].l > hs[i - 1].l + 1) res.headingSkips.push(`h${hs[i - 1].l}→h${hs[i].l} "${hs[i].t}"`);
  // touch targets
  const inter = [...document.querySelectorAll("a[href],button,input:not([type=hidden]),select,textarea,[role=button],[role=tab],[role=link],[role=checkbox],[role=radio],[role=switch],[role=menuitem],summary")].filter(visible);
  const small24 = [], small44 = [];
  for (const el of inter) {
    const r = el.getBoundingClientRect();
    // inline links inside paragraphs are exempt (2.5.8 inline exception)
    if (el.tagName === "A" && getComputedStyle(el).display === "inline" && el.closest("p,li")) continue;
    const label = el.closest("label");
    const box = label && (el.type === "checkbox" || el.type === "radio") ? label.getBoundingClientRect() : r;
    if (box.width < 24 || box.height < 24) small24.push(`${desc(el)} ${Math.round(box.width)}x${Math.round(box.height)}`);
    else if (box.width < 44 || box.height < 44) small44.push(`${desc(el)} ${Math.round(box.width)}x${Math.round(box.height)}`);
  }
  res.interactive = inter.length;
  res.targetsUnder24 = small24.length; res.targetsUnder24Samples = small24.slice(0, 8);
  res.targetsUnder44 = small44.length; res.targetsUnder44Samples = small44.slice(0, 8);
  // fixed / sticky elements covering the viewport
  const fixed = [];
  for (const el of document.body.querySelectorAll("*")) {
    const p = getComputedStyle(el).position;
    if ((p === "fixed" || p === "sticky") && visible(el)) {
      const r = el.getBoundingClientRect();
      const area = (Math.max(0, Math.min(r.right, vw) - Math.max(r.left, 0)) * Math.max(0, Math.min(r.bottom, vh) - Math.max(r.top, 0))) / (vw * vh);
      if (area > 0.005) fixed.push(`${p} ${desc(el)} top=${Math.round(r.top)} h=${Math.round(r.height)} area=${(area * 100).toFixed(1)}%`);
    }
  }
  res.fixed = fixed.slice(0, 6);
  // clipped text (overflow hidden/ellipsis, no title)
  const clipped = [];
  for (const el of document.body.querySelectorAll("p,span,a,button,td,th,h1,h2,h3,h4,label,div,li,dd,dt")) {
    if (el.children.length > 2 || !visible(el)) continue;
    const cs = getComputedStyle(el);
    if ((cs.overflowX === "hidden" || cs.overflow === "hidden" || cs.textOverflow === "ellipsis" || cs.webkitLineClamp !== "none") && el.scrollWidth > el.clientWidth + 2 && (el.textContent || "").trim().length > 3 && !el.title) clipped.push(desc(el));
    if (clipped.length > 10) break;
  }
  res.clippedText = clipped;
  // overlapping siblings text (crude): text elements intersecting with other text elements
  // images
  res.imgNoAlt = [...document.querySelectorAll("img:not([alt])")].map(desc).slice(0, 5);
  res.svgUnlabelled = [...document.querySelectorAll("svg")].filter((s) => visible(s) && !s.closest("[aria-hidden=true]") && s.getAttribute("aria-hidden") !== "true" && !s.getAttribute("aria-label") && !s.querySelector("title") && s.getAttribute("role") !== "presentation").length;
  // form fields: label + error association
  const fields = [...document.querySelectorAll("input:not([type=hidden]),select,textarea")].filter(visible);
  res.fieldsNoName = fields.filter((f) => !(f.labels && f.labels.length) && !f.getAttribute("aria-label") && !f.getAttribute("aria-labelledby") && !f.title).map(desc).slice(0, 6);
  res.fieldsPlaceholderOnly = fields.filter((f) => !(f.labels && f.labels.length) && !f.getAttribute("aria-labelledby") && f.placeholder && !f.getAttribute("aria-label")).length;
  // skip link
  const first = document.querySelector("a[href^='#']");
  res.skipLink = first && /skip|main content/i.test(first.textContent || "") ? (first.textContent || "").trim() : null;
  res.lang = document.documentElement.lang || null;
  res.title = document.title;
  return res;
}

async function tabWalk(page, n = 30) {
  await page.evaluate(() => { document.activeElement && document.activeElement.blur && document.activeElement.blur(); window.scrollTo(0, 0); });
  await page.mouse.click(1, 1).catch(() => {});
  const stops = [];
  for (let i = 0; i < n; i++) {
    await page.keyboard.press("Tab");
    const s = await page.evaluate(() => {
      const el = document.activeElement;
      if (!el || el === document.body) return { body: true };
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      const outline = cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) > 0;
      const shadow = cs.boxShadow && cs.boxShadow !== "none";
      const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      const inView = cy >= 0 && cy <= innerHeight && cx >= 0 && cx <= innerWidth;
      const topEl = inView ? document.elementFromPoint(cx, cy) : null;
      const covered = inView && topEl && !el.contains(topEl) && !topEl.contains(el) && !(el.labels && [...el.labels].some((l) => l.contains(topEl)));
      const name = (el.getAttribute("aria-label") || el.textContent || el.getAttribute("placeholder") || el.getAttribute("title") || "").trim().replace(/\s+/g, " ").slice(0, 40);
      const cls = (typeof el.className === "string" ? el.className : "").split(/\s+/).slice(0, 3).join(".");
      return { tag: el.tagName.toLowerCase(), name, cls, ring: outline || shadow, inView, covered: !!covered, coveredBy: covered ? topEl.tagName.toLowerCase() + "." + String(topEl.className).split(/\s+/).slice(0, 3).join(".") : null, w: Math.round(r.width), h: Math.round(r.height) };
    });
    stops.push(s);
  }
  // trap heuristic: last 8 stops cycle over <=2 distinct elements
  const sig = stops.map((s) => (s.body ? "body" : `${s.tag}|${s.name}|${s.cls}`));
  const tail = new Set(sig.slice(-8));
  return {
    stops: stops.length,
    noRing: stops.filter((s) => !s.body && !s.ring).map((s) => `${s.tag} "${s.name}"`).slice(0, 8),
    noRingCount: stops.filter((s) => !s.body && !s.ring).length,
    offscreen: stops.filter((s) => !s.body && !s.inView).length,
    covered: stops.filter((s) => s.covered).map((s) => `${s.tag} "${s.name}" under ${s.coveredBy}`).slice(0, 5),
    zeroSize: stops.filter((s) => !s.body && (s.w === 0 || s.h === 0)).map((s) => `${s.tag} "${s.name}"`).slice(0, 5),
    possibleTrap: tail.size <= 2 && !tail.has("body"),
    first5: sig.slice(0, 5),
  };
}

async function formCheck(page) {
  // Submit the form empty, report invalid fields and error association.
  const submit = page.locator("main form button[type=submit], main form button:not([type])").first();
  if (!(await submit.count())) return { note: "no submit button" };
  await submit.click({ timeout: 3000 }).catch(() => {});
  await page.waitForTimeout(800);
  return page.evaluate(() => {
    const form = document.querySelector("main form");
    if (!form) return { note: "no form" };
    const fields = [...form.querySelectorAll("input:not([type=hidden]),select,textarea")];
    const nativeInvalid = fields.filter((f) => !f.checkValidity()).length;
    const ariaInvalid = fields.filter((f) => f.getAttribute("aria-invalid") === "true");
    const described = ariaInvalid.filter((f) => (f.getAttribute("aria-describedby") || "").split(/\s+/).some((id) => id && document.getElementById(id)));
    const alerts = [...document.querySelectorAll("[role=alert],[aria-live]")].map((a) => (a.textContent || "").trim().slice(0, 60)).filter(Boolean);
    const focused = document.activeElement ? document.activeElement.tagName.toLowerCase() + (document.activeElement.name ? "[name=" + document.activeElement.name + "]" : "") : null;
    return { fields: fields.length, nativeInvalid, ariaInvalid: ariaInvalid.length, ariaInvalidDescribed: described.length, liveRegionsText: alerts.slice(0, 4), focusAfterSubmit: focused, novalidate: form.noValidate };
  });
}

async function menuDialogCheck(page) {
  // Mobile: find a menu/nav toggle, open it, check focus move, Tab containment, Escape and focus return.
  const cand = page.locator("header button, [aria-label*='menu' i], button[aria-expanded], button[aria-haspopup]").filter({ visible: true });
  const n = await cand.count();
  let btn = null;
  for (let i = 0; i < Math.min(n, 10); i++) {
    const b = cand.nth(i);
    const nm = ((await b.getAttribute("aria-label")) || (await b.textContent()) || "").trim();
    if (/menu|navigation|more|open/i.test(nm)) { btn = b; break; }
  }
  if (!btn) return { found: false, candidates: n };
  const name = ((await btn.getAttribute("aria-label")) || (await btn.textContent()) || "").trim().slice(0, 40);
  await btn.focus();
  await page.keyboard.press("Enter");
  await page.waitForTimeout(500);
  const opened = await page.evaluate(() => {
    const d = [...document.querySelectorAll("dialog[open],[role=dialog],[aria-modal=true],[role=menu]")].find((x) => x.getBoundingClientRect().height > 0);
    const a = document.activeElement;
    return { dialog: d ? `${d.tagName.toLowerCase()} role=${d.getAttribute("role")} modal=${d.getAttribute("aria-modal")} label=${d.getAttribute("aria-label") || d.getAttribute("aria-labelledby")}` : null, focusInside: !!(d && d.contains(a)), active: a ? a.tagName.toLowerCase() + " " + (a.textContent || "").trim().slice(0, 30) : null, expanded: null };
  });
  opened.expandedAttr = await btn.getAttribute("aria-expanded").catch(() => null);
  let escaped = false;
  for (let i = 0; i < 25; i++) {
    await page.keyboard.press("Tab");
    const inside = await page.evaluate(() => { const d = [...document.querySelectorAll("dialog[open],[role=dialog],[aria-modal=true],[role=menu]")].find((x) => x.getBoundingClientRect().height > 0); return !d || d.contains(document.activeElement); });
    if (!inside) { escaped = true; break; }
  }
  opened.focusLeavesWithTab = escaped;
  await page.keyboard.press("Escape");
  await page.waitForTimeout(400);
  opened.closedByEsc = await page.evaluate(() => ![...document.querySelectorAll("dialog[open],[role=dialog],[aria-modal=true],[role=menu]")].find((x) => x.getBoundingClientRect().height > 0));
  opened.focusReturned = await btn.evaluate((b) => document.activeElement === b).catch(() => false);
  return { found: true, name, ...opened };
}

async function resolveUrl(page, spec) {
  if (typeof spec === "string") return spec;
  await page.goto(BASE + spec.from, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle", { timeout: 8000 }).catch(() => {});
  const re = new RegExp(spec.match);
  const hrefs = await page.$$eval("a[href]", (as) => as.map((a) => new URL(a.href).pathname));
  return hrefs.find((h) => re.test(h)) || spec.from;
}

async function auditPage(page, key, url, opts, vpName) {
  await page.goto(BASE + url, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle", { timeout: 10000 }).catch(() => {});
  await page.waitForTimeout(600);
  const r = { key, url, finalUrl: page.url().replace(BASE, ""), viewport: vpName };
  try {
    const ax = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"]).exclude(".monaco-editor").analyze();
    r.axe = ax.violations.map((v) => ({ id: v.id, impact: v.impact, help: v.help, tags: v.tags.filter((t) => /^wcag\d/.test(t)), nodes: v.nodes.length, targets: v.nodes.slice(0, 4).map((n) => n.target.join(" ")), html: v.nodes.slice(0, 2).map((n) => n.html.slice(0, 160)), detail: v.id === "color-contrast" ? v.nodes.slice(0, 4).map((n) => (n.any[0] && n.any[0].data) ? `${n.any[0].data.fgColor} on ${n.any[0].data.bgColor} = ${n.any[0].data.contrastRatio} (need ${n.any[0].data.expectedContrastRatio})` : "") : undefined }));
  } catch (e) { r.axeError = String(e).slice(0, 200); }
  r.dom = await page.evaluate(domChecks);
  await page.screenshot({ path: path.join(SHOTS, `${key}-${vpName}.png`), scale: "css" }).catch(() => {});
  r.tab = await tabWalk(page, 30).catch((e) => ({ error: String(e).slice(0, 120) }));
  if (vpName === "mobile") {
    await page.goto(BASE + url, { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle", { timeout: 8000 }).catch(() => {});
    r.menu = await menuDialogCheck(page).catch((e) => ({ error: String(e).slice(0, 120) }));
  }
  if (opts && opts.form && vpName === "desktop") {
    await page.goto(BASE + url, { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle", { timeout: 8000 }).catch(() => {});
    r.form = await formCheck(page).catch((e) => ({ error: String(e).slice(0, 120) }));
  }
  return r;
}

if (require.main === module) (async () => {
  const filter = process.argv[2];
  const browser = await chromium.launch();
  for (const [role, cfg] of Object.entries(ROLES)) {
    if (filter && filter !== role) continue;
    const ctx = await browser.newContext({ viewport: VIEWPORTS.desktop, baseURL: BASE });
    const page = await ctx.newPage();
    const results = [];
    try {
      if (cfg.who) await signIn(page, cfg.who);
      for (const [key, spec, opts] of cfg.pages) {
        await page.setViewportSize(VIEWPORTS.desktop);
        let url;
        try { url = await resolveUrl(page, spec); } catch (e) { url = typeof spec === "string" ? spec : spec.from; }
        for (const vp of ["mobile", "tablet", "desktop"]) {
          await page.setViewportSize(VIEWPORTS[vp]);
          try { results.push(await auditPage(page, key, url, opts, vp)); console.log("ok", role, key, vp, url); }
          catch (e) { results.push({ key, url, viewport: vp, error: String(e).slice(0, 300) }); console.log("ERR", role, key, vp, String(e).slice(0, 150)); }
        }
      }
    } catch (e) { results.push({ role, fatal: String(e).slice(0, 400) }); console.log("FATAL", role, String(e).slice(0, 300)); }
    fs.writeFileSync(path.join(OUT, `${role}.json`), JSON.stringify(results, null, 1));
    await ctx.close();
  }
  await browser.close();
})();
module.exports = { signIn, BASE, VIEWPORTS, chromium, AxeBuilder, SHOTS };

// Page-timing baseline for the running stack (read-only browsing; GET navigations only).
// Usage (from repo root):
//   node docs/redesign/perf/page-timing.mjs [--runs 3] [--out docs/redesign/perf/page-timing.json] [--only key1,key2]
// Needs apps/web/.env.e2e.local (accounts + dev TOTP secrets; never printed) and Mailpit for new-device OTP.
// Auth state is cached under $PERF_STATE_DIR (default: OS temp) so each role signs in once.
import { createRequire } from "node:module";
import { createHmac } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { fileURLToPath } from "node:url";
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const require = createRequire(path.join(ROOT, "apps/web/package.json"));
const { chromium } = require("playwright");

const args = Object.fromEntries(process.argv.slice(2).reduce((a, v, i, arr) => (v.startsWith("--") ? [...a, [v.slice(2), arr[i + 1]]] : a), []));
const RUNS = Number(args.runs ?? 3);
const OUT = path.resolve(ROOT, args.out ?? "docs/redesign/perf/page-timing.json");
const ONLY = args.only ? new Set(args.only.split(",")) : null;
const STATE_DIR = process.env.PERF_STATE_DIR ?? path.join(os.tmpdir(), "td-perf-state");
fs.mkdirSync(STATE_DIR, { recursive: true });

const env = {};
for (const raw of fs.readFileSync(path.join(ROOT, "apps/web/.env.e2e.local"), "utf8").split(/\r?\n/)) {
  const l = raw.trim(); if (!l || l.startsWith("#")) continue; const i = l.indexOf("=");
  if (i > 0) env[l.slice(0, i).trim()] = l.slice(i + 1).trim().replace(/^(["'])(.*)\1$/, "$2");
}
const BASE = env.E2E_BASE_URL ?? "http://localhost:13000";
const MAILPIT = env.MAILPIT_URL ?? "http://localhost:8025";
// Dev TOTP secrets (public dev-only values) read from the seed file; never printed.
const SEED_TOTP = Object.fromEntries([...fs.readFileSync(path.join(ROOT, "apps/api/app/seeds/dev_users.py"), "utf8").matchAll(/^\s+"(\w+)":\s*"([A-Z2-7]{16,})",/gm)].map((m) => [m[1], m[2]]));
// Accounts at the 3-device cap are shared with other agents; use quieter accounts of the same role by default
// (override with PERF_<ROLE>_AS=<local part>, e.g. PERF_STUDENT_AS=student).
const ALT = { STUDENT: process.env.PERF_STUDENT_AS ?? "asha.student", ADMIN: process.env.PERF_ADMIN_AS ?? "admin2" };
const acct = (p) => { const base = { id: env[`E2E_${p}_IDENTIFIER`], pw: env[`E2E_${p}_PASSWORD`], totp: env[`E2E_${p}_TOTP_SECRET`] };
  if (!ALT[p] || !base.id) return base; const local = ALT[p]; return { id: `${local}@${base.id.split("@")[1]}`, pw: base.pw, totp: SEED_TOTP[local] ?? base.totp }; };

function b32(s) { const A = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"; let bits = 0, v = 0; const o = [];
  for (const c of s.replace(/=+$/, "").toUpperCase()) { const i = A.indexOf(c); if (i < 0) continue; v = (v << 5) | i; bits += 5; if (bits >= 8) { o.push((v >>> (bits - 8)) & 255); bits -= 8; } } return Buffer.from(o); }
function totp(secret, t = Date.now()) { const c = Buffer.alloc(8); c.writeBigUInt64BE(BigInt(Math.floor(t / 30000)));
  const h = createHmac("sha1", b32(secret)).update(c).digest(); const off = h[h.length - 1] & 15;
  return ((h.readUInt32BE(off) & 0x7fffffff) % 1e6).toString().padStart(6, "0"); }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function latestOtp(to, after) {
  for (let i = 0; i < 30; i++) {
    const r = await fetch(`${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:${to}`)}`);
    const msgs = ((await r.json()).messages ?? []).filter((m) => Date.parse(m.Created) >= after - 1000).sort((a, b) => Date.parse(b.Created) - Date.parse(a.Created));
    if (msgs[0]) { const b = await (await fetch(`${MAILPIT}/api/v1/message/${msgs[0].ID}`)).json(); const code = /\b(\d{6})\b/.exec(b.Text ?? "")?.[1]; if (code) return code; }
    await sleep(1000);
  }
  throw new Error("no OTP mail");
}

/** Signs in once per role; storage state (cookies incl. own td_device) kept in STATE_DIR. */
async function ensureState(browser, role, prefix) {
  const file = path.join(STATE_DIR, `${role}.json`);
  if (fs.existsSync(file)) {
    const ctx = await browser.newContext({ storageState: file }); const p = await ctx.newPage();
    const r = await p.goto(`${BASE}${role === "student" ? "/app" : `/${role === "content" ? "studio" : role}`}`);
    const ok = !/\/login/.test(p.url()) && r && r.status() < 400; await ctx.close(); if (ok) return file;
  }
  const a = acct(prefix); if (!a.id) throw new Error(`no account for ${prefix}`);
  const prev = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf8")) : null;
  const ctx = await browser.newContext();
  if (prev) await ctx.addCookies(prev.cookies.filter((c) => /td_device$/.test(c.name)));
  const page = await ctx.newPage();
  await page.goto(`${BASE}/login`);
  await page.getByLabel("Email or mobile").fill(a.id);
  await page.getByLabel(/^Password/).fill(a.pw);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL((u) => !/^\/login\/?$/.test(u.pathname), { timeout: 30000 });
  if (/\/login\/mfa/.test(page.url())) {
    // Other agents share these TOTP secrets and the api rejects a reused 30 s step: always use a
    // fresh step (wait for the next boundary) and retry once on rejection.
    for (let attempt = 0; attempt < 2 && /\/login\/mfa/.test(page.url()); attempt++) {
      const step = Math.floor(Date.now() / 30000) + 1;
      await sleep(step * 30000 - Date.now() + 300);
      await page.getByLabel("Authenticator code").fill(totp(a.totp));
      await page.getByRole("button", { name: "Verify" }).click();
      await page.waitForURL((u) => !/\/login\/mfa/.test(u.pathname), { timeout: 10000 }).catch(() => undefined);
    }
    if (/\/login\/mfa/.test(page.url())) throw new Error(`${role}: TOTP rejected twice`);
  }
  if (/\/login\/verify-device/.test(page.url())) {
    await page.waitForLoadState("networkidle").catch(() => undefined);
    const sent = Date.now();
    await page.getByRole("button", { name: /Send code by email/ }).click();
    await page.getByText(/We sent a 6-digit code/).waitFor({ timeout: 15000 });
    await page.getByLabel("6-digit code").fill(await latestOtp(a.id, sent));
    await page.getByRole("button", { name: "Confirm" }).click();
    await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 10000 }).catch(() => undefined);
    const replace = page.getByRole("button", { name: "Remove and continue" });
    if (await replace.isVisible().catch(() => false)) {
      // Never replace another agent's device (2 replacements / 30 days). Fall back to an unverified device.
      await page.getByRole("button", { name: "Cancel" }).click().catch(() => undefined);
      throw new Error(`${role}: device cap reached; not replacing a device`);
    }
    await page.waitForURL((u) => !u.pathname.startsWith("/login") || /session-choice/.test(u.pathname), { timeout: 30000 });
  }
  if (/\/login\/session-choice/.test(page.url())) {
    // Prefer an idle session without a running test; otherwise the last listed one without a test.
    const labels = page.locator("fieldset label"); const n = await labels.count(); let pick = -1;
    for (let i = 0; i < n; i++) { const t = await labels.nth(i).innerText(); if (/Test in progress/.test(t)) continue; if (!/now/.test(t)) { pick = i; break; } pick = i; }
    await labels.nth(Math.max(pick, 0)).locator("input[type=radio]").check();
    await page.getByRole("button", { name: "Sign out selected and continue" }).click();
    await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30000 });
  }
  await ctx.storageState({ path: file }); await ctx.close();
  return file;
}

// Pages: [key, role (null = anonymous), path or resolver(page) that discovers a dynamic id]
const firstHref = (re) => async (page, start) => {
  await page.goto(`${BASE}${start}`, { waitUntil: "networkidle", timeout: 30000 }).catch(() => undefined);
  const hrefs = await page.$$eval("a[href]", (as) => as.map((a) => a.getAttribute("href")));
  return hrefs.find((h) => re.test(h ?? "")) ?? null;
};
const PAGES = [
  ["public-home", null, "/"],
  ["public-courses", null, "/courses"],
  ["login", null, "/login"],
  ["student-dashboard", "student", "/app"],
  ["course-player", "student", async (p) => (await firstHref(/^\/app\/learn\/[^/]+\/[^/]+/)(p, `/app/courses/${env.E2E_FREE_COURSE_SLUG ?? "demo-dsa-free"}`)) ?? (await firstHref(/^\/app\/learn\//)(p, "/app/learning"))],
  ["test-landing", "student", `/app/tests/${env.E2E_TEST_ID}`],
  ["student-assignments", "student", "/app/assignments"],
  ["paths-player", "student", async (p) => (await firstHref(/^\/app\/path\/my\/[^/]+/)(p, "/app/path/my")) ?? "/app/path/my"],
  ["student-analytics", "student", "/app/analytics"],
  ["admin-dashboard", "admin", "/admin"],
  ["admin-users", "admin", "/admin/users"],
  ["admin-batches", "admin", "/admin/batches"],
  ["trainer-dashboard", "trainer", "/trainer"],
  ["evaluator-queue", "evaluator", "/evaluator"],
  ["studio-question-bank", "content", async (p) => (await firstHref(/^\/studio\/question-banks\/[^/]+/)(p, "/studio/question-banks")) ?? "/studio/question-banks"],
  ["test-report", "evaluator", async (p) => (await firstHref(/^\/evaluator\/tests\/[^/]+\/report/)(p, "/evaluator/tests")) ?? `/evaluator/tests/${env.E2E_TEST_ID}/report`],
];
const ROLE_PREFIX = { student: "STUDENT", admin: "ADMIN", trainer: "TRAINER", evaluator: "EVALUATOR", content: "CONTENT" };
// trainer@/evaluator@/content@ were at the 3-device cap (shared with other agents) on 2026-11-07; super_admin can open
// every staff portal, so by default staff pages are measured as the admin account (platform-wide scope = worst case).
// Set PERF_STAFF_OWN_ROLE=1 to sign in as the real role instead.
const AUTH_AS = (role) => (role && role !== "student" && role !== "admin" && !process.env.PERF_STAFF_OWN_ROLE ? "admin" : role);

const INIT = () => {
  window.__perf = { lcp: 0, lcpEl: null, cls: 0, longTasks: [] };
  try { new PerformanceObserver((l) => { for (const e of l.getEntries()) { window.__perf.lcp = e.startTime; window.__perf.lcpEl = e.element ? e.element.tagName + (e.element.id ? "#" + e.element.id : "") : (e.url || null); } }).observe({ type: "largest-contentful-paint", buffered: true }); } catch {}
  try { new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__perf.cls += e.value; }).observe({ type: "layout-shift", buffered: true }); } catch {}
  try { new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__perf.longTasks.push(Math.round(e.duration)); }).observe({ type: "longtask", buffered: true }); } catch {}
};

async function measure(ctx, url) {
  const page = await ctx.newPage();
  await page.addInitScript(INIT);
  const cdp = await ctx.newCDPSession(page);
  await cdp.send("Network.enable");
  const reqs = new Map();
  cdp.on("Network.requestWillBeSent", (e) => { if (!reqs.has(e.requestId)) reqs.set(e.requestId, { url: e.request.url, method: e.request.method, type: e.type, start: e.timestamp }); });
  cdp.on("Network.responseReceived", (e) => { const r = reqs.get(e.requestId); if (!r) return; r.status = e.response.status; r.fromCache = e.response.fromDiskCache || e.response.fromServiceWorker;
    const t = e.response.timing; if (t) r.ttfbMs = Math.round(t.receiveHeadersEnd - t.sendEnd);
    const h = Object.fromEntries(Object.entries(e.response.headers).map(([k, v]) => [k.toLowerCase(), v])); r.cacheControl = h["cache-control"]; r.contentType = h["content-type"]; r.encoding = h["content-encoding"]; r.serverTiming = h["server-timing"] ?? h["x-process-time"] ?? h["x-response-time"]; });
  cdp.on("Network.loadingFinished", (e) => { const r = reqs.get(e.requestId); if (r) { r.bytes = e.encodedDataLength; r.end = e.timestamp; } });
  cdp.on("Network.loadingFailed", (e) => { const r = reqs.get(e.requestId); if (r) r.failed = e.errorText; });
  const t0 = Date.now();
  const resp = await page.goto(url, { waitUntil: "load", timeout: 60000 });
  await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => undefined);
  await sleep(1000);
  const settledMs = Date.now() - t0;
  const m = await page.evaluate(() => { const n = performance.getEntriesByType("navigation")[0]; const fcp = performance.getEntriesByName("first-contentful-paint")[0];
    return { ttfb: n.responseStart - n.requestStart, domContentLoaded: n.domContentLoadedEventEnd, load: n.loadEventEnd, fcp: fcp ? fcp.startTime : null, docTransfer: n.transferSize, ...window.__perf }; });
  const finalUrl = page.url(); await page.close();
  const list = [...reqs.values()];
  const api = list.filter((r) => /\/api\//.test(new URL(r.url).pathname));
  const counts = {}; for (const r of api) { const k = `${r.method} ${r.url.replace(BASE, "")}`; counts[k] = (counts[k] ?? 0) + 1; }
  return { status: resp?.status(), finalUrl: finalUrl.replace(BASE, ""), settledMs, ttfbMs: Math.round(m.ttfb), fcpMs: m.fcp && Math.round(m.fcp), dclMs: Math.round(m.domContentLoaded), loadMs: Math.round(m.load), lcpMs: Math.round(m.lcp), lcpEl: m.lcpEl, cls: +m.cls.toFixed(4),
    longTasks: m.longTasks.length, longTaskMs: m.longTasks.reduce((a, b) => a + b, 0), maxLongTask: Math.max(0, ...m.longTasks),
    requests: list.length, transferKB: +(list.reduce((a, r) => a + (r.bytes ?? 0), 0) / 1024).toFixed(1),
    jsKB: +(list.filter((r) => r.type === "Script").reduce((a, r) => a + (r.bytes ?? 0), 0) / 1024).toFixed(1),
    apiCalls: api.map((r) => ({ m: r.method, u: r.url.replace(BASE, ""), s: r.status, ttfb: r.ttfbMs, kb: +((r.bytes ?? 0) / 1024).toFixed(1), st: r.serverTiming })),
    duplicates: Object.entries(counts).filter(([, c]) => c > 1).map(([k, c]) => `${k} x${c}`),
    statics: list.filter((r) => /\/_next\/static\//.test(r.url)).slice(0, 3).map((r) => ({ u: r.url.replace(BASE, ""), cc: r.cacheControl, enc: r.encoding, cached: r.fromCache })),
    docHeaders: list.find((r) => r.type === "Document") ? { cc: list.find((r) => r.type === "Document").cacheControl, enc: list.find((r) => r.type === "Document").encoding } : null,
    failed: list.filter((r) => r.failed || (r.status ?? 0) >= 400).map((r) => `${r.status ?? r.failed} ${r.url.replace(BASE, "")}`) };
}

const median = (xs) => { const s = xs.filter((x) => typeof x === "number" && !Number.isNaN(x)).sort((a, b) => a - b); return s.length ? s[Math.floor((s.length - 1) / 2)] : null; };

const browser = await chromium.launch();
const out = { at: new Date().toISOString(), base: BASE, runs: RUNS, chromium: browser.version(), pages: {} };
const states = {};
for (const [key, role, target] of PAGES) {
  if (ONLY && !ONLY.has(key)) continue;
  try {
    const as = AUTH_AS(role);
    if (as && !states[as]) states[as] = await ensureState(browser, as, ROLE_PREFIX[as]);
    const mk = () => browser.newContext(as ? { storageState: states[as] } : {});
    let p = target;
    if (typeof target === "function") { const c = await mk(); const pg = await c.newPage(); p = await target(pg); await c.close(); }
    const url = `${BASE}${p}`; const cold = [], warm = [];
    for (let i = 0; i < RUNS; i++) {
      const ctx = await mk();             // fresh context = empty HTTP cache (cold)
      cold.push(await measure(ctx, url));
      warm.push(await measure(ctx, url)); // same context = warm HTTP cache
      await ctx.close();
    }
    const sum = (rs) => Object.fromEntries(["ttfbMs", "fcpMs", "dclMs", "loadMs", "lcpMs", "cls", "settledMs", "requests", "transferKB", "jsKB", "longTasks", "longTaskMs", "maxLongTask"].map((k) => [k, median(rs.map((r) => r[k]))]));
    out.pages[key] = { role, signedInAs: as, path: p, cold: sum(cold), warm: sum(warm), sample: cold[cold.length - 1], warmSample: { apiCalls: warm[warm.length - 1].apiCalls, statics: warm[warm.length - 1].statics } };
    const c = out.pages[key].cold; console.log(`${key.padEnd(22)} ${p}  ttfb=${c.ttfbMs} lcp=${c.lcpMs} load=${c.loadMs} req=${c.requests} kb=${c.transferKB} dup=${cold[0].duplicates.length}`);
  } catch (e) { out.pages[key] = { role, error: String(e).slice(0, 300) }; console.log(`${key} ERROR ${String(e).slice(0, 200)}`); }
  fs.writeFileSync(OUT, JSON.stringify(out, null, 1));
}
await browser.close();

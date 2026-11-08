// Targeted re-checks: (1) unauthenticated deep links -> /login?next=…; (2) API-level authorisation:
// the student calling staff endpoints through the BFF (expect 401/403/404, never 200); (3) repeat
// of intermittent 503s; (4) enquiry detail, bank detail after a longer wait; (5) back/refresh.
import { writeFileSync, readFileSync, existsSync } from "node:fs";
import path from "node:path";
import { chromium, roleContext, watch, BASE, SHOTS, STATE, bff, sleep } from "./lib.mjs";

const res = { unauth: [], apiAuthz: [], repeat: [], misc: [] };
const browser = await chromium.launch();

// (1) unauthenticated
const anon = await browser.newContext();
const ap = await anon.newPage();
for (const u of ["/app", "/app/billing", "/admin", "/admin/users", "/trainer", "/evaluator", "/studio", "/desk/enquiries", "/unblock-request", "/account/restricted", "/read/does-not-exist"]) {
  const r = await ap.goto(`${BASE}${u}`).catch(() => null);
  await sleep(500);
  const final = ap.url().replace(BASE, "");
  res.unauth.push({ url: u, status: r?.status() ?? null, final, nestedNext: (final.match(/next=/g) ?? []).length + (decodeURIComponent(final).match(/next=/g) ?? []).length });
}
const apiAnon = await ap.evaluate(async () => (await fetch("/api/v1/admin/users")).status);
res.unauth.push({ url: "GET /api/v1/admin/users (anon)", status: apiAnon });
await anon.close();

// (2) student hitting staff APIs
const st = await roleContext(browser, "student");
const sp = await st.newPage();
await sp.goto(`${BASE}/app`);
for (const p of ["admin/users", "admin/ai-settings", "batches", "support/enquiries", "security/dashboard", "studio/questions?limit=1", "assignments?scope=mine", "finance/orders", "rbac/grants", "paths"]) {
  const r = await bff(sp, "GET", p);
  res.apiAuthz.push({ role: "student", path: p, status: r.status, code: r.json?.code ?? null });
}
const w = await bff(sp, "POST", "batches", { name: "AUDIT-should-fail", code: `AUDIT-X-${Date.now()}` });
res.apiAuthz.push({ role: "student", path: "POST batches", status: w.status, code: w.json?.code ?? null });
await st.close();

// trainer hitting admin APIs
const tr = await roleContext(browser, "trainer");
const tp = await tr.newPage();
await tp.goto(`${BASE}/trainer`);
for (const p of ["admin/users", "admin/ai-settings", "support/enquiries", "finance/orders", "studio/questions?limit=1"]) {
  const r = await bff(tp, "GET", p);
  res.apiAuthz.push({ role: "trainer", path: p, status: r.status, code: r.json?.code ?? null });
}
await tr.close();

// (3) + (4) admin
const ad = await roleContext(browser, "admin");
const bucket = watch(ad);
const pg = await ad.newPage();
await pg.goto(`${BASE}/admin`);
for (let i = 0; i < 3; i += 1) {
  for (const p of ["security/dashboard", "me/grants", "me/enabled-apps"]) {
    const t0 = Date.now();
    const r = await bff(pg, "GET", p);
    res.repeat.push({ path: p, status: r.status, ms: Date.now() - t0, code: r.json?.code ?? null, detail: typeof r.json === "object" ? r.json?.detail : String(r.json).slice(0, 80) });
  }
}
bucket.reset();
await pg.goto(`${BASE}/desk/enquiries`);
await pg.waitForLoadState("networkidle").catch(() => undefined);
await sleep(1500);
const rowLinks = await pg.locator("main table a, main [role=row] a").evaluateAll((as) => as.slice(0, 3).map((a) => `${a.textContent.trim()} -> ${a.getAttribute("href")}`));
const rowText = (await pg.locator("main table tbody tr").first().innerText().catch(() => "")).replace(/\s+/g, " ");
res.misc.push({ check: "enquiry queue row links", rowLinks, firstRow: rowText.slice(0, 160) });
await pg.screenshot({ path: path.join(SHOTS, "probe__desk_enquiries.png") });

// back / refresh on a list -> detail -> back
await pg.goto(`${BASE}/admin/batches`);
await pg.waitForLoadState("networkidle").catch(() => undefined);
const batch = existsSync(path.join(STATE, "audit-batch.json")) ? JSON.parse(readFileSync(path.join(STATE, "audit-batch.json"), "utf8")) : null;
if (batch) {
  await pg.getByRole("link", { name: batch.name }).first().click();
  await pg.waitForURL(/batches\/[^/]+$/);
  await pg.goBack();
  await pg.waitForLoadState("networkidle").catch(() => undefined);
  await sleep(1000);
  res.misc.push({ check: "back from batch detail", url: pg.url().replace(BASE, ""), h1: await pg.locator("h1").first().innerText().catch(() => "") });
  await pg.goForward();
  await pg.reload();
  await pg.waitForLoadState("networkidle").catch(() => undefined);
  await sleep(1000);
  res.misc.push({ check: "forward+refresh batch detail", url: pg.url().replace(BASE, ""), hasName: (await pg.locator("main").innerText()).includes(batch.name) });
}
// admin opening studio (portal gate allows super_admin, api refuses)
bucket.reset();
await pg.goto(`${BASE}/studio/question-banks`);
await pg.waitForLoadState("networkidle").catch(() => undefined);
await sleep(1500);
res.misc.push({ check: "admin -> /studio/question-banks", http: [...bucket.http], alert: (await pg.locator("main [role=alert]").allInnerTexts()).join(" | ").slice(0, 200) });
await ad.close();

// content: bank detail after longer wait
const co = await roleContext(browser, "content");
const cp = await co.newPage();
const cj = existsSync(path.join(STATE, "journey-content.json")) ? JSON.parse(readFileSync(path.join(STATE, "journey-content.json"), "utf8")) : null;
await cp.goto(`${BASE}/studio/question-banks`);
await cp.waitForLoadState("networkidle").catch(() => undefined);
await sleep(3000);
if (cj) {
  const link = cp.getByRole("link", { name: new RegExp(cj.bank) }).first();
  const found = await link.count();
  if (found) {
    await link.click();
    await cp.waitForLoadState("networkidle").catch(() => undefined);
    await sleep(6000);
  }
  const t = (await cp.locator("main").innerText()).replace(/\s+/g, " ");
  res.misc.push({ check: "content bank detail", found, url: cp.url().replace(BASE, ""), auditQuestions: (t.match(/AUDIT \d+:/g) ?? []).length, text: t.slice(0, 300) });
  await cp.screenshot({ path: path.join(SHOTS, "probe__content_bank_detail.png") });
}
await co.close();

writeFileSync(path.join(STATE, "probes.json"), JSON.stringify(res, null, 1));
console.log(JSON.stringify(res, null, 1));
await browser.close();

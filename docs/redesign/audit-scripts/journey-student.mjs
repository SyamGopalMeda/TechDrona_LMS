// Journey A: student signup -> email verify (Mailpit) -> sign in -> browse -> buy paid course with the
// fake Razorpay gateway -> access content -> lesson progress (+ reload persistence, double-submit check).
// Synthetic identity "AUDIT-..." only. Writes step log to $TEMP/td-page-audit/journey-student.json
// and saves the identity (no password printed) for the batch journey.
import { writeFileSync } from "node:fs";
import path from "node:path";
import { chromium, watch, BASE, SHOTS, STATE, mailFor, uiLogin, bff, sleep } from "./lib.mjs";

const n = `${Date.now()}`;
const who = { id: `audit.student.${n}@example.com`, pw: `audit-${n}-Correct-Horse-9`, name: `AUDIT-Student ${n.slice(-5)}` };
const steps = [];
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
const bucket = watch(ctx);
const page = await ctx.newPage();

async function step(name, fn) {
  bucket.reset();
  const t0 = Date.now();
  let ok = true;
  let note = "";
  try {
    note = (await fn()) ?? "";
  } catch (e) {
    ok = false;
    note = String(e).split("\n")[0].slice(0, 300);
  }
  const shot = `journey-student__${steps.length + 1}-${name.replace(/[^a-z0-9]+/gi, "_").slice(0, 40)}.png`;
  await page.screenshot({ path: path.join(SHOTS, shot) }).catch(() => undefined);
  const s = { step: name, ok, note, url: page.url().replace(BASE, ""), ms: Date.now() - t0, http: [...new Set(bucket.http)], console: [...new Set(bucket.console)].slice(0, 5), shot: `docs/redesign/shots/audit/${shot}` };
  steps.push(s);
  console.log(`${ok ? "OK  " : "FAIL"} ${name} -> ${s.url} ${note} ${s.http.length ? `http=${s.http.join(";")}` : ""}`);
  return ok;
}
const mainText = async () => (await page.locator("main").innerText().catch(() => "")).replace(/\s+/g, " ").slice(0, 400);

let t0 = Date.now();
await step("signup form submit", async () => {
  await page.goto(`${BASE}/signup`);
  await page.getByLabel(/Full name/).fill(who.name);
  await page.getByLabel(/^Email/).fill(who.id);
  await page.getByLabel("Day").selectOption("12");
  await page.getByLabel("Month").selectOption("April");
  await page.getByLabel("Year").selectOption("2000");
  await page.getByLabel(/^Password/).fill(who.pw);
  await page.getByRole("checkbox", { name: /I agree to the/ }).check();
  t0 = Date.now();
  await page.getByRole("button", { name: "Create account" }).click();
  await page.getByRole("heading", { name: "Check your inbox" }).waitFor({ timeout: 20_000 });
});
let token = null;
await step("verification email arrives (Mailpit)", async () => {
  const mail = await mailFor(who.id, t0, /verify\/email\//);
  token = /\/verify\/email\/([A-Za-z0-9_\-.~%]+)/.exec(mail)[1];
  return "link found";
});
await step("verify email link", async () => {
  await page.goto(`${BASE}/verify/email/${token}`);
  await page.getByRole("button", { name: "Verify my email" }).click();
  await page.getByText("Your email is verified").waitFor({ timeout: 20_000 });
});
await step("re-use verify link (expect graceful)", async () => {
  await page.goto(`${BASE}/verify/email/${token}`);
  await page.getByRole("button", { name: "Verify my email" }).click().catch(() => undefined);
  await sleep(2500);
  return mainText();
});
await step("sign in (new device flow)", async () => {
  const url = await uiLogin(page, who, "/app");
  return url.replace(BASE, "");
});
await step("dashboard loads", async () => {
  await page.goto(`${BASE}/app`);
  await page.waitForLoadState("networkidle").catch(() => undefined);
  return mainText();
});
await step("browse /courses", async () => {
  await page.goto(`${BASE}/courses`);
  const cards = await page.locator('ul[aria-label="Courses"] li').count();
  return `cards=${cards}`;
});
await step("open paid course", async () => {
  await page.goto(`${BASE}/courses/demo-aptitude-paid`);
  await page.waitForLoadState("networkidle").catch(() => undefined);
  const access = (await page.locator('aside[aria-label="Access"]').innerText().catch(() => "")).replace(/\s+/g, " ");
  return access.slice(0, 300);
});
let checkoutUrl = null;
await step("click buy CTA", async () => {
  const cta = page.locator('aside[aria-label="Access"] a, aside[aria-label="Access"] button').filter({ hasText: /buy|enrol|get|purchase|checkout|₹/i }).first();
  const label = await cta.innerText();
  await cta.click();
  await page.waitForURL(/checkout|login|pricing/, { timeout: 20_000 });
  await page.waitForLoadState("networkidle").catch(() => undefined);
  checkoutUrl = page.url();
  return `cta="${label.replace(/\s+/g, " ")}" -> ${mainText ? (await mainText()).slice(0, 250) : ""}`;
});
await step("fill billing + place order (double click)", async () => {
  await page.getByLabel("Name on invoice").fill(who.name);
  const state = page.getByLabel("State");
  const opts = await state.locator("option").allInnerTexts();
  await state.selectOption({ label: opts.find((o) => /Karnataka/.test(o)) ?? opts[1] });
  await sleep(1500);
  const btn = page.locator('form[aria-label="Billing details"] button[type="submit"]');
  const label = await btn.innerText();
  await btn.dblclick();
  await sleep(4000);
  return `button="${label}" url=${page.url().replace(BASE, "")} :: ${(await mainText()).slice(0, 250)}`;
});
await step("orders count after double-click", async () => {
  const r = await bff(page, "GET", "commerce/orders?limit=20");
  const list = r.json?.data ?? [];
  return `status=${r.status} orders=${list.length} ${list.map((o) => o.status).join(",")}`;
});
await step("pay via test gateway (success)", async () => {
  const pay = page.getByRole("button", { name: /^Pay/ }).first();
  await pay.click();
  const dlg = page.getByRole("dialog");
  await dlg.waitFor({ timeout: 10_000 });
  const dtext = (await dlg.innerText()).replace(/\s+/g, " ").slice(0, 200);
  await dlg.getByRole("button", { name: /success|succeed|approve|pay/i }).first().click();
  await page.waitForURL(/orders\//, { timeout: 30_000 });
  await sleep(4000);
  return `dialog="${dtext}" -> ${(await mainText()).slice(0, 250)}`;
});
await step("reload order page (persistence)", async () => {
  await page.reload();
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await sleep(1500);
  return (await mainText()).slice(0, 250);
});
await step("my access lists purchase", async () => {
  await page.goto(`${BASE}/app/access`);
  await page.waitForLoadState("networkidle").catch(() => undefined);
  return (await mainText()).slice(0, 300);
});
await step("my learning", async () => {
  await page.goto(`${BASE}/app/learning`);
  await page.waitForLoadState("networkidle").catch(() => undefined);
  return (await mainText()).slice(0, 300);
});
let lessonUrl = null;
await step("open purchased course + first lesson", async () => {
  await page.goto(`${BASE}/app/courses/demo-aptitude-paid`);
  await page.waitForLoadState("networkidle").catch(() => undefined);
  const link = page.locator('main a[href*="/app/learn/"]').first();
  lessonUrl = await link.getAttribute("href");
  await link.click();
  await page.waitForURL(/\/app\/learn\//, { timeout: 20_000 });
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await sleep(2000);
  const btns = await page.locator("main button").allInnerTexts();
  return `lesson=${lessonUrl} buttons=[${btns.map((b) => b.trim()).filter(Boolean).slice(0, 12).join(" | ")}]`;
});
await step("mark lesson complete", async () => {
  const b = page.getByRole("button", { name: /complete|done|finish/i }).first();
  const label = await b.innerText();
  await b.click();
  await sleep(3000);
  return `clicked "${label}" -> ${(await mainText()).slice(0, 200)}`;
});
await step("reload course: progress persisted", async () => {
  await page.goto(`${BASE}/app/courses/demo-aptitude-paid`);
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await sleep(1500);
  const done = await page.locator('[aria-label="Completed"]').count();
  const prog = await page.getByRole("progressbar").first().getAttribute("aria-valuenow").catch(() => null);
  return `completed-lessons=${done} progress=${prog}`;
});
await step("free course enrol", async () => {
  await page.goto(`${BASE}/courses/demo-dsa-free`);
  await page.waitForLoadState("networkidle").catch(() => undefined);
  const cta = page.locator('aside[aria-label="Access"] a, aside[aria-label="Access"] button').first();
  const label = await cta.innerText();
  await cta.click();
  await sleep(4000);
  return `cta="${label}" -> ${page.url().replace(BASE, "")} :: ${(await mainText()).slice(0, 200)}`;
});
await step("student back/refresh on checkout url", async () => {
  if (!checkoutUrl) return "no checkout url";
  await page.goto(checkoutUrl);
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await sleep(1500);
  return (await mainText()).slice(0, 250);
});

writeFileSync(path.join(STATE, "journey-student.json"), JSON.stringify({ who: { id: who.id, name: who.name }, steps }, null, 1));
writeFileSync(path.join(STATE, "audit-student.cred.json"), JSON.stringify(who)); // outside repo, synthetic only
await ctx.storageState({ path: path.join(STATE, "state-auditstudent.json") });
await browser.close();

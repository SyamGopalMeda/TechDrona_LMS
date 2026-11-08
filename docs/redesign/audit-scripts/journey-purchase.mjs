// Journey A2: the AUDIT student buys a plan from /pricing with the fake Razorpay gateway (test mode),
// checks double-submit, reload persistence, access, and lesson progress on the free course.
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { chromium, roleContext, watch, BASE, SHOTS, STATE, bff, sleep } from "./lib.mjs";

const who = JSON.parse(readFileSync(path.join(STATE, "audit-student.cred.json"), "utf8"));
const steps = [];
const browser = await chromium.launch();
const ctx = await roleContext(browser, "auditstudent", who);
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
  const shot = `journey-purchase__${steps.length + 1}-${name.replace(/[^a-z0-9]+/gi, "_").slice(0, 40)}.png`;
  await page.screenshot({ path: path.join(SHOTS, shot) }).catch(() => undefined);
  const s = { step: name, ok, note: String(note).slice(0, 400), url: page.url().replace(BASE, ""), ms: Date.now() - t0, http: [...new Set(bucket.http)], console: [...new Set(bucket.console)].slice(0, 4), shot: `docs/redesign/shots/audit/${shot}` };
  steps.push(s);
  console.log(`${ok ? "OK  " : "FAIL"} ${name} -> ${s.url} :: ${s.note} ${s.http.length ? `http=${s.http.join(";")}` : ""}`);
  return ok;
}
const mainText = async () => (await page.locator("main").innerText().catch(() => "")).replace(/\s+/g, " ");

let checkoutHref = null;
await step("pricing lists plans with buy links", async () => {
  await page.goto(`${BASE}/pricing`);
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await sleep(1500);
  const links = await page.locator('main a[href*="checkout"]').evaluateAll((as) => as.map((a) => `${a.textContent.trim()} => ${a.getAttribute("href")}`));
  checkoutHref = (await page.locator('main a[href*="checkout"]').first().getAttribute("href").catch(() => null));
  return `buy-links=${links.length} ${links.slice(0, 4).join(" ; ")}`;
});
await step("open checkout", async () => {
  if (!checkoutHref) throw new Error("no checkout link on /pricing");
  await page.goto(`${BASE}${checkoutHref}`);
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await sleep(1500);
  return (await mainText()).slice(0, 350);
});
await step("fill billing + place order (double-click)", async () => {
  await page.getByLabel("Name on invoice").fill(who.name);
  const state = page.getByLabel("State");
  const opts = await state.locator("option").allInnerTexts();
  await state.selectOption({ label: opts.find((o) => /Karnataka/.test(o)) ?? opts[1] });
  await sleep(2000);
  const btn = page.locator('form[aria-label="Billing details"] button[type="submit"]');
  const label = await btn.innerText();
  await btn.dblclick();
  await sleep(3000);
  const consent = page.getByRole("button", { name: "Turn on and continue" });
  if (await consent.isVisible().catch(() => false)) { await consent.click(); await sleep(5000); }
  return `button="${label}" -> ${page.url().replace(BASE, "")} :: ${(await mainText()).slice(0, 300)}`;
});
await step("orders after double-click (billing)", async () => {
  await page.goto(page.url()); // reload resumes the order (FE-27)
  await page.waitForLoadState("networkidle").catch(() => undefined);
  const r = await bff(page, "GET", "me/orders?limit=20");
  const list = r.json?.data ?? [];
  return `GET me/orders=${r.status} count=${list.length} statuses=${list.map((o) => o.status).join(",")}`;
});
await step("pay with test gateway -> success", async () => {
  const pay = page.getByRole("button", { name: /^Pay/ }).first();
  const label = await pay.innerText();
  await pay.click();
  const dlg = page.getByRole("dialog");
  await dlg.waitFor({ timeout: 10_000 });
  const dtext = (await dlg.innerText()).replace(/\s+/g, " ").slice(0, 250);
  const choices = await dlg.getByRole("button").allInnerTexts();
  await dlg.getByRole("button", { name: /succe/i }).first().click();
  await page.waitForURL(/orders\//, { timeout: 30_000 });
  await sleep(4000);
  return `pay="${label}" dialog="${dtext}" choices=[${choices.join("|")}] -> ${(await mainText()).slice(0, 250)}`;
});
await step("reload order page (persistence)", async () => {
  await page.reload();
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await sleep(2000);
  return (await mainText()).slice(0, 300);
});
await step("billing lists the order + invoice", async () => {
  await page.goto(`${BASE}/app/billing`);
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await sleep(1000);
  return (await mainText()).slice(0, 400);
});
await step("my access shows entitlement", async () => {
  await page.goto(`${BASE}/app/access`);
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await sleep(1000);
  return (await mainText()).slice(0, 400);
});
let lesson = null;
await step("free course: open first lesson", async () => {
  await page.goto(`${BASE}/app/courses/demo-dsa-free`);
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await sleep(1000);
  const a = page.locator('main a[href*="/app/learn/"]').first();
  lesson = await a.getAttribute("href");
  await page.goto(`${BASE}${lesson}`);
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await sleep(2500);
  const btns = (await page.locator("main button").allInnerTexts()).map((b) => b.trim()).filter(Boolean);
  return `lesson=${lesson} buttons=[${btns.slice(0, 12).join("|")}] :: ${(await mainText()).slice(0, 200)}`;
});
await step("lesson: mark complete / finish reading", async () => {
  await page.mouse.wheel(0, 5000); await page.evaluate(() => { window.scrollTo(0, document.body.scrollHeight); document.querySelectorAll("main *").forEach((e) => { if (e.scrollHeight > e.clientHeight + 10) e.scrollTop = e.scrollHeight; }); }); await sleep(2000);
  const b = page.getByRole("button", { name: /complete|done|finish|mark/i }).first();
  if (!(await b.isVisible().catch(() => false))) {
    // video lesson: try to play to the end
    const v = page.locator("video").first();
    if (await v.count()) {
      await v.evaluate((el) => { el.muted = true; return el.play().catch(() => undefined); });
      await sleep(3000);
      await v.evaluate((el) => { if (Number.isFinite(el.duration)) el.currentTime = el.duration - 0.2; });
      await sleep(8000);
      return `video lesson; duration=${await v.evaluate((el) => el.duration)}`;
    }
    throw new Error("no complete button and no <video>");
  }
  const label = await b.innerText();
  await b.click();
  await sleep(3000);
  return `clicked "${label}"`;
});
await step("course progress after reload", async () => {
  await page.goto(`${BASE}/app/courses/demo-dsa-free`);
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await sleep(1500);
  const done = await page.locator('[aria-label="Completed"]').count();
  const inprog = await page.locator('[aria-label="In progress"]').count();
  const prog = await page.getByRole("progressbar").first().getAttribute("aria-valuenow").catch(() => null);
  return `completed=${done} in-progress=${inprog} progress=${prog} :: ${(await mainText()).slice(0, 200)}`;
});
await step("dashboard reflects learning", async () => {
  await page.goto(`${BASE}/app`);
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await sleep(1500);
  return (await mainText()).slice(0, 300);
});
writeFileSync(path.join(STATE, "journey-purchase.json"), JSON.stringify({ steps }, null, 1));
await browser.close();

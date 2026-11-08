// AUDIT student starts the assigned batch test, answers Q1 if it is a choice, submits, and opens results.
import { readFileSync } from "node:fs";
import path from "node:path";
import { chromium, roleContext, watch, BASE, SHOTS, STATE, sleep } from "./lib.mjs";
const who = JSON.parse(readFileSync(path.join(STATE, "audit-student.cred.json"), "utf8"));
const browser = await chromium.launch();
const ctx = await roleContext(browser, "auditstudent", who);
const b = watch(ctx);
const page = await ctx.newPage();
page.setDefaultTimeout(20000);
const main = async () => (await page.locator("main").innerText().catch(() => "")).replace(/\s+/g, " ");
const shot = (n) => page.screenshot({ path: path.join(SHOTS, `journey-test__${n}.png`) });
await page.goto(`${BASE}/app/tests/01a1b606-a939-74fb-aa66-e86969099f68`);
await page.waitForLoadState("networkidle").catch(() => undefined);
for (const c of await page.getByRole("checkbox").all()) await c.check();
await page.getByRole("button", { name: "Start test" }).click();
await page.waitForURL(/attempts\//, { timeout: 30000 }).catch(() => undefined);
await sleep(3000);
await shot("1-started");
console.log("STARTED:", page.url().replace(BASE, ""), (await main()).slice(0, 300), b.http);
const radio = page.getByRole("radio").first();
if (await radio.count()) { await radio.check().catch(() => radio.click()); await sleep(1500); }
const btns = (await page.locator("button").allInnerTexts()).map((x) => x.trim()).filter(Boolean);
console.log("BUTTONS:", btns.slice(0, 25).join("|"));
const sub = page.getByRole("button", { name: /Submit/ }).first();
await sub.click();
await sleep(1500);
const dlg = page.getByRole("dialog");
if (await dlg.isVisible().catch(() => false)) {
  console.log("CONFIRM:", (await dlg.innerText()).replace(/\s+/g, " ").slice(0, 200));
  await dlg.getByRole("button", { name: /Submit/ }).last().click();
}
await sleep(4000);
await shot("2-submitted");
console.log("AFTER SUBMIT:", page.url().replace(BASE, ""), (await main()).slice(0, 300), b.http);
await browser.close();

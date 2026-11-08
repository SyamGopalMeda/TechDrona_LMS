// AUDIT student: (1) path "Mark as read" 409 body + visible message; (2) engage join + vote; (3) test start/submit.
import { readFileSync } from "node:fs";
import path from "node:path";
import { chromium, roleContext, watch, BASE, SHOTS, STATE, bff, sleep } from "./lib.mjs";
const who = JSON.parse(readFileSync(path.join(STATE, "audit-student.cred.json"), "utf8"));
const tr = JSON.parse(readFileSync(path.join(STATE, "journey-trainer.json"), "utf8"));
const browser = await chromium.launch();
const ctx = await roleContext(browser, "auditstudent", who);
const b = watch(ctx);
const page = await ctx.newPage();
page.setDefaultTimeout(20000);
const main = async () => (await page.locator("main").innerText().catch(() => "")).replace(/\s+/g, " ");
// (1)
await page.goto(`${BASE}/app/path/my/01a1b636-fb08-758c-8924-56587115a093`);
await page.waitForLoadState("networkidle").catch(() => undefined);
await sleep(1500);
const r = await bff(page, "POST", "me/paths/01a1b636-fb08-758c-8924-56587115a093/steps/01a1b636-d9d5-743b-9639-7eadba597649/complete", {});
console.log("PATH complete (direct):", r.status, JSON.stringify(r.json).slice(0, 300));
b.reset();
await page.getByRole("button", { name: "Mark as read" }).first().click();
await sleep(2500);
console.log("PATH UI after click:", (await page.locator('[role="alert"], [role="status"]').allInnerTexts()).join(" | ").replace(/\s+/g, " ").slice(0, 300), b.http);
const popup = page.waitForEvent("popup", { timeout: 8000 }).catch(() => null);
await page.getByRole("link", { name: /Open in a new tab/ }).first().click().catch(() => undefined);
const pp = await popup; if (pp) await pp.close();
await sleep(2000);
b.reset();
await page.getByRole("button", { name: "Mark as read" }).first().click().catch(() => undefined);
await sleep(2500);
await page.reload(); await page.waitForLoadState("networkidle").catch(() => undefined); await sleep(1500);
console.log("PATH after open+mark:", b.http, (await main()).slice(0, 220));
await page.screenshot({ path: path.join(SHOTS, "journey-participate__path_after_open_mark.png") });
// (2)
await page.goto(`${BASE}/app/engage/join/${tr.ids.joinCode}`);
await page.waitForLoadState("networkidle").catch(() => undefined);
await page.getByRole("button", { name: "Join" }).click();
await sleep(3000);
const t = await main();
console.log("ENGAGE after join:", page.url().replace(BASE, ""), t.slice(0, 300));
const opt = page.getByRole("radio", { name: "Arrays" }).or(page.getByRole("button", { name: /Arrays/ })).or(page.getByText("Arrays", { exact: true })).first();
if (await opt.count()) {
  await opt.click();
  const send = page.getByRole("button", { name: /submit|send|vote/i }).first();
  if (await send.count()) await send.dblclick();
  await sleep(2500);
}
console.log("ENGAGE after vote:", (await main()).slice(0, 300), b.http);
await page.screenshot({ path: path.join(SHOTS, "journey-participate__engage_after_vote.png") });
// (3)
await page.goto(`${BASE}/app/tests`);
await page.waitForLoadState("networkidle").catch(() => undefined);
await page.getByRole("link", { name: "View instructions" }).first().click();
await page.waitForLoadState("networkidle").catch(() => undefined);
await sleep(1500);
console.log("TEST instructions:", page.url().replace(BASE, ""), (await main()).slice(0, 300));
const btns = (await page.locator("main button").allInnerTexts()).map((x) => x.trim()).filter(Boolean);
console.log("TEST buttons:", btns.join("|"));
await page.screenshot({ path: path.join(SHOTS, "journey-participate__test_instructions.png") });
await browser.close();

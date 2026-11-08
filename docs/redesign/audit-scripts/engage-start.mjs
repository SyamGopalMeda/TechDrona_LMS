// Trainer presses "Start" on the AUDIT poll run saved by journey-trainer (so the student can answer).
import { readFileSync } from "node:fs";
import path from "node:path";
import { chromium, roleContext, BASE, SHOTS, STATE, sleep } from "./lib.mjs";
const tr = JSON.parse(readFileSync(path.join(STATE, "journey-trainer.json"), "utf8"));
const browser = await chromium.launch();
const ctx = await roleContext(browser, "trainer");
const page = await ctx.newPage();
await page.goto(`${BASE}${tr.ids.activityUrl}`);
await page.waitForLoadState("networkidle").catch(() => undefined);
await page.getByRole("button", { name: /Start/ }).first().click();
await sleep(3000);
console.log((await page.locator("main").innerText()).replace(/\s+/g, " ").slice(0, 300));
await page.screenshot({ path: path.join(SHOTS, "journey-engage__trainer_started.png") });
await browser.close();

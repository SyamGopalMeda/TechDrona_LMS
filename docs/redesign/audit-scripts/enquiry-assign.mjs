// Admin opens the AUDIT enquiry, assigns it to self, adds an internal note, reloads to confirm persistence.
import path from "node:path";
import { chromium, roleContext, watch, BASE, SHOTS, sleep } from "./lib.mjs";
const browser = await chromium.launch();
const ctx = await roleContext(browser, "admin");
const b = watch(ctx);
const page = await ctx.newPage();
page.setDefaultTimeout(20000);
await page.goto(`${BASE}/desk/enquiries/01a1b624-84af-77b1-a348-6ae1f621c93a`);
await page.waitForLoadState("networkidle").catch(() => undefined);
await sleep(1500);
const btns = (await page.locator("main button").allInnerTexts()).map((x) => x.trim()).filter(Boolean);
console.log("buttons:", btns.join("|"));
const assign = page.getByRole("button", { name: /assign/i }).first();
if (await assign.count()) { await assign.click(); await sleep(2500); }
await page.getByLabel("Internal note").fill("AUDIT note: synthetic enquiry, no action needed.");
await page.getByRole("button", { name: /save note|save/i }).first().click();
await sleep(2500);
await page.reload(); await page.waitForLoadState("networkidle").catch(() => undefined); await sleep(1500);
const t = (await page.locator("main").innerText()).replace(/\s+/g, " ");
console.log("after reload:", t.slice(0, 400));
console.log("note persisted:", (await page.getByLabel("Internal note").inputValue()).includes("AUDIT note"), "http:", b.http);
await page.screenshot({ path: path.join(SHOTS, "journey-admin__enquiry_assigned.png") });
await browser.close();

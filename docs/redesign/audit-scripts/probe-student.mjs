// Re-issues the two failing student writes through the BFF to capture the problem+json bodies.
import { readFileSync } from "node:fs";
import path from "node:path";
import { chromium, roleContext, BASE, STATE, bff } from "./lib.mjs";
const who = JSON.parse(readFileSync(path.join(STATE, "audit-student.cred.json"), "utf8"));
const browser = await chromium.launch();
const ctx = await roleContext(browser, "auditstudent", who);
const page = await ctx.newPage();
await page.goto(`${BASE}/app`);
const q = { json: {} };

const o = await bff(page, "POST", "commerce/orders", { price_id: "01a1af18-44ac-74e7-96df-8e90e8684ca1", coupon_code: null, billing: { name: who.name, state_code: "29", gstin: null }, quote_total_paise: q.json?.total_paise ?? 199900 });
console.log("order", o.status, JSON.stringify(o.json).slice(0, 600));
const c = await bff(page, "POST", "me/lessons/01a1af17-f164-775a-88ac-2af5ae8be688/completion", {});
console.log("completion", c.status, JSON.stringify(c.json).slice(0, 500));
await browser.close();

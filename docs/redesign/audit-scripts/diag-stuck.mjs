// Diagnoses pages stuck on a loading skeleton: logs every /api/v1 request with status + duration
// and any still-pending requests after 25 s. Usage: node diag-stuck.mjs <role> <path>
import { chromium, roleContext, BASE, sleep } from "./lib.mjs";
const [role, url] = process.argv.slice(2);
const browser = await chromium.launch();
const ctx = await roleContext(browser, role);
const page = await ctx.newPage();
const pending = new Map();
page.on("request", (r) => { if (r.url().includes("/api/v1/")) pending.set(r, Date.now()); });
page.on("requestfinished", async (r) => { if (!pending.has(r)) return; const resp = await r.response(); console.log(resp?.status(), `${Date.now() - pending.get(r)}ms`, r.method(), r.url().replace(BASE, "")); pending.delete(r); });
page.on("requestfailed", (r) => { if (!pending.has(r)) return; console.log("FAILED", r.failure()?.errorText, r.url().replace(BASE, "")); pending.delete(r); });
page.on("console", (m) => { if (m.type() === "error") console.log("console:", m.text().slice(0, 200)); });
page.on("pageerror", (e) => console.log("pageerror:", String(e).slice(0, 300)));
await page.goto(`${BASE}${url}`);
await sleep(25000);
console.log("still pending:", [...pending.keys()].map((r) => r.url().replace(BASE, "")));
console.log("h1:", await page.locator("h1").first().innerText().catch(() => "(none)"), "| skeleton:", await page.locator('main [aria-busy="true"], main .animate-pulse').count());
await browser.close();

// Visits an explicit list of (dynamic) URLs as one role and records the same diagnostics as crawl.mjs.
// Usage: node visit-list.mjs <role|auditstudent> <url> [url...]   (results appended to visits.json)
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import path from "node:path";
import { chromium, roleContext, watch, BASE, SHOTS, STATE, slug, sleep } from "./lib.mjs";

const [role, ...urls] = process.argv.slice(2);
const who = role === "auditstudent" ? JSON.parse(readFileSync(path.join(STATE, "audit-student.cred.json"), "utf8")) : undefined;
const browser = await chromium.launch();
const ctx = role === "anon" ? await browser.newContext() : await roleContext(browser, role, who);
const b = watch(ctx);
const page = await ctx.newPage();
const out = [];
for (const url of urls) {
  b.reset();
  const t0 = Date.now();
  const r = await page.goto(`${BASE}${url}`, { timeout: 45_000 }).catch(() => null);
  await page.waitForLoadState("networkidle", { timeout: 12_000 }).catch(() => undefined);
  await sleep(2500);
  const info = await page.evaluate(() => {
    const m = document.querySelector("main") ?? document.body;
    const t = (e) => (e?.textContent ?? "").replace(/\s+/g, " ").trim();
    return { h1: t(document.querySelector("h1")).slice(0, 100), alerts: Array.from(m.querySelectorAll('[role="alert"]')).map((a) => t(a).slice(0, 160)), busy: m.querySelectorAll('[aria-busy="true"]').length, text: t(m).slice(0, 220) };
  });
  const shot = `${role}__${slug(url)}.png`;
  await page.screenshot({ path: path.join(SHOTS, shot) }).catch(() => undefined);
  const rec = { role, url, final: page.url().replace(BASE, ""), status: r?.status() ?? null, ms: Date.now() - t0, ...info, http: [...new Set(b.http)], console: [...new Set(b.console)].slice(0, 4), shot: `docs/redesign/shots/audit/${shot}` };
  out.push(rec);
  console.log(`${rec.status} ${url} -> ${rec.final} | h1="${rec.h1}" alerts=${rec.alerts.length} http=${rec.http.join(";")} busy=${rec.busy} :: ${rec.text.slice(0, 120)}`);
}
const f = path.join(STATE, "visits.json");
const prev = existsSync(f) ? JSON.parse(readFileSync(f, "utf8")) : [];
writeFileSync(f, JSON.stringify([...prev, ...out], null, 1));
await browser.close();

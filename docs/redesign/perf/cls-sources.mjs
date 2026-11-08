// Lists layout-shift entries and their source nodes for given paths (diagnostic for CLS rows in perf-baseline.md).
// Usage: node docs/redesign/perf/cls-sources.mjs <role|anon> <path> [<path>...]   (state from PERF_STATE_DIR)
import { createRequire } from "node:module"; import { fileURLToPath } from "node:url"; import path from "node:path"; import os from "node:os";
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const { chromium } = createRequire(path.join(ROOT, "apps/web/package.json"))("playwright");
const [role, ...paths] = process.argv.slice(2);
const STATE = process.env.PERF_STATE_DIR ?? path.join(os.tmpdir(), "td-perf-state");
const b = await chromium.launch();
for (const p of paths) {
  const ctx = await b.newContext(role === "anon" ? {} : { storageState: path.join(STATE, `${role}.json`) });
  const page = await ctx.newPage();
  await page.addInitScript(() => { window.__ls = []; new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__ls.push({ t: Math.round(e.startTime), v: +e.value.toFixed(4), src: (e.sources || []).map((s) => { const n = s.node; return n && n.nodeType === 1 ? `${n.tagName.toLowerCase()}${n.id ? "#" + n.id : ""}.${String(n.className || "").split(" ").slice(0, 3).join(".")} ${s.previousRect.height}->${s.currentRect.height}h ${s.previousRect.y}->${s.currentRect.y}y` : String(n && n.nodeName); }) }); }).observe({ type: "layout-shift", buffered: true }); });
  await page.goto(`http://localhost:13000${p}`, { waitUntil: "networkidle" }); await page.waitForTimeout(1000);
  console.log(p, JSON.stringify(await page.evaluate(() => window.__ls), null, 0));
  await ctx.close();
}
await b.close();

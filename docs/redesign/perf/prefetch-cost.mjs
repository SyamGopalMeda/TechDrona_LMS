// Measures Next.js <Link> RSC prefetch traffic triggered by one page load (count, bytes, server time).
// Usage: node docs/redesign/perf/prefetch-cost.mjs <role|anon> <path>...   (state from PERF_STATE_DIR)
import { createRequire } from "node:module"; import { fileURLToPath } from "node:url"; import path from "node:path"; import os from "node:os";
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const { chromium } = createRequire(path.join(ROOT, "apps/web/package.json"))("playwright");
const [role, ...paths] = process.argv.slice(2);
const STATE = process.env.PERF_STATE_DIR ?? path.join(os.tmpdir(), "td-perf-state");
const b = await chromium.launch();
for (const p of paths) {
  const ctx = await b.newContext(role === "anon" ? {} : { storageState: path.join(STATE, `${role}.json`) });
  const page = await ctx.newPage(); const rsc = [];
  page.on("requestfinished", async (r) => { if (!/_rsc=/.test(r.url())) return; const t = r.timing(); const s = await r.sizes().catch(() => null);
    rsc.push({ u: r.url().replace("http://localhost:13000", "").replace(/[?&]_rsc=.*/, ""), prefetch: !!(await r.allHeaders())["next-router-prefetch"], ttfb: Math.round(t.responseStart - t.requestStart), kb: s ? +((s.responseBodySize + s.responseHeadersSize) / 1024).toFixed(1) : null }); });
  await page.goto(`http://localhost:13000${p}`, { waitUntil: "networkidle" }); await page.waitForTimeout(1500);
  const pre = rsc.filter((r) => r.prefetch);
  const med = (xs) => { const s = [...xs].sort((a, c) => a - c); return s[Math.floor((s.length - 1) / 2)]; };
  console.log(JSON.stringify({ path: p, rscRequests: rsc.length, prefetches: pre.length, prefetchKB: +pre.reduce((a, r) => a + (r.kb ?? 0), 0).toFixed(1), prefetchTtfbMedian: pre.length ? med(pre.map((r) => r.ttfb)) : null, prefetchTtfbMax: pre.length ? Math.max(...pre.map((r) => r.ttfb)) : null, sample: pre.slice(0, 4).map((r) => r.u) }));
  await ctx.close();
}
await b.close();

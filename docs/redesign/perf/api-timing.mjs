// Sequential replay of the GET endpoints captured by page-timing.mjs (through the BFF, same browser
// UA/cookies as the page runs, so the api's device/UA binding is respected). 1 warm-up + N timed calls each.
// Server time is joined from the api log by request id when `--logs <file>` is given (second pass):
//   node docs/redesign/perf/api-timing.mjs --n 7 > docs/redesign/perf/api-timing.json
//   docker compose logs api --since <start> --no-log-prefix > api.log
//   node docs/redesign/perf/api-timing.mjs --join docs/redesign/perf/api-timing.json --logs api.log
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const args = Object.fromEntries(process.argv.slice(2).reduce((a, v, i, arr) => (v.startsWith("--") ? [...a, [v.slice(2), arr[i + 1]]] : a), []));
const med = (xs) => { const s = [...xs].sort((a, b) => a - b); return s.length ? s[Math.floor((s.length - 1) / 2)] : null; };

if (args.join) {
  const res = JSON.parse(fs.readFileSync(args.join, "utf8"));
  const dur = new Map();
  for (const l of fs.readFileSync(args.logs, "utf8").split(/\r?\n/)) {
    const m = /duration_ms=([\d.]+).*request_id=(\S+)/.exec(l); if (m) dur.set(m[2], Number(m[1]));
  }
  for (const r of res.endpoints) { const s = r.requestIds.map((id) => dur.get(id)).filter((x) => x !== undefined); r.serverMs = s.map(Math.round); r.serverP50 = med(s) && Math.round(med(s)); r.bffOverheadP50 = r.serverP50 != null ? r.clientP50 - r.serverP50 : null; }
  res.endpoints.sort((a, b) => (b.serverP50 ?? b.clientP50) - (a.serverP50 ?? a.clientP50));
  fs.writeFileSync(args.join, JSON.stringify(res, null, 1));
  for (const r of res.endpoints) console.log(`${String(r.serverP50).padStart(5)} srv ${String(r.clientP50).padStart(5)} cli  ${r.as.padEnd(8)} ${r.url}`);
  process.exit(0);
}

const require = createRequire(path.join(ROOT, "apps/web/package.json"));
const { chromium } = require("playwright");
const N = Number(args.n ?? 7);
const STATE_DIR = process.env.PERF_STATE_DIR ?? path.join(os.tmpdir(), "td-perf-state");
const timing = JSON.parse(fs.readFileSync(path.join(ROOT, "docs/redesign/perf/page-timing.json"), "utf8"));
const byAs = {};
for (const p of Object.values(timing.pages)) {
  if (!p.sample || !p.signedInAs) continue;
  for (const c of p.sample.apiCalls) if (c.m === "GET" && c.s === 200) (byAs[p.signedInAs] ??= new Set()).add(c.u);
}
const browser = await chromium.launch();
const out = { at: new Date().toISOString(), n: N, endpoints: [] };
for (const [as, urls] of Object.entries(byAs)) {
  const ctx = await browser.newContext({ storageState: path.join(STATE_DIR, `${as}.json`) });
  const page = await ctx.newPage(); await page.goto(`${timing.base}/`); // same-origin page for fetch()
  for (const u of urls) {
    const call = () => page.evaluate(async (url) => { const t = performance.now(); const r = await fetch(url, { headers: { accept: "application/json" } }); await r.arrayBuffer();
      return { ms: performance.now() - t, status: r.status, rid: r.headers.get("x-request-id") }; }, u);
    await call();
    const runs = []; for (let i = 0; i < N; i++) runs.push(await call());
    out.endpoints.push({ as, url: u, status: runs[0].status, clientMs: runs.map((r) => Math.round(r.ms)), clientP50: Math.round(med(runs.map((r) => r.ms))), requestIds: runs.map((r) => r.rid).filter(Boolean) });
  }
  await ctx.close();
}
await browser.close();
console.log(JSON.stringify(out, null, 1));

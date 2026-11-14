// Read-only bundle analysis of apps/web/.next (no source maps needed).
// Usage: node docs/archive/redesign-next-app/perf/bundle-stats.mjs [path-to-.next] > out.json
import fs from "node:fs"; import path from "node:path"; import zlib from "node:zlib";
const dir = process.argv[2] || "apps/web/.next";
const m = JSON.parse(fs.readFileSync(path.join(dir, "app-build-manifest.json"), "utf8")).pages;
const gz = new Map();
const size = (f) => { if (!gz.has(f)) { const b = fs.readFileSync(path.join(dir, f)); gz.set(f, { raw: b.length, gz: zlib.gzipSync(b, { level: 9 }).length }); } return gz.get(f); };
const layouts = Object.keys(m).filter((k) => k.endsWith("/layout"));
const routes = [];
for (const key of Object.keys(m)) {
  if (!key.endsWith("/page")) continue;
  const segs = key.split("/").slice(1, -1); const files = new Set(m[key]);
  for (let i = 0; i <= segs.length; i++) { const lk = "/" + [...segs.slice(0, i), "layout"].join("/"); if (m[lk.replace("//", "/")]) m[lk.replace("//", "/")].forEach((f) => files.add(f)); }
  let js = 0, jsRaw = 0, css = 0; for (const f of files) { const s = size(f); if (f.endsWith(".js")) { js += s.gz; jsRaw += s.raw; } else if (f.endsWith(".css")) css += s.gz; }
  routes.push({ route: key.replace(/\/page$/, "") || "/", firstLoadJsGzKB: +(js / 1024).toFixed(1), rawKB: +(jsRaw / 1024).toFixed(1), cssGzKB: +(css / 1024).toFixed(1), files: [...files].length });
}
routes.sort((a, b) => b.firstLoadJsGzKB - a.firstLoadJsGzKB);
const chunks = fs.readdirSync(path.join(dir, "static/chunks"), { recursive: true }).filter((f) => f.endsWith(".js")).map((f) => { const p = "static/chunks/" + f.split(path.sep).join("/"); const s = size(p); const src = fs.readFileSync(path.join(dir, p), "utf8");
  const hints = ["recharts", "d3-", "monaco", "lodash", "victory", "react-dom", "decimal.js", "zod", "date-fns", "eventemitter3", "immer", "reselect", "redux"].filter((h) => src.includes(h));
  const usedBy = Object.keys(m).filter((k) => m[k].includes(p)).length; return { chunk: p, rawKB: +(s.raw / 1024).toFixed(1), gzKB: +(s.gz / 1024).toFixed(1), usedByEntries: usedBy, hints }; }).sort((a, b) => b.gzKB - a.gzKB);
const shared = ["webpack", "4bd1b696", "1255", "main-app"].map((h) => chunks.find((c) => c.chunk.includes(h))).filter(Boolean);
console.log(JSON.stringify({ routeCount: routes.length, shared, routes, topChunks: chunks.slice(0, 25), totalStaticJsGzKB: +(chunks.reduce((a, c) => a + c.gzKB, 0)).toFixed(1) }, null, 1));

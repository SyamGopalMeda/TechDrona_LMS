// Aggregates api request durations (server-side, from structlog `request duration_ms=...` lines).
// Usage: docker compose logs api --since <ISO> --no-log-prefix | node docs/archive/redesign-next-app/perf/api-log-stats.mjs [minCount]
// Paths are normalised (uuids/numbers -> :id). Prints JSON sorted by p50 desc.
import readline from "node:readline";
const minCount = Number(process.argv[2] ?? 1);
const by = new Map();
const rl = readline.createInterface({ input: process.stdin });
for await (const line of rl) {
  const m = /duration_ms=([\d.]+) method=(\w+) path=(\S+).*status=(\d+)/.exec(line);
  if (!m) continue;
  const p = m[3].replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi, ":id").replace(/\/\d+(?=\/|$)/g, "/:n");
  const k = `${m[2]} ${p}`;
  if (!by.has(k)) by.set(k, []);
  by.get(k).push(Number(m[1]));
}
const q = (s, f) => s[Math.min(s.length - 1, Math.floor(f * s.length))];
const rows = [...by].map(([k, v]) => { const s = v.sort((a, b) => a - b); return { endpoint: k, n: s.length, p50: Math.round(q(s, 0.5)), p95: Math.round(q(s, 0.95)), max: Math.round(s[s.length - 1]) }; })
  .filter((r) => r.n >= minCount).sort((a, b) => b.p50 - a.p50);
console.log(JSON.stringify(rows, null, 1));

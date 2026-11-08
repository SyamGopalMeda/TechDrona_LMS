// Builds the markdown inventory table (static inventory + live crawl/visit results) for audit-pages.md.
// Usage: node report-table.mjs <inv.json>  (reads crawl-*.json / visits.json from $TEMP/td-page-audit)
import { readFileSync, existsSync } from "node:fs";
import path from "node:path";
import { STATE } from "./lib.mjs";

const inv = JSON.parse(readFileSync(process.argv[2], "utf8"));
const live = new Map();
const add = (route, rec) => { if (!live.has(route)) live.set(route, []); live.get(route).push(rec); };
const toRe = (r) => new RegExp(`^${r.replace(/\[[^\]]+\]/g, "[^/?#]+")}$`);
for (const role of ["public", "student", "admin", "trainer", "evaluator", "content"]) {
  const f = path.join(STATE, `crawl-${role}.json`);
  if (!existsSync(f)) continue;
  for (const r of JSON.parse(readFileSync(f, "utf8")).results) if (!r.route.startsWith("PROBE") && !r.skipped) add(r.route, { role, ...r });
}
const vf = path.join(STATE, "visits.json");
if (existsSync(vf)) for (const v of JSON.parse(readFileSync(vf, "utf8"))) {
  const x = inv.find((i) => toRe(i.route).test(v.url.split("?")[0]));
  if (x) add(x.route, { ...v, role: v.role === "auditstudent" ? "student" : v.role });
}
const ROLE = (r) =>
  r.startsWith("/app") ? "Student" : r.startsWith("/trainer") ? "Trainer" : r.startsWith("/evaluator") ? "Evaluator" : r.startsWith("/studio") ? "Content mgr" :
  /^\/(admin|finance|desk|security|mentor)/.test(r) ? "Admin" : r.startsWith("/read") ? "Signed-in (trainer/student)" : "Public";
const verdict = (recs) => {
  if (!recs?.length) return "not visited (no instance)";
  const r = recs[recs.length - 1];
  const bits = [];
  if (r.notImplemented || /Not yet implemented/.test(r.text ?? "")) bits.push("NOT IMPLEMENTED");
  if (r.notFound) bits.push("404");
  if ((r.alerts ?? []).length) bits.push(`error state: ${r.alerts[0].slice(0, 60)}`);
  const http = (r.http ?? []).filter((h) => !/analytics/.test(h));
  if (http.length) bits.push(http.slice(0, 2).join("; "));
  if ((r.console ?? []).some((c) => /pageerror/.test(c))) bits.push("JS error");
  if (r.busy) bits.push("stuck loading");
  if (r.final && r.final.split("?")[0] !== (r.url ?? "").split("?")[0]) bits.push(`→ ${r.final.split("?")[0]}`);
  return bits.length ? bits.join(" · ") : "loads OK";
};
const esc = (s) => String(s ?? "").replace(/\|/g, "\\|");
const lines = ["| # | Route | Purpose (page title) | Roles (UX gate) | Feature folder(s) | Backing API (sample, static) | Live result |", "|---|---|---|---|---|---|---|"];
inv.forEach((x, i) => {
  const eps = x.eps.filter((e) => !/^GET me\/(grants|enabled-apps)$/.test(e)).slice(0, 4).map((e) => `\`${e}\``).join(", ") + (x.eps.length > 4 ? ` +${x.eps.length - 4}` : "");
  lines.push(`| ${i + 1} | \`${x.route}\` | ${esc(x.title || x.eyebrow || "—")} | ${ROLE(x.route)} | ${x.feats.join(", ") || "—"} | ${eps || "—"} | ${esc(verdict(live.get(x.route)))} |`);
});
process.stdout.write(lines.join("\n"));

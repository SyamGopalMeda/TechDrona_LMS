// Static route inventory (code-reviewed): page.tsx -> imported files (transitive, within src) -> api path literals.
// Usage (repo root): node docs/redesign/audit-scripts/inventory.mjs > inv.json
import { readFileSync, existsSync, readdirSync, statSync } from "node:fs";
import path from "node:path";

const SRC = path.resolve(process.argv[2] ?? "apps/web/src");
const APP = path.join(SRC, "app");
const norm = (p) => p.split(path.sep).join("/");

function walk(d, out = []) {
  for (const f of readdirSync(d)) {
    const p = path.join(d, f);
    if (statSync(p).isDirectory()) walk(p, out);
    else out.push(p);
  }
  return out;
}
const pages = walk(APP).filter((f) => path.basename(f) === "page.tsx");

function resolveImp(spec, from) {
  let base;
  if (spec.startsWith("@/")) base = path.join(SRC, spec.slice(2));
  else if (spec.startsWith(".")) base = path.resolve(path.dirname(from), spec);
  else return null;
  for (const c of [base, `${base}.ts`, `${base}.tsx`, path.join(base, "index.ts"), path.join(base, "index.tsx")])
    if (existsSync(c) && statSync(c).isFile()) return c;
  return null;
}

const EP = /\b(?:api\.(get|post|put|patch|delete)|serverApiGet|useApiAll|useApi)\s*(?:<[^()]*?>)?\(\s*([`"'])([^`"']+)\2/g;

function analyse(page) {
  const seen = new Set();
  const eps = new Set();
  const feats = new Set();
  const q = [page];
  while (q.length) {
    const f = q.pop();
    if (seen.has(f)) continue;
    seen.add(f);
    const rel = norm(path.relative(SRC, f));
    if (/^(components\/ui|lib\/api|lib\/ui|lib\/ids|components\/shell)/.test(rel)) continue;
    const m = /^features\/([^/]+)/.exec(rel);
    if (m) feats.add(m[1]);
    const s = readFileSync(f, "utf8");
    for (const mm of s.matchAll(/(?:import|export)[^'"]*?from\s+["']([^"']+)["']/g)) {
      const r = resolveImp(mm[1], f);
      if (r && !/\.test\./.test(r)) q.push(r);
    }
    for (const e of s.matchAll(EP)) eps.add(`${(e[1] ?? "get").toUpperCase()} ${e[3].replace(/\$\{[^}]+\}/g, "{}")}`);
  }
  return { feats: [...feats].sort(), eps: [...eps].sort() };
}

const ROOT = path.resolve(SRC, "../../..");
const rows = pages
  .map((p) => {
    let route = `/${norm(path.relative(APP, path.dirname(p)))}`
      .replace(/\/\([^)]+\)/g, "")
      .replace(/\/$/, "");
    if (route === "") route = "/";
    const src = readFileSync(p, "utf8");
    const title = /title:\s*["'`]([^"'`]+)/.exec(src)?.[1] ?? /PageHeader[^>]*title="([^"]+)"/.exec(src)?.[1] ?? "";
    const eyebrow = /eyebrow="([^"]+)"/.exec(src)?.[1] ?? "";
    return { route, file: norm(path.relative(ROOT, p)), title, eyebrow, ...analyse(p) };
  })
  .sort((x, y) => x.route.localeCompare(y.route));
process.stdout.write(JSON.stringify(rows, null, 1));

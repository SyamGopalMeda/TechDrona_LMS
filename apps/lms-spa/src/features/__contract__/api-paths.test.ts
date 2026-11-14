// @vitest-environment node
/**
 * Contract test: every API call a feature makes (api.get/post/…, useResource, useApi,
 * serverApiGet, apiRequest with a literal path) must exist in the backend OpenAPI document
 * (apps/api/openapi.json, dumped from the FastAPI app) with the same HTTP method.
 *
 * Endpoints the backend does not provide yet must NOT be called — the UI renders an honest
 * "Not available yet" state instead. Refresh the spec with
 * `python -m app.scripts.export_openapi` in apps/api (writes apps/api/openapi.json).
 */
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const SPA_ROOT = path.resolve(__dirname, "../../..");
const SPEC_PATH = path.resolve(SPA_ROOT, "../api/openapi.json");
const spec = JSON.parse(fs.readFileSync(SPEC_PATH, "utf8")) as {
  paths: Record<string, Record<string, unknown>>;
};

interface Route {
  method: string;
  segments: string[];
}

const routes: Route[] = Object.entries(spec.paths).flatMap(([p, ops]) =>
  Object.keys(ops).map((m) => ({ method: m.toUpperCase(), segments: p.replace(/^\/api\/v1\//, "").split("/") })),
);

/** Path params (`{id}`) match any segment; a fully dynamic call segment (`${x}`) matches any segment. */
function matches(route: Route, call: Call): boolean {
  const segs = call.path.replace(/^\//, "").split("/");
  if (route.method !== call.method || segs.length !== route.segments.length) return false;
  return route.segments.every((r, i) => r.startsWith("{") || segs[i] === "*" || segs[i] === r);
}

function walk(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const full = path.join(dir, e.name);
    return e.isDirectory() ? walk(full) : [full];
  });
}

const CALL =
  /\b(api\.(get|post|patch|put|delete)|serverApiGet|apiRequest|useResource|useApi\w*)\s*(?:<(?:[^()]|\([^()]*\))*?>)?\((?:\s*[\w.!&|()]+\s*\?)?\s*([`"'])([^`"']*)\3/g;

interface Call {
  file: string;
  method: string;
  raw: string;
  path: string;
}

function collectCalls(): Call[] {
  const featuresDir = path.join(SPA_ROOT, "src/features");
  const files = walk(featuresDir).filter((f) => /\.tsx?$/.test(f) && !/\.test\.tsx?$/.test(f));
  const calls: Call[] = [];
  for (const file of files) {
    const src = fs.readFileSync(file, "utf8");
    for (const m of src.matchAll(CALL)) {
      const raw = m[4] ?? "";
      // Dynamic prefix (e.g. `${base}/approve`) — resolved elsewhere; cannot be checked statically.
      if (raw.startsWith("${") || raw === "") continue;
      let method = m[2] ? m[2].toUpperCase() : "GET";
      if (m[1] === "apiRequest") {
        const mm = src.slice(m.index, m.index + 400).match(/method:\s*["'](\w+)["']/);
        if (mm?.[1]) method = mm[1];
      }
      let p = raw
        .split("?")[0]!
        .split("/")
        .map((seg) => (/^\$\{[^}]*\}$/.test(seg) ? "*" : seg))
        .join("/");
      if (p.startsWith("/api/v1")) p = p.slice("/api/v1".length);
      if (!p.startsWith("/")) p = `/${p}`;
      calls.push({ file: path.relative(SPA_ROOT, file).replace(/\\/g, "/"), method: method ?? "GET", raw, path: p });
    }
  }
  return calls;
}

describe("frontend ↔ backend API contract", () => {
  const calls = collectCalls();

  it("finds API calls to check", () => {
    expect(calls.length).toBeGreaterThan(100);
  });

  it("only calls endpoints (method + path) that exist in the backend OpenAPI document", () => {
    const missing = calls
      .filter((c) => !routes.some((r) => matches(r, c)))
      .map((c) => `${c.method} ${c.raw}  (${c.file})`);
    expect(missing).toEqual([]);
  });
});

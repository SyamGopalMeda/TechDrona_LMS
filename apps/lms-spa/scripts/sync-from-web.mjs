// Copies the live Next app (apps/web/src, apps/web/public) into this SPA and applies the
// mechanical SPA transforms. Re-run after apps/web changes: `npm run sync`.
//
// 1. src/** is replaced by apps/web/src/** (except src/spa/**, which is SPA-owned code), minus
//    the server-only parts that the Firebase API function replaces: middleware, route handlers
//    (app/api, app/college-portal), lib/bff, lib/college-portal.
// 2. Every async component in a non-"use client" file (ex-server components: ~100 pages plus a
//    few shared components) is wrapped with asyncComponent() from src/spa/async.tsx, which runs it
//    on the client with Suspense. Its source is otherwise unchanged.
// 3. Hand-written overrides in spa-overrides/** (same relative paths) replace the copied files:
//    the root/public layouts, PortalShell, StaffPortalGate and lib/api/server.ts.
// 4. apps/web/public is copied to public/ (Monaco is copied separately by copy-monaco.mjs).
// 5. apps/web/openapi (the API contract the contract test checks) is copied to openapi/.
import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const web = join(root, "..", "web");
const webSrc = join(web, "src");
const src = join(root, "src");
const overrides = join(root, "spa-overrides");

const EXCLUDE = [
  "middleware.ts",
  "middleware.test.ts",
  "app/api",
  "app/college-portal",
  "lib/bff",
  "lib/college-portal",
];
const excluded = (rel) => EXCLUDE.some((e) => rel === e || rel.startsWith(`${e}/`)) || /(^|\/)route\.ts$/.test(rel);

function walk(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...walk(p));
    else out.push(p);
  }
  return out;
}

const posix = (p) => p.split(sep).join("/");

// 1. clean (keep src/spa) and copy
mkdirSync(src, { recursive: true });
for (const name of readdirSync(src)) {
  if (name === "spa") continue;
  rmSync(join(src, name), { recursive: true, force: true });
}
const overridden = new Set(existsSync(overrides) ? walk(overrides).map((p) => posix(relative(overrides, p))) : []);

let copied = 0;
let wrapped = 0;
const wrappedFiles = [];
for (const file of walk(webSrc)) {
  const rel = posix(relative(webSrc, file));
  if (excluded(rel)) continue;
  const dest = join(src, rel);
  mkdirSync(dirname(dest), { recursive: true });
  if (overridden.has(rel)) continue; // written in step 3
  let text = readFileSync(file, "utf8");
  if (rel.endsWith(".tsx") && !rel.includes(".test.")) {
    const r = wrapAsyncComponents(text, rel);
    if (r.count) {
      text = r.text;
      wrapped += r.count;
      wrappedFiles.push(rel);
    }
  }
  if (rel.includes(".test.")) text = callServerInTests(text);
  writeFileSync(dest, text);
  copied += 1;
}

// 3. overrides
for (const rel of overridden) {
  const dest = join(src, rel);
  mkdirSync(dirname(dest), { recursive: true });
  cpSync(join(overrides, rel), dest);
}

// 4. public assets
const pub = join(root, "public");
for (const name of readdirSync(join(web, "public"))) {
  if (name === "vendor") continue; // vendor/monaco comes from copy-monaco.mjs
  cpSync(join(web, "public", name), join(pub, name), { recursive: true });
}

// 5. the API contract (src/features/__contract__/api-paths.test.ts checks every call against it)
rmSync(join(root, "openapi"), { recursive: true, force: true });
cpSync(join(web, "openapi"), join(root, "openapi"), { recursive: true });

writeFileSync(
  join(root, "scripts", "sync-report.json"),
  `${JSON.stringify({ copied, overrides: [...overridden].sort(), wrappedComponents: wrapped, wrappedFiles: wrappedFiles.sort() }, null, 2)}\n`,
);
console.log(`[sync] copied ${copied} files, ${overridden.size} overrides, wrapped ${wrapped} async components in ${wrappedFiles.length} files`);

/**
 * Tests that call a page's server component directly (`await Page({ params })`) call the
 * original async function, now `Page.server`, instead of the client wrapper.
 */
function callServerInTests(text) {
  const names = [...text.matchAll(/^import\s+(\w+)\s+from\s+["']@\/app\/[^"']*\/page["'];?$/gm)].map((m) => m[1]);
  for (const n of names) text = text.replace(new RegExp(String.raw`await\s+${n}\(`, "g"), `await ${n}.server(`);
  return text;
}

/**
 * `export default async function Name(` / `export async function Name(` / `async function Name(`
 * (capitalised = a component) in a file without "use client" → `async function Name__server(`
 * plus a wrapped binding with the original name and export.
 */
function wrapAsyncComponents(text, rel) {
  if (/^\s*["']use client["']/.test(text)) return { text, count: 0 };
  const re = /^(export\s+default\s+|export\s+)?async\s+function\s+([A-Z]\w*)\s*(?=[(<])/gm;
  const tails = [];
  const out = text.replace(re, (_m, exp, name) => {
    const id = JSON.stringify(`${rel}#${name}`);
    if (exp && exp.includes("default")) tails.push(`export default asyncComponent(${name}__server, ${id});`);
    else if (exp) tails.push(`export const ${name} = asyncComponent(${name}__server, ${id});`);
    else tails.push(`const ${name} = asyncComponent(${name}__server, ${id});`);
    return `async function ${name}__server`;
  });
  if (!tails.length) return { text, count: 0 };
  return {
    text: `import { asyncComponent } from "@/spa/async";\n${out}\n// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).\n${tails.join("\n")}\n`,
    count: tails.length,
  };
}

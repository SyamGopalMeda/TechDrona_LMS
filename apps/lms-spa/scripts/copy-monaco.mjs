// Copies the prebuilt Monaco AMD bundle (node_modules/monaco-editor/min/vs) to
// public/vendor/monaco/vs so the editor is served same-origin (CSP: script/style/font 'self').
// Runs before `vite` and `vite build`. Idempotent: skips when the version already matches.
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const pkgDir = join(root, "node_modules", "monaco-editor");
const src = join(pkgDir, "min", "vs");
const dest = join(root, "public", "vendor", "monaco", "vs");
const stamp = join(root, "public", "vendor", "monaco", ".version");

if (!existsSync(src)) {
  console.warn("[copy-monaco] monaco-editor/min/vs not found; run npm install. The coding editor will fall back to a plain textarea.");
  process.exit(0);
}

const version = JSON.parse(readFileSync(join(pkgDir, "package.json"), "utf8")).version;
if (existsSync(stamp) && readFileSync(stamp, "utf8").trim() === version && existsSync(join(dest, "loader.js"))) {
  process.exit(0);
}

rmSync(dest, { recursive: true, force: true });
mkdirSync(dest, { recursive: true });
cpSync(src, dest, { recursive: true });
writeFileSync(stamp, version);
console.warn(`[copy-monaco] copied monaco-editor ${version} to public/vendor/monaco/vs`);

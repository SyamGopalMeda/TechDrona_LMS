import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Config } from "tailwindcss";

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));

/*
 * Design tokens: the UX-owned preset in packages/design-tokens is the source of truth.
 * The local fallback preset (src/styles/fallback-tokens) is always applied first so that
 * every class used by src/components/ui exists; when the upstream preset is present it is
 * layered on top and wins for any key it defines. See README.md "Design tokens".
 */
const upstreamCandidates = ["tailwind-preset.cjs", "tailwind-preset.js"].map((f) =>
  path.resolve(here, "../../packages/design-tokens", f),
);
const upstreamPath = upstreamCandidates.find((p) => existsSync(p));

const fallbackPreset = require(path.join(here, "src/styles/fallback-tokens/tailwind-preset.cjs")) as Partial<Config>;
const upstreamPreset = upstreamPath
  ? (require(upstreamPath) as Partial<Config> & { default?: Partial<Config> })
  : undefined;

const presets: Partial<Config>[] = [fallbackPreset];
if (upstreamPreset) presets.push(upstreamPreset.default ?? upstreamPreset);

const config: Config = {
  presets: presets as Config[],
  // Themes switch through CSS variables (tokens.css), so no `dark:` variant is needed.
  content: ["./src/**/*.{ts,tsx}", "./index.html"],
  theme: { extend: {} },
  plugins: [],
};

export default config;

// Generates tokens.css (CSS custom properties) and tailwind-v4.css (@theme mapping) from tokens.json.
// Usage: node scripts/build.mjs
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { ROOT, tokens, flattenTheme, hexToRgb, isOpaqueHex } from "./lib.mjs";

const P = tokens.meta.prefix; // "td"
const HEADER = `/* Tech Drona design tokens v${tokens.meta.version}. GENERATED from tokens.json by scripts/build.mjs. Do not edit by hand. */\n`;

function colorDecls(theme) {
  return flattenTheme(theme)
    .map(({ name, value }) => {
      const lines = [`  --${P}-${name}: ${value};`];
      if (isOpaqueHex(value)) {
        const { r, g, b } = hexToRgb(value);
        lines.push(`  --${P}-${name}-rgb: ${r} ${g} ${b};`);
      }
      return lines.join("\n");
    })
    .join("\n");
}

function shadowDecls(set) {
  return Object.entries(set).map(([k, v]) => `  --${P}-shadow-${k}: ${v};`).join("\n");
}

function staticDecls() {
  const out = [];
  for (const [k, v] of Object.entries(tokens.font.family)) out.push(`  --${P}-font-${k}: ${v};`);
  for (const [k, v] of Object.entries(tokens.font.weight)) out.push(`  --${P}-font-weight-${k}: ${v};`);
  for (const [k, v] of Object.entries(tokens.font.size)) {
    out.push(`  --${P}-text-${k}: ${v.size};`);
    out.push(`  --${P}-text-${k}-lh: ${v.lineHeight};`);
    out.push(`  --${P}-text-${k}-ls: ${v.letterSpacing};`);
  }
  for (const [k, v] of Object.entries(tokens.layout)) out.push(`  --${P}-layout-${k}: ${v};`);
  for (const [k, v] of Object.entries(tokens.radius)) out.push(`  --${P}-radius-${k}: ${v};`);
  for (const [k, v] of Object.entries(tokens.motion.duration)) out.push(`  --${P}-duration-${k}: ${v};`);
  for (const [k, v] of Object.entries(tokens.motion.easing)) out.push(`  --${P}-ease-${k}: ${v};`);
  for (const [k, v] of Object.entries(tokens.zIndex)) out.push(`  --${P}-z-${k}: ${v};`);
  for (const [k, v] of Object.entries(tokens.opacity)) out.push(`  --${P}-opacity-${k}: ${v};`);
  return out.join("\n");
}

const light = tokens.semantic.light;
const dark = tokens.semantic.dark;
const reduced = Object.entries(tokens.motion.reducedMotion.duration)
  .map(([k, v]) => `    --${P}-duration-${k}: ${v};`)
  .join("\n");

const css = `${HEADER}
/* Fonts (load once in the app shell; self-host via next/font in production):
   ${tokens.font.googleFontsUrl} */

:root {
  color-scheme: light;
${staticDecls()}
${shadowDecls(tokens.shadow.light)}
${colorDecls(light)}
}

/* OS dark preference, unless the user explicitly chose light */
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
${shadowDecls(tokens.shadow.dark).replace(/^/gm, "  ")}
${colorDecls(dark).replace(/^/gm, "  ")}
  }
}

/* Explicit user choice (theme toggle) */
:root[data-theme="dark"],
[data-theme="dark"] {
  color-scheme: dark;
${shadowDecls(tokens.shadow.dark)}
${colorDecls(dark)}
}

:root[data-theme="light"],
[data-theme="light"] {
  color-scheme: light;
${shadowDecls(tokens.shadow.light)}
${colorDecls(light)}
}

@media (prefers-reduced-motion: reduce) {
  :root {
${reduced}
  }
}

/* Forced colours (Windows High Contrast): keep focus and state borders visible */
@media (forced-colors: active) {
  :root {
    --${P}-shadow-focus: 0 0 0 3px CanvasText;
  }
}
`;

writeFileSync(join(ROOT, "tokens.css"), css);

// Tailwind v4 CSS-first mapping. Import after tokens.css:  @import "@techdrona/design-tokens/tailwind-v4.css";
const v4Colors = flattenTheme(light)
  .map(({ name }) => `  --color-${name}: var(--${P}-${name});`)
  .join("\n");
const v4 = `${HEADER}
@theme inline {
  --font-display: var(--${P}-font-display);
  --font-sans: var(--${P}-font-sans);
  --font-mono: var(--${P}-font-mono);
${Object.keys(tokens.font.size)
  .map((k) => `  --text-${k}: var(--${P}-text-${k});\n  --text-${k}--line-height: var(--${P}-text-${k}-lh);\n  --text-${k}--letter-spacing: var(--${P}-text-${k}-ls);`)
  .join("\n")}
${Object.keys(tokens.radius).map((k) => `  --radius-${k}: var(--${P}-radius-${k});`).join("\n")}
${Object.keys(tokens.shadow.light).map((k) => `  --shadow-${k}: var(--${P}-shadow-${k});`).join("\n")}
${Object.keys(tokens.motion.easing).map((k) => `  --ease-${k}: var(--${P}-ease-${k});`).join("\n")}
${Object.entries(tokens.breakpoint).map(([k, v]) => `  --breakpoint-${k}: ${v};`).join("\n")}
${v4Colors}
}
`;
writeFileSync(join(ROOT, "tailwind-v4.css"), v4);
console.log("Wrote tokens.css and tailwind-v4.css");

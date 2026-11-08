/**
 * Tech Drona Tailwind preset (CommonJS).
 *
 * Tailwind v3:  // tailwind.config.js
 *   module.exports = { presets: [require("@techdrona/design-tokens/tailwind-preset")], content: [...] }
 * Tailwind v4:  // globals.css
 *   @import "tailwindcss";
 *   @import "@techdrona/design-tokens/tokens.css";
 *   @config "../tailwind.config.js";            (JS config that uses this preset)  -- OR --
 *   @import "@techdrona/design-tokens/tailwind-v4.css";   (CSS-first @theme mapping, no JS config)
 *
 * Every colour resolves to a CSS variable from tokens.css, so light/dark switching is done by
 * `data-theme` on <html> (or prefers-color-scheme) without `dark:` variants.
 * Opacity modifiers work (`bg-brand/10`) through the `-rgb` channel variables.
 */
const tokens = require("./tokens.json");

const P = tokens.meta.prefix;

function isOpaqueHexRef(themeValue) {
  // overlay values are 8-digit hex (already translucent) => no alpha channel variable
  return !(typeof themeValue === "string" && /^#[0-9a-f]{8}$/i.test(themeValue));
}

/** Build a nested Tailwind colour object from the light semantic theme structure. */
function buildColors(node, path = []) {
  const out = {};
  for (const [key, value] of Object.entries(node)) {
    const nextPath = [...path, key];
    if (value && typeof value === "object") {
      out[key] = buildColors(value, nextPath);
    } else {
      const name = nextPath.filter((p) => p !== "DEFAULT").join("-");
      out[key] = isOpaqueHexRef(value)
        ? `rgb(var(--${P}-${name}-rgb) / <alpha-value>)`
        : `var(--${P}-${name})`;
    }
  }
  return out;
}

const semanticColors = buildColors(tokens.semantic.light);

const fontSize = Object.fromEntries(
  Object.keys(tokens.font.size).map((k) => [
    k,
    [`var(--${P}-text-${k})`, { lineHeight: `var(--${P}-text-${k}-lh)`, letterSpacing: `var(--${P}-text-${k}-ls)` }],
  ]),
);

const mapVars = (obj, group) =>
  Object.fromEntries(Object.keys(obj).map((k) => [k, `var(--${P}-${group}-${k})`]));

module.exports = {
  darkMode: ["selector", '[data-theme="dark"]'],
  theme: {
    screens: tokens.breakpoint,
    extend: {
      colors: {
        ...semanticColors,
        // Escape hatch: raw primitives for illustrations/marketing only. Product UI uses semantic names.
        primitive: {
          indigo: tokens.color.indigo,
          teal: tokens.color.teal,
          neutral: tokens.color.neutral,
        },
      },
      fontFamily: {
        display: [`var(--${P}-font-display)`],
        sans: [`var(--${P}-font-sans)`],
        mono: [`var(--${P}-font-mono)`],
      },
      fontSize,
      fontWeight: tokens.font.weight,
      borderRadius: mapVars(tokens.radius, "radius"),
      boxShadow: mapVars(tokens.shadow.light, "shadow"),
      ringColor: { DEFAULT: `rgb(var(--${P}-focus-rgb) / <alpha-value>)` },
      ringOffsetColor: { DEFAULT: `rgb(var(--${P}-focus-offset-rgb) / <alpha-value>)` },
      transitionDuration: mapVars(tokens.motion.duration, "duration"),
      transitionTimingFunction: mapVars(tokens.motion.easing, "ease"),
      zIndex: mapVars(tokens.zIndex, "z"),
      opacity: { disabled: tokens.opacity.disabled, watermark: tokens.opacity.watermark },
      spacing: {
        gutter: `var(--${P}-layout-gutter-mobile)`,
        "gutter-lg": `var(--${P}-layout-gutter-desktop)`,
        topbar: `var(--${P}-layout-topbar)`,
        testbar: `var(--${P}-layout-testbar)`,
        sidebar: `var(--${P}-layout-sidebar)`,
        "sidebar-collapsed": `var(--${P}-layout-sidebar-collapsed)`,
        "palette-panel": `var(--${P}-layout-palette-panel)`,
        drawer: `var(--${P}-layout-drawer)`,
        "target-min": `var(--${P}-layout-target-min)`,
        target: `var(--${P}-layout-target-comfortable)`,
        "target-touch": `var(--${P}-layout-target-touch)`,
      },
      maxWidth: {
        prose: `var(--${P}-layout-container-prose)`,
        content: `var(--${P}-layout-container-content)`,
        wide: `var(--${P}-layout-container-wide)`,
      },
      minHeight: { target: `var(--${P}-layout-target-comfortable)`, "target-touch": `var(--${P}-layout-target-touch)` },
      minWidth: { target: `var(--${P}-layout-target-comfortable)`, "target-touch": `var(--${P}-layout-target-touch)` },
    },
  },
};

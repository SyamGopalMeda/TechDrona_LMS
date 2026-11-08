/**
 * FALLBACK Tailwind preset (apps/web local). Maps Tailwind colour names onto the
 * semantic CSS variables in ./tokens.css, using the same names as
 * packages/design-tokens/tokens.json (`semantic.<theme>.<group>.<name>`).
 *
 * tailwind.config.ts always loads this preset first and, when the UX-owned
 * packages/design-tokens preset exists, layers it on top, so components keep working
 * whichever preset is present. Do not add product colours here: change tokens.json.
 */
const v = (name) => `var(--td-${name})`;

const status = (group) => ({
  fg: v(`${group}-fg`),
  subtle: v(`${group}-subtle`),
  border: v(`${group}-border`),
  solid: v(`${group}-solid`),
  "on-solid": v(`${group}-on-solid`),
});

/** @type {import('tailwindcss').Config} */
module.exports = {
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: v("surface"),
          canvas: v("surface-canvas"),
          raised: v("surface-raised"),
          sunken: v("surface-sunken"),
          subtle: v("surface-subtle"),
          hover: v("surface-hover"),
          selected: v("surface-selected"),
          inverse: v("surface-inverse"),
          brand: v("surface-brand"),
          warm: v("surface-warm"),
        },
        fg: {
          DEFAULT: v("fg"),
          heading: v("fg-heading"),
          secondary: v("fg-secondary"),
          muted: v("fg-muted"),
          disabled: v("fg-disabled"),
          inverse: v("fg-inverse"),
          link: v("fg-link"),
          "link-hover": v("fg-link-hover"),
          "on-brand": v("fg-on-brand"),
          "on-surface-brand": v("fg-on-surface-brand"),
        },
        line: {
          DEFAULT: v("line"),
          subtle: v("line-subtle"),
          strong: v("line-strong"),
          control: v("line-control"),
          inverse: v("line-inverse"),
        },
        brand: {
          DEFAULT: v("brand"),
          hover: v("brand-hover"),
          active: v("brand-active"),
          subtle: v("brand-subtle"),
          "subtle-hover": v("brand-subtle-hover"),
          "on-subtle": v("brand-on-subtle"),
          on: v("brand-on"),
        },
        accent: {
          DEFAULT: v("accent"),
          hover: v("accent-hover"),
          subtle: v("accent-subtle"),
          "on-subtle": v("accent-on-subtle"),
          "on-brand": v("accent-on-brand"),
          on: v("accent-on"),
        },
        focus: { DEFAULT: v("focus"), offset: v("focus-offset") },
        success: status("success"),
        warning: status("warning"),
        danger: status("danger"),
        info: status("info"),
        scrim: v("overlay-scrim"),
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "Noto Sans", "sans-serif"],
        display: ["Plus Jakarta Sans", "Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      boxShadow: {
        xs: v("shadow-xs"),
        sm: v("shadow-sm"),
        md: v("shadow-md"),
        lg: v("shadow-lg"),
        xl: v("shadow-xl"),
        focus: v("shadow-focus"),
      },
      borderRadius: {
        xs: "0.25rem",
        sm: "0.375rem",
        md: "0.5rem",
        lg: "0.75rem",
        xl: "1rem",
        "2xl": "1.25rem",
      },
      spacing: {
        sidebar: "16.5rem",
        topbar: "3.5rem",
        touch: "2.75rem",
      },
      maxWidth: {
        prose: "45rem",
        content: "72rem",
        wide: "90rem",
      },
      zIndex: {
        sticky: "100",
        sidebar: "200",
        topbar: "300",
        banner: "400",
        dropdown: "1000",
        overlay: "1300",
        modal: "1400",
        toast: "1600",
        "skip-link": "9999",
      },
    },
  },
};

// WCAG 2.2 AA contrast check for Tech Drona semantic token pairs (light and dark).
// Text: 4.5:1 (SC 1.4.3). Large text / UI components and graphical objects: 3:1 (SC 1.4.11).
// Usage: node scripts/check-contrast.mjs [--json]
// Exit code 1 if any required pair fails. "info" rows are reported but never fail the build.
import { tokens, flattenTheme, contrast } from "./lib.mjs";

const TEXT = 4.5;
const UI = 3;

/** [foreground, background, minimum, label, required=true] using flattened semantic names. */
const pairs = [
  // Body and secondary text on every surface
  ...["fg", "fg-secondary", "fg-muted"].flatMap((f) =>
    ["surface", "surface-canvas", "surface-raised", "surface-sunken", "surface-subtle", "surface-hover", "surface-selected", "surface-warm"].map((b) => [f, b, TEXT, "text"]),
  ),
  ...["surface", "surface-canvas", "surface-subtle", "surface-warm"].map((b) => ["fg-heading", b, TEXT, "heading text"]),
  ["fg-link", "surface-warm", TEXT, "link on public (warm) canvas"],
  ["brand", "surface-warm", UI, "brand as UI on public canvas"],
  ["focus", "surface-warm", UI, "focus ring on public canvas"],
  ["line-control", "surface-warm", UI, "input border on public canvas"],
  ["brand-on-subtle", "surface-selected", TEXT, "selected nav item text"],
  ["fg-inverse", "surface-inverse", TEXT, "inverse text"],
  ["fg-on-surface-brand", "surface-brand", TEXT, "text on brand band (hero/footer)"],
  ["fg-link", "surface", TEXT, "link"],
  ["fg-link", "surface-canvas", TEXT, "link"],
  ["fg-link", "surface-subtle", TEXT, "link"],
  ["fg-link-hover", "surface", TEXT, "link hover"],
  ["fg-disabled", "surface", 1, "disabled text (exempt, SC 1.4.3)", false],
  // Brand and accent
  ["brand-on", "brand", TEXT, "primary button"],
  ["brand-on", "brand-hover", TEXT, "primary button hover"],
  ["brand-on", "brand-active", TEXT, "primary button active"],
  ["brand-on-subtle", "brand-subtle", TEXT, "subtle brand (selected nav, chip)"],
  ["brand-on-subtle", "brand-subtle-hover", TEXT, "subtle brand hover"],
  ["brand", "surface", UI, "brand as UI (icon, outline button border)"],
  ["accent-on", "accent", TEXT, "accent button"],
  ["accent-on-subtle", "accent-subtle", TEXT, "accent chip"],
  ["accent-on-brand", "surface-brand", TEXT, "footer column heading on navy band"],
  ["accent", "surface-canvas", TEXT, "eyebrow text on canvas"],
  // Controls, borders and focus
  ["line-control", "surface", UI, "input/checkbox border (SC 1.4.11)"],
  ["line-control", "surface-canvas", UI, "input border on canvas"],
  ["line-control", "surface-raised", UI, "input border on raised"],
  ["focus", "surface", UI, "focus ring (SC 2.4.13 guidance / 1.4.11)"],
  ["focus", "surface-canvas", UI, "focus ring on canvas"],
  ["focus", "surface-subtle", UI, "focus ring on subtle"],
  ["focus", "brand", 1, "focus ring adjacent to primary button (offset ring separates)", false],
  ["line", "surface", 1, "decorative divider (exempt)", false],
  // Status
  ...["success", "warning", "danger", "info"].flatMap((s) => [
    [`${s}-fg`, `${s}-subtle`, TEXT, `${s} alert text`],
    [`${s}-fg`, "surface", TEXT, `${s} inline text`],
    [`${s}-fg`, "surface-canvas", TEXT, `${s} inline text on canvas`],
    [`${s}-on-solid`, `${s}-solid`, TEXT, `${s} solid badge/button`],
    [`${s}-border`, "surface", UI, `${s} border/icon`],
  ]),
  // Risk levels L0-L4
  ...["l0", "l1", "l2", "l3", "l4"].flatMap((l) => [
    [`risk-${l}-fg`, `risk-${l}-subtle`, TEXT, `risk ${l.toUpperCase()} banner text`],
    [`risk-${l}-fg`, "surface", TEXT, `risk ${l.toUpperCase()} inline label`],
    [`risk-${l}-on-solid`, `risk-${l}-solid`, TEXT, `risk ${l.toUpperCase()} solid badge`],
    [`risk-${l}-border`, "surface", UI, `risk ${l.toUpperCase()} pip/border`],
  ]),
  // Question palette (TST-002)
  ["qstate-not-visited-fg", "qstate-not-visited", TEXT, "palette: not visited"],
  ["qstate-not-visited-border", "surface", UI, "palette: not visited border"],
  ["qstate-not-answered-fg", "qstate-not-answered", TEXT, "palette: not answered"],
  ["qstate-not-answered-border", "surface", UI, "palette: not answered border"],
  ["qstate-answered-fg", "qstate-answered", TEXT, "palette: answered"],
  ["qstate-marked-fg", "qstate-marked", TEXT, "palette: marked for review"],
  ["qstate-answered", "surface", UI, "palette: answered tile vs surface"],
  ["qstate-marked", "surface", UI, "palette: marked tile vs surface"],
  ["qstate-current-ring", "surface", UI, "palette: current question ring"],
  // Timer
  ["timer", "surface", TEXT, "timer"],
  ["timer-warn", "surface", TEXT, "timer 10/5 min"],
  ["timer-critical", "surface", TEXT, "timer 1 min"],
  // Charts (non-text graphics)
  ["chart-label", "surface", TEXT, "chart axis labels"],
  ...[1, 2, 3, 4, 5, 6, 7, 8].map((i) => [`chart-${i}`, "surface", UI, `chart series ${i} (relief: direct labels/table if < 3:1)`, false]),
  ["chart-band-1", "surface", 2, "readiness band 1 (ordinal light end >= 2:1)"],
];

const json = process.argv.includes("--json");
let failures = 0;
const report = [];

for (const mode of ["light", "dark"]) {
  const map = Object.fromEntries(flattenTheme(tokens.semantic[mode]).map((t) => [t.name, t.value]));
  for (const [fg, bg, min, label, required = true] of pairs) {
    if (!(fg in map) || !(bg in map)) throw new Error(`Unknown token in pair: ${fg} / ${bg}`);
    const ratio = contrast(map[fg], map[bg]);
    const pass = ratio + 1e-9 >= min;
    if (!pass && required) failures++;
    report.push({ mode, required, fg, bg, fgHex: map[fg], bgHex: map[bg], ratio: Number(ratio.toFixed(2)), min, label, result: pass ? "PASS" : required ? "FAIL" : "INFO" });
  }
}

if (json) console.log(JSON.stringify(report, null, 2));
else {
  for (const mode of ["light", "dark"]) {
    console.log(`\n== ${mode.toUpperCase()} ==`);
    for (const r of report.filter((x) => x.mode === mode)) {
      console.log(
        `${r.result.padEnd(4)} ${String(r.ratio.toFixed(2)).padStart(6)}:1 (min ${r.min})  ${r.fg} ${r.fgHex} on ${r.bg} ${r.bgHex}  — ${r.label}`,
      );
    }
  }
  const req = report.filter((r) => r.required);
  console.log(`\n${req.length - failures}/${req.length} required pairs pass WCAG 2.2 AA; ${failures} fail; ${report.length - req.length} informational.`);
}
process.exit(failures ? 1 : 0);

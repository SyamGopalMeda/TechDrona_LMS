// Prints a compact per-page/per-viewport digest of results/*.json (for writing the report).
const fs = require("node:fs");
const path = require("node:path");
const dir = path.join(__dirname, "results");
const files = process.argv[2] ? [process.argv[2] + ".json"] : fs.readdirSync(dir).filter((f) => f.endsWith(".json"));
const axeAgg = {};
for (const f of files) {
  const rows = JSON.parse(fs.readFileSync(path.join(dir, f), "utf8"));
  for (const r of rows) {
    if (r.fatal || r.error) { console.log("!!", f, r.key, r.viewport, r.fatal || r.error); continue; }
    const d = r.dom, t = r.tab;
    console.log(`\n## ${r.key} [${r.viewport}] ${r.url} -> ${r.finalUrl} | title="${d.title}" lang=${d.lang}`);
    for (const v of r.axe || []) {
      console.log(`  axe ${v.impact} ${v.id} x${v.nodes} ${v.tags.join(",")} :: ${v.targets.slice(0, 3).join(" | ")}${v.detail ? " :: " + v.detail.filter(Boolean).slice(0, 3).join("; ") : ""}`);
      const k = v.id; axeAgg[k] = axeAgg[k] || { impact: v.impact, pages: new Set(), help: v.help }; axeAgg[k].pages.add(r.key);
    }
    console.log(`  hOverflow=${d.hOverflow} ${d.overflowEls.slice(0, 3).join(" ; ")}`);
    console.log(`  landmarks=${JSON.stringify(d.landmarks)} h1=${d.h1count} skips=${d.headingSkips.join(";")} skipLink=${d.skipLink}`);
    console.log(`  targets<24=${d.targetsUnder24} ${d.targetsUnder24Samples.slice(0, 4).join(" ; ")}`);
    console.log(`  targets<44=${d.targetsUnder44}/${d.interactive} ${d.targetsUnder44Samples.slice(0, 3).join(" ; ")}`);
    if (d.fixed.length) console.log(`  fixed: ${d.fixed.join(" ; ")}`);
    if (d.clippedText.length) console.log(`  clipped: ${d.clippedText.slice(0, 4).join(" ; ")}`);
    if (d.imgNoAlt.length || d.fieldsNoName.length) console.log(`  imgNoAlt=${d.imgNoAlt.join(";")} fieldsNoName=${d.fieldsNoName.join(";")}`);
    if (t && !t.error) console.log(`  tab: noRing=${t.noRingCount} ${t.noRing.slice(0, 4).join(" ; ")} | offscreen=${t.offscreen} covered=${t.covered.join(" ; ")} zero=${t.zeroSize.join(";")} trap=${t.possibleTrap} first=${t.first5.slice(0, 3).join(" > ")}`);
    else if (t) console.log("  tab error", t.error);
    if (r.menu) console.log(`  menu: ${JSON.stringify(r.menu)}`);
    if (r.form) console.log(`  form: ${JSON.stringify(r.form)}`);
  }
}
console.log("\n# axe aggregate");
for (const [k, v] of Object.entries(axeAgg)) console.log(`${v.impact} ${k} (${v.pages.size} pages): ${[...v.pages].join(",")} — ${v.help}`);

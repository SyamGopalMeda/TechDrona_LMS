import AxeBuilder from "@axe-core/playwright";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { expect, type Page, type TestInfo } from "@playwright/test";

const OUT = path.join(__dirname, "..", "..", "test-results", "a11y");
const BLOCKING = new Set(["serious", "critical"]);

/** axe WCAG 2.1 A/AA scan; writes all violations, fails on serious/critical. */
export async function audit(page: Page, name: string, info: TestInfo) {
  // Let client data load settle before scanning.
  await page.waitForLoadState("networkidle").catch(() => undefined);
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    // Monaco renders its own (vendor) widget tree; audited separately by the vendor.
    .exclude(".monaco-editor")
    .analyze();
  const summary = results.violations.map((v) => ({
    id: v.id,
    impact: v.impact,
    help: v.help,
    nodes: v.nodes.length,
    targets: v.nodes.slice(0, 5).map((n) => n.target.join(" ")),
  }));
  mkdirSync(OUT, { recursive: true });
  writeFileSync(path.join(OUT, `${name}.json`), JSON.stringify({ url: page.url(), violations: summary }, null, 2));
  await info.attach(`axe-${name}`, { body: JSON.stringify(summary, null, 2), contentType: "application/json" });
  const blocking = summary.filter((v) => v.impact && BLOCKING.has(v.impact));
  expect(blocking, `serious/critical axe violations on ${name} (${page.url()})`).toEqual([]);
}


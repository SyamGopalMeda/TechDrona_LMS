import fs from "node:fs";
import { test, expect } from "@playwright/test";
import { HOME, roles, stateFile } from "../lib/roles";
import { layoutIssues, watch } from "../lib/probe";

/** Pipeline check: every QA role opens its home portal on the live site. */
for (const r of roles()) {
  test(`smoke ${r} home`, async ({ browser }, info) => {
    const ctx = await browser.newContext({ ...info.project.use, storageState: stateFile(r) });
    const page = await ctx.newPage();
    const w = watch(page);
    await page.goto(HOME[r]);
    await page.waitForLoadState("networkidle");
    const finding = { role: r, project: info.project.name, url: new URL(page.url()).pathname, title: await page.title(), layout: await layoutIssues(page), api: w.api, errors: w.errors };
    fs.mkdirSync("out/findings", { recursive: true });
    fs.writeFileSync(`out/findings/smoke-${r}-${info.project.name}.json`, JSON.stringify(finding, null, 1));
    await page.screenshot({ path: info.outputPath("home.png"), fullPage: true });
    expect(finding.url.startsWith(HOME[r])).toBeTruthy();
    await ctx.close();
  });
}

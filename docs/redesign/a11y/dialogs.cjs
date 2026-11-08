/*
 * Dialog / disclosure keyboard checks (read-only: dialogs are opened and dismissed, never submitted).
 *   node docs/redesign/a11y/dialogs.cjs
 * Writes docs/redesign/a11y/results/dialogs.json
 */
const fs = require("node:fs");
const path = require("node:path");
const { signIn, BASE, VIEWPORTS, chromium, SHOTS } = require("./audit.cjs");

const CASES = [
  // role, url, opener button name, viewport
  ["content", "/studio/question-banks", /^New bank$/, "desktop"],
  ["content", "/studio/question-banks", /^New bank$/, "mobile"],
  ["content", "/studio/tests", /New test/i, "desktop"],
  ["trainer", "/trainer/assignments", /New assignment/i, "desktop"],
];

async function probe(page, opener) {
  const btn = page.getByRole("button", { name: opener }).first();
  if (!(await btn.count())) return { found: false };
  await btn.focus();
  await page.keyboard.press("Enter");
  await page.waitForTimeout(600);
  const state = () =>
    page.evaluate(() => {
      const d = [...document.querySelectorAll("dialog[open],[role=dialog],[aria-modal=true]")].find((x) => x.getBoundingClientRect().height > 0);
      const a = document.activeElement;
      return {
        open: !!d,
        kind: d ? `${d.tagName.toLowerCase()} modal=${d.matches(":modal")} labelledby=${!!d.getAttribute("aria-labelledby")}` : null,
        focusInside: !!(d && d.contains(a)),
        active: a ? `${a.tagName.toLowerCase()} ${(a.getAttribute("aria-label") || a.textContent || a.name || "").trim().slice(0, 30)}` : null,
        fits: d ? d.getBoundingClientRect().height <= innerHeight && d.scrollHeight <= d.clientHeight + 2 ? "fits" : `overflows (h=${Math.round(d.getBoundingClientRect().height)} vh=${innerHeight}, scrollable=${d.scrollHeight > d.clientHeight})` : null,
      };
    });
  const r = { found: true, afterOpen: await state() };
  await page.screenshot({ path: path.join(SHOTS, `dialog-${r.afterOpen.open ? "open" : "none"}-${Date.now() % 100000}.png`), scale: "css" }).catch(() => {});
  let left = false;
  for (let i = 0; i < 30; i++) {
    await page.keyboard.press("Tab");
    const s = await state();
    if (!s.focusInside) { left = s.active; break; }
  }
  r.tabLeavesDialog = left;
  await page.keyboard.press("Escape");
  await page.waitForTimeout(500);
  const after = await state();
  r.closedByEscape = !after.open;
  r.focusReturnedToOpener = await btn.evaluate((b) => document.activeElement === b).catch(() => false);
  r.activeAfterClose = after.active;
  return r;
}

(async () => {
  const browser = await chromium.launch();
  const out = [];
  const byRole = {};
  for (const c of CASES) (byRole[c[0]] = byRole[c[0]] || []).push(c);
  for (const [role, cases] of Object.entries(byRole)) {
    const ctx = await browser.newContext({ viewport: VIEWPORTS.desktop });
    const page = await ctx.newPage();
    try {
      await signIn(page, role);
      for (const [, url, opener, vp] of cases) {
        await page.setViewportSize(VIEWPORTS[vp]);
        await page.goto(BASE + url);
        await page.waitForLoadState("networkidle", { timeout: 10000 }).catch(() => {});
        const r = await probe(page, opener).catch((e) => ({ error: String(e).slice(0, 200) }));
        out.push({ role, url, opener: String(opener), vp, ...r });
        console.log(role, url, vp, JSON.stringify(r));
      }
    } catch (e) { out.push({ role, fatal: String(e).slice(0, 300) }); console.log("FATAL", role, e.message); }
    await ctx.close();
  }
  fs.writeFileSync(path.join(__dirname, "results", "dialogs.json"), JSON.stringify(out, null, 1));
  await browser.close();
})();

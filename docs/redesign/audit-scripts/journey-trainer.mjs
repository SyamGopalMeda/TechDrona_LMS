// Journey C (trainer): create a structured assignment for the AUDIT batch, add a written question,
// save, reload (persistence), allocate to the batch with the Evaluator; create + publish + allocate a
// learning path; create a poll (Engage) for the batch and start a run; assign an existing test.
// Synthetic "AUDIT-" data only. Output: $TEMP/td-page-audit/journey-trainer.json (+ ids for later journeys).
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { chromium, roleContext, watch, BASE, SHOTS, STATE, sleep } from "./lib.mjs";

const batch = JSON.parse(readFileSync(path.join(STATE, "audit-batch.json"), "utf8"));
const n = `${Date.now()}`.slice(-6);
const out = { batch, ids: {}, steps: [] };
const browser = await chromium.launch();
const ctx = await roleContext(browser, "trainer");
const bucket = watch(ctx);
const page = await ctx.newPage();
page.setDefaultTimeout(20_000);
const SKIP = (process.env.AUDIT_SKIP ?? "").split(",").filter(Boolean); // e.g. AUDIT_SKIP=path:
async function step(name, fn) {
  if (SKIP.some((p) => name.startsWith(p))) return;
  bucket.reset();
  const t0 = Date.now();
  let ok = true;
  let note = "";
  try {
    note = (await fn()) ?? "";
  } catch (e) {
    ok = false;
    note = String(e).split("\n")[0].slice(0, 300);
  }
  const shot = `journey-trainer__${out.steps.length + 1}-${name.replace(/[^a-z0-9]+/gi, "_").slice(0, 40)}.png`;
  await page.screenshot({ path: path.join(SHOTS, shot) }).catch(() => undefined);
  const s = { step: name, ok, note: String(note).slice(0, 500), url: page.url().replace(BASE, ""), ms: Date.now() - t0, http: [...new Set(bucket.http)], console: [...new Set(bucket.console)].slice(0, 4), shot: `docs/redesign/shots/audit/${shot}` };
  out.steps.push(s);
  console.log(`${ok ? "OK  " : "FAIL"} ${name} -> ${s.url} :: ${s.note} ${s.http.length ? `http=${s.http.join(";")}` : ""}`);
  return ok;
}
const mainText = async () => (await page.locator("main").innerText().catch(() => "")).replace(/\s+/g, " ");
const idle = async () => { await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => undefined); await sleep(800); };
const dueLocal = () => { const d = new Date(Date.now() + 7 * 864e5); d.setMinutes(0, 0, 0); const p = (x) => String(x).padStart(2, "0"); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:00`; };

/* ---------- assignment ---------- */
const aTitle = `AUDIT-Assignment ${n}`;
await step("trainer sees the new AUDIT batch on dashboard", async () => {
  await page.goto(`${BASE}/trainer`);
  await idle();
  const t = await mainText();
  return t.includes(batch.name) ? "batch listed" : `batch NOT listed :: ${t.slice(0, 200)}`;
});
await step("assignment: New assignment dialog -> Create", async () => {
  await page.goto(`${BASE}/trainer/assignments`);
  await idle();
  await page.getByRole("button", { name: "New assignment" }).first().click();
  const dlg = page.getByRole("dialog");
  await dlg.getByLabel("Assignment name").fill(aTitle);
  await dlg.getByLabel("Total marks").fill("10");
  const owner = dlg.getByLabel("Belongs to");
  if (await owner.count()) {
    const opts = await owner.locator("option").allInnerTexts();
    const pick = opts.find((o) => o.includes(batch.name));
    if (!pick) throw new Error(`AUDIT batch not in "Belongs to": ${opts.join(" | ")}`);
    await owner.selectOption({ label: pick });
  }
  await dlg.getByRole("button", { name: "Create" }).click();
  await page.waitForURL(/\/trainer\/assignments\/[^/]+$/, { timeout: 30_000 });
  out.ids.assignmentUrl = page.url().replace(BASE, "");
  await idle();
  return out.ids.assignmentUrl;
});
await step("assignment: add section + written question + save", async () => {
  await page.getByRole("button", { name: "Add section" }).click();
  await page.getByRole("button", { name: "Add written question" }).first().click();
  await page.getByLabel("Question type").selectOption({ index: 0 });
  const types = await page.getByLabel("Question type").locator("option").allInnerTexts();
  await page.getByLabel("Marks", { exact: true }).fill("10");
  await page.getByRole("textbox", { name: /^Question/ }).last().fill("AUDIT: Explain what a database index is in two sentences.");
  await page.getByRole("button", { name: "Add question" }).click();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await sleep(2500);
  return `types=[${types.join("|")}]`;
});
await step("assignment: reload keeps the question", async () => {
  await page.reload();
  await idle();
  await sleep(1500);
  const t = await mainText();
  if (!t.includes("database index")) throw new Error(`question lost after reload :: ${t.slice(0, 200)}`);
  return t.slice(0, 200);
});
await step("assignment: allocate to AUDIT batch (manual grading + evaluator)", async () => {
  await page.getByRole("button", { name: "Allocate", exact: true }).click();
  const dlg = page.getByRole("dialog");
  const sel = dlg.getByLabel("Batch");
  await sleep(1500);
  const opts = await sel.locator("option").allInnerTexts();
  const pick = opts.find((o) => o.includes(batch.name));
  if (!pick) throw new Error(`AUDIT batch not offered: ${opts.join(" | ")}`);
  await sel.selectOption({ label: pick });
  await dlg.getByLabel("Must submit by").fill(dueLocal());
  const engines = dlg.locator("fieldset").filter({ hasText: "Grading engine" }).locator("select");
  for (let i = 0; i < (await engines.count()); i += 1) await engines.nth(i).selectOption({ label: "Manual" });
  await sleep(2000);
  const ev = dlg.getByRole("checkbox").first();
  const evLabel = await dlg.locator('ul[aria-label="Staff"]').innerText().catch(() => "no staff list");
  if (await ev.count()) await ev.check();
  await dlg.getByRole("button", { name: "Allocate to batch" }).click();
  await sleep(3000);
  const still = await dlg.isVisible().catch(() => false);
  const err = still ? (await dlg.innerText()).replace(/\s+/g, " ").slice(0, 300) : "";
  if (still) throw new Error(`dialog still open: ${err}`);
  return `staff=[${evLabel.replace(/\s+/g, " ").slice(0, 120)}]`;
});

/* ---------- learning path ---------- */
const pTitle = `AUDIT-Path ${n}`;
await step("path: + New path -> Create", async () => {
  if (process.env.AUDIT_PATH_URL) { await page.goto(`${BASE}${process.env.AUDIT_PATH_URL}`); await idle(); out.ids.pathUrl = process.env.AUDIT_PATH_URL; return "reused " + out.ids.pathUrl; }
  await page.goto(`${BASE}/trainer/paths`);
  await idle();
  await page.getByRole("button", { name: "+ New path" }).click();
  const dlg = page.getByRole("dialog");
  await dlg.getByLabel("Title").fill(pTitle);
  await dlg.getByRole("button", { name: "Create" }).click();
  await page.waitForURL(/\/trainer\/paths\/[^/]+$/, { timeout: 30_000 });
  out.ids.pathUrl = page.url().replace(BASE, "");
  await idle();
  return out.ids.pathUrl;
});
await step("path: add Reading step, save, publish", async () => {
  await page.getByRole("group", { name: "Add a step" }).getByRole("button", { name: "+ Reading" }).click();
  const titles = page.getByLabel("Title");
  await titles.last().fill("AUDIT reading step");
  await page.getByLabel("Page URL (https)").fill("https://example.com/audit-reading");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await sleep(2500);
  await page.getByRole("button", { name: "Publish", exact: true }).click();
  await sleep(3000);
  const t = await mainText();
  return t.match(/Published v\d+|Draft/)?.[0] ?? t.slice(0, 200);
});
await step("path: allocate to AUDIT batch", async () => {
  await page.getByRole("button", { name: "Allocate", exact: true }).click();
  const dlg = page.getByRole("dialog");
  await sleep(1500);
  const sel = dlg.locator("select").first();
  const opts = await sel.locator("option").allInnerTexts();
  const pick = opts.find((o) => o.includes(batch.name));
  if (!pick) throw new Error(`AUDIT batch not offered: ${opts.join(" | ")}`);
  await sel.selectOption({ label: pick });
  await dlg.getByRole("button", { name: "Allocate", exact: true }).click();
  await sleep(3000);
  if (await dlg.isVisible().catch(() => false)) throw new Error(`dialog still open: ${(await dlg.innerText()).replace(/\s+/g, " ").slice(0, 300)}`);
  await page.reload();
  await idle();
  return (await mainText()).match(/Allocated to.{0,200}/)?.[0] ?? "";
});

/* ---------- engage poll ---------- */
await step("engage: New -> Poll -> save", async () => {
  await page.goto(`${BASE}/trainer/engage`);
  await idle();
  await page.getByRole("button", { name: /^New/ }).click();
  await page.getByRole("menuitem", { name: "Poll" }).click();
  await page.waitForURL(/engage\/new/);
  await idle();
  await page.getByLabel("Title").fill(`AUDIT-Poll ${n}`);
  const sel = page.locator("main select").filter({ has: page.locator("option", { hasText: batch.name }) }).first();
  const pick = (await sel.count()) ? batch.name : null;
  if (pick) await sel.selectOption({ label: (await sel.locator("option").allInnerTexts()).find((o) => o.includes(batch.name)) });
  await page.getByRole("textbox", { name: /^Question 1/ }).first().fill("AUDIT: Which topic should we revise?");
  const o1 = page.getByPlaceholder("Option 1").first();
  const o2 = page.getByPlaceholder("Option 2").first();
  if (await o1.count()) await o1.fill("Arrays");
  if (await o2.count()) await o2.fill("Graphs");
  await page.getByRole("button", { name: /^Save poll/ }).click();
  await page.waitForURL((u) => !/\/new/.test(u.pathname), { timeout: 30_000 });
  await idle();
  out.ids.activityUrl = page.url().replace(BASE, "");
  const btns = (await page.locator("main button").allInnerTexts()).map((b) => b.trim()).filter(Boolean);
  return `batchOffered=${!!pick} -> ${out.ids.activityUrl} buttons=[${btns.slice(0, 10).join("|")}]`;
});
await step("engage: start a run", async () => {
  const start = page.getByRole("button", { name: /^(Start|Go live|Launch)/ }).first();
  await start.click();
  await sleep(4000);
  await idle();
  const t = await mainText();
  out.ids.joinCode = /\b([A-Z0-9]{5,8})\b/.exec(t.match(/code.{0,40}/i)?.[0] ?? "")?.[1] ?? null;
  out.ids.runUrl = page.url().replace(BASE, "");
  return `code=${out.ids.joinCode} :: ${t.slice(0, 250)}`;
});

/* ---------- assign a test ---------- */
await step("tests: assign first test to AUDIT batch", async () => {
  await page.goto(`${BASE}/trainer/tests`);
  await idle();
  const btn = page.getByRole("button", { name: /^Assign / }).first();
  const label = await btn.getAttribute("aria-label");
  await btn.click();
  const dlg = page.getByRole("dialog");
  const sel = dlg.getByLabel("Batch");
  await sleep(1500);
  const opts = await sel.locator("option").allInnerTexts();
  const pick = opts.find((o) => o.includes(batch.name));
  if (!pick) throw new Error(`AUDIT batch not offered: ${opts.join(" | ")}`);
  await sel.selectOption({ label: pick });
  const loc = (d) => { const p = (x) => String(x).padStart(2, "0"); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`; };
  await dlg.getByLabel("Opens").fill(loc(new Date(Date.now() - 5 * 60e3)));
  await dlg.getByLabel("Closes").fill(loc(new Date(Date.now() + 7 * 864e5)));
  const dtext = (await dlg.innerText()).replace(/\s+/g, " ").slice(0, 300);
  await dlg.getByRole("button", { name: "Assign test" }).click();
  await sleep(3000);
  if (await dlg.isVisible().catch(() => false)) throw new Error(`dialog still open: ${(await dlg.innerText()).replace(/\s+/g, " ").slice(0, 300)}`);
  return `${label} :: ${dtext}`;
});

writeFileSync(path.join(STATE, "journey-trainer.json"), JSON.stringify(out, null, 1));
await browser.close();

// Journey E (content manager): question bank "Bulk import via prompt" -> validate (bad JSON, then good)
// -> import into a NEW bank named "AUDIT-Bank ..." -> reload bank detail shows the drafts; plus the
// legacy /studio/questions/import page. Synthetic data only.
import { writeFileSync } from "node:fs";
import path from "node:path";
import { chromium, roleContext, watch, BASE, SHOTS, STATE, sleep } from "./lib.mjs";

const n = `${Date.now()}`.slice(-6);
const steps = [];
const browser = await chromium.launch();
const ctx = await roleContext(browser, "content");
const bucket = watch(ctx);
const page = await ctx.newPage();
page.setDefaultTimeout(20_000);
async function step(name, fn) {
  bucket.reset();
  const t0 = Date.now();
  let ok = true;
  let note = "";
  try { note = (await fn()) ?? ""; } catch (e) { ok = false; note = String(e).split("\n")[0].slice(0, 300); }
  const shot = `journey-content__${steps.length + 1}-${name.replace(/[^a-z0-9]+/gi, "_").slice(0, 40)}.png`;
  await page.screenshot({ path: path.join(SHOTS, shot) }).catch(() => undefined);
  const s = { step: name, ok, note: String(note).slice(0, 500), url: page.url().replace(BASE, ""), ms: Date.now() - t0, http: [...new Set(bucket.http)], console: [...new Set(bucket.console)].slice(0, 4), shot: `docs/redesign/shots/audit/${shot}` };
  steps.push(s);
  console.log(`${ok ? "OK  " : "FAIL"} ${name} -> ${s.url} :: ${s.note} ${s.http.length ? `http=${s.http.join(";")}` : ""}`);
}
const idle = async () => { await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => undefined); await sleep(800); };
const bank = `AUDIT-Bank ${n}`;
const good = JSON.stringify([
  { question: `AUDIT ${n}: Which data structure is FIFO?`, options: [{ text: "Queue", correct: true }, { text: "Stack", correct: false }], explanation: "A queue removes the oldest item first.", difficulty: "easy", tags: ["audit", "queues"] },
  { question: `AUDIT ${n}: Big-O of binary search?`, options: [{ text: "O(log n)", correct: true }, { text: "O(n)", correct: false }], explanation: "It halves the range each step.", difficulty: "easy", tags: ["audit", "search"] },
]);

await step("legacy /studio/questions/import page", async () => {
  await page.goto(`${BASE}/studio/questions/import`);
  await idle();
  return (await page.locator("main").innerText()).replace(/\s+/g, " ").slice(0, 200);
});
await step("open Bulk import dialog", async () => {
  await page.goto(`${BASE}/studio/question-banks`);
  await idle();
  await page.getByRole("button", { name: "Bulk import" }).click();
  await page.getByRole("dialog").waitFor();
  await sleep(1500);
  return (await page.getByRole("dialog").innerText()).replace(/\s+/g, " ").slice(0, 300);
});
const dlg = page.getByRole("dialog");
await step("validate malformed JSON shows problems", async () => {
  const ta = dlg.locator("textarea").last();
  await ta.fill('[{"question": "broken"');
  await dlg.getByRole("button", { name: "Validate" }).click();
  await sleep(2500);
  const importDisabled = await dlg.getByRole("button", { name: "Import", exact: true }).isDisabled();
  return `import-disabled=${importDisabled} :: ${(await dlg.innerText()).replace(/\s+/g, " ").match(/problem.{0,200}/i)?.[0] ?? "(no problem text)"}`;
});
await step("validate good JSON then Import into new AUDIT bank", async () => {
  const name = dlg.getByLabel(/name/i).last();
  if (await name.count()) await name.fill(bank).catch(() => undefined);
  await dlg.locator("textarea").last().fill(good);
  await dlg.getByRole("button", { name: "Validate" }).click();
  await sleep(2500);
  const imp = dlg.getByRole("button", { name: "Import", exact: true });
  if (await imp.isDisabled()) throw new Error(`still disabled :: ${(await dlg.innerText()).replace(/\s+/g, " ").slice(-300)}`);
  await imp.dblclick();
  await sleep(4000);
  const toast = (await page.locator('[role="status"]').allInnerTexts()).join(" | ").replace(/\s+/g, " ").slice(0, 200);
  return `toast=${toast} url=${page.url().replace(BASE, "")}`;
});
await step("reload: bank exists with 2 drafts (not 4)", async () => {
  await page.goto(`${BASE}/studio/question-banks`);
  await idle();
  const t = (await page.locator("main").innerText()).replace(/\s+/g, " ");
  const link = page.getByRole("link", { name: new RegExp(bank) }).first();
  if (!(await link.count())) {
    const m = t.match(new RegExp(`Bulk import.{0,0}|AUDIT[^|]{0,80}${n}.{0,80}`));
    return `bank link "${bank}" not found; list mentions: ${m?.[0] ?? t.slice(0, 300)}`;
  }
  await link.click();
  await idle();
  const d = (await page.locator("main").innerText()).replace(/\s+/g, " ");
  const count = (d.match(new RegExp(`AUDIT ${n}:`, "g")) ?? []).length;
  return `questions with marker=${count} :: ${d.slice(0, 250)}`;
});
writeFileSync(path.join(STATE, "journey-content.json"), JSON.stringify({ bank, steps }, null, 1));
await browser.close();

// Journey B/D: the AUDIT student (in the AUDIT batch) does the trainer's assignment, opens the path,
// joins the live poll, and opens the assigned test; then the evaluator grades + publishes and the
// student sees the result. Usage: node journey-participate.mjs [student|evaluator|result|all]
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import path from "node:path";
import { chromium, roleContext, watch, BASE, SHOTS, STATE, sleep } from "./lib.mjs";

const phase = process.argv[2] ?? "all";
const who = JSON.parse(readFileSync(path.join(STATE, "audit-student.cred.json"), "utf8"));
const tr = existsSync(path.join(STATE, "journey-trainer.json")) ? JSON.parse(readFileSync(path.join(STATE, "journey-trainer.json"), "utf8")) : { ids: {} };
const aTitle = tr.steps?.find((s) => /assignment: New/.test(s.step))?.ok ? null : null;
const steps = [];
const browser = await chromium.launch();
let page;
let bucket;
async function step(name, fn) {
  bucket.reset();
  const t0 = Date.now();
  let ok = true;
  let note = "";
  try { note = (await fn()) ?? ""; } catch (e) { ok = false; note = String(e).split("\n")[0].slice(0, 300); }
  const shot = `journey-participate__${phase}-${steps.length + 1}-${name.replace(/[^a-z0-9]+/gi, "_").slice(0, 40)}.png`;
  await page.screenshot({ path: path.join(SHOTS, shot) }).catch(() => undefined);
  const s = { phase, step: name, ok, note: String(note).slice(0, 500), url: page.url().replace(BASE, ""), ms: Date.now() - t0, http: [...new Set(bucket.http)], console: [...new Set(bucket.console)].slice(0, 4), shot: `docs/redesign/shots/audit/${shot}` };
  steps.push(s);
  console.log(`${ok ? "OK  " : "FAIL"} ${name} -> ${s.url} :: ${s.note} ${s.http.length ? `http=${s.http.join(";")}` : ""}`);
}
const idle = async () => { await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => undefined); await sleep(1200); };
const main = async () => (await page.locator("main").innerText().catch(() => "")).replace(/\s+/g, " ");

if (phase === "student" || phase === "all") {
  const ctx = await roleContext(browser, "auditstudent", who);
  bucket = watch(ctx);
  page = await ctx.newPage();
  page.setDefaultTimeout(20_000);
  await step("student: assignments list shows AUDIT assignment", async () => {
    await page.goto(`${BASE}/app/assignments`);
    await idle();
    const link = page.getByRole("link", { name: /AUDIT-Assignment/ }).first();
    if (!(await link.count())) throw new Error(`not listed :: ${(await main()).slice(0, 300)}`);
    await link.click();
    await page.waitForURL(/\/app\/assignments\/[^/]+$/);
    await idle();
    return (await main()).slice(0, 250);
  });
  await step("student: start, answer, reload keeps draft", async () => {
    const start = page.getByRole("button", { name: "Start", exact: true });
    if (await start.isVisible().catch(() => false)) { await start.click(); await idle(); }
    await page.getByLabel("Your answer").first().fill("AUDIT answer: an index is a lookup structure that speeds reads at the cost of writes.");
    await sleep(3500); // autosave
    await page.reload();
    await idle();
    const v = await page.getByLabel("Your answer").first().inputValue().catch(() => "");
    if (!v.includes("AUDIT answer")) throw new Error(`draft not restored after reload (value="${v.slice(0, 60)}")`);
    return "draft restored after reload";
  });
  await step("student: submit (confirm dialog, double-click)", async () => {
    await page.getByRole("button", { name: "Submit assignment" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Submit", exact: true }).dblclick();
    await sleep(3500);
    await page.reload();
    await idle();
    return (await main()).slice(0, 250);
  });
  await step("student: My paths shows AUDIT path", async () => {
    await page.goto(`${BASE}/app/path/my`);
    await idle();
    const link = page.getByRole("link", { name: /AUDIT-Path/ }).first();
    if (!(await link.count())) throw new Error(`not listed :: ${(await main()).slice(0, 300)}`);
    await link.click();
    await idle();
    const btns = (await page.locator("main button, main a").allInnerTexts()).map((b) => b.trim()).filter(Boolean).slice(0, 12);
    return `${(await main()).slice(0, 200)} :: controls=[${btns.join("|")}]`;
  });
  await step("student: open + complete path step", async () => {
    const open = page.getByRole("button", { name: /open|start|mark|complete|done/i }).first();
    const label = await open.innerText();
    await open.click();
    await sleep(3000);
    await page.reload();
    await idle();
    return `clicked "${label}" -> ${(await main()).slice(0, 250)}`;
  });
  await step("student: Live activities lists the AUDIT poll / join by code", async () => {
    if (tr.ids?.joinCode) {
      await page.goto(`${BASE}/app/engage/join/${tr.ids.joinCode}`);
    } else {
      await page.goto(`${BASE}/app/engage`);
    }
    await idle();
    const t = await main();
    const join = page.getByRole("link", { name: /AUDIT-Poll|Join/ }).first();
    if (!tr.ids?.joinCode && (await join.count())) { await join.click(); await idle(); }
    const opt = page.getByRole("radio", { name: "Arrays" }).or(page.getByRole("button", { name: "Arrays" })).first();
    if (await opt.count()) {
      await opt.click();
      const send = page.getByRole("button", { name: /submit|send|vote/i }).first();
      if (await send.count()) await send.click();
      await sleep(2500);
      return `voted :: ${(await main()).slice(0, 200)}`;
    }
    return `no vote control :: ${t.slice(0, 300)}`;
  });
  await step("student: Tests list shows the assigned test", async () => {
    await page.goto(`${BASE}/app/tests`);
    await idle();
    return (await main()).slice(0, 400);
  });
  await ctx.close();
}

if (phase === "evaluator" || phase === "all") {
  const ctx = await roleContext(browser, "evaluator");
  bucket = watch(ctx);
  page = await ctx.newPage();
  page.setDefaultTimeout(20_000);
  await step("evaluator: grading queue shows AUDIT assignment", async () => {
    await page.goto(`${BASE}/evaluator`);
    await idle();
    const link = page.getByRole("link", { name: /AUDIT-Assignment/ }).first();
    if (!(await link.count())) throw new Error(`not in queue :: ${(await main()).slice(0, 300)}`);
    await link.click();
    await idle();
    return (await main()).slice(0, 300);
  });
  await step("evaluator: review + finalize marks", async () => {
    await page.getByRole("button", { name: /^Review / }).first().click();
    const dlg = page.getByRole("dialog");
    await dlg.waitFor();
    await sleep(1500);
    await dlg.getByLabel(/^Marks for Q1/).fill("8");
    await dlg.getByLabel(/^Feedback for Q1/).fill("AUDIT feedback: good, mention B-trees.").catch(() => undefined);
    const reason = dlg.getByLabel(/Reason for changing/);
    if (await reason.count()) await reason.first().fill("AUDIT manual grade");
    await dlg.getByRole("button", { name: /Finalize/ }).click();
    await sleep(3000);
    const open = await dlg.isVisible().catch(() => false);
    if (open) throw new Error(`dialog still open: ${(await dlg.innerText()).replace(/\s+/g, " ").slice(-300)}`);
    await page.reload();
    await idle();
    return (await main()).match(/Finalized|Not finalized/g)?.join(",") ?? (await main()).slice(0, 200);
  });
  await step("evaluator: publish results", async () => {
    await page.getByRole("button", { name: "Publish results" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Publish", exact: true }).click();
    await sleep(3000);
    await page.reload();
    await idle();
    return (await main()).slice(0, 300);
  });
  await ctx.close();
}

if (phase === "result" || phase === "all") {
  const ctx = await roleContext(browser, "auditstudent", who);
  bucket = watch(ctx);
  page = await ctx.newPage();
  await step("student: sees published grade", async () => {
    await page.goto(`${BASE}/app/assignments`);
    await idle();
    await page.getByRole("tab", { name: "Graded" }).click();
    await sleep(1500);
    await page.getByRole("link", { name: /AUDIT-Assignment/ }).first().click();
    await idle();
    const t = await main();
    return t.slice(0, 350);
  });
  await ctx.close();
}
const f = path.join(STATE, "journey-participate.json");
const prev = existsSync(f) ? JSON.parse(readFileSync(f, "utf8")) : [];
writeFileSync(f, JSON.stringify([...prev, ...steps], null, 1));
await browser.close();

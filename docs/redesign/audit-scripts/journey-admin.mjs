// Journeys (admin side): public /enquiries submit -> admin enquiry queue; admin AI settings save
// (+ restore original); admin batch create -> add AUDIT student -> assign trainer + evaluator.
// Synthetic data only ("AUDIT-" prefix). Nothing is deleted. Output: $TEMP/td-page-audit/journey-admin.json
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import path from "node:path";
import { chromium, roleContext, watch, BASE, SHOTS, STATE, bff, sleep } from "./lib.mjs";

const steps = [];
const n = `${Date.now()}`.slice(-7);
const browser = await chromium.launch();
let page;
let bucket;
async function step(name, fn) {
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
  const shot = `journey-admin__${steps.length + 1}-${name.replace(/[^a-z0-9]+/gi, "_").slice(0, 40)}.png`;
  await page.screenshot({ path: path.join(SHOTS, shot) }).catch(() => undefined);
  const s = { step: name, ok, note: String(note).slice(0, 400), url: page.url().replace(BASE, ""), ms: Date.now() - t0, http: [...new Set(bucket.http)], console: [...new Set(bucket.console)].slice(0, 4), shot: `docs/redesign/shots/audit/${shot}` };
  steps.push(s);
  console.log(`${ok ? "OK  " : "FAIL"} ${name} -> ${s.url} :: ${s.note} ${s.http.length ? `http=${s.http.join(";")}` : ""}`);
  return ok;
}
const mainText = async () => (await page.locator("main").innerText().catch(() => "")).replace(/\s+/g, " ");

/* ---------------- public enquiry ---------------- */
const pub = await browser.newContext({ viewport: { width: 1280, height: 800 } });
bucket = watch(pub);
page = await pub.newPage();
const company = `AUDIT-Co ${n}`;
await step("public /enquiries: empty submit shows validation", async () => {
  await page.goto(`${BASE}/enquiries`);
  await page.getByRole("button", { name: "Send enquiry" }).click();
  await sleep(800);
  const errs = await page.locator('[role="alert"], [id$="-error"]').allInnerTexts();
  return `errors=${errs.length}: ${errs.slice(0, 5).join(" | ")}`;
});
await step("public /enquiries: submit (double-click)", async () => {
  await page.getByLabel("Your name").fill(`AUDIT-Enquirer ${n}`);
  await page.getByLabel("Company").fill(company);
  await page.getByLabel("Work email").fill(`audit.enquiry.${n}@example.com`);
  await page.getByLabel(/How can we help/).fill("AUDIT synthetic enquiry for the page-by-page audit. Please ignore.");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Send enquiry" }).dblclick();
  await sleep(4000);
  return (await mainText()).slice(0, 250);
});
await pub.close();

/* ---------------- admin ---------------- */
const ctx = await roleContext(browser, "admin");
bucket = watch(ctx);
page = await ctx.newPage();
await step("admin enquiry queue shows the AUDIT enquiry (once)", async () => {
  await page.goto(`${BASE}/desk/enquiries`);
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await sleep(1000);
  const hits = await page.getByText(company).count();
  if (!hits) throw new Error(`enquiry "${company}" not in queue`);
  return `rows matching=${hits}`;
});
await step("admin opens enquiry + assigns to self", async () => {
  await page.getByRole("link", { name: new RegExp(`AUDIT-Enquirer ${n}|${company}`) }).first().click();
  await page.waitForURL(/\/desk\/enquiries\//);
  await page.waitForLoadState("networkidle").catch(() => undefined);
  const b = page.getByRole("button", { name: /Assign to me/i });
  if (await b.isVisible().catch(() => false)) await b.click();
  await sleep(2000);
  await page.reload();
  await page.waitForLoadState("networkidle").catch(() => undefined);
  return (await mainText()).slice(0, 300);
});

/* AI settings: change one rate limit, save, reload, verify, restore */
let original = null;
await step("admin AI settings: save + reload persists", async () => {
  await page.goto(`${BASE}/admin/ai`);
  await page.waitForLoadState("networkidle").catch(() => undefined);
  const f = page.getByLabel("Tutor messages per minute");
  await f.waitFor({ timeout: 20_000 });
  original = await f.inputValue();
  const next = String(Number(original || "5") + 1);
  await f.fill(next);
  const save = page.locator('form[aria-label="AI settings"] button[type="submit"]');
  const label = await save.innerText();
  await save.click();
  await sleep(2500);
  const toast = (await page.locator('[role="status"], [role="alert"]').allInnerTexts()).join(" | ").slice(0, 200);
  await page.reload();
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await page.getByLabel("Tutor messages per minute").waitFor();
  const after = await page.getByLabel("Tutor messages per minute").inputValue();
  if (after !== next) throw new Error(`not persisted: before=${original} set=${next} after-reload=${after}; toast=${toast}`);
  return `button="${label}" ${original}->${after} toast=${toast}`;
});
await step("admin AI settings: restore original", async () => {
  if (original == null) return "nothing to restore";
  await page.getByLabel("Tutor messages per minute").fill(original);
  await page.locator('form[aria-label="AI settings"] button[type="submit"]').click();
  await sleep(2500);
  await page.reload();
  await page.getByLabel("Tutor messages per minute").waitFor();
  return `restored=${await page.getByLabel("Tutor messages per minute").inputValue()}`;
});

/* Batch create + add student + assign trainer/evaluator */
const code = `AUDIT-${n}`;
let batchUrl = null;
await step("admin create batch", async () => {
  await page.goto(`${BASE}/admin/batches`);
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await page.getByRole("button", { name: "Create batch" }).first().click();
  const dlg = page.getByRole("dialog");
  await dlg.getByLabel("Name").fill(`AUDIT-Batch ${n}`);
  await dlg.getByLabel("Code").fill(code);
  await dlg.getByRole("button", { name: "Create" }).dblclick();
  await sleep(3000);
  await page.reload();
  await page.waitForLoadState("networkidle").catch(() => undefined);
  const count = await page.getByText(code, { exact: true }).count();
  if (!count) throw new Error("new batch not listed after reload");
  return `listed rows with code=${count} (2 would mean double-submit created a duplicate)`;
});
await step("admin create batch with duplicate code (expect field error)", async () => {
  await page.getByRole("button", { name: "Create batch" }).first().click();
  const dlg = page.getByRole("dialog");
  await dlg.getByLabel("Name").fill(`AUDIT-Batch dup ${n}`);
  await dlg.getByLabel("Code").fill(code);
  await dlg.getByRole("button", { name: "Create" }).click();
  await sleep(2500);
  const t = (await dlg.innerText().catch(() => "dialog closed")).replace(/\s+/g, " ").slice(0, 300);
  await page.keyboard.press("Escape");
  return t;
});
await step("admin open batch detail", async () => {
  await page.goto(`${BASE}/admin/batches`);
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await page.getByRole("link", { name: `AUDIT-Batch ${n}` }).first().click();
  await page.waitForURL(/\/admin\/batches\/[^/]+$/);
  await page.waitForLoadState("networkidle").catch(() => undefined);
  batchUrl = page.url().replace(BASE, "");
  return batchUrl;
});
const credFile = path.join(STATE, "audit-student.cred.json");
const student = existsSync(credFile) ? JSON.parse(readFileSync(credFile, "utf8")) : null;
await step("admin add AUDIT student to batch", async () => {
  if (!student) throw new Error("no AUDIT student (run journey-student first)");
  await page.getByRole("button", { name: "Add student" }).click();
  const dlg = page.getByRole("dialog");
  await dlg.getByLabel("Find a person").fill(student.id);
  await dlg.getByRole("button", { name: /^Choose / }).first().click({ timeout: 15_000 });
  await dlg.getByRole("button", { name: "Add to batch" }).click();
  await sleep(2500);
  await page.reload();
  await page.waitForLoadState("networkidle").catch(() => undefined);
  const has = await page.getByText(student.name).count();
  if (!has) throw new Error("student not listed after reload");
  return "member listed after reload";
});
for (const [role, email] of [["Trainer", "trainer@dev.techdrona.local"], ["Evaluator", "evaluator@dev.techdrona.local"]]) {
  await step(`admin assign ${role}`, async () => {
    await page.getByRole("button", { name: "Assign trainer or evaluator" }).click();
    const dlg = page.getByRole("dialog");
    await dlg.getByLabel("Role").selectOption({ label: role });
    await dlg.getByLabel("Find a person").fill(email);
    await dlg.getByRole("button", { name: /^Choose / }).first().click({ timeout: 15_000 });
    await dlg.getByLabel("Reason").fill("AUDIT page-by-page audit");
    await dlg.getByRole("button", { name: "Assign" }).click();
    await sleep(3000);
    const dlgText = (await dlg.innerText().catch(() => "")).replace(/\s+/g, " ").slice(0, 200);
    await page.reload();
    await page.waitForLoadState("networkidle").catch(() => undefined);
    const staff = (await mainText()).match(/Trainer|Evaluator/g)?.length ?? 0;
    return `dialog-after="${dlgText}" role-mentions=${staff}`;
  });
}
await step("batch detail final state", async () => (await mainText()).slice(0, 600));

writeFileSync(path.join(STATE, "journey-admin.json"), JSON.stringify({ code, batchUrl, company, steps }, null, 1));
writeFileSync(path.join(STATE, "audit-batch.json"), JSON.stringify({ code, batchUrl, name: `AUDIT-Batch ${n}` }));
await browser.close();

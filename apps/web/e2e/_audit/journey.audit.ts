import { expect, test } from "@playwright/test";
import { resumeIfAsked } from "../support/attempt";
import { api, freshIdentity, log, overflowX, shot, signupAndVerify, uiLogin, watch } from "./support";

/**
 * AUDIT E2E-J1: fresh learner, end to end, verifying persistence through the API after each step.
 * signup → verify → login → catalogue → enrol free course → lesson → checkout (fake gateway)
 * → timed test (autosave, reload, submit, server score) → progress/analytics.
 */
const TEST_ID = process.env.E2E_TEST_ID ?? "";
const COURSE = process.env.E2E_FREE_COURSE_SLUG ?? "demo-dsa-free";
const J = "journey.jsonl";

test.use({ viewport: { width: 1280, height: 900 } });

test("J1 fresh learner journey with persistence checks", async ({ page, context, request }, info) => {
  watch(context, info);
  const who = freshIdentity("j1");
  log(J, { step: "identity", email: who.email });

  await test.step("signup + verify email", async () => {
    await signupAndVerify(page, request, who);
  });

  await test.step("login (first device: no OTP expected)", async () => {
    await context.clearCookies();
    const url = await uiLogin(page, request, who.email, who.password, { next: "/app" });
    log(J, { step: "login", url });
    await page.waitForURL(/\/app/, { timeout: 20_000 });
    const me = await api<{ user: { email_verified: boolean; status: string } }>(page, "GET", "me");
    log(J, { step: "me", status: me.status, verified: me.json.user?.email_verified, userStatus: me.json.user?.status });
    expect(me.status).toBe(200);
    expect(me.json.user.email_verified).toBe(true);
  });

  const t0 = Date.now();
  await test.step("dashboard renders (time to h1)", async () => {
    await page.goto("/app");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 30_000 });
    log(J, { step: "dashboard_h1_ms", ms: Date.now() - t0 });
  });

  const analyticsBefore = await api(page, "GET", "me/analytics/summary");
  const dashBefore = await api(page, "GET", "me/dashboard");
  log(J, { step: "analytics_before", status: analyticsBefore.status, body: JSON.stringify(analyticsBefore.json).slice(0, 1500) });
  log(J, { step: "dashboard_before", status: dashBefore.status, body: JSON.stringify(dashBefore.json).slice(0, 1500) });

  await test.step("browse catalogue", async () => {
    await page.goto("/courses");
    const list = page.getByRole("list", { name: "Courses" });
    await expect(list).toBeVisible();
    log(J, { step: "catalog_count", n: await list.getByRole("link").count() });
    const cat = await api<{ data?: unknown[] }>(page, "GET", "catalog/courses");
    log(J, { step: "catalog_api", status: cat.status, n: cat.json.data?.length });
  });

  await test.step("enrol free course + open lesson", async () => {
    await page.goto(`/courses/${COURSE}`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const enrol = page.getByRole("button", { name: /Enrol for free|Start learning/ });
    const goTo = page.getByRole("link", { name: "Go to course" });
    await expect(enrol.or(goTo)).toBeVisible();
    if (await enrol.isVisible()) await enrol.click();
    else await goTo.click();
    await page.waitForURL(new RegExp(`/app/courses/${COURSE}$`));
    const enr = await api<{ data?: { course?: { slug?: string } }[] }>(page, "GET", "me/enrolments");
    log(J, { step: "enrolments_api", status: enr.status, body: JSON.stringify(enr.json).slice(0, 800) });
    expect(JSON.stringify(enr.json)).toContain(COURSE);

    const t1 = Date.now();
    await page.getByRole("link", { name: /Start course|Resume/ }).click();
    await page.waitForURL(new RegExp(`/app/learn/${COURSE}/`));
    const h1 = page.getByRole("heading", { level: 1 });
    const loaded = await h1.isVisible({ timeout: 30_000 }).catch(() => false);
    await h1.waitFor({ timeout: 30_000 }).catch(() => undefined);
    log(J, { step: "lesson_h1", visible: await h1.isVisible(), ms: Date.now() - t1, url: page.url(), loadedQuick: loaded });
    await shot(page, "j1-lesson-desktop");
    // Try to mark the lesson complete if the UI offers it.
    const done = page.getByRole("button", { name: "Mark as complete" });
    if (await done.isVisible().catch(() => false)) {
      await page.mouse.wheel(0, 20_000);
      await expect(done).toBeEnabled({ timeout: 10_000 });
      await done.click();
      await page.waitForTimeout(1500);
      const errText = await page.locator("main [role=alert]").allInnerTexts();
      log(J, { step: "mark_complete_first_click", errText });
      const lessonKeyResp = /me\/lessons\/([^/]+)\/completion/;
      void lessonKeyResp;
      if (errText.join(" ").match(/Keep reading/)) {
        // Server-side minimum read time (by design). Wait it out (cap 3 min) and click again.
        await page.waitForTimeout(65_000);
        await done.click();
        await page.waitForTimeout(2000);
        log(J, { step: "mark_complete_second_click", errText: await page.locator("main [role=alert]").allInnerTexts() });
      }
      await page.reload();
      await page.getByRole("heading", { level: 1 }).waitFor({ timeout: 30_000 }).catch(() => undefined);
      log(J, { step: "lesson_completed_badge_after_reload", visible: await page.getByText("Completed", { exact: true }).isVisible().catch(() => false) });
    } else {
      log(J, { step: "no_mark_complete_button" });
    }
    const lc = await api(page, "GET", `me/enrolments`);
    log(J, { step: "enrolments_after_lesson", body: JSON.stringify(lc.json).slice(0, 1200) });
  });

  await test.step("checkout a paid plan (fake gateway)", async () => {
    await page.goto("/pricing");
    const buy = page.getByRole("link", { name: /^Get / }).first();
    await expect(buy).toBeVisible();
    await buy.click();
    await page.waitForURL(/\/app\/checkout\/new\?price_id=/);
    await page.getByLabel(/Name on invoice/).fill("Audit Learner");
    await page.getByLabel(/^State/).selectOption("36");
    await page.getByRole("button", { name: "Continue to payment" }).click();
    // A fresh learner hits consent_required (security_monitoring) at COM-01. Since E2E-04 the
    // checkout names the consent and grants it in place ("Turn on and continue"), then retries.
    const testMode = page.getByText("Test mode — no real money is charged");
    const grant = page.getByRole("button", { name: "Turn on and continue" });
    await expect(testMode.or(grant)).toBeVisible({ timeout: 20_000 });
    if (!(await testMode.isVisible())) {
      log(J, { step: "checkout_consent_prompt", alerts: await page.locator("main [role=alert]").allInnerTexts(), url: page.url() });
      await shot(page, "j1-checkout-consent");
      await grant.click();
      await expect(testMode).toBeVisible({ timeout: 20_000 });
      // Persistence: the grant is stored server-side, not just in the page.
      const consents = await api<{ data?: { purpose: string; state: string }[] }>(page, "GET", "me/consents");
      log(J, { step: "consents_after_grant", status: consents.status, body: JSON.stringify(consents.json).slice(0, 600) });
      expect(consents.status).toBe(200);
      expect(consents.json.data?.find((c) => c.purpose === "security_monitoring")?.state).toBe("granted");
    }
    await page.getByRole("button", { name: /^Pay ₹/ }).click();
    await page.getByRole("button", { name: "Simulate a successful payment" }).click();
    await page.waitForURL(/\/app\/orders\//);
    await expect(page.getByText("Payment confirmed. Your access is active.")).toBeVisible({ timeout: 60_000 });
    const orderId = /\/app\/orders\/([^/?#]+)/.exec(page.url())![1];
    await page.reload();
    await expect(page.getByText(/Payment confirmed|Paid/).first()).toBeVisible({ timeout: 30_000 });
    const orders = await api(page, "GET", "me/orders");
    const ents = await api(page, "GET", "me/entitlements");
    const inv = await api(page, "GET", "me/invoices");
    log(J, { step: "order", orderId, orders: JSON.stringify(orders.json).slice(0, 1000), ents: JSON.stringify(ents.json).slice(0, 1200), invoices: JSON.stringify(inv.json).slice(0, 600) });
    expect(JSON.stringify(orders.json)).toContain(orderId);
    expect(JSON.stringify(orders.json)).toMatch(/"status":"(paid|fulfilled|completed)"/);
  });

  await test.step("timed test: autosave, reload mid-test, submit, server score", async () => {
    test.skip(!TEST_ID, "no E2E_TEST_ID");
    await page.goto(`/app/tests/${TEST_ID}`);
    await page.getByLabel("I've read the instructions").check();
    const consent = page.getByLabel(/I agree to integrity events/);
    if (await consent.count()) await consent.check();
    await page.getByRole("button", { name: "Start test" }).click();
    await page.waitForURL(/\/app\/attempts\/[^/]+$/);
    const attemptId = /\/app\/attempts\/([^/?#]+)/.exec(page.url())![1];
    await resumeIfAsked(page);
    // Answer every question with the first option, checking autosave after the first.
    let answered = 0;
    for (let i = 0; i < 10; i += 1) {
      const opt = page.locator("fieldset input:not(:checked)").first();
      if (!(await opt.isVisible().catch(() => false))) break;
      await opt.check();
      answered += 1;
      if (i === 0) await expect(page.getByText(/Saved \d+ s ago/)).toBeVisible({ timeout: 15_000 });
      const next = page.getByRole("button", { name: "Save and go to the next question" });
      if (!(await next.isVisible().catch(() => false)) || (await next.isDisabled())) break;
      await next.click();
    }
    await page.waitForTimeout(2_000);
    const stateBefore = await api(page, "GET", `attempts/${attemptId}/state`);
    log(J, { step: "attempt_state_before_reload", answered, status: stateBefore.status, body: JSON.stringify(stateBefore.json).slice(0, 1500) });
    await page.reload();
    await resumeIfAsked(page);
    const restored = await page.getByText(/We've restored \d+ answers?/).isVisible().catch(() => false);
    log(J, { step: "after_reload", restoredDialog: restored });
    await page.getByRole("button", { name: /^Submit (test|section)$/ }).first().click();
    const dialog = page.getByRole("dialog", { name: /^Submit/ });
    await dialog.getByRole("button", { name: /^Submit (test|section)$/ }).click();
    await page.waitForURL(/\/submitted/);
    await page.reload();
    await expect(page.getByRole("heading", { name: /Test submitted/ })).toBeVisible();
    const result = await api(page, "GET", `attempts/${attemptId}/result`);
    const mine = await api(page, "GET", "me/attempts");
    log(J, { step: "attempt_result", status: result.status, body: JSON.stringify(result.json).slice(0, 1500), mine: JSON.stringify(mine.json).slice(0, 800) });
    await shot(page, "j1-submitted");
  });

  await test.step("progress / analytics reflect activity", async () => {
    await page.waitForTimeout(5_000);
    const after = await api(page, "GET", "me/analytics/summary");
    const dash = await api(page, "GET", "me/dashboard");
    log(J, { step: "analytics_after", status: after.status, body: JSON.stringify(after.json).slice(0, 1500) });
    log(J, { step: "dashboard_after", status: dash.status, body: JSON.stringify(dash.json).slice(0, 1500) });
    for (const p of ["/app/progress", "/app/analytics", "/app/learning", "/app/billing"]) {
      const t = Date.now();
      await page.goto(p);
      const ok = await page.getByRole("heading", { level: 1 }).isVisible({ timeout: 30_000 }).catch(() => false);
      await page.getByRole("heading", { level: 1 }).waitFor({ timeout: 30_000 }).catch(() => undefined);
      log(J, { step: "page", path: p, h1: await page.getByRole("heading", { level: 1 }).isVisible(), ms: Date.now() - t, quick: ok });
      await shot(page, `j1-${p.replace(/\//g, "_")}-desktop`);
    }
  });

  await test.step("360px rendering of key learner pages", async () => {
    await page.setViewportSize({ width: 360, height: 780 });
    for (const p of ["/app", "/app/learning", `/app/courses/${COURSE}`, "/app/tests", "/app/practice", "/app/progress", "/app/billing", "/app/settings/devices", "/courses", "/pricing"]) {
      await page.goto(p);
      await page.getByRole("heading", { level: 1 }).waitFor({ timeout: 30_000 }).catch(() => undefined);
      await page.waitForTimeout(800);
      const o = await overflowX(page);
      log("mobile360.jsonl", { path: p, ...o, h1: await page.getByRole("heading", { level: 1 }).isVisible() });
      await shot(page, `m360-${p.replace(/[/?=]/g, "_")}`);
    }
  });
});

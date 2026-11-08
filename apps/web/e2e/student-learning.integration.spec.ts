import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { resumeIfAsked } from "./support/attempt";
import { signIn } from "./support/auth";

/**
 * Integration-stage flows for practice and timed tests: need the running api (+ Mailpit for
 * device OTP) behind the BFF and seeded content.
 *   E2E_INTEGRATION=1 npx playwright test --grep @integration --project chromium
 * Env:
 *   E2E_STUDENT_IDENTIFIER / E2E_STUDENT_PASSWORD   an adult student with verified contacts
 *   E2E_TEST_ID                                     a free, open timed test (≥ 2 MCQ questions, attempts left;
 *                                                   dev seed: e2e-timed-test, 100 attempts)
 *   (all of these: apps/web/.env.e2e.local from scripts/reset-dev-data.ps1)
 *   MAILPIT_URL                                     default http://localhost:8025
 */
const enabled = !!process.env.E2E_INTEGRATION;
const IDENT = process.env.E2E_STUDENT_IDENTIFIER ?? "";
const PASSWORD = process.env.E2E_STUDENT_PASSWORD ?? "";
const TEST_ID = process.env.E2E_TEST_ID ?? "";

async function login(page: Page, request: APIRequestContext, next: string) {
  await signIn(page, request, { identifier: IDENT, password: PASSWORD }, next);
  await page.goto(next);
}

test.describe("practice and timed tests against the api", { tag: "@integration" }, () => {
  test.skip(!enabled || !IDENT || !PASSWORD, "set E2E_INTEGRATION=1 and E2E_STUDENT_IDENTIFIER/_PASSWORD with the api running");

  test("practice: pick a topic, answer, get immediate feedback with an explanation", async ({ page, request }) => {
    await login(page, request, "/app/practice");
    await expect(page.getByRole("heading", { name: "Practice", level: 1 })).toBeVisible();
    await page.getByRole("button", { name: "Start 10-question set" }).click();
    const paid = page.getByText("This is part of a paid plan");
    await expect(paid.or(page.getByText(/Question 1 of/))).toBeVisible({ timeout: 15_000 });
    test.skip(
      await paid.isVisible(),
      "no practice entitlement for this student (dev seed e2e_demo grants student@ all_practice: run scripts/reset-dev-data.ps1)",
    );
    await page.waitForURL(/\/app\/practice\/sessions\//);
    await expect(page.getByText(/Question 1 of/)).toBeVisible();

    // Question order is random: answer a choice question by ticking an option, a numeric one by typing.
    const option = page.locator("input[name=practice-option]").first();
    const typed = page.getByRole("textbox", { name: "Your answer" });
    await expect(option.or(typed)).toBeVisible();
    if (await option.isVisible()) await option.check();
    else await typed.fill("1");
    await page.getByRole("button", { name: "Check answer" }).click();
    // The verdict line, not the "✓ Correct answer" badge shown on the key option after a wrong pick.
    await expect(page.getByText(/^(✓ Correct(?! answer)|✕ Not quite)/)).toBeVisible();
    await expect(page.getByRole("region", { name: "Explanation" })).toBeVisible();

    // Reload keeps the answered state (server-side feedback, PLC-20).
    await page.reload();
    await expect(page.getByText(/Question 2 of/)).toBeVisible();
  });

  test("timed test: start, autosave, refresh-resume, offline sync, submit", async ({ page, context, request, isMobile }) => {
    test.skip(!TEST_ID, "set E2E_TEST_ID to an open timed test");
    await login(page, request, `/app/tests/${TEST_ID}`);

    await page.getByLabel("I've read the instructions").check();
    const consent = page.getByLabel(/I agree to integrity events/);
    if (await consent.count()) await consent.check();
    await page.getByRole("button", { name: "Start test" }).click();
    await page.waitForURL(/\/app\/attempts\/[^/]+$/);
    const attemptUrl = page.url();
    // An attempt left open by an earlier run (or SCN-02) is resumed instead of started.
    await resumeIfAsked(page);

    // Server-derived timer and the first answer autosaved.
    await expect(page.getByRole("timer")).toHaveAccessibleName(/Time left: /);
    await page.locator("fieldset input:not(:checked)").first().check();
    await expect(page.getByText(/Saved \d+ s ago/)).toBeVisible({ timeout: 15_000 });

    // Refresh → TST-004 resume with the answer restored and the timer still running.
    await page.reload();
    await expect(page.getByRole("dialog", { name: "Welcome back — your test is safe" })).toBeVisible();
    await expect(page.getByText(/We've restored \d+ answers?/)).toBeVisible();
    await page.getByRole("button", { name: "Resume test" }).click();
    // Below lg the palette is a dialog behind the "Questions n/N" button (TST-002 mobile layout).
    if (isMobile) await page.getByRole("button", { name: /^Questions \d+\/\d+$/ }).click();
    await expect(page.getByRole("button", { name: /^Question 1, answered/ }).first()).toBeVisible();
    if (isMobile) {
      await page.keyboard.press("Escape");
      await expect(page.getByRole("dialog", { name: "Questions" })).toHaveCount(0);
    }
    expect(page.url()).toBe(attemptUrl);

    // Offline: keep answering, banner shows, answers sync on reconnect.
    await page.getByRole("button", { name: "Save and go to the next question" }).click();
    await context.setOffline(true);
    await page.evaluate(() => window.dispatchEvent(new Event("offline")));
    await page.locator("fieldset input:not(:checked)").first().check();
    await expect(page.getByText(/You're offline\. Keep answering/)).toBeVisible();
    await context.setOffline(false);
    await page.evaluate(() => window.dispatchEvent(new Event("online")));
    await expect(page.getByText(/Back online\. \d+ answers? synced\./)).toBeVisible({ timeout: 20_000 });

    // Submit (TST-003 → TST-005).
    await page.getByRole("button", { name: /^Submit (test|section)$/ }).first().click();
    const dialog = page.getByRole("dialog", { name: /^Submit/ });
    await expect(dialog.getByText("Answered", { exact: true }).first()).toBeVisible();
    await dialog.getByRole("button", { name: /^Submit (test|section)$/ }).click();
    await page.waitForURL(/\/submitted/);
    await expect(page.getByRole("heading", { name: /Test submitted/ })).toBeVisible();
  });
});

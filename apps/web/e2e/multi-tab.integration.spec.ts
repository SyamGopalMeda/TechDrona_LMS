import { expect, test, type Page } from "@playwright/test";
import { audit } from "./support/a11y";
import { resumeIfAsked } from "./support/attempt";
import { account, signIn } from "./support/auth";

/**
 * SCN-02 (testing-and-acceptance-criteria §4.3): several tabs on the same laptop. One browser
 * context = one session/device. Tabs: lesson (A), practice (B), dashboard (C). A mock attempt
 * started in B and opened in C works in both tabs, each shows "already open in another tab",
 * answers save from both, and the account still has exactly one session (no cap prompt,
 * no logout). Video takeover between tabs is not covered (fake video provider locally).
 *
 *   E2E_INTEGRATION=1 npx playwright test --project=chromium multi-tab
 * Env: E2E_STUDENT_* (unrestricted), E2E_TEST_ID (open timed test with attempts left),
 *      E2E_FREE_COURSE_SLUG (default demo-dsa-free)
 */
const enabled = !!process.env.E2E_INTEGRATION;
const student = account("STUDENT");
const TEST_ID = process.env.E2E_TEST_ID ?? "";
const COURSE = process.env.E2E_FREE_COURSE_SLUG ?? "demo-dsa-free";

async function activeSessions(page: Page): Promise<{ current: number; total: number }> {
  return page.evaluate(async () => {
    const res = await fetch("/api/v1/me/sessions", { headers: { accept: "application/json" } });
    const body = (await res.json()) as { data?: { is_current?: boolean; status?: string }[] };
    const rows = (body.data ?? []).filter((s) => !s.status || s.status === "active");
    return { current: rows.filter((s) => s.is_current).length, total: rows.length };
  });
}

test.describe("SCN-02: several tabs on the same laptop", { tag: "@integration" }, () => {
  test.skip(!enabled || !student || !TEST_ID, "set E2E_INTEGRATION=1, E2E_STUDENT_* and E2E_TEST_ID");
  test.use({ viewport: { width: 1280, height: 900 } });

  test("one session; the same attempt works in two tabs with an 'open in another tab' notice", async ({ context, request }, info) => {
    const tabA = await context.newPage();
    await signIn(tabA, request, student!, "/app");
    const before = await activeSessions(tabA);

    // Tab A: a lesson. Tab B: practice. Tab C: dashboard.
    await tabA.goto(`/app/courses/${COURSE}`);
    const start = tabA.getByRole("link", { name: /Start course|Resume/ });
    if (await start.isVisible().catch(() => false)) {
      await start.click();
      await tabA.waitForURL(/\/app\/learn\//);
    }
    const tabB = await context.newPage();
    await tabB.goto("/app/practice");
    await expect(tabB.getByRole("heading", { name: "Practice", level: 1 })).toBeVisible();
    const tabC = await context.newPage();
    await tabC.goto("/app");
    await expect(tabC.getByRole("heading", { level: 1 })).toBeVisible();

    // Step 3: start the mock in tab B …
    await tabB.goto(`/app/tests/${TEST_ID}`);
    await tabB.getByLabel("I've read the instructions").check();
    const consent = tabB.getByLabel(/I agree to integrity events/);
    if (await consent.count()) await consent.check();
    await tabB.getByRole("button", { name: /Start test|Resume test|Continue/ }).first().click();
    await tabB.waitForURL(/\/app\/attempts\/[^/]+$/);
    await resumeIfAsked(tabB);

    // … then open the same attempt in tab C.
    await tabC.goto(tabB.url());
    await resumeIfAsked(tabC);

    const notice = /This test is already open in another tab/;
    await expect(tabB.getByText(notice)).toBeVisible({ timeout: 10_000 });
    await expect(tabC.getByText(notice)).toBeVisible({ timeout: 10_000 });

    // Both tabs can answer; autosave succeeds in each (no 409 "open elsewhere" — same session).
    await tabB.locator("fieldset input:not(:checked)").first().check();
    await expect(tabB.getByText(/Saved \d+ s ago|Saved just now|All answers saved/)).toBeVisible({ timeout: 20_000 });
    await tabC.getByRole("button", { name: "Save and go to the next question" }).click();
    await tabC.locator("fieldset input:not(:checked)").first().check();
    await expect(tabC.getByText(/Saved \d+ s ago|Saved just now|All answers saved/)).toBeVisible({ timeout: 20_000 });
    await expect(tabC.getByText(/open on another device|another session/i)).toHaveCount(0);

    // Accessibility of the timed-test runner (TST-002) while we have it open.
    await audit(tabC, "timed-test-runner", info);

    // Closing tab C clears the notice in tab B.
    await tabC.close();
    await expect(tabB.getByText(notice)).toBeHidden({ timeout: 10_000 });

    // Still exactly one session for this browser; no session-cap prompt or logout anywhere.
    const after = await activeSessions(tabA);
    expect(after.current).toBe(1);
    expect(after.total).toBe(before.total);
    for (const p of [tabA, tabB]) expect(p.url()).not.toMatch(/\/login/);
  });
});

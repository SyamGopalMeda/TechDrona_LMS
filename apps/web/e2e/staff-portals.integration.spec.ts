import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { signIn as sharedSignIn } from "./support/auth";

/**
 * Integration-stage staff flows: need the running api (+ Mailpit) behind the BFF and
 * seeded staff accounts.
 *   E2E_INTEGRATION=1 npx playwright test --grep @integration
 * Env:
 *   MAILPIT_URL                                   default http://localhost:8025
 *   E2E_EVALUATOR_IDENTIFIER / _PASSWORD / _TOTP_SECRET     evaluator @ batch (MFA enrolled, base32 secret)
 *   E2E_TRAINER_IDENTIFIER / _PASSWORD / _TOTP_SECRET       trainer @ batch with at least one published test in scope
 */
const enabled = !!process.env.E2E_INTEGRATION;

async function signIn(page: Page, request: APIRequestContext, next: string, identifier: string, password: string, secret?: string) {
  await sharedSignIn(page, request, { identifier, password, totpSecret: secret }, next);
  await page.waitForURL((u) => u.pathname.startsWith(next));
}

test.describe("staff portals against the api", { tag: "@integration" }, () => {
  test.skip(!enabled, "set E2E_INTEGRATION=1 with the api and Mailpit running");

  test("evaluator opens the Evaluator portal with grading screens only (no authoring)", async ({ page, request }) => {
    const id = process.env.E2E_EVALUATOR_IDENTIFIER;
    const pw = process.env.E2E_EVALUATOR_PASSWORD;
    test.skip(!id || !pw, "set E2E_EVALUATOR_IDENTIFIER and E2E_EVALUATOR_PASSWORD");
    await signIn(page, request, "/evaluator", id!, pw!, process.env.E2E_EVALUATOR_TOTP_SECRET);

    const nav = page.getByRole("navigation", { name: "Evaluator navigation" }).first();
    for (const name of ["Grading", "Tests", "Integrity flags"]) await expect(nav.getByRole("link", { name })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Courses" })).toHaveCount(0);
    await nav.getByRole("link", { name: "Grading" }).click();
    await expect(page.getByRole("heading", { name: "Grading", level: 1 })).toBeVisible();
    await page.goto("/evaluator/tests");
    await expect(page.getByRole("button", { name: "New test" })).toHaveCount(0);
  });

  test("trainer assigns a published test to a batch", async ({ page, request }) => {
    const id = process.env.E2E_TRAINER_IDENTIFIER;
    const pw = process.env.E2E_TRAINER_PASSWORD;
    test.skip(!id || !pw, "set E2E_TRAINER_IDENTIFIER and E2E_TRAINER_PASSWORD");
    await signIn(page, request, "/trainer", id!, pw!, process.env.E2E_TRAINER_TOTP_SECRET);

    await page.goto("/trainer/tests");
    await expect(page.getByRole("heading", { name: "Tests", level: 1 })).toBeVisible();
    await page.waitForLoadState("networkidle");
    test.skip(await page.getByText("No tests yet").isVisible(), "no test in the trainer's scope (run scripts/reset-dev-data.ps1: e2e_demo publishes a demo weekly test)");
    const assign = page.getByRole("button", { name: /^Assign /, disabled: false }).first();
    await expect(assign).toBeVisible();
    await assign.click();

    const dialog = page.getByRole("dialog");
    const batch = dialog.getByLabel(/^Batch/);
    const firstBatch = await batch.locator("option:not([disabled])").first().getAttribute("value");
    await batch.selectOption(firstBatch!);
    const pad = (n: number) => String(n).padStart(2, "0");
    const local = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
    // A unique window a few weeks out to avoid conflicting with earlier runs.
    const opens = new Date(Date.now() + (14 + (Date.now() % 30)) * 86_400_000);
    const closes = new Date(opens.getTime() + 2 * 3_600_000);
    await dialog.getByLabel(/^Opens/).fill(local(opens));
    await dialog.getByLabel(/^Closes/).fill(local(closes));
    await dialog.getByLabel("Release results").selectOption("after_window");
    await dialog.getByRole("button", { name: "Assign test" }).click();

    await expect(page.getByText(/^Assigned .+ to .+/)).toBeVisible();
    await expect(dialog.getByRole("table", { name: "Current assignments" })).not.toContainText("Not assigned yet");
  });
});

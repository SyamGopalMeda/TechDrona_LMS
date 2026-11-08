import { expect, test } from "@playwright/test";
import { account, latestOtp, signIn } from "./support/auth";

/**
 * SCN-10 recovery (unblock doc §6, AUTH-21/22): after a reviewer lifts the restriction
 * (`lift_pending`), the student confirms with a one-time code on the restricted screen, every
 * session is revoked, and the next sign-in has full access. Skips unless the account is
 * currently offered the `reverify` action.
 *
 *   E2E_INTEGRATION=1 npx playwright test --project=chromium --workers=1 reverify
 * Env: E2E_REVERIFY_* — the dev seed's reverify.student@ (L3 already decided as a false positive,
 *      lift pending; apps/web/.env.e2e.local), so this spec does not depend on security-console.
 *      Falls back to E2E_RESTRICTED_* (then run security-console on that account first). MAILPIT_URL
 */
const enabled = !!process.env.E2E_INTEGRATION;
const who = account("REVERIFY") ?? account("RESTRICTED");

test.describe("SCN-10: re-verification after a lift restores access", { tag: "@integration" }, () => {
  test.skip(!enabled || !who, "set E2E_INTEGRATION=1 and E2E_REVERIFY_* (or E2E_RESTRICTED_*); see scripts/reset-dev-data.ps1");

  test("code on the restricted screen → signed out → full access on next sign-in", async ({ page, request }) => {
    await signIn(page, request, who!, "/account/restricted");
    await page.goto("/account/restricted");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const panel = page.getByRole("region", { name: /Confirm it's you to get your access back/ });
    await page.waitForLoadState("networkidle");
    test.skip(!(await panel.isVisible()), "no lift pending for this account (already re-verified? run scripts/reset-dev-data.ps1)");

    const sentAt = Date.now();
    await panel.getByRole("button", { name: "Email me a code" }).click();
    await expect(panel.getByText(/^Code sent/)).toBeVisible();
    await panel.getByLabel(/6-digit code/).fill(await latestOtp(request, who!.identifier, sentAt));
    await panel.getByRole("button", { name: "Confirm and restore access" }).click();
    await page.waitForURL(/\/login\?reason=reverified/);

    await signIn(page, request, who!, "/app");
    const status = await page.evaluate(async () => (await (await fetch("/api/v1/me/security/status")).json()) as { level: number });
    expect(status.level).toBe(0);
    await page.goto("/app/practice");
    await expect(page.getByRole("heading", { name: "Practice", level: 1 })).toBeVisible();
    expect(page.url()).not.toMatch(/account\/restricted/);
  });
});

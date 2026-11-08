import { expect, test } from "@playwright/test";
import { account, signIn } from "./support/auth";

/**
 * Integration-stage smoke for the security console screens added for ADM-05/07/11 and INV-11:
 * SEC-40 dashboard tiles, the trusted-network queue, the incident register, ENG secondary data and
 * "My exports". Read-only (no decisions, no exports). Needs the running api behind the BFF.
 *
 *   E2E_INTEGRATION=1 npx playwright test --grep @integration security-staff
 *
 * Env: E2E_REVIEWER_A_IDENTIFIER / _PASSWORD / _TOTP_SECRET (a seeded security reviewer).
 */
const reviewer = account("REVIEWER_A");
const enabled = !!process.env.E2E_INTEGRATION && !!reviewer;

test.describe("security console: dashboard, incidents, reports", { tag: "@integration" }, () => {
  test.skip(!enabled, "set E2E_INTEGRATION=1 and reviewer A credentials with the api running");
  test.use({ viewport: { width: 1440, height: 1000 } });

  test("reviewer sees SEC-40 tiles and the new security screens with real data", async ({ page, request }) => {
    await signIn(page, request, reviewer!, "/security");
    await page.waitForURL(/\/security/);

    await expect(page.getByRole("heading", { name: "Account security" })).toBeVisible();
    await expect(page.getByText("Pending unblock requests")).toBeVisible();

    await page.goto("/security/incidents");
    await expect(page.getByRole("heading", { name: "Security incidents" })).toBeVisible();
    await expect(page.getByRole("table", { name: "Security incidents" }).or(page.getByText("No incidents recorded"))).toBeVisible();

    await page.goto("/security/reports/engine-health");
    await expect(page.getByText("Login failures 10min")).toBeVisible();
    await expect(page.getByRole("heading", { name: "My exports" })).toBeVisible();
  });
});

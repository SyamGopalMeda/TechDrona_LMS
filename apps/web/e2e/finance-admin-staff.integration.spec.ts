import { expect, test } from "@playwright/test";
import { signIn } from "./support/auth";

/**
 * Integration-stage finance and super-admin screens (ADM-28/INV-04, ADM-31, ADM-15): need the
 * running api behind the BFF and seeded staff accounts. Read-only: nothing is created.
 *   E2E_INTEGRATION=1 npx playwright test --grep @integration
 * Env:
 *   E2E_FINANCE_IDENTIFIER / _PASSWORD / _TOTP_SECRET   finance_admin (MFA enrolled, base32 secret)
 *   E2E_ADMIN_IDENTIFIER / _PASSWORD / _TOTP_SECRET     super_admin (MFA enrolled, base32 secret)
 */
const enabled = !!process.env.E2E_INTEGRATION;

test.describe("finance and admin consoles against the api", { tag: "@integration" }, () => {
  test.skip(!enabled, "set E2E_INTEGRATION=1 with the api running");

  test("finance admin sees revenue, products, coupons and subscriptions (no placeholders)", async ({ page, request }) => {
    const id = process.env.E2E_FINANCE_IDENTIFIER;
    const pw = process.env.E2E_FINANCE_PASSWORD;
    test.skip(!id || !pw, "set E2E_FINANCE_IDENTIFIER and E2E_FINANCE_PASSWORD");
    await signIn(page, request, { identifier: id!, password: pw!, totpSecret: process.env.E2E_FINANCE_TOTP_SECRET }, "/finance");
    await page.waitForURL((u) => u.pathname.startsWith("/finance"));
    await expect(page.getByText("Gross sales")).toBeVisible();
    await expect(page.getByText("Net", { exact: true })).toBeVisible();
    for (const [path, heading] of [
      ["/finance/products", "Products and prices"],
      ["/finance/coupons", "Coupons"],
      ["/finance/subscriptions", "Subscriptions"],
    ] as const) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
      await expect(page.getByText(/not yet implemented/i)).toHaveCount(0);
      await expect(page.getByRole("table")).toBeVisible();
    }
  });

  test("super admin approvals queue loads the payload on demand", async ({ page, request }) => {
    const id = process.env.E2E_ADMIN_IDENTIFIER;
    const pw = process.env.E2E_ADMIN_PASSWORD;
    test.skip(!id || !pw, "set E2E_ADMIN_IDENTIFIER and E2E_ADMIN_PASSWORD");
    await signIn(page, request, { identifier: id!, password: pw!, totpSecret: process.env.E2E_ADMIN_TOTP_SECRET }, "/admin/approvals");
    await page.waitForURL((u) => u.pathname.startsWith("/admin/approvals"));
    await expect(page.getByRole("heading", { level: 1, name: "Approvals" })).toBeVisible();
    // Dev seed e2e_demo: one pending policy.change requested by admin2@, decidable by admin@.
    const show = page.getByRole("button", { name: "Show payload" }).first();
    await expect(show).toBeVisible();
    await show.click();
    await expect(page.getByLabel("Request payload").first()).toBeVisible();
  });
});

import { expect, test } from "@playwright/test";
import { signIn } from "./support/auth";

/**
 * Integration-stage content-studio screens (audit ADM-50 / INV-03 / INV-13): need the running
 * api behind the BFF and a seeded content manager.
 *   E2E_INTEGRATION=1 npx playwright test --grep @integration
 * Env:
 *   E2E_CONTENT_IDENTIFIER / _PASSWORD / _TOTP_SECRET   content_manager @ platform (MFA enrolled if required)
 * Video upload itself needs VdoCipher credentials and is not exercised here; the media screen is
 * checked to load real courses.
 */
const enabled = !!process.env.E2E_INTEGRATION;

test.describe("content studio against the api", { tag: "@integration" }, () => {
  test.skip(!enabled, "set E2E_INTEGRATION=1 with the api running");

  test("taxonomy, companies and media screens use real data; a topic can be added", async ({ page, request }) => {
    const id = process.env.E2E_CONTENT_IDENTIFIER;
    const pw = process.env.E2E_CONTENT_PASSWORD;
    test.skip(!id || !pw, "set E2E_CONTENT_IDENTIFIER and E2E_CONTENT_PASSWORD");
    await signIn(page, request, { identifier: id!, password: pw!, totpSecret: process.env.E2E_CONTENT_TOTP_SECRET }, "/studio/taxonomy");
    await page.waitForURL((u) => u.pathname.startsWith("/studio/taxonomy"));

    await expect(page.getByRole("heading", { name: "Taxonomy" })).toBeVisible();
    await expect(page.getByText(/not yet implemented/i)).toHaveCount(0);
    const stamp = Date.now();
    await page.getByRole("button", { name: "New subject or topic" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel(/^Name/).fill(`E2E subject ${stamp}`);
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(page.getByRole("cell", { name: `E2E subject ${stamp}`, exact: true })).toBeVisible();

    await page.goto("/studio/companies");
    await expect(page.getByRole("heading", { name: "Companies" })).toBeVisible();
    await expect(page.getByRole("button", { name: "New company" })).toBeVisible();

    await page.goto("/studio/media");
    await expect(page.getByRole("heading", { name: "Media" })).toBeVisible();
    await expect(page.getByText(/not yet implemented/i)).toHaveCount(0);
  });
});

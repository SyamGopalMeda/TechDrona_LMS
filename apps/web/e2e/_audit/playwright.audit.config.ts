import { defineConfig } from "@playwright/test";
import base from "../../playwright.config";

/**
 * AUDIT-ONLY config (Phase A). The exploratory specs are named *.audit.ts so the product
 * suite (testDir ./e2e, default *.spec.ts match) never picks them up. Run:
 *   npx playwright test -c e2e/_audit/playwright.audit.config.ts --project=chromium --workers=1
 */
export default defineConfig({
  ...base,
  testDir: ".",
  testMatch: /.*\.audit\.ts$/,
  fullyParallel: false,
  timeout: 180_000,
  expect: { timeout: 15_000 },
  outputDir: "../../test-results/_audit",
  reporter: "list",
});

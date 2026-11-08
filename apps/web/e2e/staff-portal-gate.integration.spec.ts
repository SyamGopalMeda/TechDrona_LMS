import { expect, test } from "@playwright/test";
import { account, signIn } from "./support/auth";

/**
 * ADM-12: staff portal layouts are role-gated from `GET /me/grants` `portals`. A student who
 * opens a staff portal URL sees a 403 page with a link to their own portal, not the staff
 * shell or navigation. Needs the running api behind the BFF.
 *   E2E_INTEGRATION=1 npx playwright test --grep @integration
 * Env: E2E_STUDENT_IDENTIFIER / E2E_STUDENT_PASSWORD (a student with no staff grants).
 */
const enabled = !!process.env.E2E_INTEGRATION;

test.describe("staff portal role gate (ADM-12)", { tag: "@integration" }, () => {
  test.skip(!enabled, "set E2E_INTEGRATION=1 with the api running");

  test("a student gets the 403 page on every staff portal", async ({ page, request }) => {
    const who = account("STUDENT");
    test.skip(!who, "set E2E_STUDENT_IDENTIFIER and E2E_STUDENT_PASSWORD");
    await signIn(page, request, who!, "/app");
    await page.waitForURL((u) => u.pathname.startsWith("/app"));
    for (const path of ["/admin", "/security", "/desk", "/studio", "/finance", "/trainer", "/evaluator", "/mentor"]) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1, name: /don.t have access to the .+ portal/ })).toBeVisible();
      await expect(page.getByRole("link", { name: "Go to Student" })).toHaveAttribute("href", "/app");
      await expect(page.getByRole("navigation", { name: /navigation$/ })).toHaveCount(0);
    }
  });
});

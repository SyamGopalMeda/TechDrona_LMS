import { expect, test } from "@playwright/test";
import { account, signIn } from "./support/auth";

/**
 * ADM-12: staff portal layouts are role-gated from `GET /me/grants` `portals`. A student who
 * opens a staff portal URL is sent straight to the Student portal (/app): no 403 page, no
 * staff shell or navigation. Needs the running api behind the BFF.
 *   E2E_INTEGRATION=1 npx playwright test --grep @integration
 * Env: E2E_STUDENT_IDENTIFIER / E2E_STUDENT_PASSWORD (a student with no staff grants).
 */
const enabled = !!process.env.E2E_INTEGRATION;

test.describe("staff portal role gate (ADM-12)", { tag: "@integration" }, () => {
  test.skip(!enabled, "set E2E_INTEGRATION=1 with the api running");

  test("a student opening any staff portal lands on the Student portal", async ({ page, request }) => {
    const who = account("STUDENT");
    test.skip(!who, "set E2E_STUDENT_IDENTIFIER and E2E_STUDENT_PASSWORD");
    await signIn(page, request, who!, "/app");
    await page.waitForURL((u) => u.pathname.startsWith("/app"));
    for (const path of ["/admin", "/security", "/desk", "/studio", "/finance", "/trainer", "/evaluator", "/mentor"]) {
      await page.goto(path);
      await page.waitForURL((u) => u.pathname === "/app");
      await expect(page.getByText(/don.t have access/)).toHaveCount(0);
    }
  });
});

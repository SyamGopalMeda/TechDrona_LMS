import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { signIn } from "./support/auth";
import { waitForLoaded } from "./support/wait";

/**
 * Integration-stage flows for the catalogue, course player and checkout. They need the
 * running api behind the BFF with seeded catalog data and the fake payment gateway.
 *   E2E_INTEGRATION=1 npx playwright test --grep @integration learning-commerce
 * Env:
 *   E2E_STUDENT_IDENTIFIER / E2E_STUDENT_PASSWORD  a verified, unrestricted adult student whose
 *                                                  device is already trusted (no OTP step)
 *   E2E_FREE_COURSE_SLUG  optional: a published free course (default: first free course in /courses)
 */
const enabled = !!process.env.E2E_INTEGRATION;
const identifier = process.env.E2E_STUDENT_IDENTIFIER;
const password = process.env.E2E_STUDENT_PASSWORD;

async function login(page: Page, request: APIRequestContext, next: string) {
  await signIn(page, request, { identifier: identifier!, password: password! }, next);
}

test.describe("catalogue, player and checkout against the api", { tag: "@integration" }, () => {
  test.skip(!enabled || !identifier || !password, "set E2E_INTEGRATION=1 and E2E_STUDENT_IDENTIFIER/_PASSWORD with the api running");

  test("browse → enrol in a free course → open a lesson", async ({ page, request }) => {
    let slug = process.env.E2E_FREE_COURSE_SLUG;
    if (!slug) {
      await page.goto("/courses?price_type=free");
      const first = page.getByRole("list", { name: "Courses" }).getByRole("link").first();
      await expect(first).toBeVisible();
      slug = decodeURIComponent((await first.getAttribute("href"))!.replace(/^\/courses\//, ""));
    }
    await login(page, request, `/courses/${slug}`);
    await page.goto(`/courses/${slug}`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

    const enrol = page.getByRole("button", { name: /Enrol for free|Start learning/ });
    const goTo = page.getByRole("link", { name: "Go to course" });
    await expect(enrol.or(goTo)).toBeVisible();
    if (await enrol.isVisible()) await enrol.click();
    else await goTo.click();

    await page.waitForURL(new RegExp(`/app/courses/${slug}$`));
    await page.getByRole("link", { name: /Start course|Resume/ }).click();
    await page.waitForURL(new RegExp(`/app/learn/${slug}/`));
    await waitForLoaded(page);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Course contents" }).first()).toBeAttached();
    // Either the lesson body or a server-driven state (player, paywall, processing) — never a crash.
    await expect(page.getByRole("alert").filter({ hasText: /Something went wrong/ })).toHaveCount(0);
  });

  test("checkout a paid plan in test mode", async ({ page, request }) => {
    await login(page, request, "/pricing");
    await page.goto("/pricing");
    const buy = page.getByRole("link", { name: /^Get / }).first();
    await expect(buy).toBeVisible();
    await buy.click();
    await page.waitForURL(/\/app\/checkout\/new\?price_id=/);

    await page.getByLabel(/Name on invoice/).fill("E2E Student");
    await page.getByLabel(/^State/).selectOption("36");
    const summary = page.getByRole("complementary", { name: "Order summary" });
    await expect(summary.getByText("Total (incl. GST)")).toBeVisible();

    const cont = page.getByRole("button", { name: "Continue to payment" });
    test.skip(await cont.isDisabled(), "the seeded student already owns this plan");
    await cont.click();

    await expect(page.getByText("Test mode — no real money is charged")).toBeVisible();
    await page.getByRole("button", { name: /^Pay ₹/ }).click();
    // B2 fixed: the fake gateway's order carries checkout.test_payment, so simulation is offered.
    await expect(page.getByText("Simulating a successful payment is not available yet in this environment.")).toHaveCount(0);
    await page.getByRole("button", { name: "Simulate a successful payment" }).click();

    await page.waitForURL(/\/app\/orders\//);
    await expect(page.getByText("Payment confirmed. Your access is active.")).toBeVisible({ timeout: 60_000 });
    await page.goto("/app/billing");
    await expect(page.getByRole("table", { name: "Your orders" })).toBeVisible();
  });
});

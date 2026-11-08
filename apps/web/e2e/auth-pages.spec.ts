import { expect, test } from "@playwright/test";

/**
 * Auth/unblock page checks that need no api: rendering, keyboard flow and client validation.
 * Flows against the running backend are in identity.integration.spec.ts (@integration).
 */

test("login form is keyboard operable and validates before calling the api", async ({ page }) => {
  let apiCalls = 0;
  page.on("request", (r) => {
    if (r.url().includes("/api/v1/auth/")) apiCalls += 1;
  });
  await page.goto("/login?reason=session_expired&next=%2Fapp%2Flearning");
  await expect(page.getByRole("status")).toHaveText("Your session timed out. Please log in again.");
  await page.getByLabel("Email or mobile").focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Enter your email or mobile number.")).toBeVisible();
  await expect(page.getByText("Enter your password.")).toBeVisible();
  expect(apiCalls).toBe(0);
  expect(page.url()).not.toContain("password");
});

test("signup shows an error summary and the under-18 guardian notice", async ({ page }) => {
  await page.goto("/signup");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("alert", { name: /Please fix these \d+ problems/ })).toBeFocused();
  await page.getByLabel("Day").selectOption("5");
  await page.getByLabel("Month").selectOption("June");
  await page.getByLabel("Year").selectOption(String(new Date().getFullYear() - 15));
  await expect(page.getByText("A parent or guardian needs to agree", { exact: true })).toBeVisible();
  await expect(page.getByText(/Product news and offers/)).toHaveCount(0);
});

test("session chooser without a pending sign-in explains the expiry", async ({ page }) => {
  await page.goto("/login/session-choice");
  await expect(page.getByText("This sign-in has expired")).toBeVisible();
  await expect(page.getByRole("link", { name: "Sign in again" })).toHaveAttribute("href", "/login");
});

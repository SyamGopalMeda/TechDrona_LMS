import { expect, test } from "@playwright/test";

/**
 * Foundation smoke tests: shell routing, session gate, BFF exclusions and CSRF.
 * They do not need the api service (requests that would reach it are not asserted).
 */

test("public home renders with a skip link and main landmark, without CSP violations", async ({ page }) => {
  const cspErrors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error" && /Content Security Policy/i.test(msg.text())) cspErrors.push(msg.text());
  });
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  expect(cspErrors).toEqual([]);
  await expect(page.getByRole("main")).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
});

test("portal routes redirect to /login without a session", async ({ page }) => {
  await page.goto("/app/learning");
  await expect(page).toHaveURL(/\/login\?next=%2Fapp%2Flearning/);
});

test("the BFF never serves webhooks and requires CSRF on writes", async ({ request }) => {
  const webhook = await request.post("/api/v1/webhooks/razorpay", { data: {} });
  expect(webhook.status()).toBe(404);
  const write = await request.post("/api/v1/auth/login", { data: {} });
  expect(write.status()).toBe(403);
  expect((await write.json()).code).toBe("csrf_failed");
});

test("the CSRF cookie is issued to pages and readable by script", async ({ page, context }) => {
  await page.goto("/login");
  const cookies = await context.cookies();
  const csrf = cookies.find((c) => c.name === "td_csrf" || c.name === "__Host-td_csrf");
  expect(csrf).toBeDefined();
  expect(csrf?.httpOnly).toBe(false);
});

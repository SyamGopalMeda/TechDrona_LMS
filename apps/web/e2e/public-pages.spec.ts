import { expect, test } from "@playwright/test";

/**
 * Public pages that render without api data (FE-01/02/11/13/14/33). Data-backed pages
 * (placement, free resources) are covered by unit tests with a mocked api.
 */

for (const [path, title] of [
  ["/legal/terms", "Terms of use"],
  ["/legal/privacy", "Privacy notice"],
  ["/legal/refund-policy", "Refund policy"],
  ["/legal/device-policy", "Device policy"],
] as const) {
  test(`${path} is a real policy page with the draft banner`, async ({ page }) => {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
    await expect(page.getByText("Draft — pending legal review")).toBeVisible();
    await expect(page.getByText("Not yet implemented")).toHaveCount(0);
  });
}

test("signup consent links open readable policies", async ({ page }) => {
  await page.goto("/signup");
  await expect(page.getByRole("link", { name: "Terms" }).first()).toHaveAttribute("href", "/legal/terms");
  await page.goto("/legal/terms");
  await expect(page.getByRole("heading", { name: /Your account is for one person/ })).toBeVisible();
});

test("footer carries the sitemap links and the grievance page is reachable", async ({ page }) => {
  await page.goto("/help");
  const footer = page.getByRole("contentinfo");
  for (const name of ["Grievance officer", "Certificate verification", "Free resources", "Device policy"]) {
    await expect(footer.getByRole("link", { name })).toBeVisible();
  }
  await footer.getByRole("link", { name: "Grievance officer" }).click();
  await expect(page).toHaveURL(/\/help\/grievance$/);
  await expect(page.getByRole("heading", { level: 1, name: "Grievance officer and complaints" })).toBeVisible();
});

test("/verify accepts a typed code and goes to the certificate page", async ({ page }) => {
  await page.goto("/verify");
  await page.getByLabel("Certificate code").fill("abcd123456");
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page).toHaveURL(/\/verify\/ABCD123456$/);
});

test("unknown pages show the branded 404 inside the public chrome", async ({ page }) => {
  const res = await page.goto("/no-such-page-here");
  expect(res?.status()).toBe(404);
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  await expect(page.getByRole("contentinfo")).toBeVisible();
});

test("removed college and invite routes return 404", async ({ page }) => {
  for (const path of ["/college", "/invite/x", "/colleges"]) {
    const res = await page.goto(path);
    expect(res?.status(), path).toBe(404);
  }
});

test("/enquiries renders the corporate enquiry form", async ({ page }) => {
  const res = await page.goto("/enquiries");
  expect(res?.status()).toBe(200);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  for (const label of [/^Name/, /^Company/, /^Email/, /^Phone/, /^Message/]) await expect(page.getByLabel(label).first()).toBeVisible();
  await expect(page.getByRole("checkbox")).toBeVisible();
});

test("robots.txt and sitemap.xml are served", async ({ request }) => {
  const robots = await request.get("/robots.txt");
  expect(robots.ok()).toBe(true);
  expect(await robots.text()).toContain("Disallow: /app");
  const sitemap = await request.get("/sitemap.xml");
  expect(sitemap.ok()).toBe(true);
  expect(await sitemap.text()).toContain("/legal/privacy");
});

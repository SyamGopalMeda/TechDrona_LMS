import { expect, type Page } from "@playwright/test";

/**
 * E2E-11: client screens render a `role="status"` "Loading …" block until their data arrives. On a
 * cold `next dev` (first compile of the route) or a loaded machine that can exceed the 5 s expect
 * default, while the page itself is fine. Wait for the loading states to clear with a budget
 * that matches a cold compile, then assert on the real content with the normal timeout.
 */
export async function waitForLoaded(page: Page, timeout = 30_000) {
  await expect(page.getByRole("status").filter({ hasText: /^Loading/ })).toHaveCount(0, { timeout });
}

import { expect, type Page } from "@playwright/test";

/**
 * On the attempt runner: wait for it to load and answer the TST-004 "Welcome back" dialog if
 * the attempt already has saved answers (resumed attempt, second tab, earlier run).
 */
export async function resumeIfAsked(page: Page) {
  const dialog = page.getByRole("dialog", { name: "Welcome back — your test is safe" });
  const timer = page.getByRole("timer");
  await expect(dialog.or(timer).first()).toBeVisible({ timeout: 20_000 });
  if (await dialog.isVisible({ timeout: 2_000 }).catch(() => false)) {
    await dialog.getByRole("button", { name: "Resume test" }).click();
    await expect(dialog).toBeHidden();
  }
  await expect(timer).toBeVisible();
}

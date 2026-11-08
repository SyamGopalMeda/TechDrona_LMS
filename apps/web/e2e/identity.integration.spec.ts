import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { account, latestOtp, signIn } from "./support/auth";

/**
 * Integration-stage flows: need the running api (+ Mailpit) behind the BFF.
 *   E2E_INTEGRATION=1 npx playwright test --grep @integration
 * Env:
 *   MAILPIT_URL                       default http://localhost:8025 (dev SMTP sink)
 *   E2E_RESTRICTED_IDENTIFIER/_PASSWORD  a seeded account with an open L3/L4 case and no open request
 *                                        (dev seed: restricted.student@; all values come from
 *                                        apps/web/.env.e2e.local, see scripts/reset-dev-data.ps1)
 */
const enabled = !!process.env.E2E_INTEGRATION;
const MAILPIT = process.env.MAILPIT_URL ?? "http://localhost:8025";

interface MailpitSummary {
  ID: string;
}

async function latestMailText(request: APIRequestContext, to: string): Promise<string> {
  for (let i = 0; i < 30; i += 1) {
    const res = await request.get(`${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:${to}`)}`);
    if (res.ok()) {
      const json = (await res.json()) as { messages?: MailpitSummary[] };
      const first = json.messages?.[0];
      if (first) {
        const msg = await request.get(`${MAILPIT}/api/v1/message/${first.ID}`);
        const body = (await msg.json()) as { Text?: string; HTML?: string };
        return `${body.Text ?? ""}\n${body.HTML ?? ""}`;
      }
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`No email for ${to} in Mailpit`);
}

async function completeDeviceVerificationIfAsked(page: Page, request: APIRequestContext, email: string) {
  if (!/\/login\/verify-device/.test(page.url())) return;
  const sentAt = Date.now();
  await page.getByRole("button", { name: /Send code by email/ }).click();
  // Wait for the OTP mail itself (the inbox already holds the verification link mail).
  await page.getByLabel("6-digit code").fill(await latestOtp(request, email, sentAt));
  await page.getByRole("button", { name: "Confirm" }).click();
}

test.describe("identity flows against the api", { tag: "@integration" }, () => {
  test.skip(!enabled, "set E2E_INTEGRATION=1 with the api and Mailpit running");

  test("signup → verify email → login → sessions page", async ({ page, request, browser }) => {
    const email = `e2e+${Date.now()}@example.com`;
    const password = `e2e-${Date.now()}-correct-horse-battery`;

    await page.goto("/signup");
    await page.getByLabel(/Full name/).fill("E2E Student");
    await page.getByLabel(/^Email/).fill(email);
    await page.getByLabel("Day").selectOption("12");
    await page.getByLabel("Month").selectOption("April");
    await page.getByLabel("Year").selectOption("2000");
    await page.getByLabel(/^Password/).fill(password);
    await page.getByRole("checkbox", { name: /I agree to the/ }).check();
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page.getByRole("heading", { name: "Check your inbox" })).toBeVisible();
    expect(page.url()).not.toContain(password);

    const mail = await latestMailText(request, email);
    const link = /\/verify\/email\/([A-Za-z0-9_\-.~%]+)/.exec(mail);
    expect(link, "verification link in email").toBeTruthy();
    await page.goto(`/verify/email/${link![1]}`);
    await page.getByRole("button", { name: "Verify my email" }).click();
    await expect(page.getByText("Your email is verified")).toBeVisible();

    // Fresh browser context = no session cookie; log in with the new account.
    const ctx = await browser.newContext();
    const p2 = await ctx.newPage();
    await p2.goto("/login?next=%2Fapp%2Fsettings%2Fdevices");
    await p2.getByLabel("Email or mobile").fill(email);
    await p2.getByLabel(/^Password/).fill(password);
    await p2.getByRole("button", { name: "Sign in" }).click();
    await p2.waitForURL(/\/(app|login\/verify-device)/);
    await completeDeviceVerificationIfAsked(p2, request, email);
    await p2.waitForURL(/\/app/);
    await p2.goto("/app/settings/devices");
    await expect(p2.getByRole("list", { name: "Signed-in sessions" })).toContainText("This session");
    await expect(p2.getByRole("heading", { name: /Your devices/ })).toBeVisible();
    await ctx.close();
  });

  test("restricted account → request a review", async ({ page, request }) => {
    const who = account("RESTRICTED");
    test.skip(!who, "set E2E_RESTRICTED_IDENTIFIER and E2E_RESTRICTED_PASSWORD (seeded L3/L4 account)");

    await signIn(page, request, who!, "/account/restricted");
    await page.goto("/account/restricted");
    await expect(page.getByRole("heading", { name: /Learning access paused until|Your account is suspended pending review/ })).toBeVisible();

    // The seed (security_demo) leaves restricted.student@ without a request; a re-run (or another
    // spec) may already have filed one: then the screen shows its status instead of the
    // "Request a review" link — assert that and stop.
    const existing = page.getByRole("region", { name: /^Review request APL-\d{4}-[0-9A-Z]{6}$/ });
    const requestLink = page.getByRole("link", { name: "Request a review" });
    await expect(requestLink.or(existing).first()).toBeVisible({ timeout: 15_000 });
    if (await existing.isVisible()) {
      await expect(requestLink).toHaveCount(0);
      await expect(existing.getByRole("status")).toBeVisible();
      return;
    }
    await requestLink.click();
    await page.waitForURL(/\/unblock-request/);
    await page.getByRole("checkbox", { name: "All devices are mine" }).check();
    await page.getByLabel(/Your explanation/).fill("I use my laptop for lectures and my phone for notes at the same time, both are mine.");
    // Recognise every listed device: unticked devices are signed out on submit, and the list order
    // (seeded fixture devices vs this browser) is not stable, so ticking only one could sign us out.
    const devices = page.getByRole("group", { name: /Devices you recognise/ });
    const none = devices.getByRole("checkbox", { name: "None of these" });
    const noneHandle = await none.elementHandle();
    let ticked = 0;
    for (const box of await devices.getByRole("checkbox").all()) {
      if (await box.evaluate((el, n) => el === n, noneHandle)) continue;
      await box.check();
      ticked += 1;
    }
    expect(ticked).toBeGreaterThan(0);
    await page.getByRole("checkbox", { name: /The information I've given is true/ }).check();
    await page.getByRole("button", { name: "Send request" }).click();
    await expect(page.getByRole("heading", { name: "Request sent" })).toBeVisible();
    await expect(page.getByText(/APL-\d{4}-[0-9A-Z]{6}/).first()).toBeVisible();
  });
});

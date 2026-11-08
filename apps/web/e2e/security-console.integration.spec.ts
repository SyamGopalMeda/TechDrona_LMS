import { expect, test, type APIRequestContext, type Browser, type Page } from "@playwright/test";
import { freshTotp, signIn as sharedSignIn } from "./support/auth";

/**
 * Integration-stage flow: reviewer A proposes a lift on a high-risk L4 case (second approval
 * required, SEC-09 → 202), reviewer B approves it (SEC-10). Needs the running api behind the BFF.
 *
 *   E2E_INTEGRATION=1 npx playwright test --grep @integration security-console
 *
 * Env (seeded staff accounts with TOTP enrolled; base32 secrets):
 *   E2E_REVIEWER_A_IDENTIFIER / _PASSWORD / _TOTP_SECRET
 *   E2E_REVIEWER_B_IDENTIFIER / _PASSWORD / _TOTP_SECRET   (≠ A, did not apply the restriction)
 *   E2E_L4_CASE_ID   an open, high-risk L4 case with a linked unblock request under review
 * Dev seed (scripts/reset-dev-data.ps1 → apps/web/.env.e2e.local): reviewer A security@, reviewer B
 * security2@, the L4 case of suspended.student@ (applied by admin@). The case is consumed: re-seed
 * before running this spec again.
 */
const enabled = !!process.env.E2E_INTEGRATION && !!process.env.E2E_L4_CASE_ID && !!process.env.E2E_REVIEWER_A_IDENTIFIER && !!process.env.E2E_REVIEWER_B_IDENTIFIER;

interface Staff {
  identifier: string;
  password: string;
  totpSecret: string;
}

function staff(prefix: "A" | "B"): Staff {
  return {
    identifier: process.env[`E2E_REVIEWER_${prefix}_IDENTIFIER`] ?? "",
    password: process.env[`E2E_REVIEWER_${prefix}_PASSWORD`] ?? "",
    totpSecret: process.env[`E2E_REVIEWER_${prefix}_TOTP_SECRET`] ?? "",
  };
}

async function signIn(browser: Browser, request: APIRequestContext, who: Staff, next: string): Promise<Page> {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await sharedSignIn(page, request, { identifier: who.identifier, password: who.password, totpSecret: who.totpSecret }, next);
  await page.waitForURL(/\/security/);
  return page;
}

/** Answers the global step-up dialog (P5) if it appears. */
async function confirmStepUpIfAsked(page: Page, who: Staff) {
  const dialog = page.getByRole("dialog", { name: "Please confirm it's you" });
  if (await dialog.isVisible({ timeout: 3_000 }).catch(() => false)) {
    await dialog.getByLabel("Authenticator code").fill(await freshTotp(who.totpSecret));
    await dialog.getByRole("button", { name: "Confirm" }).click();
  }
}

async function openCase(page: Page, caseId: string) {
  await page.goto(`/security/cases/${caseId}`);
  await page.getByLabel("Reason").selectOption("appeal");
  await page.getByRole("button", { name: "Open" }).click();
  // The dev seed's E2E_L4_CASE_ID is L4 + high-risk (dual control); an L3 case still passes below.
  await expect(page.getByText(/^L[34] · (Suspended|Temporary restriction)$/).first()).toBeVisible();
}

test.describe("security console: unblock decision with a second approver", { tag: "@integration" }, () => {
  test.skip(!enabled, "set E2E_INTEGRATION=1, E2E_L4_CASE_ID and reviewer A/B credentials with the api running");
  test.use({ viewport: { width: 1440, height: 1000 } });

  test("reviewer A proposes a lift; reviewer B approves it", async ({ browser, request }) => {
    const caseId = process.env.E2E_L4_CASE_ID!;
    const a = staff("A");
    const b = staff("B");

    // Reviewer A: open evidence, then propose the lift.
    const pa = await signIn(browser, request, a, `/security/cases/${caseId}`);
    await openCase(pa, caseId);
    await expect(pa.getByText("Open Explanation and Timeline before deciding.")).toBeVisible();
    // security_demo links the engine evaluation, so the seeded case lists its contributing signals.
    await expect(pa.getByRole("table", { name: "Contributing signals" }).or(pa.getByText("No contributing signals returned"))).toBeVisible();
    await pa.getByRole("tab", { name: /Timeline \(H12\)/ }).click();
    await expect(pa.getByRole("table", { name: /User security timeline/ })).toBeVisible();
    await expect(pa.getByText("Open Explanation and Timeline before deciding.")).toBeHidden();

    await pa.getByLabel(/^Outcome/).selectOption("lift_false_positive");
    await pa.getByLabel(/Rationale \(internal\)/).fill("E2E: both devices belong to the student; hostel move documented in the request.");
    await pa.getByLabel(/^Student summary/).fill("We reviewed your request and found the activity was yours. Your access returns once you finish the verification steps.");
    await pa.getByRole("button", { name: /Submit for approval|Record decision/ }).click();
    await confirmStepUpIfAsked(pa, a);
    const pending = pa.getByRole("heading", { name: /Waiting for a second approver/ });
    const recorded = pa.getByRole("heading", { name: "Decision recorded" });
    await expect(pending.or(recorded)).toBeVisible({ timeout: 15_000 });
    if (await recorded.isVisible()) {
      // Not high-risk (e.g. the seeded L3 case): one reviewer decides; no second approval.
      await expect(pa.getByText("Lift false positive").first()).toBeVisible();
      test.info().annotations.push({ type: "note", description: "case did not require a second approver (not L4/high-risk); dual-control branch not exercised" });
      return;
    }
    await expect(pa.getByRole("button", { name: "Withdraw proposal" })).toBeVisible();
    await expect(pa.getByRole("button", { name: "Approve" })).toHaveCount(0);

    // Reviewer B: approve the pending proposal.
    const pb = await signIn(browser, request, b, `/security/cases/${caseId}`);
    await openCase(pb, caseId);
    await expect(pb.getByRole("heading", { name: /Waiting for a second approver/ })).toBeVisible();
    await pb.getByRole("button", { name: "Approve" }).click();
    const dialog = pb.getByRole("dialog", { name: "Approve this decision?" });
    await dialog.getByLabel(/Note/).fill("E2E: agree, owner verified both devices.");
    await dialog.getByRole("button", { name: "Approve" }).click();
    await confirmStepUpIfAsked(pb, b);
    await expect(pb.getByRole("heading", { name: "Decision recorded" })).toBeVisible();
    await expect(pb.getByText("Lift false positive").first()).toBeVisible();

    // The unblock queue no longer shows the request as pending second approval.
    await pb.goto("/security/unblock-requests");
    await expect(pb.getByRole("table", { name: "Unblock requests" }).or(pb.getByText("No requests match these filters"))).toBeVisible();
  });
});

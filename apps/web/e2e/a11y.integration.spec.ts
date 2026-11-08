import { expect, test, type Page } from "@playwright/test";
import { audit } from "./support/a11y";
import { account, signIn, type Account } from "./support/auth";
import { waitForLoaded } from "./support/wait";

/**
 * Accessibility sweep (WCAG 2.1 A/AA via axe-core) over the key screens. Fails on `serious`
 * and `critical` violations; every violation (all impacts) is written to
 * `test-results/a11y/<page>.json` and attached to the report.
 *
 *   E2E_INTEGRATION=1 npx playwright test --project=chromium a11y
 * Public pages run without the api. Signed-in groups need the seeded accounts:
 *   E2E_STUDENT_*      unrestricted student (dashboard, player, practice, timed test, coding)
 *   E2E_RESTRICTED_*   student under an open L3/L4 restriction (restricted screen, unblock request)
 *   E2E_REVIEWER_A_*   security reviewer with TOTP (queue, case detail; E2E_L4_CASE_ID)
 *   E2E_EVALUATOR_*    evaluator with TOTP (evaluator grading queue)
 * All of these come from apps/web/.env.e2e.local (scripts/reset-dev-data.ps1).
 */
const integration = !!process.env.E2E_INTEGRATION;
test.describe("a11y: public pages", { tag: "@a11y" }, () => {
  for (const [name, url] of [
    ["landing", "/"],
    ["login", "/login"],
    ["signup", "/signup"],
  ] as const) {
    test(name, async ({ page }, info) => {
      await page.goto(url);
      await expect(page.locator("main")).toBeVisible();
      await audit(page, name, info);
    });
  }
});

function signedIn(group: string, who: Account | null, pages: { name: string; open: (page: Page) => Promise<void> }[], next: string) {
  test.describe(`a11y: ${group}`, { tag: ["@a11y", "@integration"] }, () => {
    test.skip(!integration || !who, `set E2E_INTEGRATION=1 and the ${group} account env`);
    // Default mode: a failing page restarts the worker (re-running beforeAll) instead of skipping the rest.
    test.describe.configure({ mode: "default" });
    let page: Page;
    test.beforeAll(async ({ browser, request }) => {
      page = await (await browser.newContext()).newPage();
      await signIn(page, request, who!, next);
    });
    test.afterAll(async () => {
      await page?.context().close();
    });
    for (const p of pages) {
      test(p.name, async ({}, info) => {
        await p.open(page);
        await audit(page, p.name, info);
      });
    }
  });
}

const testId = process.env.E2E_TEST_ID ?? "";
const freeCourse = process.env.E2E_FREE_COURSE_SLUG ?? "demo-dsa-free";
const caseId = process.env.E2E_L4_CASE_ID ?? "";

signedIn(
  "student",
  account("STUDENT"),
  [
    {
      name: "student-dashboard",
      open: async (page) => {
        await page.goto("/app");
        await waitForLoaded(page);
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      },
    },
    {
      name: "course-player",
      open: async (page) => {
        // A fresh seed has no enrolment yet (spec order is alphabetical): enrol in the free course first.
        await page.goto(`/courses/${freeCourse}`);
        const enrol = page.getByRole("button", { name: /Enrol for free|Start learning/ });
        const goTo = page.getByRole("link", { name: "Go to course" });
        await expect(enrol.or(goTo)).toBeVisible();
        if (await enrol.isVisible()) await enrol.click();
        else await goTo.click();
        await page.waitForURL(new RegExp(`/app/courses/${freeCourse}$`));
        const start = page.getByRole("link", { name: /Start course|Resume/ });
        await expect(start).toBeVisible();
        await start.click();
        await page.waitForURL(/\/app\/learn\//);
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      },
    },
    {
      name: "practice",
      open: async (page) => {
        await page.goto("/app/practice");
        await expect(page.getByRole("heading", { name: "Practice", level: 1 })).toBeVisible();
      },
    },
    {
      name: "timed-test-instructions",
      open: async (page) => {
        test.skip(!testId, "E2E_TEST_ID");
        await page.goto(`/app/tests/${testId}`);
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      },
    },
    {
      name: "coding",
      open: async (page) => {
        await page.goto("/app/coding");
        const first = page.getByRole("link").filter({ hasText: /./ }).locator("xpath=self::a[contains(@href,'/app/coding/')]").first();
        await expect(first).toBeVisible();
        await first.click();
        await page.waitForURL(/\/app\/coding\/[^/]+$/);
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      },
    },
  ],
  "/app",
);

signedIn(
  "restricted student",
  account("RESTRICTED"),
  [
    {
      name: "restricted",
      open: async (page) => {
        await page.goto("/account/restricted");
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      },
    },
    {
      name: "unblock-request",
      open: async (page) => {
        await page.goto("/unblock-request");
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      },
    },
  ],
  "/account/restricted",
);

signedIn(
  "security reviewer",
  account("REVIEWER_A"),
  [
    {
      name: "security-queue",
      open: async (page) => {
        await page.goto("/security/unblock-requests");
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      },
    },
    {
      name: "case-detail",
      open: async (page) => {
        test.skip(!caseId, "E2E_L4_CASE_ID");
        await page.goto(`/security/cases/${caseId}`);
        // Audit the purpose gate, then the opened case (reason "QA sample").
        await expect(page.getByRole("region", { name: "Open case" })).toBeVisible();
        await page.getByLabel("Reason").selectOption({ label: "QA sample" });
        await page.getByRole("button", { name: "Open" }).click();
        await expect(page.getByRole("tab").first()).toBeVisible({ timeout: 15_000 });
      },
    },
  ],
  "/security",
);

signedIn(
  "evaluator",
  account("EVALUATOR"),
  [
    {
      name: "evaluator-grading",
      open: async (page) => {
        await page.goto("/evaluator");
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      },
    },
  ],
  "/evaluator",
);

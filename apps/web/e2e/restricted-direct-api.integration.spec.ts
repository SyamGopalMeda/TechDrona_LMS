import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { signIn as sharedSignIn } from "./support/auth";

/**
 * SCN-13 (testing-and-acceptance-criteria §4.14), E2E slice: a restricted (L3) student who
 * bypasses the UI and calls private content APIs straight through the BFF with a valid
 * session cookie and CSRF token gets `403 problem+json code=account_restricted` (with
 * `case_ref`, `level`, `until`, and no content), while `account_status` routes still answer.
 * The full route matrix is TS-AUTHZ / G-05 on the api side; this proves the BFF path.
 *
 *   E2E_INTEGRATION=1 npx playwright test --grep @integration restricted-direct-api
 * Env:
 *   E2E_RESTRICTED_IDENTIFIER / _PASSWORD   a seeded account under an open L3/L4 restriction
 *                                           (dev seed: restricted.student@dev.techdrona.local, L3;
 *                                           apps/web/.env.e2e.local from scripts/reset-dev-data.ps1)
 *   MAILPIT_URL                             default http://localhost:8025 (device OTP)
 */
const enabled = !!process.env.E2E_INTEGRATION;
const IDENT = process.env.E2E_RESTRICTED_IDENTIFIER ?? "";
const PASSWORD = process.env.E2E_RESTRICTED_PASSWORD ?? "";

async function signIn(page: Page, request: APIRequestContext) {
  await sharedSignIn(page, request, { identifier: IDENT, password: PASSWORD }, "/account/restricted");
}

interface Probe {
  status: number;
  contentType: string;
  body: Record<string, unknown> | null;
}

/** Same-origin fetch from the page: the browser sends the session cookie and Fetch Metadata. */
async function call(page: Page, method: string, path: string, body?: unknown): Promise<Probe> {
  return page.evaluate(
    async ({ method, path, body }) => {
      const csrf = document.cookie
        .split("; ")
        .find((c) => c.startsWith("td_csrf=") || c.startsWith("__Host-td_csrf="))
        ?.split("=")
        .slice(1)
        .join("=");
      const res = await fetch(`/api/v1/${path}`, {
        method,
        headers: {
          accept: "application/json",
          ...(body !== undefined ? { "content-type": "application/json" } : {}),
          ...(method !== "GET" && csrf ? { "x-csrf-token": decodeURIComponent(csrf) } : {}),
          ...(method === "POST" ? { "idempotency-key": crypto.randomUUID() } : {}),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        credentials: "same-origin",
      });
      let json: Record<string, unknown> | null = null;
      try {
        json = (await res.json()) as Record<string, unknown>;
      } catch {
        json = null;
      }
      return { status: res.status, contentType: res.headers.get("content-type") ?? "", body: json };
    },
    { method, path, body },
  );
}

test.describe("SCN-13: restricted user calls private APIs directly through the BFF", { tag: "@integration" }, () => {
  test.skip(!enabled || !IDENT || !PASSWORD, "set E2E_INTEGRATION=1 and E2E_RESTRICTED_IDENTIFIER/_PASSWORD (seeded L3/L4 account)");

  test("default-tagged routes → 403 account_restricted; account_status routes → 2xx", async ({ page, request }) => {
    await signIn(page, request);
    // Ensure a CSRF cookie exists for this session.
    await page.goto("/account/restricted");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

    const nil = "00000000-0000-7000-8000-000000000000";
    const denied: [string, string, unknown?][] = [
      ["POST", "attempts", { test_id: nil }],
      ["POST", "media/playback-tokens", { lesson_id: nil }],
      ["POST", `coding/problems/${nil}/run`, { language_key: "python3", source_code: "print(1)", custom_input: null }],
      ["POST", `coding/problems/${nil}/submit`, { language_key: "python3", source_code: "print(1)" }],
      ["GET", "coding/problems"],
      ["POST", "practice/sessions", { mode: "topic", size: 10 }],
      ["POST", `practice/sessions/${nil}/answers`, { question_version_id: nil, response: {} }],
    ];
    for (const [method, path, body] of denied) {
      const r = await call(page, method, path, body);
      expect.soft(r.status, `${method} /${path}`).toBe(403);
      expect.soft(r.contentType, `${method} /${path} content-type`).toContain("application/problem+json");
      expect.soft(r.body?.code, `${method} /${path} code`).toBe("account_restricted");
      expect.soft(typeof r.body?.case_ref, `${method} /${path} case_ref`).toBe("string");
      expect.soft([3, 4], `${method} /${path} level`).toContain(Number(r.body?.level));
      expect.soft("until" in (r.body ?? {}), `${method} /${path} until`).toBe(true);
      expect.soft(r.body && "data" in r.body, `${method} /${path} leaks no content`).toBeFalsy();
    }

    // account_status routes keep working (restricted screen, devices/sessions, unblock flow).
    for (const path of ["me", "me/sessions"]) {
      const r = await call(page, "GET", path);
      expect.soft(r.status, `GET /${path}`).toBe(200);
    }

    // Clearing the BFF's CSRF token does not turn a denial into anything else useful.
    const noCsrf = await page.evaluate(async () => {
      const res = await fetch("/api/v1/attempts", { method: "POST", headers: { "content-type": "application/json" }, body: "{}" });
      return { status: res.status, code: ((await res.json()) as { code?: string }).code };
    });
    expect(noCsrf).toEqual({ status: 403, code: "csrf_failed" });
  });

  test("navigating to a content page lands on the restricted screen", async ({ page, request }) => {
    await signIn(page, request);
    await page.goto("/app/coding");
    await page.waitForURL(/\/(account\/restricted|app\/account-status)/, { timeout: 15_000 });
    await expect(page.getByRole("heading", { name: /Learning access paused until|Your account is suspended pending review|account/i }).first()).toBeVisible();
  });
});

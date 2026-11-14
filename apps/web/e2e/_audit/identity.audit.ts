import { chromium, expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";
import { api, freshIdentity, latestOtp, log, mailText, shot, signupAndVerify, uiLogin, watch } from "./support";

/**
 * AUDIT E2E-ID: device/session caps, revoked-session reuse (SCN-19), logout everywhere,
 * password reset — all with fresh users so seed state is not touched.
 */
const L = "identity.jsonl";
test.use({ viewport: { width: 1280, height: 900 } });

// Chromium-family UAs only: Chromium always sends sec-ch-ua client hints, so a spoofed Firefox/Safari UA is internally inconsistent.
const UAS = [
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
  "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
];

/**
 * One simulated device = one Chromium process launched with that device's UA. A per-context
 * `userAgent` is not enough: unload-time `sendBeacon` / keepalive requests leave from the browser
 * process with the host's real UA, and the api rightly treats that UA/OS change on the session as
 * a stolen-cookie replay (TO-08, `device_mismatch`), which ended "device 3" mid-test. `_browser`
 * keeps the shared fixture signature; the launched browser closes with its context.
 */
async function device(_browser: Browser, i: number, info: Parameters<typeof watch>[1]): Promise<{ ctx: BrowserContext; page: Page }> {
  const own = await chromium.launch({ args: [`--user-agent=${UAS[i]}`] });
  const ctx = await own.newContext({ userAgent: UAS[i], viewport: { width: 1280, height: 900 }, baseURL: info.project.use.baseURL });
  ctx.on("close", () => void own.close());
  watch(ctx, info, `device${i + 1}`);
  return { ctx, page: await ctx.newPage() };
}

async function sessionCookie(ctx: BrowserContext) {
  return (await ctx.cookies()).find((c) => /td_session$/.test(c.name));
}

async function me(page: Page) {
  if (!/^http/.test(page.url())) await page.goto("/");
  return api<{ user?: { email?: string }; code?: string }>(page, "GET", "me");
}

test("ID1 device cap, session cap, revoked-session reuse, logout everywhere", async ({ browser, request }, info) => {
  const who = freshIdentity("caps");
  log(L, { t: "ID1", email: who.email });
  const d1 = await device(browser, 0, info);
  await signupAndVerify(d1.page, request, who);
  // Keep the signup session (clearing cookies would orphan it and count toward the session cap).
  await d1.page.goto("/app");
  if (/\/login/.test(d1.page.url())) await uiLogin(d1.page, request, who.email, who.password, { next: "/app" });
  log(L, { t: "ID1", step: "d1 after signup", url: d1.page.url(), me: (await me(d1.page)).status });
  const d1Cookie = await sessionCookie(d1.ctx);
  expect(d1Cookie).toBeTruthy();

  const d2 = await device(browser, 1, info);
  log(L, { t: "ID1", step: "d2 login", url: await uiLogin(d2.page, request, who.email, who.password, { next: "/app" }) });
  expect((await me(d2.page)).status).toBe(200);

  // Third device: OTP, then the session cap (2) must ask which session to end.
  const d3 = await device(browser, 2, info);
  const u3 = await uiLogin(d3.page, request, who.email, who.password, { next: "/app" });
  log(L, { t: "ID1", step: "d3 after otp", url: u3, text: (await d3.page.locator("main").innerText()).slice(0, 600) });
  await shot(d3.page, "id1-d3-session-choice");
  expect(d3.page.url()).toMatch(/\/login\/session-choice/);
  // End device 1's session (the oldest).
  await d3.page.getByRole("radio").first().check();
  await d3.page.getByRole("button", { name: "Sign out selected and continue" }).click();
  await d3.page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 20_000 });
  const s3 = await api<{ data: { status: string; is_current: boolean }[] }>(d3.page, "GET", "me/sessions");
  log(L, { t: "ID1", step: "sessions after d3", rows: s3.json.data?.map((r) => `${r.status}${r.is_current ? "*" : ""}`) });

  // Which one was ended? Check each device.
  const m1 = await me(d1.page);
  const m2 = await me(d2.page);
  log(L, { t: "ID1", step: "me after cap choice", d1: m1.status, d2: m2.status });
  await d1.page.goto("/app");
  await d1.page.waitForLoadState("networkidle").catch(() => undefined);
  log(L, { t: "ID1", step: "d1 /app after eviction", url: d1.page.url() });

  // SCN-19: reuse the revoked session cookie in a brand-new context.
  const thief = await browser.newContext();
  await thief.addCookies([{ ...d1Cookie! }]);
  const tp = await thief.newPage();
  await tp.goto("/");
  const reuse = await api<{ code?: string }>(tp, "GET", "me");
  log(L, { t: "ID1", step: "revoked cookie reuse /me", status: reuse.status, code: reuse.json.code });
  expect.soft(m1.status === 401 || m2.status === 401).toBeTruthy();
  if (m1.status === 401) expect.soft(reuse.status).toBe(401);
  await thief.close();

  // Fourth device: OTP then the device cap (3 trusted devices).
  const d4 = await device(browser, 3, info);
  await d4.page.goto("/login?next=%2Fapp");
  await d4.page.getByLabel("Email or mobile").fill(who.email);
  await d4.page.getByLabel(/^Password/).fill(who.password);
  await d4.page.getByRole("button", { name: "Log in", exact: true }).click();
  await d4.page.waitForURL(/\/login\/verify-device/, { timeout: 20_000 });
  const sentAt = Date.now();
  await d4.page.getByRole("button", { name: /Send code by email/ }).click();
  await d4.page.getByLabel("6-digit code").fill(await latestOtp(request, who.email, sentAt));
  await d4.page.getByRole("button", { name: "Confirm" }).click();
  const capLegend = d4.page.getByText(/You have \d+ registered devices/);
  await expect(capLegend).toBeVisible({ timeout: 15_000 });
  log(L, { t: "ID1", step: "d4 device cap UI", text: (await d4.page.locator("main").innerText()).slice(0, 700) });
  await shot(d4.page, "id1-d4-device-cap");
  // Before resolving, the pending d4 session must not reach private data.
  const pend = await api<{ code?: string }>(d4.page, "GET", "me/enrolments");
  log(L, { t: "ID1", step: "d4 pending session -> me/enrolments", status: pend.status, code: pend.json.code });
  expect.soft(pend.status).toBe(401);

  // Logout everywhere (from device 3): other sessions end; then sign out device 3.
  await d3.page.goto("/app/settings/devices");
  await d3.page.getByRole("button", { name: "Sign out all other sessions" }).click();
  const dlg = d3.page.getByRole("dialog");
  await dlg.getByRole("button", { name: /Sign out/ }).last().click();
  await d3.page.waitForTimeout(1500);
  const after = await api<{ data: { status: string; is_current: boolean }[] }>(d3.page, "GET", "me/sessions");
  const m2b = await me(d2.page);
  log(L, { t: "ID1", step: "after revoke-others", d2: m2b.status, rows: after.json.data?.map((r) => `${r.status}${r.is_current ? "*" : ""}`) });
  expect.soft(m2b.status).toBe(401);
  const d3Cookie = await sessionCookie(d3.ctx);
  await d3.page.getByRole("button", { name: "Sign out" }).first().click();
  await d3.page.waitForURL(/\/(login|$)/, { timeout: 15_000 }).catch(() => undefined);
  log(L, { t: "ID1", step: "d3 after sign out", url: d3.page.url() });
  const thief2 = await browser.newContext();
  await thief2.addCookies([{ ...d3Cookie! }]);
  const tp2 = await thief2.newPage();
  await tp2.goto("/");
  const reuse2 = await api<{ code?: string }>(tp2, "GET", "me");
  log(L, { t: "ID1", step: "logged-out cookie reuse /me", status: reuse2.status, code: reuse2.json.code });
  expect.soft(reuse2.status).toBe(401);
  await thief2.close();
  for (const d of [d1, d2, d3, d4]) await d.ctx.close();
});

test("ID2 password reset signs out everywhere; old password and reused link fail", async ({ browser, request }, info) => {
  const who = freshIdentity("reset");
  log(L, { t: "ID2", email: who.email });
  const d1 = await device(browser, 0, info);
  await signupAndVerify(d1.page, request, who);
  await d1.page.goto("/app");
  if (/\/login/.test(d1.page.url())) await uiLogin(d1.page, request, who.email, who.password, { next: "/app" });
  expect((await me(d1.page)).status).toBe(200);

  const d2 = await device(browser, 1, info);
  await d2.page.goto("/forgot-password");
  const t0 = Date.now();
  await d2.page.getByLabel("Email or mobile").fill(who.email);
  await d2.page.getByRole("button", { name: "Send reset instructions" }).click();
  await expect(d2.page.getByText("Check your email or phone")).toBeVisible();
  const mail = await mailText(request, who.email, t0, /reset-password\//);
  const token = /\/reset-password\/([A-Za-z0-9_\-.~%]+)/.exec(mail)![1];
  const newPw = `${who.password}-NEW`;
  await d2.page.goto(`/reset-password/${token}`);
  await d2.page.waitForTimeout(1500);
  log(L, { t: "ID2", step: "reset page", url: d2.page.url(), text: (await d2.page.locator("main").innerText()).slice(0, 500) });
  await shot(d2.page, "id2-reset-page");
  await d2.page.getByLabel(/^New password/).fill(newPw);
  await d2.page.getByLabel(/^Confirm new password/).fill(newPw);
  await d2.page.getByRole("button", { name: "Set new password" }).click();
  await expect(d2.page.getByText("Your password has been changed")).toBeVisible();
  const m1 = await me(d1.page);
  log(L, { t: "ID2", step: "d1 after reset", status: m1.status });
  expect.soft(m1.status).toBe(401);
  // Reuse the link.
  await d2.page.goto(`/reset-password/${token}`);
  await d2.page.getByLabel(/^New password/).fill(`${newPw}-2`);
  await d2.page.getByLabel(/^Confirm new password/).fill(`${newPw}-2`);
  await d2.page.getByRole("button", { name: "Set new password" }).click();
  await d2.page.waitForTimeout(1500);
  log(L, { t: "ID2", step: "reuse link", text: (await d2.page.locator("main").innerText()).slice(0, 300) });
  await expect.soft(d2.page.getByText("Your password has been changed")).toHaveCount(0);
  // Old password fails, new password works.
  const d3 = await device(browser, 0, info);
  await d3.page.goto("/login");
  await d3.page.getByLabel("Email or mobile").fill(who.email);
  await d3.page.getByLabel(/^Password/).fill(who.password);
  await d3.page.getByRole("button", { name: "Log in", exact: true }).click();
  await d3.page.waitForTimeout(2000);
  log(L, { t: "ID2", step: "old password", url: d3.page.url(), alert: (await d3.page.locator("main [role=alert]").allInnerTexts()).join(" | ").slice(0, 200) });
  expect.soft(d3.page.url()).toMatch(/\/login(\?|$)/);
  const u = await uiLogin(d3.page, request, who.email, newPw, { next: "/app" });
  log(L, { t: "ID2", step: "new password", url: u });
  expect((await me(d3.page)).status).toBe(200);
  // Notification email about the change?
  const notice = await mailText(request, who.email, t0, /password (was|has been) (reset|changed)/i).catch(() => "");
  log(L, { t: "ID2", step: "password-changed notice email", found: !!notice });
  for (const d of [d1, d2, d3]) await d.ctx.close();
});

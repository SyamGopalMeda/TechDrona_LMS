// TEMPORARY (design-system agent): before/after screenshots. Deleted after use.
import { existsSync } from "node:fs";
import path from "node:path";
import { test, type Browser } from "@playwright/test";
import { signIn, type Account } from "./support/auth";

const OUT = path.resolve(__dirname, "../../../docs/redesign/shots/design-system");
const TAG = process.env.SHOT_TAG ?? "before";
const STATE = process.env.SHOT_STATE_DIR ?? path.resolve(__dirname, "../test-results/shot-state");
const PW = "dev-only-lantern-harbour-2026";
const WHO: Record<string, Account> = {
  student: { identifier: "student@dev.techdrona.local", password: PW },
  admin: { identifier: "admin@dev.techdrona.local", password: PW, totpSecret: process.env.SHOT_ADMIN_TOTP },
};
const VIEWPORTS = { desktop: { width: 1440, height: 900 }, mobile: { width: 390, height: 844 } };

async function ctxFor(browser: Browser, who: keyof typeof WHO | null, vp: { width: number; height: number }) {
  const statePath = who ? path.join(STATE, `${who}.json`) : undefined;
  if (who && statePath && !existsSync(statePath)) {
    const c = await browser.newContext({ viewport: VIEWPORTS.desktop });
    const p = await c.newPage();
    // Sign in through the running stack (its origin is the one the api trusts), reuse the cookies here.
    const signInBase = process.env.SHOT_SIGNIN_BASE;
    if (signInBase) {
      const orig = p.goto.bind(p);
      p.goto = ((u: string, o?: Parameters<typeof orig>[1]) => orig(u.startsWith("/") ? signInBase + u : u, o)) as typeof p.goto;
    }
    await signIn(p, c.request, WHO[who]!, who === "admin" ? "/admin" : "/app");
    await c.storageState({ path: statePath });
    await c.close();
  }
  return browser.newContext({ viewport: vp, storageState: statePath });
}

test.describe.configure({ mode: "serial" });
for (const [page, who, url] of [
  ["login", null, "/login"],
  ["student-dashboard", "student", "/app"],
  ["admin-dashboard", "admin", "/admin"],
] as const) {
  test(`${TAG} ${page}`, async ({ browser }) => {
    test.setTimeout(180_000);
    for (const [vpName, vp] of Object.entries(VIEWPORTS)) {
      const ctx = await ctxFor(browser, who, vp);
      const p = await ctx.newPage();
      await p.goto(url, { waitUntil: "networkidle" });
      await p.waitForTimeout(800);
      await p.screenshot({ path: path.join(OUT, `${TAG}-${page}-${vpName}.png`), fullPage: vpName === "mobile" ? false : false });
      await ctx.close();
    }
  });
}

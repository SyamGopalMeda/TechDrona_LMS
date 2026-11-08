import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

/**
 * Loads `.env.e2e.local` (written by scripts/reset-dev-data.ps1 from the dev seeds; gitignored)
 * into process.env. Variables already set in the shell win. Plain KEY=VALUE lines; `#` comments.
 */
function loadE2eEnv(file = path.join(__dirname, ".env.e2e.local")) {
  if (!existsSync(file)) return;
  for (const raw of readFileSync(file, "utf8").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    const value = line.slice(eq + 1).trim().replace(/^(["'])(.*)\1$/, "$2");
    if (process.env[key] === undefined) process.env[key] = value;
  }
}
loadE2eEnv();

/**
 * E2E config. Browsers are not installed by `npm install`; run
 * `npx playwright install chromium` once. By default the suite starts
 * `npm run dev` itself; set E2E_BASE_URL to test an already running stack.
 * Integration env (accounts, ids): `apps/web/.env.e2e.local` from scripts/reset-dev-data.ps1;
 * then `npx playwright test --grep @integration --project=chromium --workers=1`.
 */
const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL,
    trace: "on-first-retry",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    {
      name: "mobile",
      use: {
        ...devices["Pixel 7"],
        // Chromium applies the emulated UA per page, but unload-time `sendBeacon` / keepalive
        // requests (analytics on pagehide) leave from the browser process with the host's real
        // (Windows) UA. The api treats a UA/OS change on a session as a stolen-cookie replay
        // (TO-08) and protect-locks the shared student@ fixture. A real phone never mixes UAs,
        // so make the whole browser report the Pixel 7 UA.
        launchOptions: { args: [`--user-agent=${devices["Pixel 7"].userAgent}`] },
      },
    },
  ],
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command: "npm run dev",
        url: baseURL,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
        // Local-only values so the BFF can boot without the api; never used outside e2e.
        env: {
          TD_CSRF_KEY: process.env.TD_CSRF_KEY ?? "e2e-only-csrf-key-not-a-secret",
          TD_API_INTERNAL_URL: process.env.TD_API_INTERNAL_URL ?? "http://127.0.0.1:8000",
        },
      },
});

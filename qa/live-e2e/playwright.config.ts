import { defineConfig, devices } from "@playwright/test";

/**
 * Audit of the LIVE site (never a local stack). Runs inside mcr.microsoft.com/playwright:v1.65.1-noble
 * on Cloud Build (cloudbuild.yaml). Device projects cover phone / tablet / laptop / desktop.
 * PROJECTS env (comma list) narrows the device set; ROLE_ONLY narrows roles (see lib/roles.ts).
 */
const LMS = process.env.LMS_URL ?? "https://techdrona-lms-app.web.app";

const all = [
  { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
  { name: "laptop", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 720 } } },
  { name: "tablet", use: { ...devices["iPad (gen 7)"], browserName: "chromium" as const } },
  { name: "tablet-landscape", use: { ...devices["iPad (gen 7) landscape"], browserName: "chromium" as const } },
  { name: "phone-android", use: { ...devices["Pixel 7"] } },
  { name: "phone-iphone", use: { ...devices["iPhone 13"] } }, // WebKit ≈ iOS Safari
  { name: "phone-small", use: { ...devices["iPhone SE"] } },
];
const wanted = (process.env.PROJECTS ?? "desktop").split(",").map((s) => s.trim()).filter(Boolean);

export default defineConfig({
  testDir: "./tests",
  timeout: 10 * 60_000,
  workers: Number(process.env.WORKERS ?? 2),
  retries: 0,
  reporter: [["list"], ["json", { outputFile: "out/results.json" }], ["html", { outputFolder: "out/html", open: "never" }]],
  outputDir: "out/artifacts",
  globalSetup: "./lib/global-setup.ts",
  use: {
    baseURL: LMS,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    actionTimeout: 20_000,
    navigationTimeout: 45_000,
  },
  // Chromium-only flag (WebKit refuses unknown options): small /dev/shm in the build container.
  projects: all
    .filter((p) => wanted.includes(p.name) || wanted.includes("all"))
    .map((p) => ((p.use as { defaultBrowserType?: string; browserName?: string }).browserName ?? (p.use as { defaultBrowserType?: string }).defaultBrowserType) === "chromium"
      ? { ...p, use: { ...p.use, launchOptions: { args: ["--disable-dev-shm-usage"] } } }
      : p),
});

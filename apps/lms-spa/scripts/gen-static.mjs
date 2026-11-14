// Static files for Firebase Hosting, from the build env (scripts/build-env.ts; Firebase values for
// any mode but `development`):
//
// - public/manifest.webmanifest: src/app/manifest.ts (copied unchanged from apps/web), executed
//   with Vite's SSR loader.
// - public/robots.txt: `Disallow: /`, exactly what Caddy answered on the LMS host. The LMS is the
//   back end of the website and is never indexed; X-Robots-Tag noindex is set by Hosting.
// - no sitemap.xml: Caddy answered 404 on the LMS host. A stale public/sitemap.xml is removed;
//   Hosting must route /sitemap.xml to the API function (404), see docs/firebase/agents/spa.md.
// - hosting-headers.json: firebase.json `hosting.headers` rules (src/spa/hosting-headers.ts).
//
// Usage: node scripts/gen-static.mjs [--mode production|development]
import { rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import { isDevMode, loadBuildEnv, publicEnv } from "./build-env.ts";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const modeArg = process.argv.indexOf("--mode");
const mode = modeArg > 0 ? process.argv[modeArg + 1] : "production";

const raw = loadBuildEnv(mode);
// The modules read `process.env` (rewritten to globalThis.__TD_ENV__ by vite.config.ts).
globalThis.__TD_ENV__ = { ...publicEnv(raw), TD_API_INTERNAL_URL: raw.NEXT_PUBLIC_BASE_URL ?? "" };

const server = await createServer({ root, configFile: join(root, "vite.config.ts"), mode, server: { middlewareMode: true, hmr: false }, appType: "custom", logLevel: "error", optimizeDeps: { noDiscovery: true, include: [] } });
try {
  const manifest = (await server.ssrLoadModule("/src/app/manifest.ts")).default();
  writeFileSync(join(root, "public", "manifest.webmanifest"), `${JSON.stringify(manifest, null, 2)}\n`);

  writeFileSync(join(root, "public", "robots.txt"), "User-agent: *\nDisallow: /\n");
  rmSync(join(root, "public", "sitemap.xml"), { force: true });

  const { hostingHeaders } = await server.ssrLoadModule("/src/spa/hosting-headers.ts");
  const { cspOptionsFromEnv } = await server.ssrLoadModule("/src/lib/security/csp.ts");
  const { siteBaseUrl } = await server.ssrLoadModule("/src/features/site-catalog/lib/site-url.ts");
  const csp = cspOptionsFromEnv({ ...raw, NODE_ENV: "production" });
  const authDomain = (raw.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN || (raw.NEXT_PUBLIC_FIREBASE_PROJECT_ID ? `${raw.NEXT_PUBLIC_FIREBASE_PROJECT_ID}.firebaseapp.com` : "")).trim();
  const headers = hostingHeaders({
    uploadOrigins: csp.uploadOrigins,
    // The browser fetches the website's /catalog.json (Next did it server-side): its origin.
    siteOrigin: csp.siteOrigin ?? new URL(siteBaseUrl(raw)).origin,
    analytics: !["0", "false", "off", "no"].includes(String(raw.TD_FIREBASE_ANALYTICS_ENABLED ?? "").toLowerCase()) && Boolean(raw.NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID),
    firebaseAuthDomain: authDomain || null,
  });
  const json = JSON.stringify(headers, null, 2);
  if (!isDevMode(mode)) {
    // Firebase build: only https origins from the build env, never the VM or a local service.
    const bad = json.match(/sslip\.io|localhost|127\.0\.0\.1|http:\/\/[^\s"']+/g);
    if (bad) throw new Error(`[gen-static] hosting-headers.json would contain non-Firebase origins: ${[...new Set(bad)].join(", ")}`);
  }
  writeFileSync(join(root, "hosting-headers.json"), `${json}\n`);
  console.log(`[gen-static] (${mode}) manifest.webmanifest, robots.txt (Disallow: /), hosting-headers.json; site ${raw.NEXT_PUBLIC_BASE_URL ?? "?"}`);
} finally {
  await server.close();
}

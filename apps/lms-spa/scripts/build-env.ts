/**
 * Build-time environment of the SPA, shared by vite.config.ts and scripts/gen-static.mjs (Node
 * runs this file directly with type stripping).
 *
 * - `development` (vite dev / tests): the repo-root `.env` (the VM / local values the Next app
 *   used) plus `apps/lms-spa/.env*`.
 * - any other mode (`vite build`, i.e. Firebase Hosting): `apps/lms-spa/.env.production` (Firebase
 *   origins, placeholder LMS site `techdrona-lms-app.web.app`) plus the deploy shell's
 *   environment. From the repo-root `.env` only the `NEXT_PUBLIC_FIREBASE_*` web config (project
 *   identity, public) is taken, so no VM or localhost origin reaches the bundle or the CSP.
 *
 * `VITE_X` is an alias of `NEXT_PUBLIC_X` and wins.
 */
import { fileURLToPath } from "node:url";
import { loadEnv } from "vite";

/** Public feature switches the browser reads (same names as the Next app). */
export const PUBLIC_SWITCHES = ["TD_GOOGLE_SIGNIN_ENABLED", "TD_FIREBASE_ANALYTICS_ENABLED"];

const appDir = fileURLToPath(new URL("../", import.meta.url));
const rootDir = fileURLToPath(new URL("../../../", import.meta.url));

export function isDevMode(mode: string): boolean {
  return mode === "development";
}

/** Every build-time value (public and CSP inputs such as S3_ENDPOINT_URL). Never bundled whole. */
export function loadBuildEnv(mode: string): Record<string, string> {
  const root = loadEnv(mode, rootDir, "");
  const app = loadEnv(mode, appDir, "");
  let raw: Record<string, string>;
  if (isDevMode(mode)) raw = { ...root, ...app };
  else {
    const firebaseIdentity = Object.fromEntries(Object.entries(root).filter(([k]) => k.startsWith("NEXT_PUBLIC_FIREBASE_")));
    // loadEnv(appDir) already lets the shell environment override .env.production.
    raw = { ...firebaseIdentity, ...app };
  }
  for (const [k, v] of Object.entries(raw)) {
    if (k.startsWith("VITE_")) raw[`NEXT_PUBLIC_${k.slice(5)}`] = v;
  }
  raw.NODE_ENV = isDevMode(mode) ? "development" : "production";
  return raw;
}

/** The subset that is inlined into the browser bundle (`process.env` in the copied code). */
export function publicEnv(raw: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(raw)) {
    if (k.startsWith("NEXT_PUBLIC_") || PUBLIC_SWITCHES.includes(k) || k === "NODE_ENV") out[k] = v;
  }
  return out;
}

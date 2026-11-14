/**
 * Response headers Firebase Hosting must send for the SPA (the Next app set them in
 * next.config.ts `headers()` and middleware.ts). scripts/gen-static.mjs writes them to
 * `hosting-headers.json` in firebase.json `hosting.headers` format for the platform agent.
 *
 * CSP: the Next middleware used a per-request nonce + 'strict-dynamic'. A static SPA cannot carry
 * a nonce, and 'strict-dynamic' without one would block every script, so the policy is the same
 * `buildCsp()` output with the nonce and 'strict-dynamic' removed: scripts are allowed from 'self'
 * plus the exact third-party hosts already listed as the CSP2 fallback (Razorpay, VdoCipher,
 * Google sign-in, Google Analytics). Still no 'unsafe-inline' / 'unsafe-eval' for scripts.
 *
 * Per-path policies stay per path: /login and /signup (Google sign-in hosts, COOP
 * same-origin-allow-popups) and /admin/college-data (frame-src 'self') are always opened with a
 * full page load by the SPA (src/spa/nav-store.ts DOCUMENT_ROUTES) so their own headers apply.
 */
import { buildCsp, toOrigin, type CspOptions } from "@/lib/security/csp";

export interface HostingHeaderRule {
  source: string;
  headers: { key: string; value: string }[];
}

export interface HostingCspInput extends Omit<CspOptions, "dev"> {
  /** Website origin: the browser now fetches its /catalog.json (server-side in Next). */
  siteOrigin?: string | null;
  /** Firebase Auth domain (host) for Google sign-in on /login and /signup. */
  firebaseAuthDomain?: string | null;
}

/** Firestore REST (public course state for the site catalogue, fetched by the browser now). */
export const FIRESTORE_REST = "https://firestore.googleapis.com";

export function staticCsp(opts: HostingCspInput): string {
  const nonce = "SPA";
  const csp = buildCsp(nonce, { ...opts, dev: false });
  const site = opts.siteOrigin ? toOrigin(opts.siteOrigin, false) : null;
  return csp
    .split("; ")
    .map((d) => {
      const [name, ...values] = d.split(" ");
      let v = values.filter((x) => x !== `'nonce-${nonce}'` && x !== "'strict-dynamic'");
      if (name === "connect-src") v = [...new Set([...v, FIRESTORE_REST, ...(site ? [site] : [])])];
      return `${name} ${v.join(" ")}`;
    })
    .join("; ");
}

const BASE = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(self)" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
];

const PORTAL_TILES = "https://tile.openstreetmap.org https://*.tile.openstreetmap.org https://basemaps.cartocdn.com https://*.basemaps.cartocdn.com";
/** The College Data Portal's own CSP in proxy mode (frame-ancestors 'self'). */
export const COLLEGE_PORTAL_CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "font-src 'self' data: https://fonts.gstatic.com",
  `img-src 'self' data: blob: ${PORTAL_TILES}`,
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'self'",
].join("; ");
const COLLEGE_PORTAL_HEADERS = [
  { key: "X-Frame-Options", value: "SAMEORIGIN" },
  { key: "Content-Security-Policy", value: COLLEGE_PORTAL_CSP },
  { key: "Cache-Control", value: "private, no-store" },
];

/** public/ folders and root files served as-is (not content-hashed). docs/firebase/cdn-caching.md */
export const STATIC_DIRS = ["brand", "fonts", "vendor"];
export const STATIC_ROOT_FILES = ["favicon.ico", "favicon-32.png", "apple-touch-icon.png", "icon-512.png", "manifest.webmanifest", "robots.txt"];
export const STATIC_CACHE = "public, max-age=86400";
/** GET /api/public/courses/status: browser 30 s, CDN 60 s, so a status change shows within ~1 min. */
export const COURSE_STATUS_CACHE = "public, max-age=30, s-maxage=60";

/** Rules in firebase.json order (later rules override earlier ones for the same header key). */
export function hostingHeaders(opts: HostingCspInput): HostingHeaderRule[] {
  const general = { ...opts, firebaseAuthDomain: null, frameSelf: false };
  const signIn = { ...opts, frameSelf: false };
  return [
    // index.html (served for every page route) is revalidated on each load: a deploy replaces the
    // hashed asset names it references. It carries no user data (pages load data via /api/v1).
    { source: "/**", headers: [...BASE, { key: "Content-Security-Policy", value: staticCsp(general) }, { key: "Cache-Control", value: "no-cache" }] },
    { source: "/assets/**", headers: [{ key: "Cache-Control", value: "public, max-age=31536000, immutable" }] },
    // Non-hashed files from public/ (icons, brand images, self-hosted fonts, Monaco, manifest,
    // robots.txt): same URL across deploys, so a day, not a year. A deploy clears the CDN copy.
    ...[...STATIC_DIRS.map((d) => `/${d}/**`), `/{${STATIC_ROOT_FILES.join(",")}}`].map((source) => ({
      source,
      headers: [{ key: "Cache-Control", value: STATIC_CACHE }],
    })),
    // Hosting headers REPLACE a function's own Cache-Control on 2xx answers (measured
    // 2026-11-14: the `/**` no-cache above overwrote the API's `private, no-store`). API answers
    // are personal by default: never stored by the CDN or the browser.
    { source: "/api/**", headers: [{ key: "Cache-Control", value: "private, no-store" }] },
    // The one API answer that is the same for every visitor: the website asks for it on every
    // page view. The CDN serves it for a minute (the admin screen promises "within a minute");
    // errors keep the function's no-store (Hosting does not override non-2xx answers).
    { source: "/api/public/courses/status", headers: [{ key: "Cache-Control", value: COURSE_STATUS_CACHE }] },
    // Google sign-in (Firebase Auth signInWithPopup) needs the popup to keep its opener.
    ...["/login", "/signup"].map((source) => ({
      source,
      headers: [
        { key: "Cross-Origin-Opener-Policy", value: "same-origin-allow-popups" },
        { key: "Content-Security-Policy", value: staticCsp(signIn) },
      ],
    })),
    // The only page allowed to frame the same-origin College Data Portal.
    { source: "/admin/college-data", headers: [{ key: "Content-Security-Policy", value: staticCsp({ ...general, frameSelf: true }) }] },
    // The portal itself (lmsApi -> Cloud Run college-portal) may be framed same-origin. Hosting
    // headers REPLACE the function's own, so the portal's CSP (apps/college-data/portal
    // server.js cspFor, proxy mode; index.html has no inline scripts) and its no-store caching are
    // repeated here; static assets revalidate (the portal answers 304).
    ...["/college-portal", "/college-portal/**"].map((source) => ({ source, headers: COLLEGE_PORTAL_HEADERS })),
    { source: "/college-portal/{css,js,vendor,assets}/**", headers: [{ key: "Cache-Control", value: "private, no-cache" }] },
  ];
}

/**
 * Browser replacement for the `process.env` the Next app read. Vite rewrites every
 * `process.env` reference to `globalThis.__TD_ENV__` (vite.config.ts `define`); this module,
 * imported first by main.tsx, fills it from the build-time public values.
 *
 * `TD_API_INTERNAL_URL` is the page origin so server-side helpers that built internal API URLs
 * (site catalogue course status) call the same-origin `/api/v1/**` Hosting rewrite instead.
 */
declare const __TD_BUILD_ENV__: Record<string, string>;

const g = globalThis as { __TD_ENV__?: Record<string, string | undefined> };
if (!g.__TD_ENV__) {
  g.__TD_ENV__ = {
    ...__TD_BUILD_ENV__,
    TD_API_INTERNAL_URL: typeof window !== "undefined" ? window.location.origin : "",
  };
}

export {};

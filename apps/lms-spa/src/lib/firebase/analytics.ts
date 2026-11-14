/**
 * Firebase Analytics (GA4), loaded ONLY after the learner grants the `analytics_product`
 * consent (docs/firebase/MIGRATION-PLAN.md §5.2; consent purposes: identity/schemas.py).
 *
 * - Before consent nothing loads: no Firebase/gtag script, no cookies, no requests.
 * - The consent itself lives on the server (ME-05 `GET /me/consents`). This module keeps a
 *   per-browser marker (`localStorage td.analytics_consent`) so public pages know without a
 *   request; the marker is refreshed from the server on student-portal pages, cleared on
 *   withdrawal (Privacy settings) and on sign-out. Minors cannot grant this purpose.
 * - Consent Mode v2: everything denied except `analytics_storage`; ad signals always denied;
 *   Google signals and ad personalisation off; no automatic page_view (we send our own with a
 *   scrubbed path: ids and tokens replaced, never a query string).
 * - No PII: event parameters are limited to an allow-list of non-identifying keys.
 * - Never on exam/attempt pages, guardian-consent, password-reset/verification links, or the
 *   staff consoles (admin, finance, security, studio, trainer, evaluator, desk).
 * - The LMS's first-party analytics pipeline (src/lib/analytics) stays the source for learning
 *   reports; GA4 is for product and marketing funnels only.
 */

import type { FirebaseWebConfig } from "./config";

export const CONSENT_KEY = "td.analytics_consent";
export const CONSENT_EVENT = "td:analytics-consent";
const APP_NAME = "td-analytics";

export type GaEvent = "page_view" | "sign_up" | "login" | "purchase" | "course_view";

const ALLOWED_PARAMS = new Set(["page_path", "method", "currency", "value", "transaction_id", "course_slug", "items_count"]);

type AnalyticsMod = typeof import("firebase/analytics");
interface Loaded {
  mod: AnalyticsMod;
  analytics: import("firebase/analytics").Analytics;
}
let loaded: Loaded | null = null;
let loading: Promise<Loaded | null> | null = null;
let enabled = false;

export function hasAnalyticsConsent(): boolean {
  try {
    return globalThis.localStorage?.getItem(CONSENT_KEY) === "granted";
  } catch {
    return false;
  }
}

/** Record the learner's current `analytics_product` choice in this browser. */
export function setAnalyticsConsent(granted: boolean): void {
  try {
    if (granted) globalThis.localStorage?.setItem(CONSENT_KEY, "granted");
    else globalThis.localStorage?.removeItem(CONSENT_KEY);
  } catch {
    /* storage blocked: analytics simply stays off */
  }
  if (!granted) disableAnalytics();
  try {
    globalThis.dispatchEvent?.(new Event(CONSENT_EVENT));
  } catch {
    /* non-browser */
  }
}

const BLOCKED_PREFIXES = ["/admin", "/finance", "/security", "/studio", "/trainer", "/evaluator", "/desk", "/guardian-consent", "/reset-password", "/change-password", "/accept-terms", "/verify", "/unblock-request", "/account", "/api"];

/** Whether GA may run on this path (even with consent). */
export function analyticsAllowedPath(pathname: string): boolean {
  const p = pathname.toLowerCase();
  if (BLOCKED_PREFIXES.some((b) => p === b || p.startsWith(`${b}/`))) return false;
  // Exams and attempts (integrity-sensitive), anywhere in the student portal.
  if (/\/(attempts?|exams?|tests)(\/|$)/.test(p)) return false;
  return true;
}

const ID_SEGMENT = /^(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|\d{3,}|[A-Za-z0-9_-]{24,})$/i;

/** Path with ids/tokens replaced by `:id`; never includes the query string or fragment. */
export function scrubPath(pathname: string): string {
  const path = pathname.split(/[?#]/)[0] ?? "/";
  return path
    .split("/")
    .map((seg) => (seg && ID_SEGMENT.test(seg) ? ":id" : seg))
    .join("/")
    .slice(0, 200) || "/";
}

function cleanParams(params: Record<string, string | number | undefined>): Record<string, string | number> {
  const out: Record<string, string | number> = {};
  for (const [k, v] of Object.entries(params)) {
    if (!ALLOWED_PARAMS.has(k) || v === undefined) continue;
    if (typeof v === "string" && /@|\+?\d{10,}/.test(v)) continue; // never an email or phone
    out[k] = typeof v === "string" ? v.slice(0, 100) : v;
  }
  return out;
}

/** Load Firebase Analytics (once). Call only when consent is granted. */
export async function enableAnalytics(config: FirebaseWebConfig): Promise<boolean> {
  if (!config.measurementId || !hasAnalyticsConsent()) return false;
  loading ??= (async () => {
    try {
      const [{ initializeApp, getApps }, mod] = await Promise.all([import("firebase/app"), import("firebase/analytics")]);
      if (!(await mod.isSupported())) return null;
      const app =
        getApps().find((a) => a.name === APP_NAME) ??
        initializeApp(
          { apiKey: config.apiKey, authDomain: config.authDomain, projectId: config.projectId, appId: config.appId, messagingSenderId: config.messagingSenderId, measurementId: config.measurementId },
          APP_NAME,
        );
      // Consent Mode v2 must be set before initialisation.
      mod.setConsent({
        analytics_storage: "granted",
        ad_storage: "denied",
        ad_user_data: "denied",
        ad_personalization: "denied",
        functionality_storage: "denied",
        personalization_storage: "denied",
        security_storage: "denied",
      });
      const analytics = mod.initializeAnalytics(app, {
        config: { send_page_view: false, allow_google_signals: false, allow_ad_personalization_signals: false },
      });
      return { mod, analytics };
    } catch {
      return null;
    }
  })();
  loaded = await loading;
  if (!loaded) {
    loading = null;
    return false;
  }
  if (!hasAnalyticsConsent()) return false; // withdrawn while loading
  loaded.mod.setAnalyticsCollectionEnabled(loaded.analytics, true);
  enabled = true;
  return true;
}

/** Stop collection and delete GA cookies (consent withdrawn or signed out). */
export function disableAnalytics(): void {
  if (loaded) loaded.mod.setAnalyticsCollectionEnabled(loaded.analytics, false);
  enabled = false;
  if (typeof document === "undefined") return;
  const host = globalThis.location?.hostname ?? "";
  const parts = host.split(".");
  const domains = ["", host, ...parts.slice(1).map((_, i) => `.${parts.slice(i + 1).join(".")}`)];
  for (const raw of document.cookie.split(";")) {
    const name = raw.split("=")[0]?.trim() ?? "";
    if (!name.startsWith("_ga") && name !== "_gid") continue;
    for (const d of domains) {
      document.cookie = `${name}=; Max-Age=0; path=/${d ? `; domain=${d}` : ""}`;
    }
  }
}

/** Log a GA4 event if analytics is running (no-op otherwise). Params are allow-listed. */
export function trackEvent(name: GaEvent, params: Record<string, string | number | undefined> = {}): void {
  if (!enabled || !loaded || !hasAnalyticsConsent()) return;
  if (typeof location !== "undefined" && !analyticsAllowedPath(location.pathname)) return;
  try {
    loaded.mod.logEvent(loaded.analytics, name as string, cleanParams(params));
  } catch {
    /* analytics must never break the page */
  }
}

/** Test hook. */
export function _resetAnalyticsForTests(): void {
  loaded = null;
  loading = null;
  enabled = false;
}

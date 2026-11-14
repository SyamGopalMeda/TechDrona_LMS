import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import nextConfig from "../../../next.config";
import { buildCsp, parseCsp } from "../security/csp";
import { _resetAnalyticsForTests, analyticsAllowedPath, CONSENT_KEY, enableAnalytics, hasAnalyticsConsent, scrubPath, setAnalyticsConsent, trackEvent } from "./analytics";
import { analyticsConfig, firebaseWebConfig, googleSignInConfig } from "./config";

const ENV = {
  NEXT_PUBLIC_FIREBASE_API_KEY: "test-api-key",
  NEXT_PUBLIC_FIREBASE_PROJECT_ID: "techdrona-lms",
  NEXT_PUBLIC_FIREBASE_APP_ID: "1:123:web:abc",
  NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID: "G-TEST1234",
};

describe("firebase config", () => {
  it("builds the public web config and derives authDomain", () => {
    expect(firebaseWebConfig(ENV)).toMatchObject({ projectId: "techdrona-lms", authDomain: "techdrona-lms.firebaseapp.com", measurementId: "G-TEST1234" });
    expect(firebaseWebConfig({ ...ENV, NEXT_PUBLIC_FIREBASE_API_KEY: "" })).toBeNull();
    expect(firebaseWebConfig({ ...ENV, NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID: "not-an-id" })?.measurementId).toBeUndefined();
  });

  it("kill switches turn Google sign-in and analytics off independently", () => {
    expect(googleSignInConfig(ENV)).not.toBeNull();
    expect(googleSignInConfig({ ...ENV, TD_GOOGLE_SIGNIN_ENABLED: "false" })).toBeNull();
    expect(analyticsConfig(ENV)).not.toBeNull();
    expect(analyticsConfig({ ...ENV, TD_FIREBASE_ANALYTICS_ENABLED: "off" })).toBeNull();
    expect(analyticsConfig({ ...ENV, NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID: "" })).toBeNull();
  });
});

describe("CSP and COOP for Firebase", () => {
  it("adds Firebase Auth hosts only when a page offers Google sign-in", () => {
    const off = parseCsp(buildCsp("n", { dev: false }));
    expect(off["connect-src"]).not.toContain("https://identitytoolkit.googleapis.com");
    expect(off["frame-src"]).not.toContain("https://accounts.google.com");
    const on = parseCsp(buildCsp("n", { dev: false, firebaseAuthDomain: "techdrona-lms.firebaseapp.com" }));
    expect(on["connect-src"]).toEqual(expect.arrayContaining(["https://identitytoolkit.googleapis.com", "https://securetoken.googleapis.com"]));
    expect(on["frame-src"]).toEqual(expect.arrayContaining(["https://techdrona-lms.firebaseapp.com", "https://accounts.google.com"]));
    expect(on["script-src"]).toContain("https://apis.google.com");
    expect(on["script-src"]).not.toContain("'unsafe-inline'");
    // a malformed authDomain never becomes a source
    const bad = parseCsp(buildCsp("n", { dev: false, firebaseAuthDomain: "evil.com; script-src *" }));
    expect(bad["frame-src"]?.join(" ")).not.toContain("evil.com");
  });

  it("adds Google Analytics hosts only when analytics is enabled", () => {
    expect(parseCsp(buildCsp("n", { dev: false }))["connect-src"]).not.toContain("https://*.google-analytics.com");
    const on = parseCsp(buildCsp("n", { dev: false, analytics: true }));
    expect(on["connect-src"]).toEqual(expect.arrayContaining(["https://*.google-analytics.com", "https://firebaseinstallations.googleapis.com"]));
    expect(on["script-src"]).toContain("https://www.googletagmanager.com");
    expect(on["img-src"]).toContain("https://*.google-analytics.com");
  });

  it("relaxes COOP to same-origin-allow-popups on /login and /signup only", async () => {
    const rules = (await nextConfig.headers?.()) ?? [];
    const coop = (source: string) =>
      rules
        .filter((r) => r.source === source || r.source === "/:path*")
        .flatMap((r) => r.headers)
        .filter((h) => h.key === "Cross-Origin-Opener-Policy")
        .map((h) => h.value)
        .at(-1);
    expect(coop("/login")).toBe("same-origin-allow-popups");
    expect(coop("/signup")).toBe("same-origin-allow-popups");
    expect(coop("/app")).toBe("same-origin");
  });
});

describe("analytics consent gate", () => {
  beforeEach(() => {
    localStorage.clear();
    _resetAnalyticsForTests();
  });
  afterEach(() => vi.restoreAllMocks());

  it("never loads without the analytics_product consent", async () => {
    const cfg = firebaseWebConfig(ENV)!;
    expect(hasAnalyticsConsent()).toBe(false);
    await expect(enableAnalytics(cfg)).resolves.toBe(false);
    expect(() => trackEvent("page_view", { page_path: "/" })).not.toThrow();
    setAnalyticsConsent(true);
    expect(localStorage.getItem(CONSENT_KEY)).toBe("granted");
    setAnalyticsConsent(false);
    expect(localStorage.getItem(CONSENT_KEY)).toBeNull();
  });

  it("withdrawal deletes GA cookies", () => {
    document.cookie = "_ga=GA1.1.123; path=/";
    document.cookie = "_ga_TEST1234=GS1.1; path=/";
    document.cookie = "keep=1; path=/";
    setAnalyticsConsent(false);
    expect(document.cookie).not.toContain("_ga");
    expect(document.cookie).toContain("keep=1");
  });

  it("blocks exam, attempt, guardian and staff pages", () => {
    for (const p of ["/app/tests/abc/attempt", "/app/attempts/1", "/app/exams/x", "/admin", "/finance/x", "/security", "/guardian-consent/tok", "/trainer/batches", "/reset-password/tok"]) {
      expect(analyticsAllowedPath(p)).toBe(false);
    }
    for (const p of ["/", "/courses", "/courses/python-basics", "/pricing", "/app", "/app/courses/123"]) {
      expect(analyticsAllowedPath(p)).toBe(true);
    }
  });

  it("scrubs ids and tokens from paths and drops the query", () => {
    expect(scrubPath("/app/orders/0193a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b?x=1")).toBe("/app/orders/:id");
    expect(scrubPath("/verify/email/AbCdEfGhIjKlMnOpQrStUvWxYz012345")).toBe("/verify/email/:id");
    expect(scrubPath("/courses/python-basics")).toBe("/courses/python-basics");
  });
});

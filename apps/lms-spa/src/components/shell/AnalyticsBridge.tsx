"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import type { FirebaseWebConfig } from "@/lib/firebase/config";
import { analyticsAllowedPath, CONSENT_EVENT, enableAnalytics, hasAnalyticsConsent, scrubPath, setAnalyticsConsent, trackEvent } from "@/lib/firebase/analytics";

/** Once per tab: the server's consent record is the truth (withdrawn on another device, etc.). */
let consentSynced = false;

async function syncConsentFromServer(): Promise<void> {
  try {
    const res = await fetch("/api/v1/me/consents", { credentials: "same-origin", headers: { accept: "application/json" } });
    if (!res.ok) return;
    const body = (await res.json()) as { data?: { purpose: string; state: string; available?: boolean }[] };
    const row = body.data?.find((d) => d.purpose === "analytics_product");
    const granted = row?.state === "granted" && row.available !== false;
    if (granted !== hasAnalyticsConsent()) setAnalyticsConsent(granted);
  } catch {
    /* offline: keep the current marker */
  }
}

/**
 * Firebase Analytics loader + page_view / course_view (docs/firebase/MIGRATION-PLAN.md §5.2).
 * Renders nothing. `config` is null when analytics is not configured or switched off
 * (`TD_FIREBASE_ANALYTICS_ENABLED=false`), in which case this component does nothing at all.
 */
export function AnalyticsBridge({ config }: { config: FirebaseWebConfig | null }) {
  const pathname = usePathname() ?? "/";
  const [consent, setConsent] = useState(false);

  useEffect(() => {
    if (!config) return;
    const sync = () => setConsent(hasAnalyticsConsent());
    sync();
    globalThis.addEventListener(CONSENT_EVENT, sync);
    globalThis.addEventListener("storage", sync);
    return () => {
      globalThis.removeEventListener(CONSENT_EVENT, sync);
      globalThis.removeEventListener("storage", sync);
    };
  }, [config]);

  useEffect(() => {
    // Student portal pages are only reached with a session: refresh the consent there.
    if (!config || consentSynced || !(pathname === "/app" || pathname.startsWith("/app/"))) return;
    consentSynced = true;
    void syncConsentFromServer();
  }, [config, pathname]);

  useEffect(() => {
    if (!config || !consent || !analyticsAllowedPath(pathname)) return;
    let cancelled = false;
    void enableAnalytics(config).then((ok) => {
      if (!ok || cancelled) return;
      trackEvent("page_view", { page_path: scrubPath(pathname) });
      const course = /^\/courses\/([a-z0-9-]{1,80})$/.exec(pathname);
      if (course) trackEvent("course_view", { course_slug: course[1] });
    });
    return () => {
      cancelled = true;
    };
  }, [config, consent, pathname]);

  return null;
}

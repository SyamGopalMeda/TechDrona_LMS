"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card } from "@/components/ui";

/** Same-origin entry of the College Data Portal (kept in sync with CollegeDataPortal.tsx). */
const ENTRY = "/college-portal/index.html";

/**
 * Live audit 2026-11-14 (admin.md F1): the College Data Portal is not deployed on Firebase Hosting
 * yet (it is being migrated). Hosting then answers /college-portal/** with the LMS app itself
 * (the `** → /index.html` fallback, HTTP 200), which showed "Page not found" or a blocked frame.
 *
 * The real portal is a static page without the LMS app's `<div id="root">` mount point, so:
 * - true: the portal page is served;
 * - false: 404/5xx, or the LMS app came back instead (not deployed yet);
 * - null: unknown (offline, or no fetch): callers behave as before.
 */
export function isCollegePortalPage(status: number, html: string): boolean {
  if (status < 200 || status >= 300) return false;
  return !/<div\s+id=["']root["']/i.test(html);
}

let cache: Promise<boolean | null> | null = null;

/** Tests only. */
export function resetCollegePortalCheck(): void {
  cache = null;
}

export function checkCollegePortal(): Promise<boolean | null> {
  cache ??= (async () => {
    try {
      const res = await fetch(ENTRY, { credentials: "same-origin", cache: "no-store", headers: { accept: "text/html" } });
      return isCollegePortalPage(res.status, await res.text());
    } catch {
      cache = null;
      return null;
    }
  })();
  return cache;
}

/** `true` / `false` once known, `null` while checking or unknown. */
export function useCollegePortalAvailable(): boolean | null {
  const [state, setState] = useState<boolean | null>(null);
  useEffect(() => {
    let live = true;
    void checkCollegePortal().then((v) => {
      if (live) setState(v);
    });
    return () => {
      live = false;
    };
  }, []);
  return state;
}

/** The friendly "being moved" message, used inside the Admin shell and on the stand-alone page. */
export function CollegePortalMoving({ standalone = false }: { standalone?: boolean }) {
  return (
    <Card title="College Data Portal is being moved" icon="building">
      <div role="status" className="space-y-3 text-sm text-fg-secondary">
        <p>
          We are moving the College Data Portal (colleges, contacts, calls, targets and enrolments) to its new home. It will be available here again
          soon. Your data is safe and nothing needs to be done.
        </p>
        <p className="flex flex-wrap gap-4">
          {standalone ? (
            <Link href="/admin" className="font-semibold text-fg-link underline hover:text-fg-link-hover">
              Back to Admin
            </Link>
          ) : null}
          <Link href="/modules" className="font-semibold text-fg-link underline hover:text-fg-link-hover">
            All modules
          </Link>
        </p>
      </div>
    </Card>
  );
}

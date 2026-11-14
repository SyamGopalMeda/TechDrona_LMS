"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { LoadingBlock } from "@/components/ui";
import { type ContinueArea, needsDocumentLoad, pickContinueTarget, readLastPage } from "./last-page";

/**
 * /continue: opens the page this browser last had open (in the requested module), else `fallback`.
 * The remembered page lives in localStorage, so the choice is made here in the browser.
 */
export function ContinueRedirect({ area, portals, fallback }: { area?: ContinueArea; portals: string[] | null; fallback: string }) {
  const router = useRouter();
  useEffect(() => {
    const target = pickContinueTarget({ record: readLastPage(), area, portals, fallback });
    // The College Data Portal needs its own document CSP (frame-src 'self'): load it as a document.
    if (needsDocumentLoad(target)) window.location.replace(target);
    else router.replace(target);
  }, [router, area, portals, fallback]);
  return (
    <main id="main" className="grid min-h-dvh place-items-center bg-surface-canvas px-4">
      <div className="w-full max-w-sm text-center">
        <p aria-hidden="true" className="mb-3 font-display text-base font-semibold text-fg-heading">Opening your last page…</p>
        <LoadingBlock label="Opening your last page…" size="row" rows={2} />
      </div>
    </main>
  );
}

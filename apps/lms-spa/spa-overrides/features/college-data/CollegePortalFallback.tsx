"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Logo } from "@/components/ui/Logo";
import { LoadingBlock } from "@/components/ui";
import { CollegePortalMoving } from "./availability";
import { loadedAsDocument } from "./CollegeDataPortal";

/**
 * /college-portal/** inside the LMS app. Reached by a full page load only when Hosting has no
 * College Data Portal files (not deployed yet): show "being moved" instead of "Page not found".
 * Reached by client-side routing (a soft link), the portal may well be deployed: reload once as a
 * real document so Hosting can serve it (the reload then lands here only if it is still missing).
 */
export function CollegePortalFallback() {
  const [show, setShow] = useState(false);
  useEffect(() => {
    if (loadedAsDocument(window.location.pathname)) setShow(true);
    else window.location.replace(window.location.href);
  }, []);
  return (
    <div className="min-h-dvh bg-surface-canvas text-fg">
      <header className="flex items-center gap-3 border-b border-line bg-surface px-4 py-3 sm:px-6">
        <Link href="/admin" aria-label="Tech Drona — Admin home" className="flex items-center rounded-md focus-visible:shadow-focus focus-visible:outline-none">
          <Logo alt="" tone="auto" className="h-7 sm:h-8" />
        </Link>
      </header>
      <main id="main" className="mx-auto w-full max-w-2xl px-4 py-8 sm:px-6 sm:py-12">
        <h1 className="mb-6 font-display text-2xl font-bold text-fg-heading">College Data Portal</h1>
        {show ? <CollegePortalMoving standalone /> : <LoadingBlock label="Opening the College Data Portal…" size="row" rows={2} />}
      </main>
    </div>
  );
}

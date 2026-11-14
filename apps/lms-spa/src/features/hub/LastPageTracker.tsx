"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { useEffect } from "react";
import { recordLastPage } from "./last-page";

/**
 * Remembers the current portal page (pathname + search) on every navigation, for /continue.
 * Non-portal pages are ignored by recordLastPage. Render inside <Suspense> (useSearchParams).
 */
export function LastPageTracker() {
  const pathname = usePathname();
  const search = useSearchParams()?.toString() ?? "";
  useEffect(() => {
    if (pathname) recordLastPage(search ? `${pathname}?${search}` : pathname);
  }, [pathname, search]);
  return null;
}

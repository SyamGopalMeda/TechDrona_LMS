"use client";

import { SegmentError } from "@/components/shell/SegmentError";

/**
 * Root route error boundary, for routes outside the per-segment boundaries (each portal and the
 * public site has its own error.tsx that keeps its shell). User-safe message, error digest as the
 * reference, "Try again" plus a link home so nobody is stranded.
 */
export default function RouteError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main id="main" className="px-4 py-12">
      <SegmentError error={error} reset={reset} homeHref="/" homeLabel="Go to home page" />
    </main>
  );
}

"use client";

import { useEffect, useRef } from "react";
import { ErrorState } from "@/components/ui/Display";

export interface SegmentErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
  /** The portal (or site) home this segment belongs to, e.g. "/admin". */
  homeHref: string;
  homeLabel: string;
}

/**
 * Body of every per-segment `error.tsx` (UI audit 0.2). Rendered by Next inside the segment's
 * layout, so the header, nav and footer stay and the user is never stranded on a bare error box.
 * Shows a heading for screen-reader/heading navigation, the kit ErrorState with "Try again" (the
 * route's reset) and a link to the portal home, and the error digest as the support reference.
 * Never shows `error.message` (in development it can contain internals).
 */
export function SegmentError({ error, reset, homeHref, homeLabel }: SegmentErrorProps) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    // Keep the failure visible in the browser console / monitoring, like the default boundary does.
    console.error(error);
    headingRef.current?.focus();
  }, [error]);

  return (
    <div className="mx-auto max-w-prose py-8">
      <h1 ref={headingRef} tabIndex={-1} className="mb-4 font-display text-2xl font-bold text-fg focus:outline-none">
        This page could not be loaded
      </h1>
      <ErrorState
        title="Something went wrong"
        detail="Please try again. If it keeps happening, contact support with the reference below."
        requestId={error.digest ?? null}
        onRetry={reset}
        secondaryAction={{ href: homeHref, label: homeLabel }}
      />
    </div>
  );
}

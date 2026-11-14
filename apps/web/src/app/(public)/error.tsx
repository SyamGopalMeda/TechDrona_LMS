"use client";

import { SegmentError } from "@/components/shell/SegmentError";

/** Errors in Public pages render inside its layout (header and navigation stay), with a way home. */
export default function PublicError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <SegmentError error={error} reset={reset} homeHref="/" homeLabel="Go to home page" />;
}

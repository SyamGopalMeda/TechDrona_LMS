"use client";

import { SegmentError } from "@/components/shell/SegmentError";

/** Errors in Security pages render inside its layout (header and navigation stay), with a way home. */
export default function SecurityError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <SegmentError error={error} reset={reset} homeHref="/security" homeLabel="Go to security home" />;
}

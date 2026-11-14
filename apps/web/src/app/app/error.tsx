"use client";

import { SegmentError } from "@/components/shell/SegmentError";

/** Errors in Student pages render inside its layout (header and navigation stay), with a way home. */
export default function StudentError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <SegmentError error={error} reset={reset} homeHref="/app" homeLabel="Go to my dashboard" />;
}

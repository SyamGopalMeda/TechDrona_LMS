"use client";

import { SegmentError } from "@/components/shell/SegmentError";

/** Errors in Desk pages render inside its layout (header and navigation stay), with a way home. */
export default function DeskError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <SegmentError error={error} reset={reset} homeHref="/desk" homeLabel="Go to desk home" />;
}

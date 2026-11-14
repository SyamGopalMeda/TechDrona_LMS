"use client";

import { SegmentError } from "@/components/shell/SegmentError";

/** Errors in Studio pages render inside its layout (header and navigation stay), with a way home. */
export default function StudioError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <SegmentError error={error} reset={reset} homeHref="/studio" homeLabel="Go to studio home" />;
}

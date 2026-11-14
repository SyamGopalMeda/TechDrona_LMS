"use client";

import { SegmentError } from "@/components/shell/SegmentError";

/** Errors in Trainer pages render inside its layout (header and navigation stay), with a way home. */
export default function TrainerError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <SegmentError error={error} reset={reset} homeHref="/trainer" homeLabel="Go to trainer home" />;
}

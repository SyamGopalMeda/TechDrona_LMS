"use client";

import { SegmentError } from "@/components/shell/SegmentError";

/** Errors in Finance pages render inside its layout (header and navigation stay), with a way home. */
export default function FinanceError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <SegmentError error={error} reset={reset} homeHref="/finance" homeLabel="Go to finance home" />;
}

"use client";

import { SegmentError } from "@/components/shell/SegmentError";

/** Errors in Evaluator pages render inside its layout (header and navigation stay), with a way home. */
export default function EvaluatorError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <SegmentError error={error} reset={reset} homeHref="/evaluator" homeLabel="Go to evaluator home" />;
}

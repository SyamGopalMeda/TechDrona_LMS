"use client";

import { SegmentError } from "@/components/shell/SegmentError";

/** Errors in Admin pages render inside its layout (header and navigation stay), with a way home. */
export default function AdminError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <SegmentError error={error} reset={reset} homeHref="/admin" homeLabel="Go to admin home" />;
}

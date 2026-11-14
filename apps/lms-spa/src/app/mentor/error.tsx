"use client";

import { SegmentError } from "@/components/shell/SegmentError";

/** Errors in Mentor pages render inside its layout (header and navigation stay), with a way home. */
export default function MentorError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <SegmentError error={error} reset={reset} homeHref="/mentor" homeLabel="Go to mentor home" />;
}

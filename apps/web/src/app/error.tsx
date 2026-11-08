"use client";

import { ErrorState } from "@/components/ui";

/** Route error boundary: user-safe message, error digest as reference, retry. */
export default function RouteError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="mx-auto max-w-prose px-4 py-12">
      <ErrorState error={error} requestId={error.digest ?? null} onRetry={reset} />
    </div>
  );
}

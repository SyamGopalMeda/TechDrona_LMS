"use client";

import "./globals.css";

/**
 * FE-33: last-resort boundary for errors in the root layout itself (route errors use
 * error.tsx). Must render its own <html>/<body>. Shows the digest as the support reference.
 */
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <html lang="en-IN">
      <body className="bg-surface-canvas text-fg">
        <main id="main" className="mx-auto max-w-prose px-4 py-16 text-center">
          <h1 className="font-display text-2xl font-bold">Something went wrong</h1>
          <p className="mt-2 text-sm text-fg-muted">The page could not be loaded. Please try again.</p>
          {error.digest ? (
            <p className="mt-2 text-xs text-fg-muted">
              Reference: <span className="select-all font-mono">{error.digest}</span>
            </p>
          ) : null}
          <div className="mt-6 flex justify-center gap-3">
            <button type="button" onClick={reset} className="inline-flex h-10 items-center rounded-md bg-brand px-4 text-sm font-medium text-brand-on hover:bg-brand-hover focus-visible:shadow-focus focus-visible:outline-none">
              Try again
            </button>
            {/* A plain anchor: the router may be the thing that failed. */}
            {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
            <a href="/" className="inline-flex h-10 items-center rounded-md border border-line-control px-4 text-sm font-medium text-fg hover:bg-surface-hover focus-visible:shadow-focus focus-visible:outline-none">
              Home page
            </a>
          </div>
        </main>
      </body>
    </html>
  );
}

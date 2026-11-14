import Link from "next/link";
import type { ServerResult } from "../lib/server";

/** X state for server-rendered pages: problem title + reference + a retry link (no JS needed). */
export function ServerErrorState({ result, retryHref }: { result: Extract<ServerResult<unknown>, { ok: false }>; retryHref: string }) {
  return (
    <div role="alert" className="rounded-lg border border-danger-border bg-danger-subtle p-5">
      <p className="font-semibold text-danger-fg">{result.title}</p>
      <p className="mt-1 text-sm text-fg-secondary">{result.detail}</p>
      {result.requestId ? (
        <p className="mt-2 text-xs text-fg-muted">
          Reference: <span className="select-all font-mono">{result.requestId}</span>
        </p>
      ) : null}
      <Link href={retryHref} className="mt-3 inline-block text-sm font-medium text-fg-link hover:text-fg-link-hover">
        Try again
      </Link>
    </div>
  );
}

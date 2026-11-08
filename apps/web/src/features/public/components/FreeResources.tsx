"use client";

import Link from "next/link";
import { useState } from "react";
import { Button, EmptyState, ErrorState } from "@/components/ui";
import { api } from "@/lib/api/client";
import { humanize } from "@/features/catalog/lib/format";
import type { FreeResourceDto } from "../lib/types";

interface SignedUrlDto {
  url: string;
}

const linkCls = "font-medium text-fg-link underline hover:text-fg-link-hover";

/**
 * PUB-009 resource list (CAT-06). A resource with a public `url` is a plain link; files are
 * fetched through MED downloads, which needs a session, so visitors get a sign-in gate.
 */
export function FreeResourceList({ resources, signedIn }: { resources: FreeResourceDto[]; signedIn: boolean }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  if (resources.length === 0) return <EmptyState title="No free resources yet" description="Free PDFs and cheat sheets will appear here when they are published." />;

  async function download(r: FreeResourceDto) {
    setBusy(r.id);
    setError(null);
    try {
      const res = await api.post<SignedUrlDto>("media/downloads", { resource_id: r.id }, { idempotencyKey: true });
      if (res.kind === "ok" && res.data.url) window.open(res.data.url, "_blank", "noopener,noreferrer");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-3">
      <ul className="divide-y divide-line rounded-xl border border-line bg-surface">
        {resources.map((r) => (
          <li key={r.id} className="flex flex-wrap items-center justify-between gap-3 p-4 text-sm">
            <span className="text-fg">
              {r.title}
              {r.resource_type ? <span className="text-fg-muted"> · {humanize(r.resource_type)}</span> : null}
              {r.course_slug ? (
                <>
                  {" "}
                  <Link href={`/courses/${encodeURIComponent(r.course_slug)}`} className="text-fg-link underline">
                    from the course
                  </Link>
                </>
              ) : null}
            </span>
            {r.url && /^https:\/\//.test(r.url) ? (
              <a href={r.url} target="_blank" rel="noopener noreferrer" className={linkCls}>
                Open<span className="sr-only"> {r.title}</span>
              </a>
            ) : signedIn ? (
              <Button variant="secondary" size="sm" loading={busy === r.id} onClick={() => void download(r)} aria-label={`Download ${r.title}`}>
                Download
              </Button>
            ) : (
              <Link href="/login?next=%2Ffree-resources" className={linkCls}>
                Log in to download<span className="sr-only"> {r.title}</span>
              </Link>
            )}
          </li>
        ))}
      </ul>
      {error ? <ErrorState error={error} /> : null}
    </div>
  );
}

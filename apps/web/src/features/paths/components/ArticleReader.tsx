"use client";

import Link from "next/link";
import { Badge, EmptyState, ErrorState } from "@/components/ui";
import { isApiError } from "@/lib/api/errors";
import { LoadingBlock } from "@/features/trainer/shared/ui";
import { useApi } from "@/features/trainer/shared/use-api";
import { seg } from "../lib/api";
import type { ReaderArticle } from "../lib/types";
import { ArticleRenderer, OnThisPage, useArticleToc } from "./ArticleRenderer";

const LEVEL: Record<string, string> = { beginner: "Beginner", intermediate: "Intermediate", advanced: "Advanced" };

export function useReaderArticle(id: string | null) {
  return useApi<ReaderArticle>(id ? `read/${seg(id)}` : null);
}

function studyTime(min: number | null): string | null {
  if (!min) return null;
  return min < 60 ? `About ${min} min of study` : `About ${Math.round((min / 60) * 10) / 10} h of study`;
}

/** Article body + header, used by /read/[id] and inline in the path player. */
export function ArticleView({ article, withToc = true }: { article: ReaderArticle; withToc?: boolean }) {
  const toc = useArticleToc(article.body_md);
  const time = studyTime(article.est_minutes);
  const body = (
    <article>
      <header className="mb-4">
        <h1 className="font-display text-2xl font-bold text-fg">{article.title}</h1>
        {article.subtitle ? <p className="mt-1 text-fg-muted">{article.subtitle}</p> : null}
        <div className="mt-2 flex flex-wrap gap-2">
          {article.level ? <Badge>{LEVEL[article.level] ?? article.level}</Badge> : null}
          {time ? <Badge>{time}</Badge> : null}
          {article.can_edit && article.status !== "published" ? <Badge tone="warning">Not published</Badge> : null}
        </div>
      </header>
      <ArticleRenderer source={article.body_md} />
    </article>
  );
  if (!withToc || toc.length === 0) return body;
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_14rem]">
      <div className="order-2 lg:order-1">{body}</div>
      <div className="order-1 lg:order-2">
        <OnThisPage toc={toc} />
      </div>
    </div>
  );
}

/** Stand-alone reader (`/read/[id]`). Authorisation (share audience, path learners) is the api's. */
export function ArticleReader({ id }: { id: string }) {
  const state = useReaderArticle(id);
  if (state.error) {
    if (isApiError(state.error) && (state.error.status === 404 || state.error.status === 403)) {
      return <EmptyState title="This article is not available" description="It may have been unpublished, or it is shared with a different group." action={<Link href="/app" className="text-fg-link underline">Go to your dashboard</Link>} />;
    }
    return <ErrorState error={state.error} onRetry={() => void state.reload()} />;
  }
  if (!state.data) return <LoadingBlock rows={6} label="Loading article" />;
  return (
    <div className="space-y-3">
      {state.data.can_edit ? (
        <Link href={`/trainer/paths/articles/${encodeURIComponent(state.data.id)}`} className="text-sm text-fg-link underline">
          Edit this article
        </Link>
      ) : null}
      <ArticleView article={state.data} />
    </div>
  );
}

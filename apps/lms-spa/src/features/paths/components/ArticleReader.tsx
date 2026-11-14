"use client";

import Link from "next/link";
import { Badge, Breadcrumbs, EmptyState, ErrorState, LinkButton, LoadingBlock } from "@/components/ui";
import { isApiError } from "@/lib/api/errors";
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

/**
 * Drops a leading Markdown "# Title" that repeats the article's own title, so the title isn't shown
 * twice (once as the header, once as the first line of the body).
 */
export function stripRepeatedTitle(md: string, title: string): string {
  const m = /^\s*#\s+(.+?)\s*#*\s*(?:\r?\n|$)/.exec(md);
  if (!m || m[1]!.trim().toLowerCase() !== title.trim().toLowerCase()) return md;
  return md.slice(m[0].length);
}

/**
 * Article body + header, used by /read/[id] and inline in the path player. `inline` renders the
 * title as an h3 at section size (the step's h2 is above it), so the article never outranks the page.
 */
export function ArticleView({ article, withToc = true, inline = false }: { article: ReaderArticle; withToc?: boolean; inline?: boolean }) {
  const source = stripRepeatedTitle(article.body_md, article.title);
  const toc = useArticleToc(source);
  const time = studyTime(article.est_minutes);
  const Title = inline ? "h3" : "h1";
  const body = (
    <article>
      <header className="mb-4">
        <Title className={inline ? "font-display text-lg font-bold text-fg-heading" : "font-display text-2xl font-extrabold tracking-tight text-fg-heading sm:text-[1.75rem]"}>{article.title}</Title>
        {article.subtitle ? <p className="mt-1 text-fg-muted">{article.subtitle}</p> : null}
        <div className="mt-2 flex flex-wrap gap-2">
          {article.level ? <Badge>{LEVEL[article.level] ?? article.level}</Badge> : null}
          {time ? <Badge>{time}</Badge> : null}
          {article.can_edit && article.status !== "published" ? <Badge tone="warning">Not published</Badge> : null}
        </div>
      </header>
      <ArticleRenderer source={source} />
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
      return (
        <EmptyState
          icon="document"
          title="This article is not available"
          description="It may have been unpublished, or it is shared with a different group."
          action={
            <LinkButton href="/app" variant="secondary" size="sm">
              Go to your dashboard
            </LinkButton>
          }
        />
      );
    }
    return <ErrorState error={state.error} onRetry={() => void state.reload()} />;
  }
  if (!state.data) return <LoadingBlock rows={6} label="Loading article" size="row" />;
  return (
    <div className="space-y-3">
      <Breadcrumbs
        items={
          state.data.can_edit
            ? [{ label: "Articles", href: "/trainer/paths/articles" }, { label: state.data.title }]
            : [{ label: "My paths", href: "/app/path/my" }, { label: state.data.title }]
        }
      />
      {state.data.can_edit ? (
        <Link href={`/trainer/paths/articles/${encodeURIComponent(state.data.id)}`} className="text-sm text-fg-link underline">
          Edit this article
        </Link>
      ) : null}
      <ArticleView article={state.data} />
    </div>
  );
}

import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { EmptyState, PageHeader } from "@/components/ui";
import { CatalogFilters, type CatalogFilterValues } from "@/features/catalog/components/CatalogFilters";
import { CourseGrid, ServerErrorState } from "@/features/catalog/components/CatalogParts";
import { LinkButton } from "@/features/catalog/components/LinkButton";
import { serverLoad, withQuery } from "@/features/catalog/lib/server";
import type { CourseCardDto, Paged } from "@/features/catalog/lib/types";

export const metadata: Metadata = {
  title: "Courses",
  description: "Courses for placement preparation: aptitude, programming, DSA and interview skills.",
};

type Search = Promise<Record<string, string | string[] | undefined>>;

function one(v: string | string[] | undefined): string | undefined {
  const s = Array.isArray(v) ? v[0] : v;
  return s && s.length <= 200 ? s : undefined;
}

/** PUB-002 catalog (CAT-01; CAT-07 when searching). Cursor paging via ?cursor=. */
async function Page__server({ searchParams }: { searchParams: Search }) {
  const sp = await searchParams;
  const filters: CatalogFilterValues = {
    q: one(sp.q),
    category: one(sp.category),
    level: one(sp.level),
    price_type: one(sp.price_type),
    language: one(sp.language),
  };
  const cursor = one(sp.cursor);
  const path = filters.q
    ? withQuery("catalog/search", { q: filters.q, cursor, limit: "24" })
    : withQuery("catalog/courses", { category: filters.category, level: filters.level, price_type: filters.price_type, language: filters.language, cursor, limit: "24" });
  const result = await serverLoad<Paged<CourseCardDto>>(path);
  const selfHref = withQuery("/courses", { ...filters, cursor });

  return (
    <div className="space-y-6">
      <PageHeader title="Courses" description="Structured courses with explained practice. Free courses need only a free account." />
      <CatalogFilters values={filters} />
      {!result.ok ? (
        <ServerErrorState result={result} retryHref={selfHref} />
      ) : result.data.data.length === 0 ? (
        <EmptyState
          title={cursor ? "No more courses" : "No courses match these filters"}
          description="Try a different level, language or price, or clear the filters."
          action={<LinkButton href="/courses" variant="secondary">Clear filters</LinkButton>}
        />
      ) : (
        <>
          <CourseGrid courses={result.data.data} />
          <nav aria-label="Catalog pages" className="flex justify-end gap-2">
            {cursor ? <LinkButton href={withQuery("/courses", { ...filters })} variant="secondary" size="sm">First page</LinkButton> : null}
            {result.data.page?.has_more && result.data.page.next_cursor ? (
              <LinkButton href={withQuery("/courses", { ...filters, cursor: result.data.page.next_cursor })} variant="secondary" size="sm">
                More courses
              </LinkButton>
            ) : null}
          </nav>
        </>
      )}
    </div>
  );
}

// SPA: ex-server components run on the client (scripts/sync-from-web.mjs).
export default asyncComponent(Page__server, "app/(public)/courses/page.tsx#Page");

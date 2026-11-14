import type { Metadata } from "next";
import Link from "next/link";
import { Logo, PageContainer } from "@/components/ui";
import { ArticleReader } from "@/features/paths/components/ArticleReader";

export const metadata: Metadata = { title: "Article", robots: { index: false, follow: false } };

/**
 * Shareable article reader. Requires sign-in (the api answers 401 and the client redirects to
 * /login?next=…); who may read is decided by the api from the article's share audience.
 * It sits outside the portal shells, so it carries its own slim brand bar; the reader adds the
 * breadcrumb back to Articles (authors) or My paths (learners).
 */
export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <div className="min-h-dvh bg-surface-canvas">
      <header className="border-b border-line bg-surface">
        <PageContainer width="content" align="center" className="flex h-14 items-center px-4">
          <Link href="/" className="inline-flex min-h-touch items-center rounded-md focus-visible:shadow-focus focus-visible:outline-none" aria-label="Tech Drona home">
            <Logo className="h-7 w-auto" alt="" />
          </Link>
        </PageContainer>
      </header>
      <main id="main">
        <PageContainer width="content" align="center" className="px-4 py-6 sm:py-8">
          <ArticleReader id={id} />
        </PageContainer>
      </main>
    </div>
  );
}

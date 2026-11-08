import type { Metadata } from "next";
import { ArticleReader } from "@/features/paths/components/ArticleReader";

export const metadata: Metadata = { title: "Article", robots: { index: false, follow: false } };

/**
 * Shareable article reader. Requires sign-in (the api answers 401 and the client redirects to
 * /login?next=…); who may read is decided by the api from the article's share audience.
 */
export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <main id="main" className="mx-auto w-full max-w-5xl px-4 py-8">
      <ArticleReader id={id} />
    </main>
  );
}

import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ContentDocView } from "@/features/public/components/ContentDoc";
import { findHelpArticle } from "@/features/public/content/help";

type Params = Promise<{ article: string }>;

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const doc = findHelpArticle((await params).article);
  return doc ? { title: doc.title, description: doc.summary } : { title: "Help" };
}

/** PUB-019 help article. Unknown slugs are a real 404. */
export default async function Page({ params }: { params: Params }) {
  const doc = findHelpArticle((await params).article);
  if (!doc) notFound();
  return <ContentDocView doc={doc} kind="article" back={{ href: "/help", label: "Help centre" }} />;
}

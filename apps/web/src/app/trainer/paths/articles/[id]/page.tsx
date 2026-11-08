import type { Metadata } from "next";
import { ArticleEditor } from "@/features/paths/components/Articles";

export const metadata: Metadata = { title: "Edit article" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ArticleEditor articleId={id} />;
}

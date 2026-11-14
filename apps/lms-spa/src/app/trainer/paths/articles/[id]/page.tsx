import { asyncComponent } from "@/spa/async";
import type { Metadata } from "next";
import { ArticleEditor } from "@/features/paths/components/Articles";

export const metadata: Metadata = { title: "Edit article" };

async function Page__server({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ArticleEditor articleId={id} />;
}

// SPA: ex-server components run on the client (src/spa/async.tsx).
export default asyncComponent(Page__server, "app/trainer/paths/articles/[id]/page.tsx#Page");

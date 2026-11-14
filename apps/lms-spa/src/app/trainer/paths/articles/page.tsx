import type { Metadata } from "next";
import { PageHeader } from "@/components/ui";
import { ArticleList } from "@/features/paths/components/Articles";

export const metadata: Metadata = { title: "Articles" };

export default function Page() {
  return (
    <div>
      <PageHeader
        breadcrumbs={[{ label: "Learning paths", href: "/trainer/paths" }, { label: "Articles" }]}
        title="Articles"
        description="Lessons you write once, use as path steps and share with a link."
      />
      <ArticleList />
    </div>
  );
}

import type { Metadata } from "next";
import { LinkButton, PageHeader } from "@/components/ui";
import { PathList } from "@/features/paths/components/PathList";

export const metadata: Metadata = { title: "Learning paths" };

/** Guided learning paths: list, create, AI draft. */
export default function Page() {
  return (
    <div>
      <PageHeader
        title="Learning paths"
        description="Design guided paths of readings, videos, articles, assignments and assessments."
        actions={
          <LinkButton variant="secondary" href="/trainer/paths/articles">
            Articles
          </LinkButton>
        }
      />
      <PathList />
    </div>
  );
}

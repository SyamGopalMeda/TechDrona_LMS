import type { Metadata } from "next";
import Link from "next/link";
import { PageHeader } from "@/components/ui";
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
          <Link href="/trainer/paths/articles" className="inline-flex h-10 items-center rounded-md border border-line-control px-4 text-sm font-medium hover:bg-surface-hover">
            Articles
          </Link>
        }
      />
      <PathList />
    </div>
  );
}
